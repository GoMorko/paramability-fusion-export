"""Export for Paramability button: adds it to the Utilities tab and opens the dialog."""
import os

import adsk.core
import adsk.fusion

from ... import config
from ...lib.fusion_reader.design_info import detect_up_axis
from ...lib.export_plan.sizes_table import new_table
from ...lib.fusion_reader.parameters import list_user_parameters
from ...lib.fusion_reader.step_export import count_solid_bodies
from ...lib.fusion_ui import export_dialog, handlers
from . import export_flow

_handlers = handlers.HandlerList()
_command_handlers = handlers.HandlerList()
_RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def _ui():
    return adsk.core.Application.get().userInterface


def start():
    ui = _ui()
    definition = ui.commandDefinitions.itemById(config.EXPORT_COMMAND_ID)
    if definition:
        definition.deleteMe()
    definition = ui.commandDefinitions.addButtonDefinition(
        config.EXPORT_COMMAND_ID, config.EXPORT_COMMAND_NAME, config.EXPORT_COMMAND_TOOLTIP, _RESOURCES)
    handlers.on_command_created(definition.commandCreated, _on_created, _handlers)

    workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(config.TAB_ID)
    panel = tab.toolbarPanels.itemById(config.PANEL_ID) or tab.toolbarPanels.add(config.PANEL_ID, config.PANEL_NAME)
    control = panel.controls.itemById(config.EXPORT_COMMAND_ID)
    if not control:
        control = panel.controls.addCommand(definition)
    control.isPromoted = True


def stop():
    ui = _ui()
    workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(config.TAB_ID) if workspace else None
    panel = tab.toolbarPanels.itemById(config.PANEL_ID) if tab else None
    if panel:
        control = panel.controls.itemById(config.EXPORT_COMMAND_ID)
        if control:
            control.deleteMe()
        if panel.controls.count == 0:
            panel.deleteMe()
    definition = ui.commandDefinitions.itemById(config.EXPORT_COMMAND_ID)
    if definition:
        definition.deleteMe()
    _handlers.clear()
    _command_handlers.clear()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        export_dialog.build_blocked(command, "Open a Fusion design first.")
        return
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        export_dialog.build_blocked(
            command, "This design has no history, so sizes cannot change its numbers. Turn on design history first.")
        return

    parameters = list_user_parameters(design)
    root = design.rootComponent
    body = None
    if count_solid_bodies(root) == 1 and root.bRepBodies.count == 1:
        body = root.bRepBodies.item(0)
    table = new_table(parameters)
    export_dialog.build(command, parameters, body, detect_up_axis(app), table)

    # Per-dialog handlers are replaced each time the dialog opens.
    _command_handlers.clear()
    handlers.on_input_changed(
        command.inputChanged, lambda a: export_dialog.on_input_changed(a, parameters, table), _command_handlers)
    handlers.on_pre_select(command.preSelect, lambda a: export_dialog.allow_preselect(a), _command_handlers)
    handlers.on_validate(
        command.validateInputs,
        lambda a: setattr(a, "areInputsValid", export_dialog.inputs_valid(a.inputs, parameters, table)),
        _command_handlers)
    handlers.on_execute(
        command.execute,
        lambda a: export_flow.run_export(
            design, parameters, export_dialog.read_form(a.command.commandInputs, parameters, table)),
        _command_handlers)
    handlers.on_destroy(command.destroy, lambda a: None, _command_handlers)
