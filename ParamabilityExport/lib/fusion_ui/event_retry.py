"""Fires a custom event again, later, from a background thread, when a fire did not go through.

Fusion may refuse `Application.fireCustomEvent` while the command that asks for it is still running (an export that
ended undo steps early, for one). The same call works a moment after that command has ended. The Fusion API documents
`fireCustomEvent` as the call that is safe to make from another thread, so a timer repeats it after growing delays.
Nothing else of Fusion is touched from the thread: a window, a message box or a status line must stay on the main
thread. The handler of the event runs on the main thread, as for any other fire.

`cancel` ends the pending tries of one event, or of all events; the add-in calls it when it stops, so no thread
outlives it.
"""
import threading

import adsk.core

from .log import log

DELAYS = (0.5, 1.0, 2.0, 4.0)

_lock = threading.Lock()
_timers = {}
_generation = {}
new_timer = threading.Timer


def fire_later(event_id, what, give_up=None, delays=None):
    """Try `fireCustomEvent(event_id)` again after each delay (seconds) until it fires. `what` names the event for the
    log. `give_up` (a function without arguments, or None) runs on the background thread after the last try failed:
    it must not touch Fusion's window or message boxes. A new call for the same event replaces the pending one."""
    app = adsk.core.Application.get()  # read here, on the main thread; the thread only uses it to fire
    delays = tuple(DELAYS if delays is None else delays)
    with _lock:
        generation = _generation[event_id] = _generation.get(event_id, 0) + 1
        _stop(event_id)
    _schedule(app, event_id, what, give_up, delays, 0, generation)


def cancel(event_id=None):
    """End the pending tries of `event_id`, or of every event when it is None."""
    with _lock:
        for key in ([event_id] if event_id else list(_timers)):
            _generation[key] = _generation.get(key, 0) + 1
            _stop(key)


def _stop(event_id):
    timer = _timers.pop(event_id, None)
    if timer is not None:
        timer.cancel()


def _schedule(app, event_id, what, give_up, delays, index, generation):
    timer = new_timer(delays[index], _attempt, args=(app, event_id, what, give_up, delays, index, generation))
    timer.daemon = True
    with _lock:
        if _generation.get(event_id) != generation:
            return
        _timers[event_id] = timer
    timer.start()


def _attempt(app, event_id, what, give_up, delays, index, generation):
    with _lock:
        if _generation.get(event_id) != generation:
            return
        _timers.pop(event_id, None)
    try:
        fired = bool(app.fireCustomEvent(event_id))
    except Exception as error:
        log("%s: firing the event again failed: %s" % (what, error))
        fired = False
    if fired:
        log("%s: the event fired on try %d" % (what, index + 2))
        return
    if index + 1 < len(delays):
        _schedule(app, event_id, what, give_up, delays, index + 1, generation)
        return
    log("%s: the event did not fire after %d more tries" % (what, len(delays)))
    if give_up is not None:
        try:
            give_up()
        except Exception as error:
            log("%s: giving up failed: %s" % (what, error))
