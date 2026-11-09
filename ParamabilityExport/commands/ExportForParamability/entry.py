"""Export for Paramability button: the main dialog. The user parameters become sizes of a recipe."""
import os

import adsk.core

from ... import config
from ...lib.export_plan.size_offers import offers as size_offers, table_for_body
from ...lib.fusion_reader.design_info import default_length_unit, detect_up_axis
from ...lib.fusion_reader.parameters import list_model_parameters, list_user_parameters
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.fusion_ui import handlers, recipe_dialog, result_dialog
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
    parameters = list_user_parameters(design)
    model_params = list_model_parameters(root)
    design_unit = default_length_unit(design)
    body = None
    if count_solid_bodies(root) == 1 and root.bRepBodies.count == 1:
        body = root.bRepBodies.item(0)
    captures = export_flow.CaptureCache(design)

    def offers_for(picked):
        """The dialog rows for a body: its own parameters when its steps can be read, else the whole design's."""
        capture = captures.get(picked) if picked is not None else None
        return size_offers(table_for_body(parameters, design_unit, model_params, capture), parameters, design_unit)

    offers = offers_for(body)
    recipe_dialog.build(
        command, offers, body, detect_up_axis(adsk.core.Application.get()), design_unit=design_unit)
    shown = {"body": body.entityToken if body is not None else None}

    def on_changed(args):
        inputs = args.inputs
        if args.input.id == recipe_dialog.BODY_ID:
            picked = recipe_dialog.picked_body(inputs)
            token = picked.entityToken if picked is not None else None
            if picked is not None and token != shown["body"]:
                shown["body"] = token
                recipe_dialog.apply_offers(inputs, offers, offers_for(picked))
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
