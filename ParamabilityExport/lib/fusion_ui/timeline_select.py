"""Point at a timeline step in Fusion by selecting its feature. Never moves the timeline marker."""
import adsk.core

from .log import log

CANNOT_SELECT = "Fusion cannot select this step. Look for it in the timeline."


def select_step(design, index):
    """Select the feature of the timeline item at `index`. Returns '' on success, else a plain message.

    Only the selection changes: the marker stays where it is and the design is not touched.
    """
    try:
        count = design.timeline.count
        if not isinstance(index, int) or not 0 <= index < count:
            return CANNOT_SELECT
        entity = design.timeline.item(index).entity
        if entity is None:
            return CANNOT_SELECT
        selections = adsk.core.Application.get().userInterface.activeSelections
        selections.clear()
        selections.add(entity)
        return ""
    except Exception as error:
        log("selecting the step failed: %s" % error)
        return CANNOT_SELECT
