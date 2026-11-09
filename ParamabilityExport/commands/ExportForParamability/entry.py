"""Export for Paramability button: the main dialog. The user parameters become sizes of a recipe."""
import os

import adsk.core

from ... import config
from ...lib.export_plan.marker import marker_note, read_marker
from ...lib.export_plan.stop_warning import summarize as summarize_stop
from ...lib.export_plan.size_offers import offers as size_offers, table_for_body
from ...lib.fusion_reader.design_info import default_length_unit, detect_up_axis
from ...lib.fusion_reader.parameters import list_model_parameters, list_user_parameters
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.fusion_ui.log import log, message_box
from ...lib.fusion_ui import handlers, recipe_dialog, result_dialog, timeline_select
from .. import panel
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
        """(dialog rows, warning) for a body. The rows hold its own parameters when its steps can be read, else the
        whole design's. The warning says which step stops the copy; it is None when nothing is picked."""
        capture = captures.get(picked) if picked is not None else None
        rows = size_offers(table_for_body(parameters, design_unit, model_params, capture), parameters, design_unit)
        return rows, _stop_for(capture)

    def _stop_for(capture):
        try:
            return summarize_stop(capture, has_parameters=bool(parameters))
        except Exception as exc:
            log(f"stop warning failed: {exc!r}")
            return None

    offers, stop = inspect(body)
    recipe_dialog.build(
        command, offers, body, detect_up_axis(adsk.core.Application.get()), design_unit=design_unit, stop=stop,
        marker_note=note)
    shown = {"body": body.entityToken if body is not None else None, "stop": stop}

    def show_step(inputs, button):
        """Select the stopping step in Fusion, then put the body picker and the button back as they were."""
        picked = recipe_dialog.picked_body(inputs)
        problem = timeline_select.select_step(design, (shown["stop"] or {}).get("index"))
        try:
            recipe_dialog.restore_body(inputs, picked)
            adsk.core.BoolValueCommandInput.cast(button).value = False
        except Exception as exc:
            log(f"restoring the dialog failed: {exc!r}")
        if problem:
            message_box(problem)

    def on_changed(args):
        inputs = args.inputs
        if args.input.id == recipe_dialog.BODY_ID:
            picked = recipe_dialog.picked_body(inputs)
            token = picked.entityToken if picked is not None else None
            if picked is None:
                shown["body"], shown["stop"] = None, None
                recipe_dialog.show_stop(inputs, None)
            elif token != shown["body"]:
                shown["body"] = token
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
    handlers.on_execute(
        command.execute,
        lambda a: export_flow.run_export(
            design, parameters, model_params, design_unit,
            recipe_dialog.read_form(a.command.commandInputs, offers), captures),
        _command_handlers)
    handlers.on_destroy(command.destroy, lambda a: None, _command_handlers)
