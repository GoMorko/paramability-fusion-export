"""How many separate pieces the part is in at a probe state. Pure.

Paramability builds a part only while it stays one connected solid: a step that leaves it in several pieces is refused.
Fusion accepts both ways a part comes apart: a body may hold several solids (lumps), and a cut that cuts a body in two,
or a join whose new material does not touch the body, gives new bodies next to it. So a probe read of the target holds
`pieces`: `{ "lumps": n, "others": [box] }`, the target's own solids and the boxes of the other solid bodies of its
component (`fusion_reader.probe_state`; `others` is left out when there are too many to read).

A piece split off the target lies where the part was, or next to it. So an other body counts as a piece when its box
comes within `PIECE_GAP_MM` of the box of the target at E0 or at the state; as many as did so at E0 already are not
pieces of the part (kept tool bodies, a second body of the design). A state where the part came apart while it was one
piece at E0 counts as a try that did not build: nothing is fitted to it, and the range of the size stops before it
(`translator.ranges.kept_ranges.split_cut`).
"""
# The `error` of a try that left the part in several pieces, as `report.json` lists it with the tries that did not build.
APART_ERROR = "the part came apart into %d separate pieces"
# How far (mm) the box of an other body may stand from the box of the target and still count as a piece of the part.
PIECE_GAP_MM = 1.0


def _box(record):
    if not isinstance(record, dict):
        return None
    low, high = record.get("min"), record.get("max")
    ok = all(isinstance(v, (list, tuple)) and len(v) == 3 for v in (low, high))
    return (list(low), list(high)) if ok else None


def _meets(a, b):
    return all(a[0][i] <= b[1][i] + PIECE_GAP_MM and b[0][i] <= a[1][i] + PIECE_GAP_MM for i in range(3))


def _near(read, boxes):
    """How many other bodies of `read` meet one of `boxes`, or None when they were not read."""
    others = ((read or {}).get("pieces") or {}).get("others")
    if not isinstance(others, list):
        return None
    found = [_box(b) for b in others]
    return sum(1 for b in found if b is not None and any(_meets(b, box) for box in boxes))


def _lumps(read):
    value = ((read or {}).get("pieces") or {}).get("lumps") if isinstance(read, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def count(read, e0):
    """The number of separate pieces the part is in at `read`, against the first read `e0`: the target's solids plus
    the other bodies near the target's box at `read` or at E0, less those near it at E0. None when `read` holds no
    pieces read or no box."""
    lumps, own = _lumps(read), _box((read or {}).get("box"))
    if lumps is None or own is None:
        return None
    start = _box((e0 or {}).get("box"))
    boxes = [own] + ([start] if start is not None else [])
    now = _near(read, boxes)
    before = _near(e0, [start]) if start is not None else 0
    if now is None or before is None:
        return lumps
    return lumps + max(0, now - before)


def came_apart(read, e0):
    """The number of pieces when the part is in several at `read` while it was one at E0 (`count`), else None."""
    if count(e0, e0) != 1:
        return None
    found = count(read, e0)
    return found if found is not None and found > 1 else None
