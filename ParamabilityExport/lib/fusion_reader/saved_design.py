"""The saved state of the open design, and the door to Fusion that reopens its saved version.

`read_saved_start` reads, before the export changes anything, whether the design is a cloud file with no unsaved
changes (`design_edit.saved_start.SavedStart`). `FusionReopen` is the door that `saved_start.reopen` uses: it finds the
kept version (`Data.findFileById`, then `DataFile.versions` when the latest version is another one), closes the
document without saving (`Document.close(False)`) and opens the kept version (`Documents.open`). It never saves.

Members used, all in the Fusion API reference and the installed stubs: `Document.dataFile`, `Document.isModified`,
`Document.isValid`, `Document.close`, `DataFile.id`, `DataFile.versionNumber`, `DataFile.versions` (`count`, `item`),
`DataFile.name`, `DataFile.parentProject` (`DataProject.name`), `Application.data` (`Data.findFileById`) and
`Application.documents` (`Documents.open`). A member that cannot be read gives an unknown value, and an unknown value
never offers the reopen.
"""
from ..design_edit.saved_start import NOT_SAVED, SavedStart, reopen


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


def _versions(data_file):
    """The versions of `data_file` (`DataFile.versions`), as a list; empty when they cannot be read."""
    versions = _read(lambda: data_file.versions)
    count = _read(lambda: versions.count, 0) if versions is not None else 0
    if not isinstance(count, int):
        return []
    found = (_read(lambda i=i: versions.item(i)) for i in range(count))
    return [item for item in found if item is not None]


class FusionReopen:
    """The door of `saved_start.reopen` for one Fusion document. `app` is the `Application`."""

    def __init__(self, app, document):
        self._app = app
        self._document = document

    def find(self, file_id, version):
        """The cloud file of `file_id` at `version`, or None. `findFileById` gives the latest version; an older kept
        version is looked up in its versions."""
        latest = self._app.data.findFileById(file_id)
        if latest is None:
            return None
        if latest.versionNumber == version:
            return latest
        return next((item for item in _versions(latest) if _read(lambda: item.versionNumber) == version), None)

    def still_open(self, file_id):
        """True when the kept document is still open and is still the file `file_id`."""
        document = self._document
        if document is None or not _read(lambda: document.isValid, False):
            return False
        data_file = _read(lambda: document.dataFile)
        return data_file is not None and _read(lambda: data_file.id) == file_id

    def close(self):
        """Close the document without saving (`Document.close(False)`); True when Fusion says it closed."""
        return bool(self._document.close(False))

    def open(self, data_file):
        """Open `data_file` visibly; True when Fusion gives the opened document."""
        return self._app.documents.open(data_file, True) is not None


def reopen_saved(app, document, saved_start):
    """Close `document` without saving and open the version kept in `saved_start` (`saved_start.reopen`). Returns ""
    when it worked, else the message for the person. Never raises."""
    return reopen(saved_start, FusionReopen(app, document))
