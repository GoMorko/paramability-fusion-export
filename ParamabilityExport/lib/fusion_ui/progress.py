"""Progress dialog with a cancel button."""
import adsk.core


class ProgressDialog:
    """Use as a context manager. step(index, total, name, note="") returns False when the person cancelled; a `note`
    is a last line under the message (the time the tries take).

    The message of each step is "{verb} size 2 of 5: Large", or `line(index, total, name)` when it is given. `intro`
    is a first line that stays the same: the message is then two lines, the intro and the changing line.
    `shown` is the text the dialog starts with (%v is the step, %m the last one).
    """

    def __init__(self, title, verb="Exporting", intro="", line=None, shown="Size %v of %m"):
        self._title = title
        self._verb = verb
        self._intro = intro
        self._line = line or (lambda index, total, name: f"{verb} size {index} of {total}: {name}")
        self._shown_text = shown
        self._dialog = adsk.core.Application.get().userInterface.createProgressDialog()
        self._shown = False

    def __enter__(self):
        self._dialog.isBackgroundTranslucencyEnabled = True
        self._dialog.cancelButtonText = "Cancel"
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._shown:
            self._dialog.hide()
        return False

    def step(self, index, total, name, note=""):
        if not self._shown:
            self._dialog.show(self._title, self._shown_text, 0, total, 1)
            self._shown = True
        text = self._line(index, total, name)
        lines = [line for line in (self._intro, text, note) if line]
        self._dialog.message = "\n".join(lines)
        self._dialog.progressValue = index - 1
        adsk.doEvents()
        return not self._dialog.wasCancelled
