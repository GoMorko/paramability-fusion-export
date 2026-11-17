"""Undo of an export that did not put the design back. Pure: no Fusion imports.

An export runs inside the execute event of one Fusion command, and Fusion keeps what the command did in one
transaction. When the event ends with `executeFailed` set, Fusion aborts that transaction: the design goes back to
the state it had when the person clicked OK. The files the export wrote outside Fusion stay.

`ExportOutcome` is the record the pipeline fills while it runs (`put_back.PutBack`). `decide` turns it into a
`Rollback`: abort when the health record is not `health.back_as_it_was` (the design differs, or the end check could not
confirm it is back), or when the tries ran and there is no health record. An export that never started the tries and
left no sign of a change is never aborted. `ExecuteGate` is the handler logic of the execute event: it runs the export
once and sets the abort on that first event only.

With "Lighter on memory" the tries end Fusion's steps without undo data (`undo_steps`). A step that ended so cannot be
aborted, so an abort would reach only the last step, which holds the put back and the end check. It could leave the
design worse than the put back did. So the add-in never aborts then: the rollback is `undo_unavailable`, and the window
says that the export could not be undone and gives the advice for a design that may be changed.
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

    abort: Fusion must undo the export (`executeFailed`). Never set when `undo_unavailable`.
    undo_unavailable: the design is not confirmed back, but Fusion forgot undo data during the export (Lighter on
      memory), so no abort is asked: it could not reach everything and could make the design worse.
    changed: the end check found a real change; False when the design could only not be confirmed as back.
    """

    abort: bool = False
    undo_unavailable: bool = False
    changed: bool = False

    @property
    def says(self):
        """True when the result must tell the person about the rollback: the export was undone, or could not be."""
        return self.abort or self.undo_unavailable


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
    if (health or {}).get("undo_dropped"):
        return Rollback(undo_unavailable=True, changed=changed)
    return Rollback(abort=True, changed=changed)


def lines(rollback, advice=True):
    """The sentences that say an export was undone, or could not be, for the result window. Empty otherwise. With
    `advice` False the advice for a design that may be changed is left out of the second case."""
    if not rollback.says:
        return []
    if rollback.changed:
        first = "The tries changed your design, and it did not come back to its first state."
    else:
        first = "Fusion could not confirm that your design came back to its first state after the tries."
    if rollback.undo_unavailable:
        undone = ("The add-in could not undo the export, because Lighter on memory was on. Your design may be changed."
                  + (" " + health_module.NO_UNDO_ADVICE if advice else ""))
    else:
        undone = "The add-in undid everything the export did in Fusion. Your design is as it was before the export."
    return [first + " " + undone, "The file is saved. Check its sizes before you use it."]


def check_lines(health, rollback):
    """The sentences of the "Check your design" part of a result: the health lines, and with a rollback the lines
    that say the export was undone, or could not be. After a full undo the health lines about the design (Undo advice,
    changed steps) no longer hold, so only the undo lines stay. When the export could not be undone the health lines
    stay, and they carry the advice when they have any."""
    found = health_module.health_lines(health)
    if rollback.abort:
        return lines(rollback)
    if rollback.undo_unavailable:
        return lines(rollback, advice=not found) + found
    return found


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
