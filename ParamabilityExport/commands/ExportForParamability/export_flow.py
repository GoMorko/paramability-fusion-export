"""What happens when the person clicks OK in Export for Paramability: ask where to save, run the export pipeline
(`export_plan.pipeline`) against Fusion, write the file and show the result.

The export is the STEP of the part as it is, the capture of its steps, the sketch measuring, one translation with
the motion it gave, and the file (`export_plan.pipeline` describes the sequence).

The measuring changes parameters; the pipeline puts every parameter back whatever happens. A body inside a component
is handled the same way: its sketches are read at every measuring row.
"""
import os
import tempfile
import time

from ...lib.export_plan import health as health_module
from ...lib.design_edit.marker import read_marker
from ...lib.package.naming import body_file_title, component_names, design_title, package_file_name
from ...lib.export_plan.pipeline import ExportRequest, run_parts_pipeline, run_pipeline
from ...lib.export_plan import undo_steps
from ...lib.export_plan.time_limit import DEFAULT_SECONDS
from ...lib.dialog_model.result_rows import parts_result_view, result_view
from ...lib.dialog_model.stop_warning import saved_message, status_text
from ...lib.fusion_reader import design_info
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.probe_state import read_state
from ...lib.fusion_reader.read_gap_reach import read_reach
from ...lib.fusion_reader.read_geometry import ReadContext
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.sketch_keep import SketchKeeper
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui import result_dialog
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import log, message_box
from ...lib.fusion_ui.notice import status_notice
from ...lib.package.writer import write_package
from ...lib.timing.capture_timer import CaptureTimer
from ...lib.timing.export_timing import ExportTiming
from .. import export_common


def _read_capture(design, current, timer=None):
    """The capture, or the exception that stopped it. Only a lost timeline marker is not swallowed. `timer` is the
    `CaptureTimer` that gets the time of the read."""
    try:
        return read_capture(design, current, timer=timer)
    except MarkerError:
        raise
    except Exception as exc:
        log(f"capture failed: {exc!r}")
        return exc


def _timed_capture(design, current, timing, part=None):
    """`_read_capture`, with the time of the read noted in `timing` (an `ExportTiming`)."""
    timer = CaptureTimer()
    capture = _read_capture(design, current, timer)
    timing.note_capture(timer.summary(), part)
    return capture


def _same_marker(capture, design):
    """True when the capture was read with the timeline marker where it is now."""
    now = read_marker(design.timeline)
    return now is None or capture.get("marker") == now


class CaptureCache:
    """The capture of each picked body. The dialog reads it to scope the parameters to the body, and the export
    reuses it when it is still the same dialog and the marker has not moved. A failed read is not kept. The time of
    each read is kept too and goes to the export's timing (`timing`) as the time of a read made earlier."""

    def __init__(self, design):
        self._design = design
        self._read = {}
        self._summaries = {}

    def clear(self):
        """Drop every capture read so far; the dialog calls it when it closes, so the reads do not stay in memory
        until the next export."""
        self._read.clear()
        self._summaries.clear()

    def read_seconds(self, body):
        """Seconds the read of `body` took (`CaptureTimer.summary`), or None when it was not read."""
        found = self._summaries.get(body.entityToken)
        return found.get("seconds") if isinstance(found, dict) else None

    def get(self, body, timing=None, part=None):
        token = body.entityToken
        cached = self._read.get(token)
        if isinstance(cached, dict) and _same_marker(cached, self._design):
            if timing is not None:
                timing.note_capture(self._summaries.get(token), part, cached=True)
            return cached
        timer = CaptureTimer()
        capture = _read_capture(self._design, resolve_body(self._design, token, body), timer)
        self._read[token] = capture
        self._summaries[token] = timer.summary()
        if timing is not None:
            timing.note_capture(self._summaries[token], part)
        return capture


def _timed_reader(port, ctx):
    """`read(request)` of one probe state; a read times its parts on the port's `read_timer`, which
    `pipeline.ProbeRun` sets only while it reads."""
    def read(request):
        ctx.timer = port.read_timer
        return read_state(port.design, request, ctx)
    return read


class FusionPort:
    """The pipeline's door to Fusion (`export_plan.pipeline.ExportPort`) for one picked body."""

    undo_steps = None  # set by `undo_steps.attach`
    read_timer = None  # lent by `pipeline.ProbeRun` while it reads

    def __init__(self, design, body, units, captures=None):
        self.design, self.body, self.token, self.units = design, body, body.entityToken, units
        self.store = DesignParameterStore(design)
        self._captures = captures
        self.timing = ExportTiming()

    def _current(self):
        return resolve_body(self.design, self.token, self.body)

    def export_step(self, path):
        export_body_step(self.design, self._current(), path)

    def read_capture(self):
        if self._captures is not None:
            return self._captures.get(self.body, self.timing)
        return _timed_capture(self.design, self._current(), self.timing)

    def read_reach(self, capture, gaps):
        return read_reach(self.design, capture, gaps)

    def probe_reader(self):
        return _timed_reader(self, ReadContext(self.design, self._current()))

    def sketch_keeper(self, tokens):
        return SketchKeeper(self.design, tokens)

    def progress(self, verb):
        return export_common.progress_dialog(verb)

    def warn_unrestored(self, names):
        export_common.warn_unrestored(names)

    def warn_left_off(self, names, undo_dropped=False):
        export_common.warn_left_off(names, undo_dropped)

    def warn_steps(self, lines):
        export_common.warn_steps(lines)

    def log(self, text):
        log(text)


class FusionPartsPort:
    """The parts pipeline's door to Fusion (`export_plan.pipeline.PartsPort`) for several picked bodies."""

    undo_steps = None  # set by `undo_steps.attach`
    read_timer = None  # lent by `pipeline.ProbeRun` while it reads

    def __init__(self, design, bodies, units, captures=None):
        self.design, self.bodies, self.units = design, list(bodies), units
        self.tokens = [b.entityToken for b in self.bodies]
        self.count = len(self.bodies)
        self.store = DesignParameterStore(design)
        self._captures = captures
        self.timing = ExportTiming()

    def _current(self, index):
        return resolve_body(self.design, self.tokens[index], self.bodies[index])

    def body_names(self):
        root = self.design.rootComponent
        return [body_label(b, root) for b in self.bodies]

    def export_step(self, index, path):
        export_body_step(self.design, self._current(index), path)

    def read_capture(self, index):
        part = self.body_names()[index]
        if self._captures is not None:
            return self._captures.get(self.bodies[index], self.timing, part)
        return _timed_capture(self.design, self._current(index), self.timing, part)

    def read_reach(self, index, capture, gaps):
        return read_reach(self.design, capture, gaps)

    def probe_reader(self, index):
        return _timed_reader(self, ReadContext(self.design, self._current(index)))

    def sketch_keeper(self, tokens):
        return SketchKeeper(self.design, tokens)

    def progress(self, verb):
        return export_common.progress_dialog(verb)

    def warn_unrestored(self, names):
        export_common.warn_unrestored(names)

    def warn_left_off(self, names, undo_dropped=False):
        export_common.warn_left_off(names, undo_dropped)

    def warn_steps(self, lines):
        export_common.warn_steps(lines)

    def log(self, text):
        log(text)


def body_label(body, root):
    """The name a picked body has in the file: the name of its component when that holds only this body, else the
    component and body names, or the body name for a body of the root. Never raises."""
    try:
        name = body.name
        component = body.parentComponent
        if component.entityToken == root.entityToken:
            return name
        return component.name if component.bRepBodies.count == 1 else "%s %s" % (component.name, name)
    except Exception:
        try:
            return body.name
        except Exception:
            return ""


PENDING_POSITION_MESSAGE = (
    "Capture the position of moved parts first (Position, Capture Position), then export again.")


def position_pending(design):
    """True when parts were moved by hand and the position is not captured. An unreadable answer counts as no.

    It has to be asked before any read that moves the timeline marker, since that can drop a pending move."""
    try:
        return bool(design.snapshots.hasPendingSnapshot)
    except Exception:
        return False


def _show_result(file_name, result, ticked, parts=False):
    """The result dialog for a recipe. A part saved as a fixed shape (or a dialog that cannot start) gets the message
    box, which starts with the stopping step, and then a line in Fusion's status area. A design that may be changed
    gets its own message box first.

    The file is saved by now, so nothing here may report a failed export."""
    manifest, report, health = result.manifest, result.report, result.health
    try:
        make_view = parts_result_view if parts else result_view
        view = make_view(file_name, manifest, report, result.table, ticked)
    except Exception as exc:
        log(f"result view failed: {exc!r}")
        view = None
    if view is None:
        try:
            if parts:
                text, notice = "Saved %s. %s" % (file_name, " ".join(manifest.get("notes") or [])), ""
            else:
                text, notice = saved_message(manifest, report, file_name), status_text(report)
        except Exception as exc:
            log(f"saved message failed: {exc!r}")
            text, notice = "Saved %s." % file_name, ""
        message_box(health_module.with_lines(text, health), error=health_module.design_changed(health))
        status_notice(notice)
    else:
        if health_module.design_changed(health):
            message_box("\n\n".join(health_module.health_lines(health)), error=True)
        result_dialog.show(view)


def run_export(design, parameters, model_params, design_unit, form, captures=None, timeline_start=None, command=None):
    """Run one export. Parameters are always put back before this returns.

    `captures` is the dialog's CaptureCache; a capture it already holds for the picked body is not read again.
    `timeline_start` is the timeline steps read when the dialog opened (`timeline_health.read_timeline`), before the
    dialog's capture moved the marker; the export compares the steps with it at the end.
    `command` is the running Fusion command; with the dialog's "lighter on memory" box on, the tries end its steps
    without undo data (`undo_steps`)."""
    app = export_common.app()
    bodies = form["bodies"]
    body = form["body"]
    if not bodies:
        message_box("Pick a body to export.")
        return
    if position_pending(design):
        message_box(PENDING_POSITION_MESSAGE)
        return
    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(body_file_title(title, component_names(bodies))))
    if out_path is None:
        return

    marker = read_marker(design.timeline)
    request = ExportRequest(
        title=title, writer=export_common.writer_for(app), up_axis=form["up_axis"], parameters=parameters,
        model_params=model_params, design_unit=design_unit, ticked=form["ticked"], ranges=form["ranges"],
        marker=marker, faster_tries=bool(form.get("faster_tries", True)), timeline_start=timeline_start,
        probe_time_limit=form.get("probe_time_limit", DEFAULT_SECONDS))

    units = {p["name"]: p["unit"] for p in parameters}
    steps = undo_steps.command_steps(command, log) if form.get("light_undo") else None

    def work():
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            if body is not None:
                result = run_pipeline(undo_steps.attach(FusionPort(design, body, units, captures), steps), request, tmp)
            else:
                result = run_parts_pipeline(
                    undo_steps.attach(FusionPartsPort(design, bodies, units, captures), steps), request, tmp)
            written = time.perf_counter()
            write_package(out_path, result.manifest, result.files)
            log("package written in %.2f s" % (time.perf_counter() - written))
        return os.path.basename(out_path), result

    saved = export_common.run_guarded(design, marker, work)
    if saved is not None:
        _show_result(saved[0], saved[1], form["ticked"], parts=body is None)
