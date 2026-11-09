"""The export of one body into a recipe package, from the capture to the manifest. Pure: no Fusion imports.

Both exports run this one sequence, with options:

- The plain export (`check_sizes` off) asks nothing of Fusion beyond the capture, the STEP of the part and the sketch
  measuring: no size checks, no tries to build, no shortened ranges. A size that a value cannot follow stays free
  with a warning.
- The checked export adds one check STEP per kept size, a try at the other end of each range (smaller steps where
  Fusion cannot build, `size_narrowing`) and a second translation with what these found. Unless `keep_doubtful` is
  set, a size that cannot be followed fully is fixed.

Steps, in order: read the capture, translate once to learn which sizes the recipe keeps, plan and run the size
checks, run the sketch probe, translate again with what was found, and assemble the package. The sketch probe runs
in both exports whenever a sketch can be followed.

Fusion is reached only through the port the caller hands in (see `ExportPort`), so tests run the whole sequence with
fakes. Parameters are changed by the runs and put back on every way out: when a step fails, when the person cancels,
and before the probe's last read. What is left over (a parameter that would not go back, sketches that did not return
to their start, a probe that could not measure) goes into the `health` record of the result.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..params import size_table as size_tables
from ..params.listing import list_parameters
from ..probe.motion import OPTIMISTIC
from . import health as health_module
from .body_scope import other_sketch_names, scope_inputs
from .probe_flow import SizeProbe, covers_a_sketch, kept_size_names
from .recipe_export import free_sizes, plan_single_export, translate_capture, with_translated_limits
from .restore import restore_parameters
from .runner import ExportCancelled, RowExport
from .size_checks import build_failures, check_at, into_range, plan_checks, read_checks
from .size_narrowing import narrow_failed
from .size_offers import labels, sizes_for_checks


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one, tests pass a fake.

    store: the parameter store (`apply.apply_row_values` and `restore.restore_parameters` list what it needs, plus
      `saved_expressions`).
    units: {parameter name: Fusion unit string}.
    export_step(path): write the STEP of the picked body as the design is now.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
    snapshot(skip, source): the sketch numbers of the body's component now (sketches in `skip` left out), with the
      body's place in the assembly when `source` names where it comes from.
    probe_reader(): a callable `read(request)` giving one probe state, or raising.
    progress(verb): a context manager whose value has `step(index, total, name)`; the step returns False when the
      person cancelled.
    warn_unrestored(names): tell the person that these parameters could not be put back, when the export stops.
    log(text): a line for the log.
    """

    store: object
    units: dict

    def export_step(self, path): ...

    def read_capture(self): ...

    def snapshot(self, skip, source): ...

    def probe_reader(self): ...

    def progress(self, verb): ...

    def warn_unrestored(self, names): ...

    def log(self, text): ...


@dataclass
class ExportRequest:
    """The person's choices and the design's parameters for one export."""

    title: str
    writer: str
    up_axis: str
    parameters: list
    model_params: list
    design_unit: str
    ticked: list
    ranges: dict
    check_sizes: bool = False
    keep_doubtful: bool = False
    marker: Optional[dict] = None


@dataclass
class PipelineResult:
    """What `run_pipeline` made: the package parts, the report, and the size table the export ended with."""

    manifest: dict
    files: dict
    report: dict
    table: object
    health: dict = field(default_factory=dict)


def run_pipeline(port, request, tmp):
    """The package of one export. `tmp` is a folder that holds the STEP files until the package is written.

    Raises what a failing step raises (`RowBuildError`, `StepExportError`, `PackageCapError`, `ExportCancelled`,
    `MarkerError`); the parameters are back by then and `port.warn_unrestored` has named any that are not."""
    return _Pipeline(port, request, tmp).run()


def _target_info(capture):
    """(component name, sketch scope, placement source) of the picked body from its capture.

    The scope is the component name shown before a sketch name in a reason; empty for a body of the root.
    Unknown values are empty strings, and the component name is then "the part"."""
    target = (capture or {}).get("target") or {}
    component = target.get("component") or {}
    place = target.get("placement") or {}
    name = component.get("name") or ""
    return name or "the part", "" if component.get("root") else name, place.get("source") or ""


class CheckRun:
    """Exports the STEP of each size check and tries the ends of each range, in one job: one baseline, and the
    parameters put back after every run. It keeps the sketches read at every check and, when a probe runs, the probe
    state of every row that built; both are keyed by the row key. `rows` lists (row, result) of every row run.
    `read_failure` holds the first probe read that failed: the probe is then not used."""

    def __init__(self, port, tmp, skip_sketches, source, probe=None):
        self.port, self.tmp, self.skip, self.source, self.probe = port, tmp, skip_sketches, source, probe
        self.snapshots, self.reads, self.rows = {}, {}, []
        self.read_failure = None
        self._runs = 0
        self.job = RowExport(port.store, port.units, self._export)

    def _export(self, path):
        key = self.job.current_key
        if path is not None:
            self.port.export_step(path)
            self.snapshots[key] = self.port.snapshot(self.skip, self.source)
        if self.probe is not None and self.read_failure is None:
            try:
                self.reads[key] = self.probe.read_now()
            except ExportCancelled:
                raise
            except Exception as exc:
                self.read_failure = exc
                self.port.log(f"size probe read failed: {exc!r}")

    def _run(self, rows, step, until_built=False):
        self._runs += 1
        folder = os.path.join(self.tmp, "checks", "run%d" % self._runs)
        os.makedirs(folder, exist_ok=True)
        results = self.job.run(rows, folder, step, tolerate_build_errors=True, until_built=until_built)
        self.rows.extend(zip(rows, results))
        return results

    def run(self, checks):
        """The results of the checks, in order."""
        with self.port.progress("Checking") as progress:
            return self._run([c["row"] for c in checks], progress.step)

    def narrow(self, checks, results, sizes, size_labels):
        """Try both ends of each checked size (`size_narrowing`). Returns a `Narrowing`."""
        with self.port.progress("Trying") as progress:
            def run_size(size, values, with_step, description):
                rows = [check_at(size, v, sizes)["row"] for v in values]
                if not with_step:
                    rows = [dict(r, step=False) for r in rows]
                number = 1 + next((i for i, c in enumerate(checks) if c["param"] == size["param"]), 0)
                return self._run(rows, lambda *a: progress.step(number, len(checks), description), until_built=True)

            return narrow_failed(checks, results, sizes, run_size, size_labels)

    def recheck(self, kept, sizes, recipe_sizes):
        """The kept checks with each one outside the recipe's range of its size (`size_checks.into_range`) run again
        at the end of that range. A check that cannot move there, or does not build there, is left out."""
        moved = {c["size"]: value for c, value in into_range(kept, recipe_sizes)}
        if not moved:
            return kept
        by_param = {s["param"]: s for s in sizes}
        redo = [check_at(by_param[c["param"]], moved[c["size"]], sizes) for c in kept
                if c["size"] in moved and moved[c["size"]] is not None]
        with self.port.progress("Checking") as progress:
            results = self._run([c["row"] for c in redo], progress.step) if redo else []
        again = {c["size"]: {**c, "step_file": r["step_file"]} for c, r in zip(redo, results) if not r.get("error")}
        return [again[c["size"]] if c["size"] in again else c for c in kept
                if c["size"] not in moved or c["size"] in again]

    def try_rows(self, rows):
        """Run the probe's extra rows (no STEP). Returns their results."""
        with self.port.progress("Trying") as progress:
            return self._run(rows, progress.step)

    def probe_states(self, start=0):
        """(values, result, read) of the rows run, from row number `start` on, for `SizeProbe.add_states`."""
        out = []
        for row, result in self.rows[start:]:
            state = row.get("state") or {}
            values = {param: state[param] for param in row.get("varied") or [] if param in state}
            out.append((values, result, self.reads.get(row.get("key", row["name"]))))
        return out


class _Pipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.checked = bool(request.check_sizes)
        self.loose = not (self.checked and request.keep_doubtful)
        self.saved = None
        self.unrestored = []
        self.table = None
        self.probe = None
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motion = None
        self.doubtful, self.measured = [], []

    def run(self):
        self.saved = self.port.store.saved_expressions()
        done = False
        try:
            result = self._run()
            done = True
            return result
        finally:
            failed = self._restore()
            if not done and failed:
                self.port.warn_unrestored(failed)

    def _restore(self):
        """Put every parameter back to its saved expression. Returns the names that would not go back, and keeps
        them for the health record. Safe to call at any time."""
        self.unrestored = restore_parameters(self.port.store, self.saved)
        return self.unrestored

    # ---- stages -----------------------------------------------------------------------------------------------

    def _run(self):
        port, request = self.port, self.request
        part_step = os.path.join(self.tmp, "part.step")
        port.export_step(part_step)
        capture = port.read_capture()
        model, quantities = scope_inputs(capture, request.model_params)
        self.table = size_tables.build(
            request.parameters, request.ticked, model, request.design_unit, quantity_params=quantities,
            ranges=request.ranges)

        kept, unchecked, failures, narrowed, final = [], [], [], [], None
        if isinstance(capture, dict):
            kept, unchecked, failures, narrowed, final = self._translate_and_check(capture)

        self._restore()
        gap = self._restore_gap()
        probe_report = self._close_probe()
        health = health_module.make_health(self.unrestored, gap, self.probe_status, self.probe_error)
        manifest, files, report = plan_single_export(
            capture if capture is not None else RuntimeError("The steps were not read."),
            part_step, request.title, request.writer, request.up_axis,
            size_table=self.table, checks=kept,
            fixed=[{"name": m["name"], "reason": m["reason"]} for m in self.measured], unchecked=unchecked,
            listing=self._listing(), motion=self.motion, probe=probe_report, build_failures=failures,
            narrowed=narrowed, marker=request.marker,
            loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful], loose_sizes=self.loose,
            translated=final, plain=not self.checked, health=health)
        return PipelineResult(manifest, files, report, self.table, health)

    def _translate_and_check(self, capture):
        """The stages that need a capture. Returns (kept checks, unchecked sizes, build failures, narrowed ends, the
        final translation)."""
        request = self.request
        kept, unchecked, failures, narrowed, checks, not_checked = [], [], [], [], [], []
        first = self._translation(capture, OPTIMISTIC if covers_a_sketch(capture) else None, plain=not self.checked)
        if first is None:
            return kept, unchecked, failures, narrowed, None
        planned = with_translated_limits(self.table, first)
        keep = kept_size_names(planned, free_sizes(first.recipe))
        sizes = sizes_for_checks(planned, request.parameters, keep=keep)
        if self.checked:
            checks, not_checked = plan_checks(sizes)
            unchecked = [s["size"] for s in not_checked]
        else:
            not_checked = sizes

        self.probe = self._start_probe(capture)
        part_name, scope, source = _target_info(capture)
        skip = other_sketch_names(capture) | (self.probe.skip if self.probe is not None else set())
        run = CheckRun(self.port, self.tmp, skip, source, self.probe) if checks or self.probe is not None else None
        baseline = self.port.snapshot(skip, source) if checks else None

        if checks:
            results = run.run(checks)
            narrowing = run.narrow(checks, results, sizes, labels(self.table))
            failures = build_failures(checks, results, narrowing.tries)
            checks, results, sizes, narrowed = (
                narrowing.checks, narrowing.results, narrowing.sizes, narrowing.narrowed)
            if narrowed:
                self.table = self.table.with_narrowed(narrowing.moved_ends(self.table))
            kept, self.measured, self.doubtful = read_checks(
                checks, results, baseline, run.snapshots, labels(self.table), part_name=part_name, scope=scope,
                loose=self.loose, failed_ends=narrowing.failed_ends)
        if self.probe is not None:
            found = self._measure(run, sizes, not_checked)
            if found is not None:
                (self.doubtful if self.loose else self.measured).extend(found)
        if self.measured:
            self.table = self.table.with_fixed({m["param"]: m["reason"] for m in self.measured})
        # The translation with what the checks found can raise a minimum or shorten a range further.
        final = self._translation(capture, self.motion, plain=not self.checked)
        if final is not None and kept:
            before = [c["size"] for c in kept]
            kept = run.recheck(kept, sizes, final.recipe.get("sizes") or {})
            unchecked += [n for n in before if n not in {c["size"] for c in kept}]
        return kept, unchecked, failures, narrowed, final

    # ---- translation ------------------------------------------------------------------------------------------

    def _translation(self, capture, motion, plain):
        """The translator's result when it gives a recipe, else None (the plan then reports the reason). Never
        raises."""
        try:
            result = translate_capture(
                capture, self.request.up_axis, self.table, motion, loose=self.loose, plain=plain)
        except Exception as exc:
            self.port.log(f"translation failed: {exc!r}")
            return None
        return result if result.recipe is not None else None

    def _listing(self):
        """The design's parameters for the manifest, or None when they cannot be listed. Never stops the export."""
        try:
            return list_parameters(self.request.parameters, self.request.model_params, self.request.design_unit)
        except Exception as exc:
            self.port.log(f"parameter list failed: {exc!r}")
            return None

    # ---- the sketch probe -------------------------------------------------------------------------------------

    def _start_probe(self, capture):
        """The size probe with its first read, or None when no sketch can be followed or it could not start. A probe
        that could not start is noted for the person; it never stops the export."""
        try:
            if not covers_a_sketch(capture):
                return None
            self.probe_status = health_module.FAILED
            self.probe_error = "The first read of the sketches did not work."
            probe = SizeProbe.start(capture, self.table, self.port.probe_reader())
        except Exception as exc:
            self.port.log(f"size probe could not start: {exc!r}")
            self.probe_error = repr(exc)
            return None
        if probe is not None:
            self.probe_status = health_module.MEASURED
            self.probe_error = ""
        return probe

    def _measure(self, run, sizes, not_checked):
        """The probe's extra rows and its result: the sizes the probe cannot follow, or None when the probe failed.

        The states are every row the checks ran, then the extra rows at the ends of the ranges as the checks left
        them. A failure other than a cancel leaves the translation without a motion (no size behind a sketch is then
        followed, by the translator's own rule) and is noted for the person. The parameters are put back before the
        last read."""
        probe = self.probe
        try:
            self._use_reads(run)
            probe.add_states(run.probe_states())
            rows = probe.probe_rows(sizes, [s["param"] for s in not_checked])
            if rows:
                start = len(run.rows)
                run.try_rows(rows)
                self._use_reads(run)
                probe.add_states(run.probe_states(start))
            self._restore()
            found = probe.finish(probe.read_now(), labels(self.table), self.loose)
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"size probe failed: {exc!r}")
            self.probe_status, self.probe_error = health_module.FAILED, repr(exc)
            self.motion = None
            return None
        self.motion = probe.motion
        return found

    @staticmethod
    def _use_reads(run):
        if run.read_failure is not None:
            raise run.read_failure

    def _restore_gap(self):
        """How far the sketches are from their start after the last restore, or None when that cannot be told. Read
        again here because the checks after the probe changed the design once more."""
        if self.probe is None or self.probe_status != health_module.MEASURED:
            return None
        try:
            return self.probe.measure_restore(self.probe.read_now())
        except Exception as exc:
            self.port.log(f"reading the sketches after the restore failed: {exc!r}")
            return None

    def _close_probe(self):
        """The probe's record for `report.json`, or None when it did not run or failed."""
        if self.probe is None or self.probe_status != health_module.MEASURED:
            return None
        return self.probe.report()
