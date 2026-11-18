"""The saved state of the design when an export starts, and the reopen of that saved version. Pure: no Fusion imports.

An export that leaves the design changed and cannot undo it (with "Lighter on memory" on, Fusion forgot the Undo data
of the tries) can offer the person to reopen the design from its last save. That is safe only when the open design
was that save: saved in the cloud and with no unsaved changes when the export started. Else the person's own unsaved
work would be lost. `SavedStart` holds what the command read before any change (`fusion_reader.saved_design`).

`reopen` runs the reopen after the person clicked for it, through a door to Fusion (`fusion_reader.saved_design
.FusionReopen`): find the kept version, check that the design is still open, close it without saving, open the kept
version. It never saves and never deletes. Each failure stops there and gives a plain message; the design stays as it
is, or, when only the open failed, the message says where to find the design.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SavedStart:
    """What the design was when the export started.

    in_cloud: the document has a cloud file (`Document.dataFile` is not null).
    modified: `Document.isModified`; None when it could not be read.
    file_id: `DataFile.id` of that file, "" when unknown.
    version: `DataFile.versionNumber` of the version that was open, None when unknown.
    name: the name of the file, for the messages.
    project: the name of the project that holds the file, for the messages.
    """

    in_cloud: bool = False
    modified: Optional[bool] = None
    file_id: str = ""
    version: Optional[int] = None
    name: str = ""
    project: str = ""

    @property
    def can_reopen(self):
        """True when the open design was its saved version: in the cloud, read as not modified, with a known file and
        version. A value that could not be read counts as no."""
        return bool(self.in_cloud and self.modified is False and self.file_id and isinstance(self.version, int))


NOT_SAVED = SavedStart()


def _design(start, first=False):
    if start.name:
        return '"%s"' % start.name
    return "The design" if first else "the design"


def not_found_message(start):
    return ("The add-in could not find the saved version of %s, so it did not close the design. Check the connection "
            "to the cloud. To get the design back, close it without saving and open it again from the Data Panel."
            % _design(start))


def not_open_message(start):
    return "%s is not open any more, so the add-in did not reopen it." % _design(start, first=True)


def close_failed_message(start):
    return ("Fusion did not close %s. The design is still open as it was after the export, and nothing was saved."
            % _design(start))


def open_failed_message(start):
    where = (" It is in the project \"%s\"." % start.project) if start.project else ""
    return ("%s was closed without saving, but Fusion did not open it again. Open it from the Data Panel.%s"
            % (_design(start, first=True), where))


def _still_open(fusion, start, default=True):
    """`fusion.still_open`, or `default` when it raises."""
    try:
        return bool(fusion.still_open(start.file_id))
    except Exception:
        return default


def reopen(start, fusion):
    """Close the design without saving and open the version kept in `start`. Returns "" when it worked, else the
    message for the person. Never raises.

    `fusion` has `find(file_id, version)` (the cloud file of that version, or None), `still_open(file_id)` (the
    document is open and still that file), `close()` (closes it without saving, True when it worked) and `open(file)`
    (True when the file opened). Nothing is closed before the version to open is found."""
    if start is None or not start.can_reopen:
        return not_found_message(start or NOT_SAVED)
    try:
        found = fusion.find(start.file_id, start.version)
    except Exception:
        found = None
    if found is None:
        return not_found_message(start)
    if not _still_open(fusion, start, default=False):
        return not_open_message(start)
    try:
        closed = fusion.close()
    except Exception:
        closed = False
    # A close that answers no or raises may still have closed the design: only a design still open stops here.
    if not closed and _still_open(fusion, start):
        return close_failed_message(start)
    try:
        opened = fusion.open(found)
    except Exception:
        opened = False
    return "" if opened else open_failed_message(start)
