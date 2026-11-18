"""The dialog shown after a recipe is saved: the sections of `dialog_model.result_rows` (result, sizes, steps left
out, what to check), each as a `# Title` line followed by its lines. Each size is one line in the sizes section.

It is a small command of its own. Fusion does not allow starting a command from inside another command's events,
so `show` fires a custom event; its handler starts the dialog after the export command has ended. When the event or
the dialog cannot start, the same story goes to a message box.

A view with `reopen` (`dialog_model.result_rows`, `export_plan.rollback.reopen_offered`) gets the button "Reopen the
design from its last save" under its `reopen` section. A click hands the reopen to `reopen.request`, which runs it
once the click's event has returned. The dialog never reopens on its own: only that click starts it.
"""
import adsk.core

from ..dialog_model.dialog_rows import escape, text_rows
from ..export_plan.rollback import REOPEN_BUTTON
from . import reopen
from .handlers import HandlerList, on_command_created, on_custom_event, on_input_changed
from .log import log, message_box

COMMAND_ID = "ParamabilityExportResultCommand"
COMMAND_NAME = "Saved for Paramability"
EVENT_ID = "ParamabilityExportResultEvent"
REOPEN_ID = "pm_result_reopen_button"
_MAX_ROWS = 12

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
    reopen.start()


def show(view):
    """Open the result dialog for a view from dialog_model.result_rows.result_view; else show its message.

    The dialog opens after the calling command has ended."""
    _pending["view"] = view
    try:
        if not _fire():
            raise RuntimeError("The result event did not fire.")
    except Exception as error:
        log("result dialog failed: %s" % error)
        _fallback()


def _fire():
    """Fire the result event. When it does not fire, register it again and fire once more: another copy of the
    add-in that stopped (an older version loaded at the same time) removes the event of the same id."""
    if adsk.core.Application.get().fireCustomEvent(EVENT_ID):
        return True
    log("the result event did not fire; registering it again")
    start()
    return adsk.core.Application.get().fireCustomEvent(EVENT_ID)


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
        view = _pending.get("view") or {}
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID, view.get("title") or COMMAND_NAME, "What the last export saved.", "")
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
    reopen.remove()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    view = _pending.pop("view", None)
    if view is None:
        return
    try:
        build(command, view)
        if view.get("reopen"):
            on_input_changed(command.inputChanged, lambda a: on_input(a.input.id), _handlers)
    except Exception as error:
        log("building the result dialog failed: %s" % error)
        message_box(view["message"])


def on_input(input_id):
    """A click in the result dialog: the reopen button asks for the reopen (`reopen.request`); nothing else acts."""
    if input_id == REOPEN_ID:
        reopen.request(COMMAND_ID)


def build(command, view):
    """Add the inputs of the result dialog. view comes from dialog_model.result_rows.result_view."""
    command.isOKButtonVisible = False
    try:
        command.cancelButtonText = "Close"
    except Exception as error:
        log("close button text failed: %s" % error)
    for section in view["sections"]:
        _add_text(command.commandInputs, "pm_result_" + section["key"], section["title"], section["lines"])
        if section["key"] == "reopen" and view.get("reopen"):
            command.commandInputs.addBoolValueInput(REOPEN_ID, REOPEN_BUTTON, False, "", False)


def _add_text(inputs, input_id, title, lines):
    """A read only text box: a bold `# title` line (when there is a title) and the lines under it."""
    shown = ["<b>%s</b>" % escape("# " + title)] if title else []
    shown += [escape(line) for line in lines]
    count = text_rows(([("# " + title)] if title else []) + lines, cap=_MAX_ROWS)
    inputs.addTextBoxCommandInput(input_id, "", "<br>".join(shown), count, True)
