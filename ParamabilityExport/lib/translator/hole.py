"""Hole and thread handlers (HoleFeature, ThreadFeature).

A hole with a flat end, or through all the way, is a recipe `hole`. A blind hole with a drill tip has no recipe
`hole` form, so it becomes a revolve cut of the hole's profile (shank, optional step or cone, and the cone of the
tip) turned about the hole axis. Measured `end_points` and `side_cylinders` check the stored direction and size.
Hole points follow sizes when the probe's motion file moves them (sketch_motion.py).
"""
import math

from ..package.numbers import round9

from . import range_check, sketch_motion, values, vec
from .values import Quantity
from .result import Refusal, StepResult


MARGIN_MM = 0.01
DIAMETER_TOL = 1e-3
BEHIND_TOL = 1e-6
FLAT_TIP_DEG = 179.999
MIN_COUNTERSINK_DEG, MAX_COUNTERSINK_DEG = 60.0, 120.0
TAPPED = ("tapped", "taperTapped")


def _vec(values):
    return [round9(v) for v in values]


def _is_flat(tip_deg):
    return tip_deg is None or tip_deg >= FLAT_TIP_DEG


def _perpendicular(direction):
    """A unit vector square to `direction`: d x world X, or d x world Y when d is close to X."""
    other = [0.0, 1.0, 0.0] if abs(direction[0]) > 0.9 else [1.0, 0.0, 0.0]
    return vec.unit(vec.cross(direction, other))


def _direction(data, ctx):
    """Unit hole direction (into the material), negated when a measured end lies behind the positions."""
    direction = vec.unit(data["direction"])
    positions = data["positions"]
    for at, end in enumerate(data.get("end_points") or []):
        start = positions[min(at, len(positions) - 1)]
        if vec.dot(vec.sub(end, start), direction) < -BEHIND_TOL:
            ctx.note("Fusion stored the hole direction the other way; the measured end of the hole was used.")
            return vec.scale(direction, -1.0)
    return direction


def _check_size(data, ctx, count, diameter):
    """Note when the measured cylinder faces disagree with the stored diameter or number of holes."""
    cylinders = list(data.get("side_cylinders") or [])
    if not cylinders:
        return
    bore = data.get("counterbore")
    if bore:
        cylinders = [c for c in cylinders if abs(2 * c["radius"] - bore["diameter"]) > DIAMETER_TOL] or cylinders
    if len(cylinders) != count or any(abs(2 * c["radius"] - diameter) > DIAMETER_TOL for c in cylinders):
        ctx.note("The measured size of this hole differs from its stored size; the stored size was used.")


def _drill_diameter(data):
    """Diameter of the drilled bore of a cosmetic tapped hole, or a Refusal.

    The widest measured cylinder that is not wider than the stored size: a counterbore wall is wider, and the
    thread's nominal size is the stored one.
    """
    limit = float(data["diameter"]) / 2.0 + DIAMETER_TOL
    radii = [float(c["radius"]) for c in data.get("side_cylinders") or [] if float(c["radius"]) <= limit]
    if not radii:
        return Refusal("The drill size of this tapped hole could not be measured.")
    return 2.0 * max(radii)


def _diameter(data, ctx):
    """Diameter to cut: the stored one, or for a tapped hole the measured drill size, or a Refusal."""
    if data.get("tap_type") not in TAPPED:
        return float(data["diameter"])
    if data.get("tap_type") == "taperTapped":
        return Refusal("Tapered threads are not copied yet.")
    if data.get("thread_modeled") is None:
        return Refusal("The thread of this hole could not be read.")
    if data["thread_modeled"]:
        return Refusal("Modeled threads are not copied yet.")
    drilled = _drill_diameter(data)
    if not isinstance(drilled, Refusal):
        ctx.note("The thread of this hole is not copied; it was cut as a plain hole.")
    return drilled


def _is_tipped(data, tip, ctx):
    """True for a conical drill point, False for a flat end, or a Refusal.

    The measured shape of the end faces (`end_face_types`) wins over the stored tip angle.
    """
    stored_tipped = not _is_flat(tip)
    measured = set(data.get("end_face_types") or [])
    if not measured:
        return stored_tipped
    if measured == {"cone"}:
        tipped = True
    elif measured == {"plane"}:
        tipped = False
    else:
        return Refusal("The end of this hole could not be told apart as flat or pointed.")
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


def _sizes(item, ctx, diameter, depth, counterbore, countersink):
    data = item["data"]
    if data.get("tap_type") in TAPPED:
        values.pin(ctx, item, "diameter", "the thread of %s sets the drill size" % item.get("name", "a hole"))
        diameter_q = Quantity(diameter)
    else:
        diameter_q = values.quantity(ctx, item, "diameter", diameter, absolute=True)
    depth_q = None if depth is None else values.quantity(ctx, item, "extent.depth", depth, absolute=True)
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


def hole(item, ctx):
    data = item.get("data") or {}
    if not data.get("positions") or not data.get("direction") or not data.get("diameter"):
        return Refusal("This hole has no readable position or size.")
    hole_type = data.get("hole_type", "simple")
    counterbore = data.get("counterbore") if hole_type == "counterbore" else None
    countersink = data.get("countersink") if hole_type == "countersink" else None
    if hole_type not in ("simple", "counterbore", "countersink") or (
        (hole_type == "counterbore" and not counterbore) or (hole_type == "countersink" and not countersink)
    ):
        return Refusal("This kind of hole is not copied yet.")
    extent = data.get("extent") or {}
    if extent.get("kind") not in ("distance", "throughAll"):
        return Refusal("This way of setting the hole depth is not copied yet.")
    through = extent["kind"] == "throughAll"
    depth = None if through else float(extent["depth"])
    if not through and not depth > 0:
        return Refusal("This hole has no depth.")

    diameter = _diameter(data, ctx)
    if isinstance(diameter, Refusal):
        return diameter
    direction = _direction(data, ctx)
    _check_size(data, ctx, len(data["positions"]), diameter)
    sizes = _sizes(item, ctx, diameter, depth, counterbore, countersink)

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
        points = sketch_motion.points(ctx, item, data["positions"])
        return StepResult.of(_tip_step(p, direction, profile) for p in points)
    return StepResult.of(_hole_step(p, direction, sizes.diameter, sizes.depth, sizes.counterbore, sizes.countersink)
                         for p in sketch_motion.points(ctx, item, data["positions"]))


def thread(item, ctx):
    """A cosmetic thread changes no solid: it makes no step. A modeled one is refused."""
    if (item.get("data") or {}).get("modeled"):
        return Refusal("Modeled threads are not copied yet.")
    ctx.note("The thread is not copied; the exported shape has none either.")
    return StepResult()
