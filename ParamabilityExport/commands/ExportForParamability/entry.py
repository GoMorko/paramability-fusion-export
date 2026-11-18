"""Export for Paramability button: the main dialog. The user parameters become sizes of a recipe."""
import os

import adsk.core

from ... import config
from ...lib.design_edit.marker import marker_note, read_marker
from ...lib.design_edit.timeline_health import read_timeline
from ...lib.dialog_model.stop_warning import summarize as summarize_stop, summarize_many as summarize_stops
from ...lib.export_plan.rollback import ExecuteGate
from ...lib.export_plan.size_offers import offers as size_offers, table_for_bodies, table_for_body
from ...lib.fusion_reader.design_info import default_length_unit, detect_up_axis
from ...lib.fusion_reader.parameters import list_model_parameters, list_user_parameters
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.saved_design import read_saved_start
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.fusion_ui.log import log, message_box
from ...lib.fusion_ui import handlers, progress, recipe_dialog, result_dialog, timeline_select
from ...lib.timing.timer import Timer
from .. import export_common, panel
from . import export_flow

_handlers = handlers.HandlerList()
_command_handlers = handlers.HandlerList()
_RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def start():
    panel.add_button(
        config.EXPORT_COMMAND_ID, config.EXPORT_COMMAND_NAME, config.EXPORT_COMMAND_TOOLTIP, _RESOURCES,
        _on_created, _handlers, promoted=True)
    result_dialog.start()


def stop():
    progress.close_all()
    panel.remove_button(config.EXPORT_COMMAND_ID)
    _handlers.clear()
    _command_handlers.clear()
    result_dialog.remove()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    design, reason = panel.design_or_reason()
    if design is None:
        recipe_dialog.build_blocked(command, reason)
        return
    # Asked first: reading the timeline for the offers moves the marker, which can drop a position not yet captured.
    if export_flow.position_pending(design):
        recipe_dialog.build_blocked(command, export_flow.PENDING_POSITION_MESSAGE)
        return

    # Read before anything moves the marker: whether the design is its last save decides if a design the export
    # cannot undo may be reopened from that save (`export_plan.rollback.reopen_offered`).
    saved_start = read_saved_start(_document_of(design))
    # Read before the capture below moves the marker: the export compares the steps with this at its end.
    timeline_start = read_timeline(DesignParameterStore(design))
    root = design.rootComponent
    note = marker_note(read_marker(design.timeline))
    parameters = list_user_parameters(design)
    model_params = list_model_parameters(root)
    design_unit = default_length_unit(design)
    body = None
    if count_solid_bodies(root) == 1 and root.bRepBodies.count == 1:
        body = root.bRepBodies.item(0)
    captures = export_flow.CaptureCache(design)

    def inspect(picked):
        """(dialog rows, warning) for the picked bodies (a list). The rows hold their own parameters when their steps
        can be read, else the whole design's; with several bodies a parameter any of them uses is ticked. The warning
        says which step stops the copy, per body; it is None when nothing is picked."""
        found = [captures.get(b) for b in picked]
        if len(picked) <= 1:
            capture = found[0] if found else None
            rows = size_offers(table_for_body(parameters, design_unit, model_params, capture), parameters, design_unit)
            return rows, _stop_for(picked, capture)
        table = table_for_bodies(parameters, design_unit, model_params, found)
        return size_offers(table, parameters, design_unit), _stops_for(picked, found)

    def _warn(picked, work):
        """The warning from `work()`, or None when it fails. The log gets the time of the warning and of the reads of
        the steps it uses: the reads are the slow part, the warning itself should stay in the milliseconds."""
        timer = Timer()
        try:
            with timer.span("warning"):
                return work()
        except Exception as exc:
            log(f"stop warning failed: {exc!r}")
            return None
        finally:
            if picked:
                _log_warning_time(picked, timer.seconds("warning"))

    def _log_warning_time(picked, seconds):
        try:
            reads = ", ".join("?" if r is None else "%.1f" % r for r in (captures.read_seconds(b) for b in picked))
            log("warning under the body picker: %.2f s; reading the steps of the picked bodies: %s s" % (
                seconds, reads))
        except Exception as exc:
            log(f"timing the warning failed: {exc!r}")

    def _stop_for(picked, capture):
        return _warn(picked, lambda: summarize_stop(capture, has_parameters=bool(parameters)))

    def _stops_for(picked, found):
        return _warn(picked, lambda: summarize_stops(
            list(zip([b.name for b in picked], found)), has_parameters=bool(parameters)))

    offers, stop = inspect([body] if body is not None else [])
    recipe_dialog.build(
        command, offers, body, detect_up_axis(adsk.core.Application.get()), design_unit=design_unit, stop=stop,
        marker_note=note)
    _add_version(command)
    shown = {"bodies": (body.entityToken,) if body is not None else (), "stop": stop}

    def show_step(inputs, button):
        """Select the stopping step in Fusion, then put the body picker and the button back as they were."""
        picked = recipe_dialog.picked_bodies(inputs)
        problem = timeline_select.select_step(design, (shown["stop"] or {}).get("index"))
        try:
            recipe_dialog.restore_bodies(inputs, picked)
            adsk.core.BoolValueCommandInput.cast(button).value = False
        except Exception as exc:
            log(f"restoring the dialog failed: {exc!r}")
        if problem:
            message_box(problem)

    def on_changed(args):
        inputs = args.inputs
        if args.input.id == recipe_dialog.BODY_ID:
            picked = recipe_dialog.picked_bodies(inputs)
            tokens = tuple(b.entityToken for b in picked)
            if not picked:
                shown["bodies"], shown["stop"] = (), None
                recipe_dialog.show_stop(inputs, None)
            elif tokens != shown["bodies"]:
                shown["bodies"] = tokens
                fresh, shown["stop"] = inspect(picked)
                recipe_dialog.apply_offers(inputs, offers, fresh)
                recipe_dialog.show_stop(inputs, shown["stop"])
        elif args.input.id == recipe_dialog.SHOW_ID:
            show_step(inputs, args.input)
        else:
            recipe_dialog.handle_change(inputs, offers, args.input)

    # Per-dialog handlers are replaced each time the dialog opens.
    _command_handlers.clear()
    handlers.on_input_changed(command.inputChanged, on_changed, _command_handlers)
    handlers.on_pre_select(command.preSelect, recipe_dialog.allow_preselect, _command_handlers)
    handlers.on_validate(
        command.validateInputs,
        lambda a: setattr(a, "areInputsValid", recipe_dialog.inputs_valid(a.inputs, offers)),
        _command_handlers)
    gate = ExecuteGate(log)

    def on_execute(args):
        """Run the export once per dialog, and have Fusion undo it when the design is not back. A step the export
        starts (`export_plan.undo_steps`) fires this event again, while the export runs or after it; the gate lets only
        the first event run the export and set the abort."""
        gate.run(args, lambda outcome: export_flow.run_export(
            design, parameters, model_params, design_unit, recipe_dialog.read_form(args.command.commandInputs, offers),
            captures, timeline_start, command=args.command, outcome=outcome, saved_start=saved_start))

    handlers.on_execute(command.execute, on_execute, _command_handlers)
    handlers.on_destroy(command.destroy, lambda a: captures.clear(), _command_handlers)


def _document_of(design):
    """The document of `design` (`Product.parentDocument`), or None when it cannot be read."""
    try:
        return design.parentDocument
    except Exception as exc:
        log(f"reading the document of the design failed: {exc!r}")
        return None


def _add_version(command):
    """A last line in the export dialog with the version of this add-in, so a person who loaded several copies sees
    which one runs. Never raises."""
    try:
        text = "Add-in version %s" % export_common.addin_release()
        command.commandInputs.addTextBoxCommandInput("pm_addin_version", "", text, 1, True)
    except Exception as exc:
        log(f"showing the add-in version failed: {exc!r}")
