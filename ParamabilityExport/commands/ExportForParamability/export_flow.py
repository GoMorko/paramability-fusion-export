"""What happens when the person clicks OK in Export for Paramability.

Order: the STEP of the part as it is, the capture of its steps, a first translation that shows which sizes the
recipe keeps, one check STEP per kept size, then the translation again with what the checks found, and the file. The
checks change parameters one at a time; RowExport puts every parameter back whatever happens.
"""
import os
import tempfile

from ...lib.export_plan.apply import RowBuildError
from ...lib.export_plan.body_scope import other_sketches, scope_inputs
from ...lib.export_plan.errors import StepExportError
from ...lib.export_plan.messages import recipe_saved_message
from ...lib.export_plan.naming import design_title, package_file_name
from ...lib.export_plan.recipe_export import free_sizes, plan_single_export, translate_capture
from ...lib.export_plan.runner import ExportCancelled, RowExport
from ...lib.export_plan.size_checks import plan_checks, read_checks
from ...lib.export_plan.size_offers import labels, sizes_for_checks
from ...lib.export_plan.temp_copy import MARKER_MESSAGE, marker_at_end
from ...lib.fusion_reader import design_info
from ...lib.fusion_reader.bodies import is_root_body
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.sketches import read_sketches
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import error_box, log, message_box
from ...lib.fusion_ui.progress import ProgressDialog
from ...lib.package.caps import PackageCapError
from ...lib.package.writer import write_package
from ...lib.params import size_table as size_tables
from ...lib.params.listing import list_parameters
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


class CaptureCache:
    """The capture of each picked body. The dialog reads it to scope the parameters to the body, and the export
    reuses it when it is still the same dialog. A failed read is not kept."""

    def __init__(self, design):
        self._design = design
        self._read = {}

    def get(self, body):
        token = body.entityToken
        cached = self._read.get(token)
        if isinstance(cached, dict):
            return cached
        capture = _read_capture(self._design, resolve_body(self._design, token, body))
        self._read[token] = capture
        return capture


def _run_checks(design, store, units, body, token, checks, tmp, job_box, skip_sketches):
    """Export one STEP per check. Returns (results, sketch numbers per check row, the job)."""
    snapshots = {}
    root = design.rootComponent

    def export_check(path):
        export_body_step(design, resolve_body(design, token, body), path)
        snapshots[job.current_row] = read_sketches(root, skip_sketches)

    job = RowExport(store, units, export_check)
    job_box.append(job)
    os.makedirs(os.path.join(tmp, "checks"), exist_ok=True)
    with ProgressDialog("Export for Paramability", verb="Checking") as progress:
        results = job.run([c["row"] for c in checks], os.path.join(tmp, "checks"), progress.step,
                          tolerate_build_errors=True)
    return results, snapshots


def _first_translation(capture, up_axis, table):
    """The translator's result when it gives a recipe, else None (the plan then reports the reason)."""
    try:
        result = translate_capture(capture, up_axis, table)
    except Exception as exc:
        log(f"first translation failed: {exc!r}")
        return None
    return result if result.recipe is not None else None


def _parameter_listing(parameters, model_params, design_unit):
    """The design's parameters for the manifest, or None when they cannot be listed. Never stops the export."""
    try:
        return list_parameters(parameters, model_params, design_unit)
    except Exception as exc:
        log(f"parameter list failed: {exc!r}")
        return None


def run_export(design, parameters, model_params, design_unit, form, captures=None):
    """Run one export. Parameters are always put back before this returns.

    `captures` is the dialog's CaptureCache; a capture it already holds for the picked body is not read again."""
    app = export_common.app()
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
    in_component = not is_root_body(body, design.rootComponent)
    jobs = []
    try:
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            part_step = os.path.join(tmp, "part.step")
            current = resolve_body(design, token, body)
            export_body_step(design, current, part_step)
            # The translator reads root timeline features only; a body in a component stays a fixed shape.
            if in_component:
                capture = None
            elif captures is not None:
                capture = captures.get(body)
            else:
                capture = _read_capture(design, current)

            model, quantities = scope_inputs(capture, model_params)
            table = size_tables.build(
                parameters, form["ticked"], model, design_unit, quantity_params=quantities)

            checks, kept, measured, unchecked = [], [], [], []
            if isinstance(capture, dict):
                # Checks go only to the sizes the recipe keeps after translation.
                first = _first_translation(capture, form["up_axis"], table)
                if first is not None:
                    sizes = sizes_for_checks(table, parameters, keep=free_sizes(first.recipe))
                    checks, not_checked = plan_checks(sizes)
                    unchecked = [s["size"] for s in not_checked]
                if checks:
                    skip = other_sketches(capture)
                    baseline = read_sketches(design.rootComponent, skip)
                    results, snapshots = _run_checks(
                        design, DesignParameterStore(design), units, body, token, checks, tmp, jobs, skip)
                    kept, measured = read_checks(checks, results, baseline, snapshots, labels(table))
                    if measured:
                        table = table.with_fixed({m["param"]: m["reason"] for m in measured})

            manifest, files, _report = plan_single_export(
                capture if capture is not None else RuntimeError("The steps were not read."),
                part_step, title, export_common.writer_for(app), form["up_axis"], in_component=in_component,
                size_table=table, checks=kept,
                fixed=[{"name": m["name"], "reason": m["reason"]} for m in measured], unchecked=unchecked,
                listing=_parameter_listing(parameters, model_params, design_unit))
            write_package(out_path, manifest, files)
        message_box(recipe_saved_message(manifest, os.path.basename(out_path)))
    except ExportCancelled:
        message_box("Export cancelled. Your parameters are back to their values.")
    except (RowBuildError, StepExportError, PackageCapError, MarkerError) as exc:
        message_box(f"{exc}\n\nNothing was saved. Your parameters are back to their values.", error=True)
    except Exception:
        error_box("The export stopped. Nothing was saved.")
    finally:
        for job in jobs:
            export_common.warn_unrestored(job)
