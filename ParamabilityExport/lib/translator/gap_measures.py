"""The measured body around a gap, and a measure moved into the recipe's coordinates.

A measure is `{ box, volume }`: the box around the walk's body and its volume. The exported body has the reader's
measures on the item; a tool body has what was measured on the tool itself (`tool_walk`).
"""
import math

MAX_MEASURE = 1e6


def _root(ctx):
    while ctx.outer is not None:
        ctx = ctx.outer
    return ctx


def _measure(box, volume):
    if not _is_box(box) or not _finite(volume):
        return None
    return {"box": {"min": list(box["min"]), "max": list(box["max"])}, "volume": float(volume)}


def _state(record):
    record = record if isinstance(record, dict) else {}
    return _measure(record.get("box"), record.get("volume_mm3"))


def measures(ctx, item):
    """`(before, after)` of the body this walk builds around `item`, each `{ box, volume }` or None. The exported body
    has the reader's measures on the item; a tool body has what was measured on the tool itself (`tool_walk`)."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    if _root(ctx).is_target(ctx.target):
        before = _state(item.get("target_before")) or _measure(data.get("target_box_before"), data.get("volume_before"))
        return before, _state(item.get("target_after"))
    return _measure(data.get("target_box_before"), data.get("volume_before")), None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_box(box):
    return isinstance(box, dict) and all(
        isinstance(box.get(k), (list, tuple)) and len(box[k]) == 3 and all(_finite(v) for v in box[k])
        for k in ("min", "max"))


def to_recipe(move):
    """The 12 numbers of a `place.Move`: the 3 by 3 rows, then the offset."""
    return [float(c) for row in move.rows for c in row] + [float(v) for v in move.offset]


def moved_measure(measure, move):
    """A `{ box, volume }` in recipe coordinates: the box around the moved corners. None when out of bounds."""
    if measure is None:
        return None
    lo, hi = measure["box"]["min"], measure["box"]["max"]
    corners = [[(lo, hi)[(n >> axis) & 1][axis] for axis in range(3)] for n in range(8)]
    moved = [[sum(move.rows[i][k] * p[k] for k in range(3)) + move.offset[i] for i in range(3)] for p in corners]
    box = {"min": [min(p[i] for p in moved) + 0.0 for i in range(3)],
           "max": [max(p[i] for p in moved) + 0.0 for i in range(3)]}
    numbers = box["min"] + box["max"]
    if any(abs(v) > MAX_MEASURE for v in numbers) or not 0 <= measure["volume"] <= MAX_MEASURE ** 2:
        return None
    return {"box": box, "volume": measure["volume"]}
