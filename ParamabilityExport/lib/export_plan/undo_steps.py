"""Keep the size tries out of Fusion's undo data (an experiment the person turns on in the dialog). Pure: no Fusion
imports.

The export runs inside one command, and Fusion keeps undo data for every rebuild of that command until it ends; a long
export can grow Fusion by many GB. `Command.beginStep(makeExistingStepNonUndoable=True)` (a preview API) ends the
command's current step without undo data and starts a new one. The tries call it at points where every value is back
(`ProbeRun`, before each row and after the tries), so what is dropped holds no change the add-in does not undo itself.

Fail safe: when the call is missing, raises or answers False, no further call is made and the export goes on as
without the experiment. `record` is the `timing.undo` block of `report.json` (docs/capture-format.md).
"""
from . import health as health_module


class UndoSteps:
    """Calls `begin_step(True)` at each point the tries are back at the design's own values (`drop`).

    `begin_step` is `Command.beginStep`, or None when the command has none. `record` holds `on` (always True here),
    `applied` (a call worked), `steps` (calls that worked) and `error` (why calls stopped, else empty)."""

    def __init__(self, begin_step, log):
        self._begin = begin_step
        self._log = log
        self.record = {"on": True, "applied": False, "steps": 0, "error": ""}
        if begin_step is None:
            self._stop("This Fusion version has no Command.beginStep.")

    def _stop(self, why):
        self._begin = None
        self.record["error"] = why
        try:
            self._log("keeping the tries out of Undo stopped: " + why)
        except Exception:
            pass

    def drop(self):
        """End the command's current step without undo data. Never raises."""
        if self._begin is None:
            return
        try:
            done = self._begin(True)
        except Exception as exc:
            self._stop(repr(exc))
            return
        if done is False:
            self._stop("Fusion did not start a new step.")
            return
        self.record["steps"] += 1
        self.record["applied"] = True


def attach(port, steps):
    """Give `port` the `UndoSteps` the tries call (None when the box is off) and note it in the port's timing (the
    record is read when `report.json` is made). Returns the port."""
    port.undo_steps = steps
    timing = getattr(port, "timing", None)
    if timing is not None:
        timing.undo = steps.record if steps is not None else {"on": False}
    return port


def drop_after(steps, health):
    """Once the export put the design back, drop the undo data of its last part too (the marker and the suppressed
    steps put back), so Undo does not bring back the state of the tries. Kept when the design may be changed
    (`health`), so Undo can still help there. Not done when no call worked during the tries."""
    if steps is not None and steps.record["applied"] and not health_module.design_changed(health):
        steps.drop()


def command_steps(command, log):
    """The `UndoSteps` of a running Fusion command. Never raises: a command without `beginStep` gives one that only
    records that."""
    try:
        begin = getattr(command, "beginStep", None)
    except Exception:
        begin = None
    if begin is None:
        return UndoSteps(None, log)
    return UndoSteps(lambda non_undoable: begin(non_undoable), log)
