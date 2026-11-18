"""Undo of an export that did not put the design back. Pure: no Fusion imports.

An export runs inside the execute event of one Fusion command, and Fusion keeps what the command did in one
transaction. When the event ends with `executeFailed` set, Fusion aborts that transaction: the design goes back to
the state it had when the person clicked OK. The files the export wrote outside Fusion stay.

`ExportOutcome` is the record the pipeline and the command fill while the export runs (`put_back.PutBack`,
`export_common.run_guarded`). `decide` turns it into a `Rollback`: abort when the health record is not
`health.back_as_it_was` (the design differs, or the end check could not confirm it is back), when the tries ran and
there is no health record, or when something after the health record could not be confirmed (`unconfirmed`, such as a
timeline marker that did not go back at the very end). An export that never started the tries and left no sign of a
change is never aborted. `ExecuteGate` is the handler logic of the execute event: it runs the export once and sets the
abort on that first event only.

With "Lighter on memory" the tries end Fusion's steps without undo data (`undo_steps`). A step that ended so cannot be
aborted, so an abort would reach only the last step, which holds the put back and the end check. It could leave the
design worse than the put back did. So the add-in never aborts once undo data was dropped (`ExportOutcome.undo_dropped`,
also when the export kept no health record): the rollback is `undo_unavailable`, and the window says that the export
could not be undone and gives the advice for a design that may be changed.

The texts say what the add-in asked Fusion to do, not that the design is back: the windows of the export show before
Fusion aborts the command. They say whether the file was saved (`ExportOutcome.saved`).

`reopen_offered` says when the result window tells the person how to get the design back as it was saved: only for
`undo_unavailable`, and only when the design has a saved cloud version (`design_edit.saved_start.SavedStart.can_reopen`).
`reopen_lines` are the steps: close the design without saving, then open it again from the Data Panel. The add-in does
not close or open the design itself (see `docs/developer-guide.md`). When Fusion showed unsaved changes at the start
(`SavedStart.unsaved_at_start`), a line before the steps says that every change since the last save is lost: Fusion
also counts the add-in's own marker moves as unsaved changes, so the add-in cannot tell them from the person's own, and
the person decides. After an abort Fusion undoes the export itself, so no steps are given.
"""
from dataclasses import dataclass
from typing import Optional

from . import health as health_module

# What Fusion shows when it aborts the command (`CommandEventArgs.executeFailedMessage`), then `SAVED` or `NOT_SAVED`.
ABORT_MESSAGE = (
    "The export could not confirm that your design came back as it was, so the add-in asked Fusion to undo "
    "everything the export did.")
SAVED = "The file is saved. Check its sizes before you use it."
NOT_SAVED = "No file was saved."
# The title of the result window's steps to get the design back (`reopen_offered`).
REOPEN_TITLE = "Reopen the design"
REOPEN_INTRO = (
    "Fusion could not undo the export. To get your design back as it was saved, close it without saving and open it "
    "again:")
REOPEN_UNSAVED = (
    "Fusion showed unsaved changes in your design when the export started. They can come from an earlier export or "
    "from opening the export dialog, or be your own changes. Closing without saving loses every change since the last "
    "save.")
REOPEN_CLOSE = "1. In Fusion choose File > Close (or close the design's tab)."
REOPEN_DISCARD = "2. When Fusion asks to save, click Don't Save."


@dataclass
class ExportOutcome:
    """What an export tells about the design when it ends, on every way it ends.

    health: the `health.make_health` record of the export, or None when it could not be made (the export stopped
      before it, and the end check did not run or failed).
    touched: True once the tries began, so the design was changed and put back by the add-in.
    undo_dropped: True once Fusion forgot undo data during the export (Lighter on memory, `undo_steps`); set by
      `PutBack` from the record of the undo steps, also when no health record is made.
    unconfirmed: True when a check after the health record could not confirm the design is back (the timeline
      marker did not go back at the very end).
    saved: True once the export wrote its file.
    """

    health: Optional[dict] = None
    touched: bool = False
    undo_dropped: bool = False
    unconfirmed: bool = False
    saved: bool = False


@dataclass(frozen=True)
class Rollback:
    """The verdict for one export.

    abort: Fusion must undo the export (`executeFailed`). Never set when `undo_unavailable`.
    undo_unavailable: the design is not confirmed back, but Fusion forgot undo data during the export (Lighter on
      memory), so no abort is asked: it could not reach everything and could make the design worse.
    changed: the end check found a real change; False when the design could only not be confirmed as back.
    saved: the export wrote its file (`ExportOutcome.saved`).
    """

    abort: bool = False
    undo_unavailable: bool = False
    changed: bool = False
    saved: bool = False

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
    unconfirmed = unconfirmed or outcome.unconfirmed
    if not (changed or unconfirmed):
        return NO_ROLLBACK
    saved = bool(outcome.saved)
    # Dropped undo data is checked first: an abort could then reach only the last step and leave the design worse.
    if outcome.undo_dropped or (health or {}).get("undo_dropped"):
        return Rollback(undo_unavailable=True, changed=changed, saved=saved)
    return Rollback(abort=True, changed=changed, saved=saved)


def reopen_offered(start, rollback):
    """True when the result window gives the steps to get the design back as it was saved: the export could not be
    undone (`undo_unavailable`) and `start` (a `SavedStart`, or None when not read) shows the open design has a saved
    cloud version."""
    return bool(rollback.undo_unavailable and start is not None and start.can_reopen)


def _open_again(start):
    """The third step: where to find the saved version, from what `start` knows (project, file name, version)."""
    parts = []
    if start is not None and start.project:
        parts.append("project \"%s\"" % start.project)
    if start is not None and start.name:
        parts.append("file \"%s\"" % start.name)
    if start is not None and start.version is not None:
        parts.append("version %d" % start.version)
    return "3. Open the design again from the Data Panel" + (" (%s)." % ", ".join(parts) if parts else ".")


def reopen_lines(start):
    """The lines of the result window's steps for `start` (a `SavedStart`): the warning that changes since the last
    save are lost when Fusion showed unsaved changes at the start (or `start` is None), the intro, then the steps."""
    warning = [REOPEN_UNSAVED] if start is None or start.unsaved_at_start else []
    return warning + [REOPEN_INTRO, REOPEN_CLOSE, REOPEN_DISCARD, _open_again(start)]


def abort_message(rollback):
    """What Fusion shows when it aborts the command for `rollback`."""
    return ABORT_MESSAGE + " " + (SAVED if rollback.saved else NOT_SAVED)


def lines(rollback, advice=True):
    """The sentences that say an export was undone, or could not be, for the result window. Empty otherwise. With
    `advice` False the advice for a design that may be changed is left out of the second case."""
    if not rollback.says:
        return []
    # Worded for every export: the size tries, the size choices and the Orca output, which runs no tries.
    if rollback.changed:
        first = "The export changed your design, and it did not come back to its first state."
    else:
        first = "Fusion could not confirm that your design came back to its first state after the export."
    if rollback.undo_unavailable:
        undone = ("The add-in could not undo the export, because Lighter on memory was on. Your design may be changed."
                  + (" " + health_module.NO_UNDO_ADVICE if advice else ""))
    else:
        undone = ("The add-in asked Fusion to undo everything the export did. Fusion does it when the export ends. "
                  "Then check that your design looks as it did before the export.")
    return [first + " " + undone, SAVED if rollback.saved else NOT_SAVED]


def check_lines(health, rollback):
    """The sentences of the "Check your design" part of a result: the health lines, and with a rollback the lines
    that say the export was undone, or could not be. After a full undo the health lines about the design (Undo advice,
    changed steps) no longer hold, so only the undo lines and the lines about the copy stay (`health.copy_lines`:
    tries that stopped early, sketches not measured). When the export could not be undone the health lines stay, and
    they carry the advice when they have any."""
    found = health_module.health_lines(health)
    if rollback.abort:
        return lines(rollback) + health_module.copy_lines(health)
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
                args.executeFailedMessage = abort_message(self.rollback)
        except Exception as exc:
            if self._log is not None:
                self._log("undoing the export failed: %r" % (exc,))
