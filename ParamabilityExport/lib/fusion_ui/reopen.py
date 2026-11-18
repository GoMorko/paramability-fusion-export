"""The reopen of the design from its last save, after the person clicks for it in the result window.

The export keeps the document and its `SavedStart` (`keep`) when it offers the reopen (`export_plan.rollback
.reopen_offered`). The button of the result window calls `request`, which fires a custom event. Its handler runs once
the button's own event has returned: it ends the result window (`UserInterface.terminateActiveCommand`, only when that
window is the active command), then closes the design without saving and opens the kept version
(`fusion_reader.saved_design.reopen_saved`). A failure shows a plain message and leaves Fusion as it is. Nothing is
ever saved. When Fusion refuses to fire the event, `event_retry` fires it again from a background thread.
"""
import adsk.core

from ..fusion_reader.saved_design import reopen_saved
from . import event_retry
from .handlers import HandlerList, on_custom_event
from .log import log, message_box
from .notice import status_notice

EVENT_ID = "ParamabilityExportReopenEvent"
BY_HAND = "To get the design back, close it without saving and open it again from the Data Panel."
NOT_STARTED = "The add-in could not start the reopen. " + BY_HAND
WAITING = "The reopen starts in a moment."
WINDOW_LEFT = "The add-in could not close the result window, so it did not reopen the design. " + BY_HAND

_event_handlers = HandlerList()
_kept = {}


def start():
    """Register the custom event of the reopen. Call once when the add-in starts. A failure is logged only: the
    button then starts nothing and the log says so (`request`)."""
    try:
        app = adsk.core.Application.get()
        app.unregisterCustomEvent(EVENT_ID)  # left over from an add-in that did not stop cleanly
        _event_handlers.clear()
        on_custom_event(app.registerCustomEvent(EVENT_ID), run_pending, _event_handlers, "reopening the design")
    except Exception as error:
        log("registering the reopen event failed: %s" % error)


def remove():
    """Drop the custom event and what was kept when the add-in stops, and end the pending fires."""
    event_retry.cancel(EVENT_ID)
    try:
        adsk.core.Application.get().unregisterCustomEvent(EVENT_ID)
    except Exception as error:
        log("removing the reopen event failed: %s" % error)
    _event_handlers.clear()
    _kept.clear()


def keep(document, saved_start):
    """Keep the document of the last export and its `SavedStart`, for a later click on the reopen button."""
    _kept.clear()
    _kept.update(document=document, start=saved_start)


def forget():
    """Drop what `keep` kept: the last export offers no reopen."""
    _kept.clear()


def request(window_command_id):
    """Ask for the reopen; it runs after the event that calls this has returned. `window_command_id` is the id of the
    result window's command, which the reopen ends first. When Fusion refuses the fire, it is tried again from a
    background thread (`event_retry`); a background thread cannot show a message box, so a reopen that never starts
    is only logged."""
    if "start" not in _kept:
        return
    _kept["window"] = window_command_id
    event_retry.cancel(EVENT_ID)
    try:
        fired = _fire()
    except Exception as error:
        log("reopen failed to start: %s" % error)
        fired = False
    if not fired:
        log("the reopen event did not fire; trying again later")
        status_notice(WAITING)
        event_retry.fire_later(EVENT_ID, "reopening the design", lambda: log("reopen failed to start: " + NOT_STARTED))


def _fire():
    """Fire the reopen event. When it does not fire, register it again and fire once more: another copy of the
    add-in that stopped removes the event of the same id."""
    if adsk.core.Application.get().fireCustomEvent(EVENT_ID):
        return True
    log("the reopen event did not fire; registering it again")
    start()
    return adsk.core.Application.get().fireCustomEvent(EVENT_ID)


def run_pending(args=None):
    """The handler of the reopen event: run the reopen that `request` asked for, if any."""
    document, saved_start, window = _kept.pop("document", None), _kept.pop("start", None), _kept.pop("window", None)
    if saved_start is None:
        return
    app = adsk.core.Application.get()
    if not _end_window(app, window):
        message_box(WINDOW_LEFT, error=True)
        return
    log("reopening %s, version %s, without saving" % (saved_start.name or "the design", saved_start.version))
    problem = reopen_saved(app, document, saved_start)
    if problem:
        log("reopen: " + problem)
        message_box(problem, error=True)


def _end_window(app, window):
    """End the result window when it is the active command. True when no command of it is left running."""
    try:
        ui = app.userInterface
        if window and ui.activeCommand == window:
            return bool(ui.terminateActiveCommand())
        return True
    except Exception as error:
        log("ending the result window failed: %s" % error)
        return False
