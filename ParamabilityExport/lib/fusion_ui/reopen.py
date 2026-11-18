"""The reopen of the design from its last save, after the person clicks for it in the result window.

The export keeps the document and its `SavedStart` (`keep`) when it offers the reopen (`export_plan.rollback
.reopen_offered`). The button of the result window calls `request`. That marks the reopen as asked for and tries to end
the result window (`UserInterface.terminateActiveCommand`, only when that window is the active command). The reopen
itself never runs inside the click: it runs in `window_ended`, which `result_dialog` calls when Fusion reports that
the result window's command has ended (`UserInterface.commandTerminated`). `window_ended` closes the design without
saving and opens the kept version (`fusion_reader.saved_design.reopen_saved`). A failure shows a plain message and
leaves Fusion as it is. Nothing is ever saved. A window that ends without the click reopens nothing.
"""
import adsk.core

from ..fusion_reader.saved_design import reopen_saved
from .log import log, message_box

_kept = {}


def remove():
    """Drop what was kept, when the add-in stops."""
    _kept.clear()


def keep(document, saved_start):
    """Keep the document of the last export and its `SavedStart`, for a later click on the reopen button."""
    _kept.clear()
    _kept.update(document=document, start=saved_start)


def forget():
    """Drop what `keep` kept: the last export offers no reopen."""
    _kept.clear()


def request(window_command_id):
    """The click on the reopen button: mark the reopen as asked for, and try to end the result window now. The reopen
    runs in `window_ended`, whether or not the window ends at once. `window_command_id` is the id of the result
    window's command. False when nothing is kept to reopen."""
    if "start" not in _kept:
        return False
    _kept["requested"] = True
    _end_window(adsk.core.Application.get(), window_command_id)
    return True


def is_requested():
    """True when the person clicked the reopen button and the reopen has not run yet."""
    return bool(_kept.get("requested")) and "start" in _kept


def window_ended():
    """The result window has ended: run the reopen when the button asked for it, once. Else nothing happens."""
    if not is_requested():
        return
    document, saved_start = _kept.pop("document", None), _kept.pop("start")
    _kept.clear()
    log("reopening %s, version %s, without saving" % (saved_start.name or "the design", saved_start.version))
    problem = reopen_saved(adsk.core.Application.get(), document, saved_start)
    if problem:
        log("reopen: " + problem)
        message_box(problem, error=True)


def _end_window(app, window):
    """Ask Fusion to end the result window when it is the active command. Fusion may refuse inside the click's own
    event, so a failure only goes to the log: the person closes the window by hand and the reopen runs then."""
    try:
        ui = app.userInterface
        if window and ui.activeCommand == window:
            if not ui.terminateActiveCommand():
                log("Fusion did not end the result window; the reopen runs when it is closed")
    except Exception as error:
        log("ending the result window failed: %s" % error)
