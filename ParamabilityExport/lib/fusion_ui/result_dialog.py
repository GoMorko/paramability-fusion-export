"""The dialog shown after a recipe is saved: each size with its check result, what stays fixed, the variables.

It is a small command of its own, started when the export ends. When it cannot be started, the same story goes
to a message box.
"""
import html

import adsk.core

from ..export_plan.dialog_rows import wrap_name
from .handlers import HandlerList, on_command_created
from .log import log, message_box

COMMAND_ID = "ParamabilityExportResultCommand"
COMMAND_NAME = "Saved for Paramability"
_COLUMNS = ("name", "range", "check")
_HEADERS = {"name": "Parameter", "range": "Range", "check": "Check"}
_RATIO = "6:3:3"
_MAX_FIXED_ROWS = 6

_handlers = HandlerList()
_pending = {}


def show(view):
    """Open the result dialog for a view from export_plan.result_rows.result_view; else show its message."""
    _pending["view"] = view
    try:
        ui = adsk.core.Application.get().userInterface
        old = ui.commandDefinitions.itemById(COMMAND_ID)
        if old:
            old.deleteMe()
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID, COMMAND_NAME, "What the last export saved.", "")
        _handlers.clear()
        on_command_created(definition.commandCreated, _on_created, _handlers)
        definition.execute()
    except Exception as error:
        log("result dialog failed: %s" % error)
        _pending.pop("view", None)
        message_box(view["message"])


def remove():
    """Drop the command definition when the add-in stops."""
    try:
        definition = adsk.core.Application.get().userInterface.commandDefinitions.itemById(COMMAND_ID)
        if definition:
            definition.deleteMe()
    except Exception as error:
        log("removing the result command failed: %s" % error)
    _handlers.clear()
    _pending.clear()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    view = _pending.pop("view", None)
    if view is None:
        return
    try:
        build(command, view)
    except Exception as error:
        log("building the result dialog failed: %s" % error)
        message_box(view["message"])


def build(command, view):
    """Add the inputs of the result dialog. view comes from export_plan.result_rows.result_view."""
    command.isOKButtonVisible = False
    try:
        command.cancelButtonText = "Close"
    except Exception as error:
        log("close button text failed: %s" % error)
    inputs = command.commandInputs
    inputs.addTextBoxCommandInput("pm_result_saved", "", html.escape(view["saved"]), 3, True)

    sizes = inputs.addGroupCommandInput("pm_result_sizes", view["size_title"])
    sizes.isExpanded = True
    if view["rows"]:
        _build_table(sizes.children, view["rows"])
    else:
        sizes.children.addTextBoxCommandInput("pm_result_none", "", "No parameter became a size.", 1, True)

    if view["fixed"]:
        fixed = inputs.addGroupCommandInput("pm_result_fixed", "Stays fixed")
        fixed.isExpanded = True
        fixed.children.addTextBoxCommandInput(
            "pm_result_fixed_text", "", "<br>".join(html.escape(line) for line in view["fixed"]),
            min(len(view["fixed"]) * 2, _MAX_FIXED_ROWS), True)
    if view["variables"]:
        inputs.addTextBoxCommandInput("pm_result_variables", "", html.escape(view["variables"]), 2, True)


def _build_table(children, rows):
    table = children.addTableCommandInput("pm_result_table", "", len(_COLUMNS), _RATIO)
    for col, key in enumerate(_COLUMNS):
        table.addCommandInput(children.addTextBoxCommandInput("pm_result_head_" + key, "", _HEADERS[key], 1, True),
                              0, col)
    for index, row in enumerate(rows):
        for col, key in enumerate(_COLUMNS):
            text, lines = wrap_name(row[key]) if key == "name" else (html.escape(row[key]), 1)
            cell = children.addTextBoxCommandInput("pm_result_%s_%d" % (key, index), "", text, lines, True)
            table.addCommandInput(cell, index + 1, col)
