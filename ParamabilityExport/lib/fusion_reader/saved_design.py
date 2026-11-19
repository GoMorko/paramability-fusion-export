"""The saved state of the open design.

`read_saved_start` reads, before the export changes anything, whether the design is a cloud file and whether Fusion
showed unsaved changes (`design_edit.saved_start.SavedStart`). It only reads: the add-in never closes or opens a
document (see `agent-docs/developer-guide.md`).

Members used, all in the Fusion API reference and the installed stubs: `Document.dataFile`, `Document.isModified`,
`DataFile.id`, `DataFile.versionNumber`, `DataFile.name` and `DataFile.parentProject` (`DataProject.name`). A member
that cannot be read gives an unknown value, and an unknown value never offers the steps.
"""
from ..design_edit.saved_start import NOT_SAVED, SavedStart


def _read(read, default=None):
    try:
        return read()
    except Exception:
        return default


def read_saved_start(document):
    """The `SavedStart` of `document`, read now. Never raises; a document that cannot be read gives `NOT_SAVED`."""
    if document is None:
        return NOT_SAVED
    data_file = _read(lambda: document.dataFile)
    modified = _read(lambda: document.isModified)
    if data_file is None:
        return SavedStart(in_cloud=False, modified=modified if isinstance(modified, bool) else None)
    version = _read(lambda: data_file.versionNumber)
    project = _read(lambda: data_file.parentProject)
    return SavedStart(
        in_cloud=True,
        modified=modified if isinstance(modified, bool) else None,
        file_id=_read(lambda: data_file.id) or "",
        version=version if isinstance(version, int) and not isinstance(version, bool) else None,
        name=_read(lambda: data_file.name) or "",
        project=(_read(lambda: project.name) if project is not None else "") or "")
