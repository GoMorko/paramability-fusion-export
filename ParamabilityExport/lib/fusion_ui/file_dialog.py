"""Save file dialog for the package."""
import adsk.core

from ..package.naming import with_extension


def ask_save_path(initial_name):
    """Return the chosen path with the .paramability extension, or None when cancelled."""
    ui = adsk.core.Application.get().userInterface
    dialog = ui.createFileDialog()
    dialog.title = "Save for Paramability"
    dialog.filter = "Paramability package (*.paramability)"
    dialog.initialFilename = initial_name
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        return None
    return with_extension(dialog.filename)
