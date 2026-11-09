"""What happens when the person clicks OK in Export size choices: read the sizes, ask where to save, export each
size, write the file. One size gives a plain part; two or more give a dropdown of ready-made sizes."""
import os
import tempfile

from ...lib.export_plan.assemble import build_package
from ...lib.package.naming import design_title, package_file_name, saved_message
from ...lib.design_edit.runner import RowExport
from ...lib.dialog_model.sizes_text import pick_default_index, read_sizes
from ...lib.design_edit.marker import read_marker
from ...lib.fusion_reader import design_info
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import message_box
from ...lib.fusion_ui.progress import ProgressDialog
from ...lib.package.writer import write_package
from .. import export_common


def run_export(design, parameters, form):
    """Run one export. Parameters are always put back before this returns."""
    app = export_common.app()
    read = read_sizes(form["sizes_text"], parameters)
    if read.problems:
        message_box("The sizes need a fix:\n\n" + "\n".join(read.problems))
        return
    body = form["body"]
    if body is None:
        message_box("Pick a body to export.")
        return

    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(title))
    if out_path is None:
        return

    units = {p["name"]: p["unit"] for p in parameters}
    token = body.entityToken
    marker = read_marker(design.timeline)
    store = DesignParameterStore(design)

    def export_step(path):
        export_body_step(design, resolve_body(design, token, body), path)

    job = RowExport(store, units, export_step)

    def work():
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            with ProgressDialog("Export size choices") as progress:
                results = job.run(read.rows, tmp, progress.step)
            default_index = pick_default_index(read.rows, form["default_name"])
            manifest, files = build_package(
                title, export_common.writer_for(app), results, read.columns, parameters, default_index,
                form["choice_name"], form["up_axis"], design_info.default_length_unit(design))
            write_package(out_path, manifest, files)
        message_box(saved_message(len(results), os.path.basename(out_path)))

    export_common.run_guarded(design, marker, work, lambda: job.restore_failures)
