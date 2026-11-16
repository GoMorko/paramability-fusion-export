"""Export for Orca (experimental) button: the export dialog for one body, saving an OrcaSlicer 2.5 project."""
import os

import adsk.core

from ... import config
from ...lib.design_edit.marker import marker_note, read_marker
from ...lib.dialog_model.orca_result import preview as left_out_preview
from ...lib.design_edit.timeline_health import read_timeline
from ...lib.export_plan.size_offers import offers as size_offers, table_for_body
from ...lib.fusion_reader.design_info import default_length_unit, detect_up_axis
from ...lib.fusion_reader.parameters import list_model_parameters, list_user_parameters
from ...lib.fusion_reader.rows import DesignParameterStore
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.fusion_ui import handlers, recipe_dialog
from ...lib.fusion_ui.log import log
from .. import panel
from ..ExportForParamability.export_flow import PENDING_POSITION_MESSAGE, CaptureCache, position_pending
from . import export_flow

_handlers = handlers.HandlerList()
_command_handlers = handlers.HandlerList()
_RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def start():
    panel.add_button(config.ORCA_COMMAND_ID, config.ORCA_COMMAND_NAME, config.ORCA_COMMAND_TOOLTIP, _RESOURCES,
                     _on_created, _handlers)


def stop():
    panel.remove_button(config.ORCA_COMMAND_ID)
    _handlers.clear()
    _command_handlers.clear()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    design, reason = panel.design_or_reason()
    if design is None:
        recipe_dialog.build_blocked(command, reason)
        return
    if position_pending(design):
        recipe_dialog.build_blocked(command, PENDING_POSITION_MESSAGE)
        return

    timeline_start = read_timeline(DesignParameterStore(design))
    root = design.rootComponent
    note = marker_note(read_marker(design.timeline))
    parameters = list_user_parameters(design)
    model_params = list_model_parameters(root)
    design_unit = default_length_unit(design)
    body = None
    if count_solid_bodies(root) == 1 and root.bRepBodies.count == 1:
        body = root.bRepBodies.item(0)
    captures = CaptureCache(design)

    def offers_for(picked):
        """The dialog rows for the picked body: its own parameters when its steps can be read."""
        capture = captures.get(picked) if picked is not None else None
        return size_offers(table_for_body(parameters, design_unit, model_params, capture), parameters, design_unit)

    up_axis = detect_up_axis(adsk.core.Application.get())

    def left_out_for(picked):
        """The warning about the steps the copy will leave out, or None (nothing picked, nothing left out, or the
        preview failed)."""
        if picked is None:
            return None
        try:
            return left_out_preview(captures.get(picked), up_axis)
        except Exception as exc:
            log(f"left out preview failed: {exc!r}")
            return None

    offers = offers_for(body)
    recipe_dialog.build(command, offers, body, up_axis, design_unit=design_unit, stop=left_out_for(body),
                        marker_note=note, orca=True)
    shown = {"body": body.entityToken if body is not None else None}

    def on_changed(args):
        inputs = args.inputs
        if args.input.id == recipe_dialog.BODY_ID:
            picked = recipe_dialog.picked_body(inputs)
            token = picked.entityToken if picked is not None else None
            if picked is None:
                shown["body"] = None
                recipe_dialog.show_stop(inputs, None)
            elif token != shown["body"]:
                shown["body"] = token
                recipe_dialog.apply_offers(inputs, offers, offers_for(picked))
                recipe_dialog.show_stop(inputs, left_out_for(picked))
        else:
            recipe_dialog.handle_change(inputs, offers, args.input)

    _command_handlers.clear()
    handlers.on_input_changed(command.inputChanged, on_changed, _command_handlers)
    handlers.on_pre_select(command.preSelect, recipe_dialog.allow_preselect, _command_handlers)
    handlers.on_validate(
        command.validateInputs,
        lambda a: setattr(a, "areInputsValid", recipe_dialog.inputs_valid(a.inputs, offers, limit=1)),
        _command_handlers)
    exported = {"started": False}

    def on_execute(args):
        """Run the export once per dialog."""
        if exported["started"]:
            return
        exported["started"] = True
        export_flow.run_export(design, parameters, model_params, design_unit,
                               recipe_dialog.read_form(args.command.commandInputs, offers), captures, timeline_start)

    handlers.on_execute(command.execute, on_execute, _command_handlers)
    handlers.on_destroy(command.destroy, lambda a: captures.clear(), _command_handlers)
