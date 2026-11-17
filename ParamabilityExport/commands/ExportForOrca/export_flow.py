"""What happens when the person clicks OK in Export for Orca: ask where to save, run the export pipeline with the
Orca output (`ExportRequest.output`), write the `.3mf` and show the result.

The pipeline reads the mesh of the part, the capture and the size table, translates once (no size tries), puts the
design back and checks it, as for a recipe (`export_plan.pipeline`).
"""
import os
import tempfile

from ...lib.dialog_model.orca_result import orca_view
from ...lib.design_edit.marker import read_marker
from ...lib.export_plan import health as health_module
from ...lib.export_plan import rollback, undo_steps
from ...lib.export_plan.orca_export import ORCA, write_orca_package
from ...lib.export_plan.pipeline import ExportRequest, run_pipeline
from ...lib.fusion_reader import design_info
from ...lib.fusion_ui import result_dialog
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import log, message_box
from ...lib.package.naming import ORCA_EXTENSION, body_file_title, component_names, design_title, package_file_name
from .. import export_common
from ..ExportForParamability.export_flow import PENDING_POSITION_MESSAGE, FusionPort, position_pending


def _show_result(file_name, result, ticked, undo=rollback.NO_ROLLBACK):
    """The result dialog; the message box when the view cannot be made. The file is saved by now. When the export is
    undone (`undo`, `export_plan.rollback`) the check lines say so."""
    try:
        view = orca_view(file_name, result.report, ticked, undo)
    except Exception as exc:
        log(f"Orca result view failed: {exc!r}")
        message_box("Saved %s." % file_name)
        return
    if health_module.design_changed(result.health) or undo.abort:
        message_box("\n\n".join(rollback.check_lines(result.health, undo)), error=True)
    result_dialog.show(view)


def run_export(design, parameters, model_params, design_unit, form, captures=None, timeline_start=None,
               outcome=None):
    """Run one Orca export of the one picked body and return its `rollback.ExportOutcome`. Never raises. Parameters
    are always put back before this returns. `outcome` is the record the export fills in (made here when None); the
    caller reads it to tell Fusion to undo the export when the design is not back (`rollback.ExecuteGate`)."""
    outcome = rollback.ExportOutcome() if outcome is None else outcome
    return export_common.contained(outcome, lambda: _run_export(
        design, parameters, model_params, design_unit, form, captures, timeline_start, outcome))


def _run_export(design, parameters, model_params, design_unit, form, captures, timeline_start, outcome):
    app = export_common.app()
    body = form["body"]
    if body is None:
        message_box("Pick one body to export.")
        return
    if position_pending(design):
        message_box(PENDING_POSITION_MESSAGE)
        return
    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(body_file_title(title, component_names([body])), ORCA_EXTENSION),
                             orca=True)
    if out_path is None:
        return

    marker = read_marker(design.timeline)
    request = ExportRequest(
        title=title, writer=export_common.writer_for(app), up_axis=form["up_axis"], parameters=parameters,
        model_params=model_params, design_unit=design_unit, ticked=form["ticked"], ranges={}, marker=marker,
        faster_tries=False, timeline_start=timeline_start, probe_time_limit=None, output=ORCA, outcome=outcome)
    units = {p["name"]: p["unit"] for p in parameters}

    def work():
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            result = run_pipeline(undo_steps.attach(FusionPort(design, body, units, captures), None), request, tmp)
        write_orca_package(out_path, result.orca)
        return os.path.basename(out_path), result

    saved = export_common.run_guarded(design, marker, work)
    undo = rollback.decide(outcome)
    if saved is not None:
        _show_result(saved[0], saved[1], form["ticked"], undo)
    elif undo.abort:
        export_common.tell_undone(undo)
