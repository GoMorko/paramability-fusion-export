"""The export of one body into a recipe package, from the capture to the manifest. Pure: no Fusion imports.

The sequence asks Fusion for the capture, the STEP of the part as it is and the sketch measuring. A size that a value
cannot follow is left free with a warning, and the ranges are the ones in the dialog table.

Steps, in order: read the capture, translate once to learn which sizes the recipe keeps, run the sketch probe (it
only recomputes), translate again with the motion it found, and assemble the package. The probe runs whenever a
sketch can be followed. When the first translation leaves steps out, or stops because the part holds too many gaps,
Fusion is asked which step made the faces each later step picks (`reach_pass`) before anything else, and the part is
translated again with the answer.

Fusion is reached only through the port the caller hands in (see `ExportPort`), so tests run the whole sequence with
fakes. Parameters are changed by the probe and put back on every way out: when a step fails, when the person
cancels, and before the probe's last read. What is left over (a parameter that would not go back, sketches that did
not return to their start, a probe that could not measure) goes into the `health` record of the result. Timeline items
suppressed for the tries (`timeline_trim`, only when the person asks for it) are turned back on in the same places,
before the timeline marker goes back.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..params import size_table as size_tables
from ..params.listing import list_parameters
from ..probe.plan import MAX_PROBE_ROWS, NEARER_STEPS
from ..sketch_values.motion import OPTIMISTIC
from . import health as health_module
from . import messages
from .body_scope import body_links, scope_inputs
from .reach_pass import needs_reach, with_reach
from .probe_flow import SizeProbe, covers_a_sketch, extra_size_params, kept_size_names, shadow_of
from .recipe_export import free_sizes, plan_single_export, translate_capture
from ..design_edit.restore import restore_parameters
from ..design_edit.runner import ExportCancelled, RowExport
from .size_offers import discovery_sizes, labels, probe_sizes
from .timeline_trim import TryTimeline


def plan_rows_left(rows):
    """How many probe rows the cap leaves after `rows`."""
    return max(0, MAX_PROBE_ROWS - len(rows))


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one, tests pass a fake.

    store: the parameter store (`apply.apply_row_values` and `restore.restore_parameters` list what it needs, plus
      `saved_expressions`).
    units: {parameter name: Fusion unit string}.
    export_step(path): write the STEP of the picked body as the design is now.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
    read_reach(capture, gaps): the `reach` of the capture when the steps at the timeline indexes `gaps` are left out
      of the copy (`read_gap_reach.read_reach`); raises `MarkerError` when the timeline marker cannot go back.
    probe_reader(): a callable `read(request)` giving one probe state, or raising.
    progress(verb): a context manager whose value has `step(index, total, name)`; the step returns False when the
      person cancelled.
    warn_unrestored(names): tell the person that these parameters could not be put back, when the export stops.
    warn_left_off(names): optional; tell the person that these timeline steps, turned off for the tries
      (`timeline_trim`), could not be turned back on.
    log(text): a line for the log.
    """

    store: object
    units: dict

    def export_step(self, path): ...

    def read_capture(self): ...

    def read_reach(self, capture, gaps): ...

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
    faster_tries: bool = False  # suppress the timeline items the tries do not use (`timeline_trim`)


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


def warn_left_off(port, timeline):
    """Tell the person about timeline items that would not turn back on after the tries (`TryTimeline.left_off`)."""
    names = timeline.left_off if timeline is not None else []
    warn = getattr(port, "warn_left_off", None)
    if names and warn is not None:
        warn(names)


class MarkerNotHeld(Exception):
    """A probe read was asked for while the timeline marker sat before the position the tries need."""


class ProbeRun:
    """Runs the probe's rows in one job: one baseline, and the parameters put back after every row. The rows only
    recompute (no STEP). It keeps the probe state read at every row that built, by row key, and `rows` lists
    (row, result) of every row run. `read_failure` holds the first probe read that failed: the probe is then not
    used.

    A row that did not build, or left a followed sketch on another outline, may leave that sketch there after the
    parameters are put back. The design is then read again before the next row (`starts`, by row key), so the motion
    knows whether that row started from the right outline."""

    def __init__(self, port, tmp, probe):
        self.port, self.tmp, self.probe = port, tmp, probe
        self.reads, self.rows, self.starts = {}, [], {}
        self.read_failure = None
        self._previous = None  # key of the row run last
        self.job = RowExport(port.store, port.units, self._export, self._before_row)

    def _read_now(self):
        """The probe state of the design now. Raises when the timeline marker is not where the tries keep it: a read
        before it would miss items the sketches need, so the row counts as not read."""
        holds = getattr(self.port.store, "marker_holds", None)
        if holds is not None and not holds():
            raise MarkerNotHeld("The timeline marker was not where the tries keep it.")
        return self.probe.read_now()

    def _before_row(self, row):
        """`RowExport`'s hook once the parameters are back: read the design when the row before did not build or
        read a followed sketch on another outline."""
        key = row.get("key", row["name"])
        previous, self._previous = self._previous, key
        if previous is None or self.read_failure is not None:
            return
        read = self.reads.get(previous)
        if read is not None and not self.probe.off_outline(read):
            return
        try:
            self.starts[key] = self._read_now()
        except ExportCancelled:
            raise
        except Exception as exc:
            self.read_failure = exc
            self.port.log(f"size probe read failed: {exc!r}")

    def _export(self, path):
        """`RowExport`'s step callback: a probe row has no STEP, so `path` is None and only the state is read."""
        key = self.job.current_key
        if self.read_failure is None:
            try:
                self.reads[key] = self._read_now()
            except ExportCancelled:
                raise
            except Exception as exc:
                self.read_failure = exc
                self.port.log(f"size probe read failed: {exc!r}")

    def try_rows(self, rows):
        """Run the probe's rows. Returns their results."""
        done = len(self.rows)
        with self.port.progress(messages.TRY_VERB) as progress:
            def step(index, total, label):
                # The window counts the tries of the whole export, not of this batch.
                return progress.step(done + index, done + total, label)

            results = self.job.run(rows, self.tmp, step, tolerate_build_errors=True)
        self.rows.extend(zip(rows, results))
        return results

    def probe_states(self, since=0):
        """(values, result, read, start) of the rows run from number `since` on, for `SizeProbe.add_states`."""
        out = []
        for row, result in self.rows[since:]:
            state = row.get("state") or {}
            values = {param: state[param] for param in row.get("varied") or [] if param in state}
            key = row.get("key", row["name"])
            out.append((values, result, self.reads.get(key), self.starts.get(key)))
        return out

    def run_rows(self, rows):
        """Run `rows` and give the probe the states they gave. Raises the first failed read."""
        done = len(self.rows)
        self.try_rows(rows)
        if self.read_failure is not None:
            raise self.read_failure
        self.probe.add_states(self.probe_states(done))

    def _retry(self, sizes):
        """Rows nearer to the value for the sizes whose rows did not build (`SizeProbe.nearer_rows`), one step per
        batch, while rows and steps are left."""
        for _ in range(len(NEARER_STEPS) + 1):
            nearer = self.probe.nearer_rows(sizes, plan_rows_left(self.rows))
            if not nearer:
                break
            self.run_rows(nearer)

    def measure(self, rows, sizes):
        """The near rows, rows nearer still for the sizes whose rows did not build, then the far range ends while
        rows are left (and nearer rows for those that did not build), then the rows that check the other sizes of a
        value that one size moves along a curve (`SizeProbe.check_rows`)."""
        if rows:
            self.run_rows(rows)
        self._retry(sizes)
        far = self.probe.far_rows(sizes, plan_rows_left(self.rows))
        if far:
            self.run_rows(far)
            self._retry(sizes)
        check = self.probe.check_rows(sizes, plan_rows_left(self.rows))
        if check:
            self.run_rows(check)

    def discover(self, tries):
        """Read the design once the parameters are back, then run the discovery rows in the room the other rows left
        and keep what they found. Returns the parameters that changed the part."""
        self.probe.set_discovery_base(self._read_now())
        found = self.probe.discovery_rows(list(tries), plan_rows_left(self.rows))
        if not found:
            return []
        done = len(self.rows)
        self.try_rows(found)
        if self.read_failure is not None:
            raise self.read_failure
        self.probe.discover([(row, result, self.reads.get(row.get("key", row["name"])))
                             for row, result in self.rows[done:]])
        return self.probe.also_changes


class _Pipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.saved = None
        self.unrestored = []
        self.table = None
        self.capture = None  # the capture the translations used, with `reach` when steps were left out
        self.probe = None
        self.roll = None
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motion = None
        self.doubtful = []
        self.also = []

    def run(self):
        self.saved = self.port.store.saved_expressions()
        done = False
        try:
            result = self._run()
            done = True
            return result
        finally:
            failed = self._restore()
            self._end_roll()
            if not done and failed:
                self.port.warn_unrestored(failed)
            warn_left_off(self.port, self.roll)

    def _end_trim(self):
        """Turn back on the timeline items suppressed for the tries (a no-op when none were)."""
        if self.roll is not None:
            self.roll.end_trim()

    def _end_roll(self):
        """Turn the suppressed items back on and put the timeline marker back where the export found it (a no-op
        when nothing was changed)."""
        if self.roll is not None:
            self.roll.end()

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
        self._end_trim()
        gap = self._restore_gap()
        self._end_roll()
        probe_report = self._close_probe()
        shadow = shadow_of(self.probe, port.log) if self.probe is not None else None
        health = health_module.make_health(self.unrestored, gap, self.probe_status, self.probe_error,
                                           self._unchecked(), self.motion.flipped if self.motion is not None else ())
        capture = self.capture if self.capture is not None else capture
        manifest, files, report = plan_single_export(
            capture if capture is not None else RuntimeError("The steps were not read."),
            part_step, request.title, request.writer, request.up_axis,
            size_table=self.table, listing=self._listing(), motion=self.motion, probe=probe_report,
            marker=request.marker, loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful],
            translated=final, health=health, also=self.also, derived=shadow)
        return PipelineResult(manifest, files, report, self.table, health)

    def _translate_and_measure(self, capture):
        """The stages that need a capture: the first translation, the sketch probe and the translation with the
        motion it found. Returns the final translation (a refusal included), or None when it failed."""
        self.capture = capture
        first_motion = OPTIMISTIC if covers_a_sketch(capture) else None
        first = self._translation(capture, first_motion)
        if first is None:
            return None
        if needs_reach(first):
            capture = self.capture = with_reach(self.port.read_reach, capture, first, self.port.log)
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
            self.roll = TryTimeline(self.port.store, self.port.log, self.request.faster_tries)
            probe = self.probe
            self.roll.begin([capture], lambda: probe.matches_start(probe.read_now()))
            tries = discovery_sizes(self.table, self.request.parameters, capture)
            found = self._measure(ProbeRun(self.port, self.tmp, self.probe), sizes, extra, tries)
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

    def _measure(self, run, sizes, extra=(), tries=()):
        """The probe's rows and its result: the sizes the probe cannot follow, or None when the probe failed.

        The rows put every size at the ends of its range where a size moves a sketch, then the sizes in `extra` (tried
        on a guess, `probe_flow.extra_size_params`) while rows are left. A row that does not build is tried again
        nearer to the value now (`ProbeRun.measure`). Rows still left try the unticked parameters
        in `tries` once each (`size_offers.discovery_sizes`); they only find which of them also change the part
        (`self.also`) and are not used for the motion. A failure other than a cancel
        leaves the translation without a motion (no size behind a sketch is then followed, by the translator's own
        rule) and is noted for the person. The parameters are put back, and the suppressed items turned back on,
        before the last read."""
        probe = self.probe
        try:
            run.measure(probe.probe_rows(sizes, extra), sizes)
            self.also = run.discover(tries)
            if self.roll is not None:
                self.roll.tries_done()
            self._restore()
            self._end_trim()
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

    def _unchecked(self):
        """What the restore check could not compare, for the health record."""
        return list(self.probe.restore_unchecked) if self.probe is not None else []

    def _close_probe(self):
        """The probe's record for `report.json`, or None when it did not run or failed."""
        if self.probe is None or self.probe_status != health_module.MEASURED:
            return None
        report = self.probe.report()
        if self.roll is not None and self.roll.record is not None:
            report["timeline"] = self.roll.record
        return report
