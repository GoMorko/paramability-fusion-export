"""Hole and cosmetic thread handlers (HoleFeature, ThreadFeature); modeled threads are in `thread.py`.

A hole with a flat end, or through all the way, is a recipe `hole`. A hole that ends at a face or body is a blind hole
of the measured depth. A tapped hole with a modeled thread is a hole at the thread's minor diameter plus an internal
recipe `thread` for each position. A blind hole with a drill tip has no recipe
`hole` form, so it becomes a revolve cut of the hole's profile (shank, optional step or cone, and the cone of the
tip) turned about the hole axis. Measured `end_points` and `side_cylinders` check the stored direction and size.
Hole points follow sizes when the probe's motion file moves them (sketch/sketch_motion.py). A hole on a sketch point, or on a
flat face, of another component moves with that place (ref_motion.py).
"""
import math

from ...design_model.problem import Problem
from ...design_model.steps import hole as facts
from ...design_model.values import Quantity, Sized
from ...geometry import vec
from ...package.numbers import round9

from .. import ref_motion, values
from ..faces import follow
from ..faces.slabs import as_quantity
from ..ranges import range_check
from ..result import Refusal, StepResult
from ..sketch import sketch_motion
from . import thread as threads


MARGIN_MM = 0.01
FLAT_TIP_DEG = 179.999
MIN_COUNTERSINK_DEG, MAX_COUNTERSINK_DEG = 60.0, 120.0


def _vec(values):
    return [round9(v) for v in values]


def _is_flat(tip_deg):
    return tip_deg is None or tip_deg >= FLAT_TIP_DEG


def _perpendicular(direction):
    """A unit vector square to `direction`: d x world X, or d x world Y when d is close to X."""
    other = [0.0, 1.0, 0.0] if abs(direction[0]) > 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(direction, other))


def _direction(data, ctx):
    """Unit hole direction (into the material); the measured end of the hole wins over the stored direction."""
    found = facts.direction_of(data)
    if found.flipped:
        ctx.note("Fusion stored the hole direction the other way; the measured end of the hole was used.")
    return found.unit


def _check_size(data, ctx, count, diameter):
    """Note when the measured cylinder faces disagree with the stored diameter or number of holes."""
    if facts.size_differs(data, count, diameter):
        ctx.note("The measured size of this hole differs from its stored size; the stored size was used.")


def _is_tipped(data, tip, ctx):
    """True for a conical drill point, False for a flat end, or a Refusal.

    The measured shape of the end faces (`facts.end_shape`) wins over the stored tip angle.
    """
    stored_tipped = not _is_flat(tip)
    measured = facts.end_shape(data)
    if measured is None:
        return stored_tipped
    if measured == facts.MIXED:
        return Refusal("The end of this hole could not be told apart as flat or pointed.")
    tipped = measured == facts.CONE
    if tipped != stored_tipped:
        ctx.note("Fusion stored the drill tip of this hole differently from its measured end; the measured end was used.")
    return tipped


def _tip_profile(diameter, depth, tip_deg, counterbore, countersink):
    """Outline in (radial, depth) coordinates as [x, y] numbers or formulas. `depth` runs to the shoulder.

    `diameter`, `depth` and the counterbore and countersink sizes are Quantities, so the outline can follow sizes.
    The counterbore or countersink must fit the hole (`_misfit`).
    """
    radius = diameter.scaled(0.5)
    tip_run = 1.0 / math.tan(math.radians(tip_deg) / 2.0)
    apex = depth.plus(radius.scaled(tip_run))
    zero, top = Quantity(0.0), Quantity(-MARGIN_MM)
    points = [(zero, top)]
    if counterbore:
        wide = counterbore["diameter"].scaled(0.5)
        bore_depth = counterbore["depth"]
        points += [(wide, top), (wide, bore_depth), (radius, bore_depth)]
    elif countersink:
        half = math.tan(math.radians(countersink["angle_deg"].n) / 2.0)
        wide = countersink["diameter"].scaled(0.5)
        points += [(wide.plus(MARGIN_MM * half), top), (radius, wide.plus(radius.scaled(-1)).scaled(1.0 / half))]
    else:
        points.append((radius, top))
    points += [(radius, depth), (zero, apex)]
    return [[x.json(), y.json()] for x, y in points]


def _misfit(sizes, tipped, through):
    """Why a counterbore or countersink does not fit its hole at the current values, or None when it does."""
    bore, sink = sizes.counterbore, sizes.countersink
    if bore and not (bore["diameter"].n > sizes.diameter.n and (through or 0 < bore["depth"].n < sizes.depth.n)):
        return "The counterbore of this hole does not fit its size."
    if sink:
        angle = sink["angle_deg"].n
        wider = sink["diameter"].n > sizes.diameter.n
        if tipped:
            half = math.tan(math.radians(angle) / 2.0) if 0 < angle < 180 else None
            fits = wider and half is not None and (sink["diameter"].n - sizes.diameter.n) / 2.0 / half < sizes.depth.n
        else:
            fits = wider and MIN_COUNTERSINK_DEG <= angle <= MAX_COUNTERSINK_DEG
        if not fits:
            return "The countersink of this hole does not fit its size."
    return None


def _unfollow(ctx, why, *quantities):
    """The quantities as plain numbers; the sizes they read are marked for `why` (`Context.doubt`)."""
    ctx.doubt(tuple(dict.fromkeys(r for q in quantities for r in q.reads)), why)
    return [Quantity(q.n) for q in quantities]


def _stays_positive(ctx, difference):
    """True when a Quantity stays above zero at every corner of the size ranges (a plain number is not tested)."""
    return not difference.sized or range_check.sweep(ctx.table, difference.text, difference.reads).above(0.0)


def _keep_fit(ctx, item, sizes, tipped):
    """A counterbore or countersink that fits at the current values must fit at every size of the ranges: its
    diameter stays wider than the hole's, its depth shallower than the hole's (for a countersink the cone's run, in
    a hole with a drill tip). When it does not, the values involved are written as numbers and their sizes marked."""
    name = item.get("name", "a hole")
    diameter, depth = sizes.diameter, sizes.depth
    bore, sink = sizes.counterbore, sizes.countersink
    if bore:
        why = "the counterbore of %s would stop fitting its hole at some sizes" % name
        if not _stays_positive(ctx, bore["diameter"].plus(diameter.scaled(-1))):
            bore["diameter"], diameter = _unfollow(ctx, why, bore["diameter"], diameter)
        if depth is not None and not _stays_positive(ctx, depth.plus(bore["depth"].scaled(-1))):
            bore["depth"], depth = _unfollow(ctx, why, bore["depth"], depth)
    if sink:
        why = "the countersink of %s would stop fitting its hole at some sizes" % name
        if not _stays_positive(ctx, sink["diameter"].plus(diameter.scaled(-1))):
            sink["diameter"], diameter = _unfollow(ctx, why, sink["diameter"], diameter)
        if tipped:
            half = math.tan(math.radians(sink["angle_deg"].n) / 2.0)
            run = sink["diameter"].plus(diameter.scaled(-1)).scaled(0.5 / half)
            if not _stays_positive(ctx, depth.plus(run.scaled(-1))):
                sink["diameter"], diameter, depth = _unfollow(ctx, why, sink["diameter"], diameter, depth)
    sizes.diameter, sizes.depth = diameter, depth


def _hole_step(position, direction, diameter, depth, counterbore, countersink):
    step = {"kind": "hole", "origin": list(position), "direction": _vec(direction), "diameter": diameter.json(),
            "depth": None if depth is None else depth.json()}
    if counterbore:
        step["counterbore"] = {"diameter": counterbore["diameter"].json(), "depth": counterbore["depth"].json()}
    if countersink:
        step["countersink"] = {"diameter": countersink["diameter"].json(),
                               "angleDeg": countersink["angle_deg"].json()}
    return step


def _tip_step(position, direction, profile):
    across = _perpendicular(direction)
    return {
        "kind": "revolve",
        "sketch": {
            "on": {"origin": list(position), "normal": _vec(vec.cross(across, direction)), "xDir": _vec(across)},
            "outer": {"kind": "polygon", "points": profile},
        },
        "axis": {"point": [0, 0], "dir": [0, 1]},
        "combine": "cut",
    }


class _Sizes:
    """The numbers of a hole as Quantities (they follow sizes when their parameters do)."""

    def __init__(self, diameter, depth, counterbore, countersink):
        self.diameter, self.depth = diameter, depth
        self.counterbore, self.countersink = counterbore, countersink


def _sizes(item, ctx, diameter, depth, counterbore, countersink, depth_q=None):
    data = item["data"]
    if facts.tap_of(data) != facts.PLAIN:
        values.pin(ctx, item, "diameter", "the thread of %s sets the drill size" % item.get("name", "a hole"))
        diameter_q = Quantity(diameter)
    else:
        diameter_q = values.quantity(ctx, item, "diameter", diameter, absolute=True)
    if depth_q is None and depth is not None:
        depth_q = values.quantity(ctx, item, "extent.depth", depth, absolute=True)
    bore = None
    if counterbore:
        bore = {"diameter": values.quantity(ctx, item, "counterbore.diameter", counterbore["diameter"], absolute=True),
                "depth": values.quantity(ctx, item, "counterbore.depth", counterbore["depth"], absolute=True)}
    sink = None
    if countersink:
        values.pin(ctx, item, "countersink.angle_deg", "the countersink of %s needs its angle to stay as it is"
                   % item.get("name", "a hole"))
        sink = {"diameter": values.quantity(ctx, item, "countersink.diameter", countersink["diameter"], absolute=True),
                "angle_deg": Quantity(countersink["angle_deg"])}
    return _Sizes(diameter_q, depth_q, bore, sink)


def hole(ctx, step):
    item, data = step.brought, step.brought_data
    problem = facts.placed(data)
    if problem:
        return threads.refusal(problem)
    kind = facts.kind_of(data)
    if isinstance(kind, Problem):
        return threads.refusal(kind)
    counterbore = kind.recess if kind.name == facts.COUNTERBORE else None
    countersink = kind.recess if kind.name == facts.COUNTERSINK else None
    extent = facts.extent_of(data)
    if isinstance(extent, Problem):
        return threads.refusal(extent)
    through = extent.kind == facts.THROUGH_ALL
    up_to = extent.kind == facts.TO_ENTITY
    depth = extent.depth

    tap = facts.tap_of(data)
    if isinstance(tap, Problem):
        return threads.refusal(tap)
    spec = None
    if tap == facts.PLAIN:
        diameter = float(data["diameter"])
    else:
        bore = facts.tapped_bore(data, item.get("name", "a hole"), threads.PITCHES)
        if isinstance(bore, Problem):
            return threads.refusal(bore)
        diameter, spec = bore
        if spec is None:
            ctx.note("The thread of this hole is not copied; it was cut as a plain hole.")
    moved = ref_motion.hole_moves(ctx, item, data)
    direction = _direction(data, ctx)
    _check_size(data, ctx, len(data["positions"]), diameter)
    points = _moved_points(ctx, item, data["positions"], moved)
    depth_q = None
    if up_to:
        depth_q = _up_to_depth(item, ctx, data, direction, points)
        if isinstance(depth_q, Refusal):
            return depth_q
        depth = depth_q.n
    sizes = _sizes(item, ctx, diameter, depth, counterbore, countersink, depth_q)

    tip = data.get("tip_angle_deg")
    tipped = False
    if through:
        values.handled(ctx, item, "tip_angle_deg")
    else:
        values.pin(ctx, item, "tip_angle_deg",
                   "the drill tip of %s needs it to stay as it is" % item.get("name", "a hole"))
        tipped = _is_tipped(data, tip, ctx)
        if isinstance(tipped, Refusal):
            return tipped
    if tipped and (tip is None or not 0 < tip < 180):
        return Refusal("The drill tip angle of this hole could not be read.")
    misfit = _misfit(sizes, tipped, through)
    if misfit:
        return Refusal(misfit)
    _keep_fit(ctx, item, sizes, tipped)
    if tipped:
        profile = _tip_profile(sizes.diameter, sizes.depth, float(tip), sizes.counterbore, sizes.countersink)
        steps = [_tip_step(p, direction, profile) for p in points]
    else:
        steps = [_hole_step(p, direction, sizes.diameter, sizes.depth, sizes.counterbore, sizes.countersink)
                 for p in points]
    if spec is not None:
        cut = threads.hole_threads(ctx, item, data, spec, points, direction, sizes.depth, through)
        if isinstance(cut, Refusal):
            return cut
        steps += cut
    return StepResult.of(steps)


def _along_shifts(points, direction):
    """How far each written hole point moves along `direction` with the sizes: a Quantity per point whose number is
    zero (the sum of each coordinate's formula less its number)."""
    out = []
    for point in points:
        total = Quantity(0.0)
        for c, d in zip(point, direction):
            q = as_quantity(c)
            if abs(d) > 1e-9 and q.sized:
                total = total.plus(q.plus(-q.n).scaled(d))
        out.append(total)
    return out


def _up_to_depth(item, ctx, data, direction, points):
    """The depth of a hole that ends at a face or body, as a Quantity, or a Refusal. It is the measured distance from
    the entry to the flat end of the hole; it follows the face the hole reaches (`follow.target_shift`) and the entry."""
    measured = facts.reach_depth(data, direction)
    if isinstance(measured, Problem):
        return threads.refusal(measured)
    shifts = _along_shifts(points, direction)
    if any(shift.sized and not shift.same_as(shifts[0]) for shift in shifts):
        ctx.doubt(tuple(dict.fromkeys(r for shift in shifts for r in shift.reads)),
                  "the holes of %s do not all move the same way along their depth" % item.get("name", "a hole"))
        shifts = [Quantity(0.0)] * len(shifts)
    reach = follow.target_shift(ctx, item, data["extent"], direction, "ends at")
    if reach is None:
        reach = Quantity(0.0)
    depth = reach.plus(measured - reach.n) if reach.sized else Quantity(measured)
    depth = depth.plus(shifts[0].scaled(-1))
    if depth.sized and not values.stays_positive(ctx.table, depth):
        ctx.doubt(depth.reads, "%s would end before it starts at some sizes" % item.get("name", "a hole"))
        depth = Quantity(measured)
    return depth


def _moved_points(ctx, item, rows, moved):
    """The written hole points, each moved by the formulas of `moved` (how far the place it sits on moves)."""
    points = sketch_motion.points(ctx, item, rows)
    for point, move in zip(points, moved):
        for c, q in enumerate(move):
            if q.sized:
                at = point[c]
                base = Quantity(at.n, at["expr"], at.reads) if isinstance(at, Sized) else Quantity(float(at))
                point[c] = base.plus(q).json()
    return points


def thread(ctx, step):
    """A cosmetic thread changes no solid: it makes no step. A modeled one is `thread.feature`."""
    if step.brought_data.get("modeled"):
        return threads.feature(step.brought, ctx)
    ctx.note("The thread is not copied; the exported shape has none either.")
    return StepResult()
