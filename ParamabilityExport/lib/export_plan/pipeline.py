"""The export of one body into a recipe package, from the capture to the manifest. Pure: no Fusion imports.

The sequence asks Fusion for the capture, the STEP of the part as it is and the sketch measuring. A size that a value
cannot follow is left free with a warning, and the ranges are the ones in the dialog table.

Steps, in order: read the capture, translate once to learn which sizes the recipe keeps, run the sketch probe (it
only recomputes), translate again with the motion it found, and assemble the package. The probe runs whenever a
sketch can be followed.

Fusion is reached only through the port the caller hands in (see `ExportPort`), so tests run the whole sequence with
fakes. Parameters are changed by the probe and put back on every way out: when a step fails, when the person
cancels, and before the probe's last read. What is left over (a parameter that would not go back, sketches that did
not return to their start, a probe that could not measure) goes into the `health` record of the result.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..params import size_table as size_tables
from ..params.listing import list_parameters
from ..sketch_values.motion import OPTIMISTIC
from . import health as health_module
from .body_scope import body_links, scope_inputs
from .probe_flow import SizeProbe, covers_a_sketch, extra_size_params, kept_size_names
from .recipe_export import free_sizes, plan_single_export, translate_capture
from ..design_edit.restore import restore_parameters
from ..design_edit.runner import ExportCancelled, RowExport
from .size_offers import labels, probe_sizes


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one, tests pass a fake.

    store: the parameter store (`apply.apply_row_values` and `restore.restore_parameters` list what it needs, plus
      `saved_expressions`).
    units: {parameter name: Fusion unit string}.
    export_step(path): write the STEP of the picked body as the design is now.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
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
    """The package of one export. `tmp` is a folder that holds the STEP file of the part until the package is written.

    Raises what a failing step raises (`RowBuildError`, `StepExportError`, `PackageCapError`, `ExportCancelled`,
    `MarkerError`); the parameters are back by then and `port.warn_unrestored` has named any that are not."""
    return _Pipeline(port, request, tmp).run()


class ProbeRun:
    """Runs the probe's rows in one job: one baseline, and the parameters put back after every row. The rows only
    recompute (no STEP). It keeps the probe state read at every row that built, by row key, and `rows` lists
    (row, result) of every row run. `read_failure` holds the first probe read that failed: the probe is then not
    used."""

    def __init__(self, port, tmp, probe):
        self.port, self.tmp, self.probe = port, tmp, probe
        self.reads, self.rows = {}, []
        self.read_failure = None
        self.job = RowExport(port.store, port.units, self._export)

    def _export(self, path):
        """`RowExport`'s step callback: a probe row has no STEP, so `path` is None and only the state is read."""
        key = self.job.current_key
        if self.read_failure is None:
            try:
                self.reads[key] = self.probe.read_now()
            except ExportCancelled:
                raise
            except Exception as exc:
                self.read_failure = exc
                self.port.log(f"size probe read failed: {exc!r}")

    def try_rows(self, rows):
        """Run the probe's rows. Returns their results."""
        with self.port.progress("Trying") as progress:
            results = self.job.run(rows, self.tmp, progress.step, tolerate_build_errors=True)
        self.rows.extend(zip(rows, results))
        return results

    def probe_states(self):
        """(values, result, read) of the rows run, for `SizeProbe.add_states`."""
        out = []
        for row, result in self.rows:
            state = row.get("state") or {}
            values = {param: state[param] for param in row.get("varied") or [] if param in state}
            out.append((values, result, self.reads.get(row.get("key", row["name"]))))
        return out


class _Pipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.saved = None
        self.unrestored = []
        self.table = None
        self.probe = None
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motion = None
        self.doubtful = []

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
            ranges=request.ranges, links=body_links(capture))

        final = self._translate_and_measure(capture) if isinstance(capture, dict) else None

        self._restore()
        gap = self._restore_gap()
        probe_report = self._close_probe()
        health = health_module.make_health(self.unrestored, gap, self.probe_status, self.probe_error)
        manifest, files, report = plan_single_export(
            capture if capture is not None else RuntimeError("The steps were not read."),
            part_step, request.title, request.writer, request.up_axis,
            size_table=self.table, listing=self._listing(), motion=self.motion, probe=probe_report,
            marker=request.marker, loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful],
            translated=final, health=health)
        return PipelineResult(manifest, files, report, self.table, health)

    def _translate_and_measure(self, capture):
        """The stages that need a capture: the first translation, the sketch probe and the translation with the
        motion it found. Returns the final translation (a refusal included), or None when it failed."""
        first_motion = OPTIMISTIC if covers_a_sketch(capture) else None
        first = self._translation(capture, first_motion)
        if first is None:
            return None
        if first.recipe is None:
            # The plan translates without a motion at this point, so the first look's refusal is its result only
            # when the first look had none either.
            return first if first_motion is None else None
        free = free_sizes(first.recipe)
        extra = extra_size_params(self.table, free)
        keep = kept_size_names(self.table, free) | {self.table.size_name(n) for n in extra}
        sizes = probe_sizes(self.table, self.request.parameters, keep=keep)

        self.probe = self._start_probe(capture)
        if self.probe is not None:
            found = self._measure(ProbeRun(self.port, self.tmp, self.probe), sizes, extra)
            if found is not None:
                self.doubtful.extend(found)
        return self._translation(capture, self.motion)

    # ---- translation ------------------------------------------------------------------------------------------

    def _translation(self, capture, motion):
        """The translator's result, a refusal included (the plan reports its reason without translating again), or
        None when the translator failed. Never raises."""
        try:
            result = translate_capture(capture, self.request.up_axis, self.table, motion)
        except Exception as exc:
            self.port.log(f"translation failed: {exc!r}")
            return None
        return result

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

    def _measure(self, run, sizes, extra=()):
        """The probe's rows and its result: the sizes the probe cannot follow, or None when the probe failed.

        The rows put every size at the ends of its range where a size moves a sketch, then the sizes in `extra` (tried
        on a guess, `probe_flow.extra_size_params`) while rows are left. A failure other than a cancel
        leaves the translation without a motion (no size behind a sketch is then followed, by the translator's own
        rule) and is noted for the person. The parameters are put back before the last read."""
        probe = self.probe
        try:
            rows = probe.probe_rows(sizes, extra)
            if rows:
                run.try_rows(rows)
                if run.read_failure is not None:
                    raise run.read_failure
                probe.add_states(run.probe_states())
            self._restore()
            found = probe.finish(probe.read_now(), labels(self.table))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"size probe failed: {exc!r}")
            self.probe_status, self.probe_error = health_module.FAILED, repr(exc)
            self.motion = None
            return None
        self.motion = probe.motion
        return found

    def _restore_gap(self):
        """How far the sketches are from their start after the last restore, or None when that cannot be told. Read
        again here because the probe rows changed the design once more."""
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
