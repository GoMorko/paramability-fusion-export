"""The saved state of the design when an export starts. Pure: no Fusion imports.

An export that leaves the design changed and cannot undo it (with "Lighter on memory" on, Fusion forgot the Undo data
of the tries) tells the person how to get the design back as it was saved: close it without saving and open it again
from the Data Panel. That needs a saved cloud version, and the person must know when unsaved changes would be lost.
`SavedStart` holds what the command read before any change (`fusion_reader.saved_design`): where the saved version is
and whether Fusion showed unsaved changes. The add-in never closes or opens the design itself.
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
        """True when the design has a saved version to get back: in the cloud, with a known file and version. A value
        that could not be read counts as no."""
        return bool(self.in_cloud and self.file_id and isinstance(self.version, int))

    @property
    def unsaved_at_start(self):
        """True when Fusion showed unsaved changes when the export started, or this could not be read. Fusion also
        counts the add-in's own marker moves of an earlier export or dialog as unsaved changes, so this does not prove
        that the person changed the design; closing without saving then loses every change since the last save."""
        return self.modified is not False


NOT_SAVED = SavedStart()
