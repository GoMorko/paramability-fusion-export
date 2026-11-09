"""Safe cleanup of the temporary component copy.

Fusion inserts new timeline items at the timeline marker, which need not be the end of the timeline. So the cleanup
never picks items by position: it deletes the occurrence it holds, then only the timeline entities that were not in
the timeline before the copy. Entities are compared as Fusion objects (`==`), never by token text.
"""


def _same(a, b):
    """Two timeline entities are the same Fusion object. Token text is not used: it can change over time."""
    try:
        return a is b or bool(a == b)
    except Exception:
        return False


def _entities(timeline):
    """The entity of each timeline item in order; None for an item without one or one that cannot be read."""
    out = []
    for i in range(timeline.count):
        try:
            out.append(timeline.item(i).entity)
        except Exception:
            out.append(None)
    return out


def timeline_state(timeline):
    """(item count, entities) of the timeline now. Taken before the copy, it says what the design held then."""
    try:
        entities = _entities(timeline)
    except Exception:
        return 0, []
    return len(entities), [e for e in entities if e is not None]


def created_entities(timeline, before):
    """The timeline entities that are not in `before` (`timeline_state` taken before the copy), in timeline order.

    The old entities keep their order, so most are matched by one comparison with the next old entity; only the
    others are compared with every old entity. When more are found than the timeline grew by, a match failed and an
    entity of the design could be among them: nothing is returned. Items without an entity are never returned.
    """
    count_before, old = before
    try:
        now = _entities(timeline)
    except Exception:
        return []
    grown = len(now) - count_before
    if grown <= 0:
        return []
    created, j = [], 0
    for entity in now:
        if entity is None:
            continue
        if j < len(old) and _same(entity, old[j]):
            j += 1
        elif not any(_same(entity, o) for o in old):
            created.append(entity)
    return created if len(created) <= grown else []


def delete_created_items(timeline, before):
    """Delete the timeline entities the copy added (`created_entities`), last first. Returns the number deleted.
    Never raises."""
    deleted = 0
    for entity in reversed(created_entities(timeline, before)):
        try:
            entity.deleteMe()
            deleted += 1
        except Exception:
            pass
    return deleted


def remove_temporary_copy(timeline, occurrence, before):
    """Delete the temporary occurrence (None when it was not made), then any timeline entity the copy added that
    is still there."""
    if occurrence is not None:
        try:
            occurrence.deleteMe()
        except Exception:
            pass
    return delete_created_items(timeline, before)
