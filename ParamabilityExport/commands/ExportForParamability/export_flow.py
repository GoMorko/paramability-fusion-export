"""What happens when the person clicks OK in Export for Paramability.

Order: the STEP of the part as it is, the capture of its steps, a first translation that shows which sizes the
recipe keeps and the ranges it gives them, one check STEP per kept size, a try at the other end of each range (and
smaller steps where Fusion cannot build, `size_narrowing`), extra rows that only recompute (to see how sketches move
with sizes), then the translation again with what these found, and the file. Each run changes parameters; RowExport
puts every parameter back whatever happens. A body inside a component is handled the same way: its sketches and its
place in the assembly are read at every check.

A size that the recipe cannot follow fully stays free with a warning (`loose` in the manifest), unless the person
ticked "Keep doubtful sizes fixed"; only a size Fusion cannot build at any other value is always fixed.
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
from ...lib.export_plan.recipe_export import (
    free_sizes, plan_single_export, translate_capture, with_translated_limits)
from ...lib.export_plan.runner import ExportCancelled, RowExport
from ...lib.export_plan.size_checks import (
    PLACEMENT_KEY, build_failures, check_at, frame_numbers, into_range, plan_checks, read_checks)
from ...lib.export_plan.size_narrowing import narrow_failed
from ...lib.export_plan.size_offers import labels, sizes_for_checks
from ...lib.export_plan.marker import not_put_back_message, put_back, read_marker
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


class _CheckRun:
    """Exports the STEP of each size check and tries the ends of each range, in one job: one baseline, and the
    parameters put back after every run. It keeps the sketches read at every check and, when a probe runs, the probe
    state of every row that built; both are keyed by the row key. `rows` lists (row, result) of every row run."""

    def __init__(self, design, store, units, body, token, tmp, jobs, skip_sketches, source, probe=None):
        self.design, self.body, self.token = design, body, token
        self.tmp, self.skip, self.source, self.probe = tmp, skip_sketches, source, probe
        self.component = _target_component(design, body)
        self.snapshots, self.reads, self.rows = {}, {}, []
        self._runs = 0
        self.job = RowExport(store, units, self._export)
        jobs.append(self.job)

    def _export(self, path):
        current = resolve_body(self.design, self.token, self.body)
        if path is not None:
            export_body_step(self.design, current, path)
            self.snapshots[self.job.current_key] = _snapshot(self.component, current, self.source, self.skip)
        if self.probe is not None:
            self.reads[self.job.current_key] = self.probe.read_now()

    def _run(self, rows, step, until_built=False):
        self._runs += 1
        folder = os.path.join(self.tmp, "checks", "run%d" % self._runs)
        os.makedirs(folder, exist_ok=True)
        results = self.job.run(rows, folder, step, tolerate_build_errors=True, until_built=until_built)
        self.rows.extend(zip(rows, results))
        return results

    def run(self, checks):
        """The results of the checks, in order."""
        with ProgressDialog("Export for Paramability", verb="Checking") as progress:
            return self._run([c["row"] for c in checks], progress.step)

    def narrow(self, checks, results, sizes, size_labels):
        """Try both ends of each checked size (`size_narrowing`). Returns a `Narrowing`."""
        with ProgressDialog("Export for Paramability", verb="Trying") as progress:
            def run_size(size, values, with_step, description):
                rows = [check_at(size, v, sizes)["row"] for v in values]
                if not with_step:
                    rows = [dict(r, step=False) for r in rows]
                number = 1 + next((i for i, c in enumerate(checks) if c["param"] == size["param"]), 0)
                return self._run(rows, lambda *a: progress.step(number, len(checks), description), until_built=True)

            return narrow_failed(checks, results, sizes, run_size, size_labels)

    def recheck(self, kept, sizes, recipe_sizes):
        """The kept checks with each one outside the recipe's range of its size (`size_checks.into_range`) run again
        at the end of that range. A check that cannot move there, or does not build there, is left out."""
        moved = {c["size"]: value for c, value in into_range(kept, recipe_sizes)}
        if not moved:
            return kept
        by_param = {s["param"]: s for s in sizes}
        redo = [check_at(by_param[c["param"]], moved[c["size"]], sizes) for c in kept
                if c["size"] in moved and moved[c["size"]] is not None]
        with ProgressDialog("Export for Paramability", verb="Checking") as progress:
            results = self._run([c["row"] for c in redo], progress.step) if redo else []
        again = {c["size"]: {**c, "step_file": r["step_file"]} for c, r in zip(redo, results) if not r.get("error")}
        return [again[c["size"]] if c["size"] in again else c for c in kept
                if c["size"] not in moved or c["size"] in again]

    def try_rows(self, rows):
        """Run the probe's extra rows (no STEP). Returns their results."""
        with ProgressDialog("Export for Paramability", verb="Trying") as progress:
            return self._run(rows, progress.step)

    def probe_states(self, start=0):
        """(values, result, read) of the rows run, from row number `start` on, for `SizeProbe.add_states`."""
        out = []
        for row, result in self.rows[start:]:
            state = row.get("state") or {}
            values = {param: state[param] for param in row.get("varied") or [] if param in state}
            out.append((values, result, self.reads.get(row.get("key", row["name"]))))
        return out


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


def _finish_probe(probe, run, sizes, not_checked, size_labels, loose):
    """The probe's extra rows and its result: (motion, report record, sizes the probe cannot follow).

    The states are every row the checks ran, then the extra rows at the ends of the ranges as the checks left them.
    A failure other than a cancel leaves the translation without a motion (no size behind a sketch is then followed,
    by the translator's own rule); the parameters are back by then."""
    try:
        probe.add_states(run.probe_states())
        rows = probe.probe_rows(sizes, [s["param"] for s in not_checked])
        if rows:
            start = len(run.rows)
            run.try_rows(rows)
            probe.add_states(run.probe_states(start))
        found = probe.finish(probe.read_now(), size_labels, loose)
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


def _first_translation(capture, up_axis, table, loose=True):
    """The translator's result when it gives a recipe, else None (the plan then reports the reason).

    A part with sketches the probe can follow is translated without fixing sizes for them, so the sizes that move
    only sketches stay in the list of sizes to check."""
    return _translation(capture, up_axis, table, OPTIMISTIC if covers_a_sketch(capture) else None, loose)


def _translation(capture, up_axis, table, motion, loose):
    """The translator's result when it gives a recipe, else None. Never raises."""
    try:
        result = translate_capture(capture, up_axis, table, motion, loose=loose)
    except Exception as exc:
        log(f"translation failed: {exc!r}")
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
    marker = read_marker(design.timeline)
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

            loose = not form.get("keep_doubtful")
            checks, kept, measured, doubtful, unchecked, failures, narrowed = [], [], [], [], [], [], []
            motion, probe_report, final = None, None, None
            if isinstance(capture, dict):
                # Checks go only to the sizes the recipe keeps after translation, within the ranges it gives them.
                first = _first_translation(capture, form["up_axis"], table, loose)
                if first is not None:
                    planned = with_translated_limits(table, first)
                    keep = kept_size_names(planned, free_sizes(first.recipe))
                    sizes = sizes_for_checks(planned, parameters, keep=keep)
                    checks, not_checked = plan_checks(sizes)
                    unchecked = [s["size"] for s in not_checked]
                if checks:
                    store = DesignParameterStore(design)
                    part_name, scope, source = _target_info(capture)
                    probe = _start_probe(design, body, token, capture, table)
                    skip = other_sketch_names(capture) | (probe.skip if probe is not None else set())
                    baseline = _snapshot(_target_component(design, body), current, source, skip)
                    run = _CheckRun(design, store, units, body, token, tmp, jobs, skip, source, probe)
                    results = run.run(checks)
                    narrowing = run.narrow(checks, results, sizes, labels(table))
                    failures = build_failures(checks, results, narrowing.tries)
                    checks, results, sizes, narrowed = (
                        narrowing.checks, narrowing.results, narrowing.sizes, narrowing.narrowed)
                    if narrowed:
                        table = table.with_narrowed(narrowing.moved_ends(table))
                    kept, measured, doubtful = read_checks(
                        checks, results, baseline, run.snapshots, labels(table), part_name=part_name, scope=scope,
                        loose=loose, failed_ends=narrowing.failed_ends)
                    if probe is not None:
                        motion, probe_report, found = _finish_probe(
                            probe, run, sizes, not_checked, labels(table), loose)
                        (doubtful if loose else measured).extend(found)
                    if measured:
                        table = table.with_fixed({m["param"]: m["reason"] for m in measured})
                    # The translation with what the checks found can raise a minimum or shorten a range further.
                    final = _translation(capture, form["up_axis"], table, motion, loose)
                    if final is not None and kept:
                        before = [c["size"] for c in kept]
                        kept = run.recheck(kept, sizes, final.recipe.get("sizes") or {})
                        unchecked += [n for n in before if n not in {c["size"] for c in kept}]

            manifest, files, report = plan_single_export(
                capture if capture is not None else RuntimeError("The steps were not read."),
                part_step, title, export_common.writer_for(app), form["up_axis"],
                size_table=table, checks=kept,
                fixed=[{"name": m["name"], "reason": m["reason"]} for m in measured], unchecked=unchecked,
                listing=_parameter_listing(parameters, model_params, design_unit),
                motion=motion, probe=probe_report, build_failures=failures, narrowed=narrowed, marker=marker,
                loose=[{"name": m["name"], "reason": m["reason"]} for m in doubtful], loose_sizes=loose,
                translated=final)
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
        if marker is not None and not put_back(design.timeline, marker):
            message_box(not_put_back_message(marker), error=True)
    if saved is not None:
        _show_result(*saved, form["ticked"])
