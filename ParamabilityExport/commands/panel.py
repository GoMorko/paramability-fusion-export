"""The Paramability panel and its buttons, shared by the commands."""
import adsk.core

from .. import config


def _ui():
    return adsk.core.Application.get().userInterface


def add_button(command_id, name, tooltip, resources, on_created, handlers, promoted=False):
    """Register a button definition and put it in the Paramability panel (made when missing)."""
    from ..lib.fusion_ui import handlers as handler_utils

    ui = _ui()
    definition = ui.commandDefinitions.itemById(command_id)
    if definition:
        definition.deleteMe()
    definition = ui.commandDefinitions.addButtonDefinition(command_id, name, tooltip, resources)
    handler_utils.on_command_created(definition.commandCreated, on_created, handlers)

    workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(config.TAB_ID)
    panel = tab.toolbarPanels.itemById(config.PANEL_ID) or tab.toolbarPanels.add(config.PANEL_ID, config.PANEL_NAME)
    control = panel.controls.itemById(command_id)
    if not control:
        control = panel.controls.addCommand(definition)
    control.isPromoted = promoted


def remove_button(command_id):
    """Remove the button and its definition; the panel goes when it is empty."""
    ui = _ui()
    workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
    tab = workspace.toolbarTabs.itemById(config.TAB_ID) if workspace else None
    panel = tab.toolbarPanels.itemById(config.PANEL_ID) if tab else None
    if panel:
        control = panel.controls.itemById(command_id)
        if control:
            control.deleteMe()
        if panel.controls.count == 0:
            panel.deleteMe()
    definition = ui.commandDefinitions.itemById(command_id)
    if definition:
        definition.deleteMe()


def design_or_reason():
    """(design, None) for a design the export can use, else (None, plain sentence for the person)."""
    import adsk.fusion

    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        return None, "Open a Fusion design first."
    if design.designType != adsk.fusion.DesignTypes.ParametricDesignType:
        return None, "This design has no history, so sizes cannot change its numbers. Turn on design history first."
    return design, None
