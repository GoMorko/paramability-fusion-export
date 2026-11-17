"""One export of one body: the stages from the capture to the manifest."""
import os
import traceback

from ...design_edit.runner import ExportCancelled
from ...params import size_table as size_tables
from ...params.listing import list_parameters
from ...sketch_values.motion import OPTIMISTIC
from ...timing.export_timing import ExportTiming
from .. import health as health_module
from ..body_scope import body_links, scope_inputs
from ..probe_flow import SizeProbe, covers_a_sketch, shadow_of, sizes_to_try
from ..reach_pass import needs_reach, with_reach
from ..orca_export import ORCA, plan_orca_export
from ..recipe_export import free_sizes, plan_single_export, translate_capture
from ..size_offers import discovery_sizes, labels
from .port import PipelineResult
from .probe_run import ProbeRun
from .put_back import PutBack


def run_pipeline(port, request, tmp):
    """The package of one export. `tmp` is a folder that holds the STEP file of the part until the package is written.

    Raises what a failing step raises (`RowBuildError`, `StepExportError`, `PackageCapError`, `ExportCancelled`,
    `MarkerError`); the parameters are back by then and `port.warn_unrestored` has named any that are not
    (`put_back.PutBack`)."""
    return _Pipeline(port, request, tmp).run()


class _Pipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.put_back = None  # `PutBack` of this export, from the start of `run`
        self.table = None
        self.capture = None  # the capture the translations used, with `reach` when steps were left out
        self.probe = None
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motion = None
        self.doubtful = []
        self.also = []
        self.timing = port.timing or ExportTiming()

    def run(self):
        self.put_back = PutBack.start(self.port, self.request, self.timing)
        try:
            result = self._run()
        except BaseException:
            self.put_back.close_failed()
            raise
        self.put_back.close(result.health)
        return result

    # ---- stages -----------------------------------------------------------------------------------------------

    def _run(self):
        if self.request.output == ORCA:
            return self._run_orca()
        port, request = self.port, self.request
        timing = self.timing
        part_step = os.path.join(self.tmp, "part.step")
        with timing.span("step_export"):
            port.export_step(part_step)
        with timing.span("capture"):
            capture = port.read_capture()
        with timing.span("size_table"):
            self.table = self._size_table(capture)

        final = self._translate_and_measure(capture) if isinstance(capture, dict) else None

        self.put_back.settle(self._restore_gap, self._outline_gap,
                             self._body_check if self.probe is not None else None)
        with timing.span("probe"):
            probe_report = self._close_probe()
            shadow = shadow_of(self.probe, port.log) if self.probe is not None else None
        flipped = self.motion.flipped if self.motion is not None else ()
        health = health_module.make_health(self.put_back.health_inputs(
            self.probe_status, self.probe_error, self._unchecked(), flipped, self._changed()))
        capture = self.capture if self.capture is not None else capture
        manifest, files, report = plan_single_export(
            capture if capture is not None else RuntimeError("The steps were not read."),
            part_step, request.title, request.writer, request.up_axis,
            size_table=self.table, listing=self._listing(), motion=self.motion, probe=probe_report,
            marker=request.marker, loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful],
            translated=final, health=health, also=self.also, derived=shadow, timing=self.timing)
        return PipelineResult(manifest, files, report, self.table, health)

    def _size_table(self, capture):
        model, quantities = scope_inputs(capture, self.request.model_params)
        return size_tables.build(
            self.request.parameters, self.request.ticked, model, self.request.design_unit, quantity_params=quantities,
            ranges=self.request.ranges, links=body_links(capture))

    def _run_orca(self):
        """The Orca output: the mesh of the part, the capture, the size table and one translation. No size tries:
        Orca follows only what the steps' own values and the simple sketches say, so nothing is measured, and the
        ranges of the dialog are not used. The design is put back and checked as for a recipe."""
        port, request, timing = self.port, self.request, self.timing
        with timing.span("step_export"):  # the mesh stands where the STEP of the part does
            mesh = port.read_mesh()
        with timing.span("capture"):
            capture = port.read_capture()
        with timing.span("size_table"):
            self.table = self._size_table(capture)
        final = None
        if isinstance(capture, dict):
            self.capture = capture
            final = self._translation(capture, None, "translate_final")
        self.put_back.settle(lambda: None, lambda: None)
        health = health_module.make_health(self.put_back.health_inputs(self.probe_status, "", [], ()))
        package = plan_orca_export(
            capture if capture is not None else RuntimeError("The steps were not read."), mesh, request.title,
            request.writer, request.up_axis, size_table=self.table, listing=self._listing(), health=health,
            marker=request.marker, translated=final, timing=self.timing)
        return PipelineResult(None, {}, package.report, self.table, health, orca=package)

    def _translate_and_measure(self, capture):
        """The stages that need a capture: the first translation, the sketch probe and the translation with the
        motion it found. Returns the final translation (a refusal included), or None when it failed."""
        self.capture = capture
        first_motion = OPTIMISTIC if covers_a_sketch(capture) else None
        first = self._translation(capture, first_motion, "translate_first")
        if first is None:
            return None
        if needs_reach(first):
            with self.timing.span("reach"):
                capture = self.capture = with_reach(self.port.read_reach, capture, first, self.port.log)
            first = self._translation(capture, first_motion, "translate_first")
            if first is None:
                return None
        if first.recipe is None:
            # The plan translates without a motion at this point, so the first look's refusal is its result only
            # when the first look had none either.
            return first if first_motion is None else None
        free = free_sizes(first.recipe)
        sizes, extra = sizes_to_try(self.table, self.request.parameters, free)

        with self.timing.span("probe"):
            self.probe = self._start_probe(capture)
            if self.probe is not None:
                probe = self.probe
                self.put_back.hold_timeline([capture], lambda: probe.matches_start(probe.read_now()))
                tries = discovery_sizes(self.table, self.request.parameters, capture)
                run = ProbeRun(self.port, self.tmp, self.probe, before_discovery=self.put_back.end_trim,
                               time_limit=self.request.probe_time_limit, clock=self.timing.clock)
                found = self._measure(run, sizes, extra, tries)
                if found is not None:
                    self.doubtful.extend(found)
        return self._translation(capture, self.motion, "translate_final")

    # ---- translation ------------------------------------------------------------------------------------------

    def _translation(self, capture, motion, phase):
        """The translator's result, a refusal included (the plan reports its reason without translating again), or
        None when the translator failed. Never raises. `phase` is the timing phase the time is added to."""
        try:
            with self.timing.span(phase):
                result = translate_capture(capture, self.request.up_axis, self.table, motion, timer=self.timing,
                                           output=self.request.output)
        except Exception as exc:
            self.port.log(f"translation failed: {exc!r}\n{traceback.format_exc()}")
            return None
        if getattr(result, "error_trace", None):
            self.port.log(f"translation stopped on an error:\n{result.error_trace}")
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
        on a guess, `probe_flow.sizes_to_try`) while rows are left. A row that does not build is tried again
        nearer to the value now (`ProbeRun.measure`). Rows still left try the unticked parameters
        in `tries` once each (`size_offers.discovery_sizes`); they only find which of them also change the part
        (`self.also`) and are not used for the motion. A failure other than a cancel
        leaves the translation without a motion (no size behind a sketch is then followed, by the translator's own
        rule) and is noted for the person. The design is put back before the last read, also when the tries fail or
        are cancelled (`PutBack.tries_done`, `PutBack.tries_ended`)."""
        probe = self.probe
        try:
            run.measure(probe.probe_rows(sizes, extra), sizes)
            self.also = run.discover(tries)
            self.put_back.tries_done(run)
            found = probe.finish(probe.read_now(), labels(self.table))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"size probe failed: {exc!r}")
            self.probe_status, self.probe_error = health_module.FAILED, repr(exc)
            self.motion = None
            return None
        finally:
            self.put_back.tries_ended(run)
        self.motion = probe.motion
        return found

    def _restore_gap(self):
        """How far the sketches are from their start after the last restore, or None when that cannot be told. Read
        again here because the probe rows changed the design once more; also after tries that failed, which can
        leave a sketch on another solution."""
        if self.probe is None:
            return None
        try:
            return self.probe.measure_restore(self.probe.read_now())
        except Exception as exc:
            self.port.log(f"reading the sketches after the restore failed: {exc!r}")
            return None

    def _outline_gap(self):
        """The sketch gap from a read of the outlines only, or None without a probe."""
        if self.probe is None:
            return None
        return self.probe.measure_restore(self.probe.read_now(outline=True))

    def _unchecked(self):
        """What the restore check could not compare, for the health record."""
        return list(self.probe.restore_unchecked) if self.probe is not None else []

    def _changed(self):
        """The sketches the restore check found on another outline, for the health record."""
        return list(self.probe.restore_changed) if self.probe is not None else []

    def _body_check(self):
        """What of the part's body differs from its start once the design is back (`SizeProbe.measure_body`)."""
        return self.probe.measure_body()

    def _close_probe(self):
        """The probe's record for `report.json`, or None when it did not run or failed."""
        if self.probe is None or self.probe_status != health_module.MEASURED:
            return None
        report = self.probe.report()
        timeline = self.put_back.timeline_record
        if timeline is not None:
            report["timeline"] = timeline
        return report
