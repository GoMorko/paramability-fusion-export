"""Export size choices button: opens the dialog of the sizes table and runs the value rows export."""
import os

import adsk.core

from ... import config
from ...lib.design_edit.marker import marker_note, read_marker
from ...lib.dialog_model.sizes_table import new_table
from ...lib.fusion_reader.design_info import detect_up_axis
from ...lib.fusion_reader.parameters import list_user_parameters
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.export_plan.rollback import ExecuteGate
from ...lib.fusion_ui import export_dialog, handlers
from ...lib.fusion_ui.log import log
from .. import panel
from . import export_flow

_handlers = handlers.HandlerList()
_command_handlers = handlers.HandlerList()
_RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def start():
    panel.add_button(
        config.ROWS_COMMAND_ID, config.ROWS_COMMAND_NAME, config.ROWS_COMMAND_TOOLTIP, _RESOURCES,
        _on_created, _handlers)


def stop():
    panel.remove_button(config.ROWS_COMMAND_ID)
    _handlers.clear()
    _command_handlers.clear()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    design, reason = panel.design_or_reason()
    if design is None:
        export_dialog.build_blocked(command, reason)
        return

    parameters = list_user_parameters(design)
    root = design.rootComponent
    body = None
    if count_solid_bodies(root) == 1 and root.bRepBodies.count == 1:
        body = root.bRepBodies.item(0)
    table = new_table(parameters)
    export_dialog.build(command, parameters, body, detect_up_axis(adsk.core.Application.get()), table,
                        marker_note=marker_note(read_marker(design.timeline)))

    # Per-dialog handlers are replaced each time the dialog opens.
    _command_handlers.clear()
    handlers.on_input_changed(
        command.inputChanged, lambda a: export_dialog.on_input_changed(a, parameters, table), _command_handlers)
    handlers.on_pre_select(command.preSelect, lambda a: export_dialog.allow_preselect(a), _command_handlers)
    handlers.on_validate(
        command.validateInputs,
        lambda a: setattr(a, "areInputsValid", export_dialog.inputs_valid(a.inputs, parameters, table)),
        _command_handlers)
    gate = ExecuteGate(log)
    handlers.on_execute(
        command.execute,
        lambda a: gate.run(a, lambda outcome: export_flow.run_export(
            design, parameters, export_dialog.read_form(a.command.commandInputs, parameters, table), outcome)),
        _command_handlers)
    handlers.on_destroy(command.destroy, lambda a: None, _command_handlers)
