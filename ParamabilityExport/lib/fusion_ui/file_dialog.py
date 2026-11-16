"""Save file dialog for the package."""
import adsk.core

from ..package.naming import EXTENSION, ORCA_EXTENSION, with_extension


def ask_save_path(initial_name, orca=False):
    """Return the chosen path with the .paramability extension (.3mf for the Orca output), or None when
    cancelled."""
    ui = adsk.core.Application.get().userInterface
    dialog = ui.createFileDialog()
    dialog.title = "Save for OrcaSlicer" if orca else "Save for Paramability"
    dialog.filter = "OrcaSlicer project (*.3mf)" if orca else "Paramability package (*.paramability)"
    dialog.initialFilename = initial_name
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        return None
    return with_extension(dialog.filename, ORCA_EXTENSION if orca else EXTENSION)
