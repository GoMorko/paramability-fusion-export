"""The dialog shown after a recipe is saved: the sections of `dialog_model.result_rows` (reopen, what to check,
result, sizes, steps left out, more sizes). Each section is a group with the section title, and its lines are a
read only text box that scrolls when the lines are many. The groups of `OPEN_SECTIONS` start open and the others
start folded, so the window is short. When Fusion cannot make a group the sections are text boxes, each with a
`# Title` line. Each size is one line in the sizes section.

It is a small command of its own. Fusion does not allow starting a command from inside another command's events,
so `show` fires a custom event; its handler starts the dialog after the export command has ended. Fusion may refuse
the fire while the export command still runs; `event_retry` then fires it again from a timer thread, after the
command has ended. When the dialog cannot start, a short summary goes to a message box. When the event never fires,
the summary goes to the log only: a background thread must not open a message box.

A view with `reopen` (`dialog_model.result_rows`, `export_plan.rollback.reopen_offered`) gets the button "Reopen the
design from its last save" under its `reopen` section, the first section. A click hands the reopen to
`reopen.request`, which runs it once the click's event has returned. The dialog never reopens on its own: only that
click starts it.
"""
import adsk.core

from ..dialog_model.dialog_rows import escape, text_rows
from ..export_plan.rollback import REOPEN_BUTTON
from . import event_retry, reopen
from .handlers import HandlerList, on_command_created, on_custom_event, on_input_changed
from .log import log, message_box
from .notice import status_notice

COMMAND_ID = "ParamabilityExportResultCommand"
COMMAND_NAME = "Saved for Paramability"
EVENT_ID = "ParamabilityExportResultEvent"
REOPEN_ID = "pm_result_reopen_button"
MAX_ROWS = 12
OPEN_SECTIONS = ("reopen", "check", "result", "next")
DIALOG_SIZE = (560, 480)
WAITING = "Saved. The result window opens in a moment."

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
        on_custom_event(app.registerCustomEvent(EVENT_ID), on_event, _event_handlers, "showing the result")
    except Exception as error:
        log("registering the result event failed: %s" % error)
    reopen.start()


def show(view):
    """Open the result dialog for a view from dialog_model.result_rows.result_view; else show its summary.

    The dialog opens after the calling command has ended. When Fusion refuses the fire now, it is tried again from a
    background thread (`event_retry`) and the person sees a line in the status area meanwhile."""
    event_retry.cancel(EVENT_ID)
    _pending["view"] = view
    try:
        fired = _fire()
    except Exception as error:
        log("firing the result event failed: %s" % error)
        fired = False
    if not fired:
        log("the result event did not fire; trying again later")
        status_notice(WAITING)
        event_retry.fire_later(EVENT_ID, "showing the result", lambda: log(summary(_pending.get("view") or view)))


def _fire():
    """Fire the result event. When it does not fire, register it again and fire once more: another copy of the
    add-in that stopped (an older version loaded at the same time) removes the event of the same id."""
    if adsk.core.Application.get().fireCustomEvent(EVENT_ID):
        return True
    log("the result event did not fire; registering it again")
    start()
    return adsk.core.Application.get().fireCustomEvent(EVENT_ID)


def summary(view):
    """The short text of a view for a message box or the log."""
    return view.get("summary") or view["message"]


def _fallback():
    view = _pending.pop("view", None)
    if view is not None:
        message_box(summary(view))


def on_event(args):
    """Start the result dialog; the message box when that fails."""
    event_retry.cancel(EVENT_ID)
    if "view" not in _pending:
        return  # an earlier event already opened the window
    try:
        ui = adsk.core.Application.get().userInterface
        old = ui.commandDefinitions.itemById(COMMAND_ID)
        if old:
            old.deleteMe()
        view = _pending["view"]
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID, view.get("title") or COMMAND_NAME, "What the last export saved.", "")
        _handlers.clear()
        on_command_created(definition.commandCreated, _on_created, _handlers)
        definition.execute()
    except Exception as error:
        log("result dialog failed: %s" % error)
        _fallback()


def remove():
    """Drop the custom event and the command definition when the add-in stops, and end the pending fires."""
    event_retry.cancel()
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
        message_box(summary(view))


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
    try:
        command.setDialogInitialSize(*DIALOG_SIZE)
    except Exception as error:
        log("result window size failed: %s" % error)
    for section in view["sections"]:
        inputs, grouped = _section_inputs(command.commandInputs, section)
        add_text(inputs, "pm_result_" + section["key"], section["title"], section["lines"], heading=not grouped)
        if section["key"] == "reopen" and view.get("reopen"):
            inputs.addBoolValueInput(REOPEN_ID, REOPEN_BUTTON, False, "", False)


def _section_inputs(inputs, section):
    """`(inputs, grouped)`: the children of a new group for the section, open or folded by `OPEN_SECTIONS`. When Fusion
    cannot make the group, the command's own inputs and False."""
    try:
        group = inputs.addGroupCommandInput("pm_group_" + section["key"], section["title"])
        group.isExpanded = section["key"] in OPEN_SECTIONS
        return group.children, True
    except Exception as error:
        log("grouping the result window failed: %s" % error)
        return inputs, False


def add_text(inputs, input_id, title, lines, heading=True):
    """A read only text box with at most `MAX_ROWS` rows (a longer text scrolls inside it): a bold `# title` line
    (when there is a title and `heading`) and the lines under it."""
    head = [("# " + title)] if title and heading else []
    shown = ["<b>%s</b>" % escape(line) for line in head] + [escape(line) for line in lines]
    inputs.addTextBoxCommandInput(input_id, "", "<br>".join(shown), text_rows(head + lines, cap=MAX_ROWS), True)
