"""What happens when the person clicks OK in Export for Paramability: ask where to save, run the export pipeline
(`export_plan.pipeline`) against Fusion, write the file and show the result.

The export is the STEP of the part as it is, the capture of its steps, the sketch measuring, one translation with
the motion it gave, and the file (`export_plan.pipeline` describes the sequence).

The measuring changes parameters; the pipeline puts every parameter back whatever happens. A body inside a component
is handled the same way: its sketches are read at every measuring row.
"""
import os
import tempfile

from ...lib.export_plan import health as health_module
from ...lib.design_edit.marker import read_marker
from ...lib.package.naming import design_title, package_file_name
from ...lib.export_plan.pipeline import ExportRequest, run_pipeline
from ...lib.export_plan.parts_pipeline import run_parts_pipeline
from ...lib.dialog_model.result_rows import parts_result_view, result_view
from ...lib.dialog_model.stop_warning import saved_message, status_text
from ...lib.fusion_reader import design_info
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.probe_state import read_state
from ...lib.fusion_reader.read_gap_reach import read_reach
from ...lib.fusion_reader.read_geometry import ReadContext
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui import result_dialog
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import log, message_box
from ...lib.fusion_ui.notice import status_notice
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

    def export_step(self, path):
        export_body_step(self.design, self._current(), path)

    def read_capture(self):
        if self._captures is not None:
            return self._captures.get(self.body)
        return _read_capture(self.design, self._current())

    def read_reach(self, capture, gaps):
        return read_reach(self.design, capture, gaps)

    def probe_reader(self):
        ctx = ReadContext(self.design, self._current())
        return lambda request: read_state(self.design, request, ctx)

    def progress(self, verb):
        return export_common.progress_dialog(verb)

    def warn_unrestored(self, names):
        export_common.warn_unrestored(names)

    def log(self, text):
        log(text)


class FusionPartsPort:
    """The parts pipeline's door to Fusion (`export_plan.parts_pipeline.PartsPort`) for several picked bodies."""

    def __init__(self, design, bodies, units, captures=None):
        self.design, self.bodies, self.units = design, list(bodies), units
        self.tokens = [b.entityToken for b in self.bodies]
        self.count = len(self.bodies)
        self.store = DesignParameterStore(design)
        self._captures = captures

    def _current(self, index):
        return resolve_body(self.design, self.tokens[index], self.bodies[index])

    def body_names(self):
        root = self.design.rootComponent
        return [body_label(b, root) for b in self.bodies]

    def export_step(self, index, path):
        export_body_step(self.design, self._current(index), path)

    def read_capture(self, index):
        if self._captures is not None:
            return self._captures.get(self.bodies[index])
        return _read_capture(self.design, self._current(index))

    def read_reach(self, index, capture, gaps):
        return read_reach(self.design, capture, gaps)

    def probe_reader(self, index):
        ctx = ReadContext(self.design, self._current(index))
        return lambda request: read_state(self.design, request, ctx)

    def progress(self, verb):
        return export_common.progress_dialog(verb)

    def warn_unrestored(self, names):
        export_common.warn_unrestored(names)

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


def run_export(design, parameters, model_params, design_unit, form, captures=None):
    """Run one export. Parameters are always put back before this returns.

    `captures` is the dialog's CaptureCache; a capture it already holds for the picked body is not read again."""
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
    out_path = ask_save_path(package_file_name(title))
    if out_path is None:
        return

    marker = read_marker(design.timeline)
    request = ExportRequest(
        title=title, writer=export_common.writer_for(app), up_axis=form["up_axis"], parameters=parameters,
        model_params=model_params, design_unit=design_unit, ticked=form["ticked"], ranges=form["ranges"],
        marker=marker)

    units = {p["name"]: p["unit"] for p in parameters}

    def work():
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            if body is not None:
                result = run_pipeline(FusionPort(design, body, units, captures), request, tmp)
            else:
                result = run_parts_pipeline(FusionPartsPort(design, bodies, units, captures), request, tmp)
            write_package(out_path, result.manifest, result.files)
        return os.path.basename(out_path), result

    saved = export_common.run_guarded(design, marker, work)
    if saved is not None:
        _show_result(saved[0], saved[1], form["ticked"], parts=body is None)
