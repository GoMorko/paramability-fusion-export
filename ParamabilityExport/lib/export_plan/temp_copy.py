"""Safe cleanup of the temporary component copy.

Fusion inserts new timeline items at the timeline marker, not at the end. So cleanup never deletes by index: it
deletes only entities whose token was not in the timeline before the copy, and the export refuses to start while the
marker is rolled back.
"""
from .errors import StepExportError

MARKER_MESSAGE = "Move the timeline marker to the end, then try again."


def marker_at_end(timeline):
    """True when the timeline marker sits after the last item (or the design has no timeline)."""
    try:
        return timeline.markerPosition == timeline.count
    except Exception:
        return True


def require_marker_at_end(timeline):
    if not marker_at_end(timeline):
        raise StepExportError(MARKER_MESSAGE)


def _token(entity):
    try:
        return entity.entityToken
    except Exception:
        return None


def timeline_tokens(timeline):
    """Entity tokens of every timeline item that has an entity."""
    tokens = set()
    try:
        for i in range(timeline.count):
            try:
                entity = timeline.item(i).entity
            except Exception:
                continue
            token = _token(entity) if entity is not None else None
            if token:
                tokens.add(token)
    except Exception:
        pass
    return tokens


def delete_created_items(timeline, tokens_before):
    """Delete timeline entities that were not there before the copy. Items without a token are left alone.

    Returns the number of entities deleted. Never raises.
    """
    created = []
    try:
        for i in range(timeline.count):
            try:
                entity = timeline.item(i).entity
            except Exception:
                continue
            token = _token(entity) if entity is not None else None
            if token and token not in tokens_before:
                created.append(entity)
    except Exception:
        return 0
    deleted = 0
    for entity in reversed(created):
        try:
            entity.deleteMe()
            deleted += 1
        except Exception:
            pass
    return deleted


def remove_temporary_copy(timeline, occurrence, tokens_before):
    """Delete the temporary occurrence, then any timeline entity the copy added that is still there."""
    try:
        occurrence.deleteMe()
    except Exception:
        pass
    return delete_created_items(timeline, tokens_before)
