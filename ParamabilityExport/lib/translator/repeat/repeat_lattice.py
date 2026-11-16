"""The grid of a rectangular pattern: how Fusion measured its distance, and the directions, spacing and copy counts
that follow from the measured copies.
"""
from ...design_model.steps.repeat import FIT_TOL_MM, kept_elements, solve_lattice
from ...design_model.values import Quantity, wrapped
from ...design_model import words as shared
from ...geometry import vec
from .. import ref_motion, values
from ..result import Refusal


def _distance_kind(data):
    """How Fusion measures the pattern distance: `spacing` (between neighbours) or `extent` (first to last), or None.

    When the reader could not name it, the measured copies tell: the kind whose grid holds every kept copy.
    """
    kind = data.get("distance_type")
    if kind in ("spacing", "extent"):
        return kind
    kept = kept_elements(data)
    if not kept:
        return None
    for guess in ("spacing", "extent"):
        axes = []
        for which in ("one", "two"):
            count = int(data.get("quantity_" + which) or 1)
            direction = data.get("direction_" + which)
            distance = abs(float(data.get("distance_" + which) or 0.0))
            if count > 1 and direction and vec.length(direction) > 1e-9 and distance > 1e-9:
                step = distance if guess == "spacing" else distance / _extent_gaps(data, which, count)
                axes.append((vec.unit(direction), step, count))
        if not axes or not all(step > 1e-9 for _, step, _ in axes):
            return None
        if len(axes) == 2 and 1.0 - vec.dot(axes[0][0], axes[1][0]) ** 2 < 1e-9:
            return None
        fits = True
        for element in kept:
            indexes, residual = solve_lattice(element["frame"]["origin"], [(d, s) for d, s, _ in axes])
            if residual > FIT_TOL_MM or any(abs(i) >= c for i, (_, _, c) in zip(indexes, axes)):
                fits = False
                break
        if fits:
            return guess
    return None


def _extent_gaps(data, which, count):
    """How many gaps the extent distance holds. An ordinary direction runs from the first copy to the last
    (`count - 1`). A symmetric direction reaches the distance ahead of the original, and behind it too for an odd
    count (`count // 2` gaps each way); for an even count Fusion keeps the copy ahead at the distance and puts the
    extra copy on that side, so the one behind stops a gap short."""
    return max(count // 2, 1) if data.get("symmetric_" + which) else count - 1


def _extent_step_q(data, which, distance, count_q):
    """The spacing of an extent distance as a Quantity (`_extent_gaps`)."""
    if not data.get("symmetric_" + which):
        return distance.divided_by(gaps_between(count_q))
    if not count_q.sized:
        return distance.divided_by(Quantity(float(max(int(count_q.n) // 2, 1))))
    text = "max(floor(%s / 2), 1)" % wrapped(count_q.text)
    return distance.divided_by(Quantity(float(max(int(count_q.n) // 2, 1)), text, count_q.reads))


def _axis_step(item, ctx, which, quantity, count_q, kind):
    """Spacing along one direction as a Quantity, from the pattern distance and how Fusion measures it."""
    data = item["data"]
    raw = float(data.get("distance_" + which) or 0.0)
    if kind not in ("spacing", "extent"):
        return Refusal("The spacing of this pattern could not be read.")
    distance = values.quantity(ctx, item, "distance_" + which, abs(raw), sign=-1 if raw < 0 else 1, absolute=True)
    if kind == "extent":
        step = _extent_step_q(data, which, distance, count_q)
    else:
        step = distance
    if not step.n > 1e-9:
        return Refusal("The spacing of this pattern could not be read.")
    return step


def gaps_between(count_q):
    """The gaps between `count` copies; a count that follows sizes never gives zero gaps, so one copy divides by 1."""
    if not count_q.sized:
        return count_q.plus(-1)
    return Quantity(count_q.n - 1, "max(%s - 1, 1)" % count_q.text, count_q.reads)


def lattice_axes(item, ctx):
    """The directions that have more than one copy, as dicts {dir, step, count, step_q, count_q, symmetric, which,
    sign}; or a Refusal. `sign` is -1 when the distance is negative, so the copies run against `dir`.

    `step` and `count` are the numbers; `step_q` and `count_q` are Quantities that may follow sizes.
    """
    data = item["data"]
    kind = _distance_kind(data)
    axes = []
    for which, dir_key, qty_key in (("one", "direction_one", "quantity_one"), ("two", "direction_two", "quantity_two")):
        quantity = int(data.get(qty_key) or 1)
        if quantity < 1:
            return Refusal("This pattern has no copies.")
        if quantity == 1:
            values.pin(ctx, item, "quantity_" + which, "a count of one copy cannot follow it")
            values.handled(ctx, item, "distance_" + which)
            continue
        if abs(float(data.get("distance_" + which) or 0.0)) < 1e-9:
            # Copies spaced 0 apart sit on one another, so the direction adds no place.
            values.pin(ctx, item, "quantity_" + which, "copies spaced 0 apart add no place")
            values.pin(ctx, item, "distance_" + which, "copies spaced 0 apart add no place")
            continue
        direction = data.get(dir_key)
        if not direction or vec.length(direction) < 1e-9:
            return Refusal(shared.PATTERN_DIRECTION_UNREAD)
        place = data.get(dir_key + "_place")
        if isinstance(place, dict) and place.get("assembly"):
            ref_motion.check_direction(ctx, item, place, "spreads copies along")
        count_q = values.quantity(ctx, item, "quantity_" + which, quantity, dim="scalar", whole=True)
        step_q = _axis_step(item, ctx, which, quantity, count_q, kind)
        if isinstance(step_q, Refusal):
            return step_q
        # A negative distance runs the copies against the direction: `sign` says which way the distance points.
        sign = -1 if float(data.get("distance_" + which) or 0.0) < 0 else 1
        axes.append({"dir": vec.unit(direction), "step": step_q.n, "count": quantity, "step_q": step_q,
                     "count_q": count_q, "symmetric": bool(data.get("symmetric_" + which)), "which": which,
                     "sign": sign})
    if not axes:
        return Refusal(shared.PATTERN_NO_COPIES)
    if len(axes) == 2 and 1.0 - vec.dot(axes[0]["dir"], axes[1]["dir"]) ** 2 < 1e-9:
        return Refusal(shared.PATTERN_ONE_LINE)
    return axes
