"""The dialog shown after a recipe is saved: each size with what it becomes in Paramability, what stays fixed, the
variables.

It is a small command of its own. Fusion does not allow starting a command from inside another command's events,
so `show` fires a custom event; its handler starts the dialog after the export command has ended. When the event or
the dialog cannot start, the same story goes to a message box.
"""
import html

import adsk.core

from ..export_plan.dialog_rows import wrap_name
from .handlers import HandlerList, on_command_created, on_custom_event
from .log import log, message_box

COMMAND_ID = "ParamabilityExportResultCommand"
COMMAND_NAME = "Saved for Paramability"
EVENT_ID = "ParamabilityExportResultEvent"
_COLUMNS = ("name", "range", "check")
_HEADERS = {"name": "Parameter", "range": "Range", "check": "In Paramability"}
_RATIO = "6:3:3"
_MAX_FIXED_ROWS = 6

_handlers = HandlerList()
_event_handlers = HandlerList()
_pending = {}


def start():
    """Register the custom event that opens the dialog. Call once when the add-in starts.

    A failure is logged only: `show` then falls back to the message box."""
    try:
        app = adsk.core.Application.get()
        app.unregisterCustomEvent(EVENT_ID)  # left over from an add-in that did not stop cleanly
        _event_handlers.clear()
        on_custom_event(app.registerCustomEvent(EVENT_ID), _on_event, _event_handlers, "showing the result")
    except Exception as error:
        log("registering the result event failed: %s" % error)


def show(view):
    """Open the result dialog for a view from export_plan.result_rows.result_view; else show its message.

    The dialog opens after the calling command has ended."""
    _pending["view"] = view
    try:
        if not adsk.core.Application.get().fireCustomEvent(EVENT_ID):
            raise RuntimeError("The result event did not fire.")
    except Exception as error:
        log("result dialog failed: %s" % error)
        _fallback()


def _fallback():
    view = _pending.pop("view", None)
    if view is not None:
        message_box(view["message"])


def _on_event(args):
    """Start the result dialog; the message box when that fails."""
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
        _fallback()


def remove():
    """Drop the custom event and the command definition when the add-in stops."""
    try:
        adsk.core.Application.get().unregisterCustomEvent(EVENT_ID)
    except Exception as error:
        log("removing the result event failed: %s" % error)
    _event_handlers.clear()
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
    _add_lines(inputs, "pm_result_warnings", "Check your design", view.get("warnings"), 3)

    sizes = inputs.addGroupCommandInput("pm_result_sizes", view["size_title"])
    sizes.isExpanded = True
    if view["rows"]:
        _build_table(sizes.children, view["rows"], view.get("check_header"))
    else:
        sizes.children.addTextBoxCommandInput("pm_result_none", "", "No parameter became a size.", 1, True)

    _add_lines(inputs, "pm_result_fixed", "Stays fixed", view["fixed"], 2)
    _add_lines(inputs, "pm_result_loose", "May give unexpected results", view.get("loose"), 3)
    if view["variables"]:
        inputs.addTextBoxCommandInput("pm_result_variables", "", html.escape(view["variables"]), 2, True)


def _add_lines(inputs, group_id, title, lines, rows_per_line):
    """An open group with one text box of `lines`; nothing when there are none."""
    if not lines:
        return
    group = inputs.addGroupCommandInput(group_id, title)
    group.isExpanded = True
    group.children.addTextBoxCommandInput(
        group_id + "_text", "", "<br>".join(html.escape(line) for line in lines),
        min(len(lines) * rows_per_line, _MAX_FIXED_ROWS), True)


def _build_table(children, rows, check_header=None):
    table = children.addTableCommandInput("pm_result_table", "", len(_COLUMNS), _RATIO)
    headers = dict(_HEADERS, check=check_header or _HEADERS["check"])
    for col, key in enumerate(_COLUMNS):
        table.addCommandInput(children.addTextBoxCommandInput("pm_result_head_" + key, "", headers[key], 1, True),
                              0, col)
    for index, row in enumerate(rows):
        for col, key in enumerate(_COLUMNS):
            text, lines = wrap_name(row[key]) if key == "name" else (html.escape(row[key]), 1)
            cell = children.addTextBoxCommandInput("pm_result_%s_%d" % (key, index), "", text, lines, True)
            table.addCommandInput(cell, index + 1, col)
