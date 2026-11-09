"""What happens when the person clicks OK: read sizes, ask where to save, export each size, write the file."""
import os
import tempfile

import adsk.core

from ... import config
from ...lib.export_plan.apply import RowBuildError
from ...lib.export_plan.assemble import build_package
from ...lib.export_plan.naming import (
    addin_version, design_title, package_file_name, saved_message, writer_text)
from ...lib.export_plan.recipe_export import plan_single_export, recipe_saved_message
from ...lib.export_plan.runner import ExportCancelled, RowExport
from ...lib.export_plan.sizes_text import pick_default_index, read_sizes
from ...lib.fusion_reader import design_info
from ...lib.fusion_reader.bodies import is_root_body
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.export_plan.errors import StepExportError
from ...lib.export_plan.temp_copy import marker_at_end, MARKER_MESSAGE
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import error_box, log, message_box
from ...lib.fusion_ui.progress import ProgressDialog
from ...lib.package.caps import PackageCapError
from ...lib.package.writer import write_package

_ADDIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_export(design, parameters, form):
    """Run one export. Parameters are always put back before this returns."""
    app = adsk.core.Application.get()
    read = read_sizes(form["sizes_text"], parameters)
    if read.problems:
        message_box("The sizes need a fix:\n\n" + "\n".join(read.problems))
        return
    body = form["body"]
    if body is None:
        message_box("Pick a body to export.")
        return

    if not marker_at_end(design.timeline):
        message_box(MARKER_MESSAGE)
        return

    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(title))
    if out_path is None:
        return

    units = {p["name"]: p["unit"] for p in parameters}
    token = body.entityToken
    store = DesignParameterStore(design)

    as_recipe = bool(form.get("as_recipe")) and len(read.rows) == 1
    # The translator reads root timeline features only; a body in a component stays a fixed shape.
    in_component = as_recipe and not is_root_body(body, design.rootComponent)
    captured = {}

    def export_step(path):
        current = resolve_body(design, token, body)
        export_body_step(design, current, path)
        if as_recipe and not in_component:
            # Read while the size values are applied, so the recipe matches the STEP. A failure only costs the recipe.
            try:
                captured["value"] = read_capture(design, current, up_axis=form["up_axis"])
            except MarkerError:
                raise
            except Exception as exc:
                log(f"capture failed: {exc!r}")
                captured["value"] = exc

    job = RowExport(store, units, export_step)
    try:
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            with ProgressDialog("Export for Paramability") as progress:
                results = job.run(read.rows, tmp, progress.step)
            default_index = pick_default_index(read.rows, form["default_name"])
            writer = writer_text(
                addin_version(os.path.join(_ADDIN_DIR, config.ADDIN_NAME + ".manifest")),
                design_info.fusion_version(app))
            if as_recipe:
                manifest, files, _report = plan_single_export(
                    captured.get("value", RuntimeError("The steps were not read.")), results[0]["step_file"],
                    title, writer, form["up_axis"], in_component=in_component)
                message = recipe_saved_message(manifest, os.path.basename(out_path))
            else:
                manifest, files = build_package(
                    title, writer, results, read.columns, parameters, default_index,
                    form["choice_name"], form["up_axis"])
                message = saved_message(len(results), os.path.basename(out_path))
            write_package(out_path, manifest, files)
        message_box(message)
    except ExportCancelled:
        message_box("Export cancelled. Your parameters are back to their values.")
    except (RowBuildError, StepExportError, PackageCapError, MarkerError) as exc:
        message_box(f"{exc}\n\nNothing was saved. Your parameters are back to their values.", error=True)
    except Exception:
        error_box("The export stopped. Nothing was saved.")
    finally:
        if job.restore_failures:
            names = ", ".join(job.restore_failures)
            log(f"could not restore: {names}")
            message_box(
                "These parameters could not be set back, please check them: " + names
                + ".\nUse Undo in Fusion if they look wrong.", error=True)
