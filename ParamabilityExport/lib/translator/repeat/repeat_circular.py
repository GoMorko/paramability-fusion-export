"""Circular patterns (CircularPatternFeature), and the motion of a turn about an axis.

A turn about an axis that sits on a face or edge of the part follows sizes (`axis_shift`). A pattern that turns copies
to both sides of the original is written as a part turning each way (`repeat/symmetric.py`).
"""
import math

from ...geometry import vec
from ...package.numbers import round9
from ..faces import follow
from .. import ref_motion, values
from . import symmetric
from ..faces.follow import Motion
from .repeat_build import build, keep_pattern_fixed, round_vec
from .repeat_elements import FIT_TOL_MM, in_component, kept_elements
from .repeat_lattice import gaps_between
from .repeat_sources import split_sources
from ..result import Refusal
from ..values import Quantity

ANGLE_TOL_DEG = 1e-6
FULL_TURN_DEG = 360.0


def _skip_places(places, total):
    """Copy numbers 1..total-1 that no kept element sits on."""
    return [n for n in range(1, total) if n not in places]


def _turn_about(frame, axis):
    """Signed turn of an element frame about the unit `axis` in degrees (right hand rule), or None when the frame
    is not a rotation about that axis."""
    helper = vec.cross(axis, [1.0, 0.0, 0.0])
    if vec.length(helper) < 0.5:
        helper = vec.cross(axis, [0.0, 1.0, 0.0])
    v = vec.unit(helper)

    def image(w):
        return [sum(frame[name][i] * w[k] for k, name in enumerate("xyz")) for i in range(3)]

    if not vec.close(image(axis), axis, 1e-6):
        return None
    turned = image(v)
    return math.degrees(math.atan2(vec.dot(axis, vec.cross(v, turned)), vec.dot(v, turned)))


def _copy_number(angle, delta, sign, count, full):
    """Copy number k when `angle` sits at sign * k * delta (mod 360), else None."""
    a = (sign * angle) % FULL_TURN_DEG
    if FULL_TURN_DEG - a <= ANGLE_TOL_DEG:
        a = 0.0
    k = round(a / delta)
    if abs(a - k * delta) > ANGLE_TOL_DEG:
        return None
    if k == count and full:
        k = 0
    return k if 0 <= k < count else None


UNIT_DIRECTIONS = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


def axis_shift(ctx, item, axis, direction):
    """How the axis point moves with sizes, as three Quantities (zero where it stays). An axis on a face or edge that
    sizes move takes the move; the part of it along the axis is left out, it changes nothing. An axis that cannot be
    followed stays where it is. An axis of another component moves as the probe measured it (`ref_motion`)."""
    if axis.get("assembly"):
        shifts = ref_motion.axis_moves(ctx, item, axis, "turns copies about")
    else:
        shifts = []
        for unit in UNIT_DIRECTIONS:
            shift = follow.place_plane(ctx, item, axis, unit, "turns copies about")
            if shift is None:
                return [Quantity(0.0)] * 3
            shifts.append(shift)
    return [shift if shift.sized and abs(abs(d) - 1) >= 1e-9 else Quantity(0.0) for shift, d in zip(shifts, direction)]


def turn_motion(point, moved, direction, angle, needs, by):
    """The turn about the axis through `point`, with the shift that follows `moved` (how the axis point moves)."""
    base = Motion.turn(point, direction, angle, needs, by)
    if not any(q.sized for q in moved):
        return base
    shift = []
    for i in range(3):
        total = Quantity(base.shift[i].n)
        for j in range(3):
            coefficient = (1.0 if i == j else 0.0) - base.rows[i][j]
            if abs(coefficient) > 1e-12 and moved[j].sized:
                total = total.plus(moved[j].scaled(coefficient))
        shift.append(total)
    return Motion(base.rows, shift, needs, by)


def _signed_copy(angle, delta, count):
    """The signed copy number k when `angle` sits at k * delta (a turn of 360 degrees more or less counts as the
    same), with k inside the copies a pattern of `count` can reach; else None."""
    for wrap in (0.0, -FULL_TURN_DEG, FULL_TURN_DEG):
        k = round((angle + wrap) / delta)
        if abs(angle + wrap - k * delta) <= ANGLE_TOL_DEG and abs(k) < count:
            return k
    return None


def _tried_turns(direction, point, angle_q):
    """`places_at` of `symmetric.extra_side`: the signed copy numbers of the copies the probe read at a try, for the
    turn between copies that the sizes of that try give. None when a copy does not sit on that turn or the count read
    differs from the one the formulas give."""
    def places_at(env, read, count):
        total = symmetric.value_at(angle_q, env)
        if total is None or total <= 0 or (read.get("count") or [None])[0] != count:
            return None
        found = []
        for element in read.get("elements") or []:
            turn = _turn_about(element["frame"], direction)
            if turn is None or not vec.close(vec.frame_apply(element["frame"], point), point, FIT_TOL_MM):
                return None
            k = _signed_copy(turn, total / (count - 1), count)
            if k is None:
                return None
            found.append(k)
        return found
    return places_at


def _measured_places(setup):
    """`(steps, every)`: `steps` pairs each kept element with its signed copy number and `every` lists the copy numbers
    of all elements, when the measured copies follow the rule of `repeat/symmetric.py`. Else `(None, reason)`."""
    count, delta, point, direction, turns = (setup[key] for key in ("count", "delta", "point", "direction", "turns"))
    steps = [(element, _signed_copy(turn, delta, count)) for element, turn in turns]
    if any(k is None for _, k in steps):
        return None, "The copies of this pattern are not spread evenly round the axis."
    every = []
    for element in setup["data"]["elements"]:
        turn = _turn_about(element["frame"], direction)
        if turn is not None and vec.close(vec.frame_apply(element["frame"], point), point, FIT_TOL_MM):
            k = _signed_copy(turn, delta, count)
            if k is not None:
                every.append(k)
    if 0 not in every:
        return None, "The original sits between two copies of this pattern, which is not copied yet."
    if symmetric.reach(every, count) is None:
        return None, ("The copies of this pattern do not spread to both sides of the first one by the rule that was "
                      "expected.")
    return steps, every


def _on_step(turn, delta):
    """True when `turn` sits on a whole number of steps of `delta` (a turn of 360 degrees more or less counts as the
    same)."""
    for wrap in (0.0, -FULL_TURN_DEG, FULL_TURN_DEG):
        if abs(turn + wrap - round((turn + wrap) / delta) * delta) <= ANGLE_TOL_DEG:
            return True
    return False


def _centred_places(setup):
    """The signed copy numbers of an odd count centred on the original, or None.

    Fusion's own transforms of a symmetric turn do not always show the copies behind the original on their side, so
    an odd count is taken as centred when every copy is listed and kept, the original is among them, and each copy
    still turns by a whole number of steps."""
    count, delta, data = setup["count"], setup["delta"], setup["data"]
    elements = data["elements"]
    left_out = set(data.get("suppressed_ids") or [])
    if count % 2 == 0 or len(elements) != count or any(
            e.get("suppressed") or e.get("id") in left_out for e in elements):
        return None
    turns = [turn for _, turn in setup["turns"]]
    if not any(_on_step(turn, FULL_TURN_DEG) for turn in turns) or not all(_on_step(t, delta) for t in turns):
        return None
    return list(range(-(count // 2), count // 2 + 1))


def _symmetric_circular(item, ctx, setup):
    """A circular pattern that turns copies to both sides of the original: a part turning one way and a part turning
    the other, both from the original (`repeat/symmetric.py`). `setup` holds what `circular` has read."""
    count, delta, point, direction, turns = (setup[key] for key in ("count", "delta", "point", "direction", "turns"))
    steps, every = _measured_places(setup)
    if steps is None:
        centred = _centred_places(setup)
        if centred is None:
            return Refusal(every)
        every = centred
        steps = [(None, k) for k in every]
    reach = symmetric.reach(every, count)
    back, forward = reach
    count_q, angle_q = setup["count_q"], setup["angle_q"]
    side = symmetric.extra_side(ctx, item, count_q, count, (back, forward),
                                _tried_turns(direction, point, angle_q))
    back_q, forward_q = symmetric.part_counts(count_q, back, forward, side)
    moved = axis_shift(ctx, item, setup["axis"], direction)
    present = {k for _, k in steps}
    needs = count_q.reads + angle_q.reads
    name = item.get("name", "")
    motions = {k: turn_motion(point, moved, direction, k * delta, needs, name) for k in sorted(present) if k}
    parts = []
    for sign, part_count, part_q in ((1, forward + 1, forward_q), (-1, back + 1, back_q)):
        skip = [n for n in range(1, part_count) if sign * n not in present]
        if part_count == 1 and not part_q.sized:
            continue
        parts.append((sign, part_count, part_q, skip))
    built = []
    for sign, part_count, part_q, skip in parts:
        polar = {"axisPoint": round_vec(point), "axis": round_vec(vec.scale(direction, sign)), "count": part_count,
                 "angleDeg": round9((part_count - 1) * delta)}
        step = {"kind": "pattern", "polar": polar}
        if skip:
            step["skip"] = skip
        built.append((step, [m for k, m in motions.items() if (k > 0) == (sign > 0)]))
    result = build(ctx, item, setup["solids"], setup["finishes"], built, "pattern")
    if isinstance(result, Refusal):
        return result
    left_out = any(skip for *_, skip in parts)
    keep_pattern_fixed(ctx, item, left_out, setup["finishes"], ("quantity",), ("total_angle_deg",))
    for (sign, part_count, part_q, skip), (step, _) in zip(parts, built):
        polar = step["polar"]
        if any(q.sized for q in moved):
            polar["axisPoint"] = [q.plus(c).json() if q.sized else round9(c) for q, c in zip(moved, point)]
        side = angle_q.times(part_q.plus(-1.0)).divided_by(gaps_between(count_q))
        polar["angleDeg"] = side.json()
        polar["count"] = part_q.json() if part_q.sized and not skip else part_count
    return result


def circular(item, ctx, sources=None):
    """`sources` is `(solid step ids, finish steps)` when the caller wrote what the pattern repeats."""
    item = in_component(item, ctx)
    data = item.get("data") or {}
    sources = split_sources(data, ctx, "pattern") if sources is None else sources
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    axis = data.get("axis") or {}
    if "point" not in axis or "dir" not in axis:
        return Refusal("The turning axis of this pattern could not be read.")
    count = int(data.get("quantity") or 1)
    if count < 2:
        return Refusal("This pattern makes no copies.")
    raw_total = float(data.get("total_angle_deg") or 0.0)
    total_deg = abs(raw_total)
    full = abs(total_deg - FULL_TURN_DEG) <= ANGLE_TOL_DEG
    if not full and not 0 < total_deg < FULL_TURN_DEG:
        return Refusal("The angle of this pattern could not be read.")
    delta = FULL_TURN_DEG / count if full else total_deg / (count - 1)
    kept = kept_elements(data)
    if kept is None:
        return Refusal("The copies of this pattern could not be read.")

    direction = vec.unit(axis["dir"])
    point = axis["point"]
    turns = []
    for element in kept:
        frame = element["frame"]
        turn = _turn_about(frame, direction)
        # The axis point must stay where it is under the element's transform.
        if turn is None or not vec.close(vec.frame_apply(frame, point), point, FIT_TOL_MM):
            return Refusal("The copies of this pattern do not turn about the axis that was read.")
        turns.append((element, turn))

    if data.get("symmetric") and not full:
        count_q = values.quantity(ctx, item, "quantity", count, dim="scalar", whole=True)
        angle_q = values.quantity(ctx, item, "total_angle_deg", total_deg, dim="angle",
                                  sign=-1 if raw_total < 0 else 1, absolute=True)
        return _symmetric_circular(item, ctx, {
            "data": data, "solids": solids, "finishes": finishes, "axis": axis, "count": count, "delta": delta,
            "point": point, "direction": direction, "turns": turns, "count_q": count_q, "angle_q": angle_q})

    sign = next((s for s in (1, -1) if all(_copy_number(t, delta, s, count, full) is not None for _, t in turns)), 0)
    if not sign:
        return Refusal("The copies of this pattern are not spread evenly round the axis.")
    if sign < 0:
        direction = vec.scale(direction, -1)
    by_place = {_copy_number(t, delta, sign, count, full): element for element, t in turns}
    skip = _skip_places(by_place, count)

    moved = axis_shift(ctx, item, axis, direction)
    polar = {"axisPoint": round_vec(point), "axis": round_vec(direction), "count": count}
    if not full:
        polar["angleDeg"] = round9((count - 1) * delta)
    pattern = {"kind": "pattern", "polar": polar}
    if skip:
        pattern["skip"] = skip
    count_q = values.quantity(ctx, item, "quantity", count, dim="scalar", whole=True)
    angle_q = None
    if full:
        values.pin(ctx, item, "total_angle_deg", "%s turns a full circle only while its angle is a plain 360"
                   % item.get("name", "a pattern"))
    else:
        angle_q = values.quantity(ctx, item, "total_angle_deg", total_deg, dim="angle",
                                  sign=-1 if raw_total < 0 else 1, absolute=True)
    needs = count_q.reads + (angle_q.reads if angle_q is not None else ())
    motions = [turn_motion(point, moved, direction, n * delta, needs, item.get("name", ""))
               for n in sorted(by_place) if n > 0]
    steps = build(ctx, item, solids, finishes, [(pattern, motions)], "pattern")
    if isinstance(steps, Refusal):
        return steps
    if any(q.sized for q in moved):
        polar["axisPoint"] = [q.plus(c).json() if q.sized else round9(c) for q, c in zip(moved, point)]
    if angle_q is not None:
        polar["angleDeg"] = angle_q.json()
    keep_pattern_fixed(ctx, item, skip, finishes, ("quantity",), ("total_angle_deg",))
    polar["count"] = count_q.json() if count_q.sized and not skip else count
    return steps
