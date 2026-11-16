"""Scale handler (ScaleFeature).

A Scale stretches bodies about one point, by one factor or by one factor per axis. It becomes a `scale` step in the
list of the body it scales: the app scales everything built before it in that list, and every later value stays as
Fusion measured it at that point of the timeline. A `scale` cannot be the first step of a list, so a Scale before
any written step is left out.

What the scale did is checked against the body as measured before and after the item: the volume must change by the
product of the factors, and each side of the body's box must move as the factors and the point say. A Scale that
fails a check, scales sketches as well, or cannot be read is left out. The factors follow sizes; a factor whose
formula would leave the range the app takes (0.001 to 1000) is written as its number. The point is written where it
was measured; the sizes that may move it (a sketch point, a construction point, a corner of the part) are marked.

Factors per axis are along the axes of the body's component. The recipe is carried into the assembly by a rigid map
(`place.place`), which can put them on other axes only when it turns each axis onto an axis, so a Scale that differs
per axis in a component turned by a part of a quarter turn is left out.

After the step, the placers of the earlier steps cannot place picks (`faces/scaled_placer.py`), so later picks on
their faces mark their sizes.
"""
from ...capture_model import gap_hints
from ...design_model import reach
from ...geometry import rigid
from ...package.numbers import round9
from .. import values
from ..faces.scaled_placer import ScaleMaker
from ..place import axis_turn
from ..result import Refusal, StepResult

# The factors the recipe takes.
MIN_FACTOR, MAX_FACTOR = 0.001, 1000.0
# How far the volume after the scale may lie from the volume before times the factors: a part of it, plus mm3.
VOLUME_TOL, VOLUME_TOL_MM3 = 1e-4, 1e-3
# How far a side of the box after the scale may lie from where the factors put it: mm, plus a part of the box size.
BOX_TOL_MM, BOX_TOL = 0.01, 1e-4


def _name(item):
    return item.get("name") or "This scale"


def _refuse(text):
    return Refusal(text, cause=gap_hints.SCALE)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_box(box):
    return isinstance(box, dict) and all(
        isinstance(box.get(k), list) and len(box[k]) == 3 and all(_is_number(v) for v in box[k]) for k in ("min", "max"))


def _target(ctx, data):
    """`(record, after)` of the walk's body among the scaled bodies, or None."""
    bodies, after = data.get("bodies") or [], data.get("after") or []
    n = next((n for n, body in enumerate(bodies) if isinstance(body, dict) and ctx.is_target(body)), None)
    if n is None or n >= len(after) or not isinstance(after[n], dict):
        return None
    return bodies[n], after[n]


def _factors(data):
    """The three measured factors (x, y, z), or None when they cannot be read."""
    if data.get("uniform") is True:
        found = [data.get("factor")] * 3
    elif data.get("uniform") is False:
        found = data.get("factors")
    else:
        return None
    if not isinstance(found, list) or len(found) != 3 or not all(_is_number(f) for f in found):
        return None
    return [float(f) for f in found]


def _turns_off_axes(ctx):
    """True when the recipe is carried into the assembly by a map that turns some axis off the axes."""
    frames = [rigid.move_for(ctx.capture).rows]
    frame = ctx.component_frame()
    if frame is not None:
        frames.append(rigid.move_from_frame(frame).rows)
    return any(axis_turn(rows) is None for rows in frames)


def _volume_matches(record, after, factors):
    before, now = record.get("volume_before"), after.get("volume")
    if not _is_number(before) or not _is_number(now):
        return None
    expected = before * factors[0] * factors[1] * factors[2]
    return abs(now - expected) <= VOLUME_TOL * abs(expected) + VOLUME_TOL_MM3


def _box_matches(record, after, center, factors):
    before, now = record.get("box_before"), after.get("box")
    if not _is_box(before) or not _is_box(now):
        return None
    for i in range(3):
        size = before["max"][i] - before["min"][i]
        for key in ("min", "max"):
            expected = center[i] + factors[i] * (before[key][i] - center[i])
            if abs(now[key][i] - expected) > BOX_TOL_MM + BOX_TOL * abs(size * factors[i]):
                return False
    return True


def _factor(ctx, item, path, literal):
    why = "%s needs a factor between %g and %g" % (_name(item), MIN_FACTOR, MAX_FACTOR)
    q = values.quantity(ctx, item, path, literal, dim="scalar", absolute=True)
    q = values.stays_above(ctx, item, q, MIN_FACTOR, why)
    return values.stays_below(ctx, item, q, MAX_FACTOR + 1e-9, why)


def _point(ctx, item, record):
    """The written point. A point that sizes may move stays where it was measured, and those sizes are marked."""
    names = reach.reference_sizes(ctx.table, ctx.timeline, item, record)
    if names:
        ctx.doubt(names, "%s scales about a point that may move with it, and the copy cannot follow that" % _name(item))
    return [round9(c) for c in record["point"]]


def _checked(ctx, item, data):
    """`(record, after, center, factors)` of a Scale the copy can write, or a Refusal."""
    name = _name(item)
    if data.get("input_kind") != "bodies":
        return _refuse("%s scales sketches or other items, and only a scale of bodies is copied." % name)
    found = _target(ctx, data)
    if found is None or found[0].get("foreign"):
        return _refuse("The body that %s scales could not be measured." % name)
    point = data.get("point")
    if not isinstance(point, dict) or point.get("kind") == "other" or not isinstance(point.get("point"), list):
        return _refuse("The point that %s scales about could not be read, or it is in another component." % name)
    factors = _factors(data)
    if factors is None:
        return _refuse("The factor of %s could not be read." % name)
    if not all(MIN_FACTOR <= f <= MAX_FACTOR for f in factors):
        return _refuse("%s scales by a factor under %g or over %g." % (name, MIN_FACTOR, MAX_FACTOR))
    if not ctx.steps:
        return _refuse("%s scales a body that nothing in the copy builds before it." % name)
    if data.get("uniform") is False and _turns_off_axes(ctx):
        return _refuse("%s scales each axis by its own factor in a component that is turned at an angle." % name)
    record, after = found
    center = [float(c) for c in point["point"]]
    volume, box = _volume_matches(record, after, factors), _box_matches(record, after, center, factors)
    if volume is None or box is None:
        return _refuse("The body was not measured around %s, so the scale cannot be checked." % name)
    if not volume or not box:
        return _refuse("%s does not change the body as its factors and point say." % name)
    return record, after, center, factors


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    found = _checked(ctx, item, data)
    if isinstance(found, Refusal):
        return found
    _, _, center, factors = found
    if data.get("uniform"):
        factor = _factor(ctx, item, "factor", factors[0]).json()
    else:
        factor = [_factor(ctx, item, "factors.%d" % n, f).json() for n, f in enumerate(factors)]
    out = StepResult()
    out.add({"kind": "scale", "factor": factor, "point": _point(ctx, item, data["point"])},
            [ScaleMaker(center, factors)])
    return out
