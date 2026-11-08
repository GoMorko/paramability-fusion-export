"""Progress dialog with a cancel button."""
import adsk.core


class ProgressDialog:
    """Use as a context manager. step(index, total, name) returns False when the person cancelled."""

    def __init__(self, title):
        self._title = title
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

    def step(self, index, total, name):
        if not self._shown:
            self._dialog.show(self._title, "Size %v of %m", 0, total, 1)
            self._shown = True
        self._dialog.message = f"Exporting size {index} of {total}: {name}"
        self._dialog.progressValue = index - 1
        adsk.doEvents()
        return not self._dialog.wasCancelled
