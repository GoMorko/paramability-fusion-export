"""Undo of an export that did not put the design back. Pure: no Fusion imports.

An export runs inside the execute event of one Fusion command, and Fusion keeps what the command did in one
transaction. When the event ends with `executeFailed` set, Fusion aborts that transaction: the design goes back to
the state it had when the person clicked OK. The files the export wrote outside Fusion stay.

`ExportOutcome` is the record the pipeline fills while it runs (`put_back.PutBack`). `decide` turns it into a
`Rollback`: abort when the health record is not `health.back_as_it_was` (the design differs, or the end check could not
confirm it is back), or when the tries ran and there is no health record. An export that never started the tries and left no sign of a
change is never aborted. `ExecuteGate` is the handler logic of the execute event: it runs the export once and sets the
abort on that first event only.

With "Lighter on memory" the tries end Fusion's steps without undo data (`undo_steps`). A step that ended so cannot be
aborted, so the abort reaches only the part after the last such step. The rollback is then `partial`.
"""
from dataclasses import dataclass
from typing import Optional

from . import health as health_module

# What Fusion shows when it aborts the command (`CommandEventArgs.executeFailedMessage`).
ABORT_MESSAGE = (
    "The export could not put your design back as it was, so Fusion undoes everything the export did. "
    "The file is saved.")


@dataclass
class ExportOutcome:
    """What an export tells about the design when it ends, on every way it ends.

    health: the `health.make_health` record of the export, or None when it could not be made (the export stopped
      before it, and the end check did not run or failed).
    touched: True once the tries began, so the design was changed and put back by the add-in.
    """

    health: Optional[dict] = None
    touched: bool = False


@dataclass(frozen=True)
class Rollback:
    """The verdict for one export.

    abort: Fusion must undo the export (`executeFailed`).
    partial: the abort cannot reach everything, because Fusion forgot undo data during the export.
    changed: the end check found a real change; False when the design could only not be confirmed as back.
    """

    abort: bool = False
    partial: bool = False
    changed: bool = False


NO_ROLLBACK = Rollback()


def decide(outcome):
    """The `Rollback` of an export, from its `ExportOutcome` (None counts as an export that changed nothing)."""
    if outcome is None:
        return NO_ROLLBACK
    health = outcome.health
    changed = health_module.design_changed(health)
    # A health record is trusted as it is: any doubt in it (`back_as_it_was`) aborts, with or without a warning line.
    # Without one, the tries decide: no tries ran, so nothing was changed that needs undoing.
    unconfirmed = not health_module.back_as_it_was(health) if health is not None else outcome.touched
    if not (changed or unconfirmed):
        return NO_ROLLBACK
    return Rollback(abort=True, partial=bool((health or {}).get("undo_dropped")), changed=changed)


def lines(rollback):
    """The sentences that say an export was undone, for the result window. Empty without an abort."""
    if not rollback.abort:
        return []
    if rollback.changed:
        first = "The tries changed your design, and it did not come back to its first state."
    else:
        first = "Fusion could not confirm that your design came back to its first state after the tries."
    if rollback.partial:
        undone = ("Lighter on memory was on, so the add-in could only undo the last part of the export. "
                  "Your design may still be changed. " + health_module.NO_UNDO_ADVICE)
    else:
        undone = "The add-in undid everything the export did in Fusion. Your design is as it was before the export."
    return [first + " " + undone, "The file is saved. Check its sizes before you use it."]


def check_lines(health, rollback):
    """The sentences of the "Check your design" part of a result: the health lines, and with an abort the lines that
    say the export was undone. After a full undo the health lines about the design (Undo advice, changed steps) no
    longer hold, so only the undo lines stay; after a partial one both stay."""
    if not rollback.abort:
        return health_module.health_lines(health)
    return lines(rollback) + (health_module.health_lines(health) if rollback.partial else [])


def with_lines(text, health, rollback):
    """`text` with the check lines added below it, for a message box (`health.with_lines` with the undo lines)."""
    return text + "".join("\n\n" + line for line in check_lines(health, rollback))


class ExecuteGate:
    """The execute handler of an export command: runs the export once and sets the abort when the design is not back.

    A step that the export starts (`undo_steps`) fires the execute event again, while the export runs or after it.
    Those events do nothing and abort nothing: only the first event runs the export and holds the verdict.
    `log` is a function that takes one text, or None."""

    def __init__(self, log=None):
        self.started = False
        self.outcome = None
        self.rollback = NO_ROLLBACK
        self._log = log

    def run(self, args, export):
        """Run `export(outcome)` for the first event; do nothing for a later one. `args` is the event's
        `CommandEventArgs`. The abort is set also when `export` raises, and the error then goes on."""
        if self.started:
            return
        self.started = True
        self.outcome = ExportOutcome()
        try:
            export(self.outcome)
        finally:
            self._apply(args)

    def _apply(self, args):
        """Set `executeFailed` and its message on `args` when the outcome asks for it. Never raises."""
        try:
            self.rollback = decide(self.outcome)
            if self.rollback.abort:
                args.executeFailed = True
                args.executeFailedMessage = ABORT_MESSAGE
        except Exception as exc:
            if self._log is not None:
                self._log("undoing the export failed: %r" % (exc,))
