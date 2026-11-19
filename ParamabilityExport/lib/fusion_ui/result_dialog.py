"""The dialog shown after a recipe is saved: the sections of `dialog_model.result_rows` (reopen steps, what to check,
result, sizes, steps left out, more sizes). Each section is a group with the section title, and its lines are a
read only text box that scrolls when the lines are many. The groups of `OPEN_SECTIONS` start open and the others
start folded, so the window is short. When Fusion cannot make a group the sections are text boxes, each with a
`# Title` line. Each size is one line in the sizes section.

It is a small command of its own. Fusion does not allow starting a command from inside another command's events, and
it refuses `Application.fireCustomEvent` after an export that ended undo steps early. So `show` only keeps the view and
the id of the export command that runs now. When Fusion reports that this command has ended
(`UserInterface.commandTerminated`, `on_terminated`), the window starts. When no command of the caller runs, the
window starts at once. A view that never got its window is dropped when the next export starts (`drop_pending`). When
the window cannot start, a short summary goes to a message box; the window and the box never both show.

The dialog only shows text. It never closes or opens a design: Fusion does not support that inside a command event
(see `agent-docs/developer-guide.md`). A view with `reopen` has the steps to get the design back as it was saved in its first
section.
"""
import adsk.core

from ..dialog_model.dialog_rows import escape, text_rows
from .handlers import HandlerList, on_command_created, on_command_terminated
from .log import log, message_box
from .notice import status_notice

COMMAND_ID = "ParamabilityExportResultCommand"
COMMAND_NAME = "Saved for Paramability"
MAX_ROWS = 12
OPEN_SECTIONS = ("reopen", "check", "result", "next")
DIALOG_SIZE = (560, 480)
WAITING = "Saved. The result window opens when the export has ended."

_handlers = HandlerList()
_end_handlers = HandlerList()
_listening = {}
_pending = {}  # `view` and `command`: the result that waits for the end of the command `command`
_ready = {}  # `view`: the result of the window that is being made


def start():
    """Listen for the end of commands (`UserInterface.commandTerminated`). Call once when the add-in starts.

    A failure is logged only: `show` then starts the window at once, or falls back to the message box."""
    _stop_listening()
    try:
        event = adsk.core.Application.get().userInterface.commandTerminated
        _listening["event"] = event
        _listening["handler"] = on_command_terminated(event, on_terminated, _end_handlers, "showing the result")
    except Exception as error:
        _listening.clear()
        log("listening for the end of commands failed: %s" % error)


def _stop_listening():
    event, handler = _listening.pop("event", None), _listening.pop("handler", None)
    if event is not None and handler is not None:
        try:
            event.remove(handler)
        except Exception as error:
            log("removing the command end handler failed: %s" % error)
    _end_handlers.clear()


def show(view, command_id=None):
    """Open the result dialog for a view from dialog_model.result_rows.result_view; else show its summary.

    `command_id` is the id of the command that calls this. When that command runs now, the window opens when Fusion
    reports its end (`on_terminated`) and the person sees a line in the status area meanwhile. Else it opens now."""
    _pending.clear()
    _pending["view"] = view
    running = _running_command()
    if command_id and running == command_id and "handler" in _listening:
        _pending["command"] = command_id
        log("the result window opens when %s has ended" % command_id)
        status_notice(WAITING)
        return
    log("opening the result window now (command running: %r)" % running)
    _open()


def drop_pending():
    """Drop a result that never got its window. Call when an export starts."""
    if _pending.pop("view", None) is not None:
        log("a result that was never shown is dropped")
    _pending.clear()


def _running_command():
    """The id of the command that runs now, or an empty text when it cannot be read."""
    try:
        return adsk.core.Application.get().userInterface.activeCommand or ""
    except Exception as error:
        log("reading the running command failed: %s" % error)
        return ""


def summary(view):
    """The short text of a view for a message box or the log."""
    return view.get("summary") or view["message"]


def _fallback():
    view = _ready.pop("view", None)
    if view is not None:
        message_box(summary(view))


def on_terminated(args):
    """A command has ended. The command the pending result waits for starts the window. Other commands change
    nothing."""
    if "view" in _pending and args.commandId == _pending.get("command"):
        _open()


def _open():
    """Start the result dialog for the pending view; the message box when that fails."""
    view = _pending.pop("view", None)
    _pending.clear()
    if view is None:
        return
    _ready["view"] = view
    try:
        ui = adsk.core.Application.get().userInterface
        old = ui.commandDefinitions.itemById(COMMAND_ID)
        if old:
            old.deleteMe()
        definition = ui.commandDefinitions.addButtonDefinition(
            COMMAND_ID, view.get("title") or COMMAND_NAME, "What the last export saved.", "")
        _handlers.clear()
        on_command_created(definition.commandCreated, _on_created, _handlers)
        definition.execute()
    except Exception as error:
        log("result dialog failed: %s" % error)
        _fallback()


def remove():
    """Take the handler off the command end event and drop the command definition when the add-in stops."""
    _stop_listening()
    try:
        definition = adsk.core.Application.get().userInterface.commandDefinitions.itemById(COMMAND_ID)
        if definition:
            definition.deleteMe()
    except Exception as error:
        log("removing the result command failed: %s" % error)
    _handlers.clear()
    _pending.clear()
    _ready.clear()


def _on_created(args):
    command = adsk.core.CommandCreatedEventArgs.cast(args).command
    view = _ready.pop("view", None)
    if view is None:
        return
    try:
        build(command, view)
    except Exception as error:
        log("building the result dialog failed: %s" % error)
        message_box(summary(view))


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
