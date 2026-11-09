"""What happens when the person clicks OK in Export for Paramability: ask where to save, run the export pipeline
(`export_plan.pipeline`) against Fusion, write the file and show the result.

Plain export (the default): the STEP of the part as it is, the capture of its steps, the sketch measuring, one
translation with the motion it gave, and the file. There are no size checks and no shortened ranges. Checked export
("Check sizes in Fusion") adds the size checks and a second translation; `export_plan.pipeline` describes both.

Each run changes parameters; the pipeline puts every parameter back whatever happens. A body inside a component is
handled the same way: its sketches and its place in the assembly are read at every check.
"""
import os
import tempfile

from ...lib.export_plan import health as health_module
from ...lib.export_plan.marker import read_marker
from ...lib.export_plan.naming import design_title, package_file_name
from ...lib.export_plan.pipeline import ExportRequest, run_pipeline
from ...lib.export_plan.result_rows import result_view
from ...lib.export_plan.size_checks import PLACEMENT_KEY, frame_numbers
from ...lib.export_plan.stop_warning import saved_message, status_text
from ...lib.fusion_reader import design_info, placement
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.probe_state import read_state
from ...lib.fusion_reader.read_geometry import ReadContext
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.sketches import read_sketches
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui import result_dialog
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import log, message_box
from ...lib.fusion_ui.notice import status_notice
from ...lib.fusion_ui.progress import ProgressDialog
from ...lib.package.writer import write_package
from .. import export_common


def _read_capture(design, current):
    """The capture, or the exception that stopped it. Only a lost timeline marker is not swallowed."""
    try:
        return read_capture(design, current)
    except MarkerError:
        raise
    except Exception as exc:
        log(f"capture failed: {exc!r}")
        return exc


def _same_marker(capture, design):
    """True when the capture was read with the timeline marker where it is now."""
    now = read_marker(design.timeline)
    return now is None or capture.get("marker") == now


class CaptureCache:
    """The capture of each picked body. The dialog reads it to scope the parameters to the body, and the export
    reuses it when it is still the same dialog and the marker has not moved. A failed read is not kept."""

    def __init__(self, design):
        self._design = design
        self._read = {}

    def get(self, body):
        token = body.entityToken
        cached = self._read.get(token)
        if isinstance(cached, dict) and _same_marker(cached, self._design):
            return cached
        capture = _read_capture(self._design, resolve_body(self._design, token, body))
        self._read[token] = capture
        return capture


class FusionPort:
    """The pipeline's door to Fusion (`export_plan.pipeline.ExportPort`) for one picked body."""

    def __init__(self, design, body, units, captures=None):
        self.design, self.body, self.token, self.units = design, body, body.entityToken, units
        self.store = DesignParameterStore(design)
        self._captures = captures

    def _current(self):
        return resolve_body(self.design, self.token, self.body)

    def _component(self):
        try:
            return self.body.parentComponent
        except Exception:
            return self.design.rootComponent

    def export_step(self, path):
        export_body_step(self.design, self._current(), path)

    def read_capture(self):
        if self._captures is not None:
            return self._captures.get(self.body)
        return _read_capture(self.design, self._current())

    def snapshot(self, skip, source):
        """The sketches of the body's component, plus its place in the assembly when that can be read."""
        state = read_sketches(self._component(), skip)
        frame = placement.read_frame(self._current(), source) if source else None
        if frame is not None:
            state[PLACEMENT_KEY] = frame_numbers(frame)
        return state

    def probe_reader(self):
        ctx = ReadContext(self.design, self._current())
        return lambda request: read_state(self.design, request, ctx)

    def progress(self, verb):
        return ProgressDialog("Export for Paramability", verb=verb)

    def warn_unrestored(self, names):
        export_common.warn_unrestored(names)

    def log(self, text):
        log(text)


PENDING_POSITION_MESSAGE = (
    "Capture the position of moved parts first (Position, Capture Position), then export again.")


def position_pending(design):
    """True when parts were moved by hand and the position is not captured. An unreadable answer counts as no.

    It has to be asked before any read that moves the timeline marker, since that can drop a pending move."""
    try:
        return bool(design.snapshots.hasPendingSnapshot)
    except Exception:
        return False


def _show_result(file_name, result, ticked):
    """The result dialog for a recipe. A part saved as a fixed shape (or a dialog that cannot start) gets the message
    box, which starts with the stopping step, and then a line in Fusion's status area. A design that may be changed
    gets its own message box first.

    The file is saved by now, so nothing here may report a failed export."""
    manifest, report, health = result.manifest, result.report, result.health
    try:
        view = result_view(file_name, manifest, report, result.table, ticked)
    except Exception as exc:
        log(f"result view failed: {exc!r}")
        view = None
    if view is None:
        try:
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


def run_export(design, parameters, model_params, design_unit, form, captures=None):
    """Run one export. Parameters are always put back before this returns.

    `captures` is the dialog's CaptureCache; a capture it already holds for the picked body is not read again."""
    app = export_common.app()
    body = form["body"]
    if body is None:
        message_box("Pick a body to export.")
        return
    if position_pending(design):
        message_box(PENDING_POSITION_MESSAGE)
        return
    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(title))
    if out_path is None:
        return

    marker = read_marker(design.timeline)
    request = ExportRequest(
        title=title, writer=export_common.writer_for(app), up_axis=form["up_axis"], parameters=parameters,
        model_params=model_params, design_unit=design_unit, ticked=form["ticked"], ranges=form["ranges"],
        check_sizes=bool(form.get("check_sizes")), keep_doubtful=bool(form.get("keep_doubtful")), marker=marker)

    def work():
        port = FusionPort(design, body, {p["name"]: p["unit"] for p in parameters}, captures)
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            result = run_pipeline(port, request, tmp)
            write_package(out_path, result.manifest, result.files)
        return os.path.basename(out_path), result

    saved = export_common.run_guarded(design, marker, work)
    if saved is not None:
        _show_result(saved[0], saved[1], form["ticked"])
