"""Progress dialog with a cancel button, and the list of dialogs that are on screen."""
import adsk.core

from .log import log

# The dialogs that were shown and not hidden yet. `close_all` hides them, so none stays on screen.
_on_screen = []


def close_all():
    """Hide every progress dialog that is still on screen. A hide that fails is logged, never raised."""
    for dialog in list(_on_screen):
        dialog.close()


class ProgressDialog:
    """Use as a context manager. step(index, total, name, note="") returns False when the person cancelled; a `note`
    is a last line under the message (the time the tries take).

    The message of each step is "{verb} size 2 of 5: Large", or `line(index, total, name)` when it is given. `intro`
    is a first line that stays the same: the message is then two lines, the intro and the changing line.
    `shown` is the text the dialog starts with (%v is the step, %m the last one).

    The window hides when the `with` block ends, unless `keep_open` is set: the block is then one part of a longer
    job, and `close()` (or `close_all()`) hides the window when the whole job is over. The window opens at the first
    step and stays the same window for every later block, so Cancel and the step count carry over.
    """

    def __init__(self, title, verb="Exporting", intro="", line=None, shown="Size %v of %m", keep_open=False):
        self._title = title
        self._verb = verb
        self._intro = intro
        self._line = line or (lambda index, total, name: f"{verb} size {index} of {total}: {name}")
        self._shown_text = shown
        self._keep_open = keep_open
        self._dialog = adsk.core.Application.get().userInterface.createProgressDialog()
        self._shown = False
        self._total = None
        self.closed = False

    def __enter__(self):
        self._dialog.isBackgroundTranslucencyEnabled = True
        self._dialog.cancelButtonText = "Cancel"
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._keep_open:
            self.close()
        return False

    def step(self, index, total, name, note=""):
        if not self._shown:
            self._dialog.show(self._title, self._shown_text, 0, total, 1)
            self._shown, self._total, self.closed = True, total, False
            _on_screen.append(self)
        elif total != self._total:
            self._total = total
            try:
                self._dialog.maximumValue = total
            except Exception as exc:
                log(f"progress window: the last step could not be changed: {exc!r}")
        text = self._line(index, total, name)
        lines = [line for line in (self._intro, text, note) if line]
        self._dialog.message = "\n".join(lines)
        self._dialog.progressValue = index - 1
        adsk.doEvents()
        return not self._dialog.wasCancelled

    def close(self):
        """Hide the window when it is on screen. Never raises. Later steps open a new window."""
        self.closed = True
        if self in _on_screen:
            _on_screen.remove(self)
        if not self._shown:
            return
        self._shown = False
        try:
            self._dialog.hide()
        except Exception as exc:
            log(f"progress window: it could not be hidden: {exc!r}")


class DialogSet:
    """The progress dialogs of one export, one per verb. `make(verb)` builds a dialog; the same verb always gets the
    same dialog, so the tries of every batch share one window. A dialog that was closed is made again."""

    def __init__(self, make):
        self._make = make
        self._by_verb = {}

    def get(self, verb):
        dialog = self._by_verb.get(verb)
        if dialog is None or dialog.closed:
            dialog = self._by_verb[verb] = self._make(verb)
        return dialog
