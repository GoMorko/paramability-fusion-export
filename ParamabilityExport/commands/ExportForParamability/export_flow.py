"""What happens when the person clicks OK in Export for Paramability.

Order: the STEP of the part as it is, the capture of its steps, a first translation that shows which sizes the
recipe keeps, one check STEP per kept size, extra rows that only recompute (to see how sketches move with sizes),
then the translation again with what these found, and the file. Each run changes parameters; RowExport puts every
parameter back whatever happens. A body inside a component is handled the same way: its sketches and its place in
the assembly are read at every check.
"""
import os
import tempfile

from ...lib.export_plan.apply import RowBuildError
from ...lib.export_plan.body_scope import other_sketch_names, scope_inputs
from ...lib.export_plan.errors import StepExportError
from ...lib.export_plan.stop_warning import saved_message, status_text
from ...lib.export_plan.result_rows import result_view
from ...lib.export_plan.naming import design_title, package_file_name
from ...lib.export_plan.probe_flow import SizeProbe, covers_a_sketch, kept_size_names
from ...lib.export_plan.recipe_export import free_sizes, plan_single_export, translate_capture
from ...lib.export_plan.runner import ExportCancelled, RowExport
from ...lib.export_plan.size_checks import PLACEMENT_KEY, build_failures, frame_numbers, plan_checks, read_checks
from ...lib.export_plan.size_offers import labels, sizes_for_checks
from ...lib.export_plan.temp_copy import MARKER_MESSAGE, marker_at_end
from ...lib.fusion_reader import design_info, placement
from ...lib.fusion_reader.capture import MarkerError, read_capture
from ...lib.fusion_reader.probe_state import read_state
from ...lib.fusion_reader.read_geometry import ReadContext
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.sketches import read_sketches
from ...lib.fusion_reader.step_export import export_body_step, resolve_body
from ...lib.fusion_ui.file_dialog import ask_save_path
from ...lib.fusion_ui.log import error_box, log, message_box
from ...lib.fusion_ui.notice import status_notice
from ...lib.fusion_ui.progress import ProgressDialog
from ...lib.fusion_ui import result_dialog
from ...lib.package.caps import PackageCapError
from ...lib.package.writer import write_package
from ...lib.params import size_table as size_tables
from ...lib.params.listing import list_parameters
from ...lib.probe.motion import OPTIMISTIC
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


def _target_info(capture):
    """(component name, sketch scope, placement source) of the picked body from its capture.

    The scope is the component name shown before a sketch name in a reason; empty for a body of the root.
    Unknown values are empty strings, and the component name is then "the part".
    """
    target = (capture or {}).get("target") or {}
    component = target.get("component") or {}
    place = target.get("placement") or {}
    name = component.get("name") or ""
    return name or "the part", "" if component.get("root") else name, place.get("source") or ""


def _snapshot(component, body, source, skip):
    """The sketches of the body's component, plus its place in the assembly when that can be read."""
    state = read_sketches(component, skip)
    frame = placement.read_frame(body, source) if source else None
    if frame is not None:
        state[PLACEMENT_KEY] = frame_numbers(frame)
    return state


def _target_component(design, body):
    try:
        return body.parentComponent
    except Exception:
        return design.rootComponent


def _run_checks(design, store, units, body, token, checks, tmp, job_box, skip_sketches, source, probe=None):
    """Export one STEP per check. Returns (results, snapshots per check row, probe states of the checks that built)."""
    snapshots, reads = {}, []
    component = _target_component(design, body)

    def export_check(path):
        current = resolve_body(design, token, body)
        export_body_step(design, current, path)
        snapshots[job.current_row] = _snapshot(component, current, source, skip_sketches)
        if probe is not None:
            reads.append(probe.read_now())

    job = RowExport(store, units, export_check)
    job_box.append(job)
    os.makedirs(os.path.join(tmp, "checks"), exist_ok=True)
    with ProgressDialog("Export for Paramability", verb="Checking") as progress:
        results = job.run([c["row"] for c in checks], os.path.join(tmp, "checks"), progress.step,
                          tolerate_build_errors=True)
    return results, snapshots, reads


def _run_probe_rows(store, units, rows, job_box, probe):
    """Recompute at each extra size setting and read the sketches there. No STEP. Returns (results, reads)."""
    reads = []
    job = RowExport(store, units, lambda path: reads.append(probe.read_now()))
    job_box.append(job)
    with ProgressDialog("Export for Paramability", verb="Trying") as progress:
        results = job.run(rows, "", progress.step, tolerate_build_errors=True)
    return results, reads


def _start_probe(design, body, token, capture, table):
    """The size probe with its first read, or None when no sketch can be followed. Never stops the export."""
    try:
        if not covers_a_sketch(capture):
            return None
        ctx = ReadContext(design, resolve_body(design, token, body))
        return SizeProbe.start(capture, table, lambda request: read_state(design, request, ctx))
    except Exception as exc:
        log(f"size probe could not start: {exc!r}")
        return None


def _finish_probe(design, store, units, probe, sizes, checks, results, reads, not_checked, jobs, size_labels):
    """Phase 2 of the probe and its result: (motion, report record, sizes the probe makes fixed).

    A failure other than a cancel leaves the translation without a motion (every size behind a sketch is then fixed
    by the translator's own rule); the parameters are back by then."""
    try:
        probe.add_checks(checks, results, reads)
        rows = probe.probe_rows(sizes, checks, results, [s["param"] for s in not_checked])
        if rows:
            tried, tried_reads = _run_probe_rows(store, units, rows, jobs, probe)
            probe.add_tried(tried, tried_reads)
        found = probe.finish(probe.read_now(), size_labels)
    except ExportCancelled:
        raise
    except Exception as exc:
        log(f"size probe failed: {exc!r}")
        return None, None, []
    return probe.motion, probe.report(), found


PENDING_POSITION_MESSAGE = (
    "Capture the position of moved parts first (Position, Capture Position), then export again.")


def position_pending(design):
    """True when parts were moved by hand and the position is not captured. An unreadable answer counts as no.

    It has to be asked before any read that moves the timeline marker, since that can drop a pending move."""
    try:
        return bool(design.snapshots.hasPendingSnapshot)
    except Exception:
        return False


def _first_translation(capture, up_axis, table):
    """The translator's result when it gives a recipe, else None (the plan then reports the reason).

    A part with sketches the probe can follow is translated without fixing sizes for them, so the sizes that move
    only sketches stay in the list of sizes to check."""
    try:
        result = translate_capture(capture, up_axis, table, OPTIMISTIC if covers_a_sketch(capture) else None)
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


def _show_result(file_name, manifest, report, table, ticked):
    """The result dialog for a recipe. A part saved as a fixed shape (or a dialog that cannot start) gets the message
    box, which starts with the stopping step, and then a line in Fusion's status area.

    The file is saved by now, so nothing here may report a failed export."""
    try:
        view = result_view(file_name, manifest, report, table, ticked)
    except Exception as exc:
        log(f"result view failed: {exc!r}")
        view = None
    if view is None:
        try:
            text, notice = saved_message(manifest, report, file_name), status_text(report)
        except Exception as exc:
            log(f"saved message failed: {exc!r}")
            text, notice = "Saved %s." % file_name, ""
        message_box(text)
        status_notice(notice)
    else:
        result_dialog.show(view)


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
    if position_pending(design):
        message_box(PENDING_POSITION_MESSAGE)
        return
    title = design_title(design_info.document_name(app))
    out_path = ask_save_path(package_file_name(title))
    if out_path is None:
        return

    units = {p["name"]: p["unit"] for p in parameters}
    token = body.entityToken
    jobs = []
    saved = None
    try:
        with tempfile.TemporaryDirectory(prefix="paramability_", ignore_cleanup_errors=True) as tmp:
            part_step = os.path.join(tmp, "part.step")
            current = resolve_body(design, token, body)
            export_body_step(design, current, part_step)
            if captures is not None:
                capture = captures.get(body)
            else:
                capture = _read_capture(design, current)

            model, quantities = scope_inputs(capture, model_params)
            table = size_tables.build(
                parameters, form["ticked"], model, design_unit, quantity_params=quantities, ranges=form["ranges"])

            checks, kept, measured, unchecked, failures = [], [], [], [], []
            motion, probe_report = None, None
            if isinstance(capture, dict):
                # Checks go only to the sizes the recipe keeps after translation.
                first = _first_translation(capture, form["up_axis"], table)
                if first is not None:
                    keep = kept_size_names(table, free_sizes(first.recipe))
                    sizes = sizes_for_checks(table, parameters, keep=keep)
                    checks, not_checked = plan_checks(sizes)
                    unchecked = [s["size"] for s in not_checked]
                if checks:
                    store = DesignParameterStore(design)
                    part_name, scope, source = _target_info(capture)
                    probe = _start_probe(design, body, token, capture, table)
                    skip = other_sketch_names(capture) | (probe.skip if probe is not None else set())
                    baseline = _snapshot(_target_component(design, body), current, source, skip)
                    results, snapshots, reads = _run_checks(
                        design, store, units, body, token, checks, tmp, jobs, skip, source, probe)
                    failures = build_failures(checks, results)
                    kept, measured = read_checks(
                        checks, results, baseline, snapshots, labels(table), part_name=part_name, scope=scope)
                    if probe is not None:
                        motion, probe_report, found = _finish_probe(
                            design, store, units, probe, sizes, checks, results, reads, not_checked, jobs,
                            labels(table))
                        measured = measured + found
                    if measured:
                        table = table.with_fixed({m["param"]: m["reason"] for m in measured})

            manifest, files, report = plan_single_export(
                capture if capture is not None else RuntimeError("The steps were not read."),
                part_step, title, export_common.writer_for(app), form["up_axis"],
                size_table=table, checks=kept,
                fixed=[{"name": m["name"], "reason": m["reason"]} for m in measured], unchecked=unchecked,
                listing=_parameter_listing(parameters, model_params, design_unit),
                motion=motion, probe=probe_report, build_failures=failures)
            write_package(out_path, manifest, files)
            saved = (os.path.basename(out_path), manifest, report, table)
    except ExportCancelled:
        message_box("Export cancelled. Your parameters are back to their values.")
    except (RowBuildError, StepExportError, PackageCapError, MarkerError) as exc:
        message_box(f"{exc}\n\nNothing was saved. Your parameters are back to their values.", error=True)
    except Exception:
        error_box("The export stopped. Nothing was saved.")
    finally:
        for job in jobs:
            export_common.warn_unrestored(job)
    if saved is not None:
        _show_result(*saved, form["ticked"])
