"""Safe cleanup of the temporary component copy.

Fusion inserts new timeline items at the timeline marker, so the export refuses to start while the marker is rolled
back. With the marker at the end, the copy adds items after the ones that were there. Cleanup deletes only those, and
only entities that were not in the timeline before. Entities are compared as objects, never by token text.
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


def _same(a, b):
    """Two timeline entities are the same Fusion object. Token text is not used: it can change over time."""
    try:
        return a is b or bool(a == b)
    except Exception:
        return False


def timeline_state(timeline):
    """(item count, entities) of the timeline now. Taken before the copy, it says what the design held then."""
    entities = []
    try:
        count = timeline.count
        for i in range(count):
            try:
                entity = timeline.item(i).entity
            except Exception:
                continue
            if entity is not None:
                entities.append(entity)
    except Exception:
        return 0, []
    return count, entities


def delete_created_items(timeline, before):
    """Delete the timeline entities the copy added. `before` is `timeline_state` taken before the copy.

    The marker was at the end, so new items sit after the first `count` items. Only those, and only when they are
    not an entity of `before`, are deleted; nothing is deleted when the timeline did not grow. Items without an
    entity are left alone. Returns the number deleted. Never raises.
    """
    count_before, entities = before
    try:
        count = timeline.count
        if count <= count_before:
            return 0
        created = []
        for i in range(count_before, count):
            try:
                entity = timeline.item(i).entity
            except Exception:
                continue
            if entity is not None and not any(_same(entity, old) for old in entities):
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


def remove_temporary_copy(timeline, occurrence, before):
    """Delete the temporary occurrence, then any timeline entity the copy added that is still there."""
    try:
        occurrence.deleteMe()
    except Exception:
        pass
    return delete_created_items(timeline, before)
