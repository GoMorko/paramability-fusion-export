"""Extrude feature handler (ExtrudeFeature): sketch profiles swept along their sketch normal.

Profiles that share a curve are merged into one outline (outlines.py); each outline becomes one recipe `extrude` step
per side. Fusion's sign conventions are checked against the measured
`end_offset` (where the end face landed), which wins when the two disagree. With the probe's motion file the outline
and its sketch plane follow sizes (sketch_motion.py). A start or reach on a flat face or plane follows the earlier
step that made it (follow.target_shift), else the offset the probe measured for it (reach_motion.py, and ref_motion.py
for one of another component).

A thin extrude of one closed outline without holes is written with the recipe's `thin` wall (thin_wall.py): the wall
thickness follows its parameter, and the side of the outline comes from the measured area of the end face. Open lines,
several outlines, outlines with holes, two sided and tapered thin extrudes are refused.

An extrude of text or spline outlines is also checked against the volume Fusion made.

A flat face of the part used as the outline is drawn again from the earlier extrude that made it, or written as
measured with the sizes that may change it marked (face_outline.py). Sketch outlines beside the face must lie on its
plane.
"""
import heapq
import math

from ..package.numbers import round9

from . import (face_outline, follow, kept_ranges, loops, notes, outlines, placement, reach_motion, sketch_motion,
               thin_wall, values, vec)
from .footprint import Footprint, polyline
from .placer_makers import SlabMaker, ThinWallMaker
from .result import Refusal, StepResult
from .values import Quantity


# Fusion's positive taper angle widens the walls going away from the sketch (the API reference says it tapers
# outward, and measured side walls agree). The recipe leans walls in for a positive `taperDeg`, so the two are opposite.
# A tapered extrude is only copied when the measured end face area (`end_area` against `profile_area`) agrees.
FUSION_TAPER_SIGN = -1

MAX_TAPER_DEG = 45.0
TAPER_MARGIN_DEG = 0.01
PARALLEL_TOL = 1e-9
SIGN_TOL = 1e-9
LENGTH_TOL = 1e-3
AREA_RELATIVE_TOL = 1e-6
# Sine of the wall lean: about 0.006 degrees.
LEAN_TOL = 1e-4
PLANE_TOL = 1e-4
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
# A tapered cut through all whose walls lean in ends this far (mm) past the part.
THROUGH_TAPER_MARGIN_MM = 1.0
COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect", "newBody": "new"}


def _sign_of(value):
    return -1 if value < 0 else 1


def _parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


def _fits(sign, rel_end, reach, other):
    """True when a face at `rel_end` can lie in an extrude that goes `reach` along `sign` and `other` the other way."""
    limit = reach if _sign_of(rel_end) == sign else other
    return abs(rel_end) <= limit + LENGTH_TOL


def _choose_sign(ctx, geometric, rel_end, reach=None, other=None):
    """Direction (+1 along the sketch normal, -1 against it): the measured end face wins over the stored sign.

    A two sided extrude passes `reach` (this side) and `other` (the other side): its end faces lie on both sides, so
    the measured face turns the direction only when it fits the turned extrude and not the stored one."""
    if rel_end is None or abs(rel_end) < SIGN_TOL:
        return geometric
    measured = _sign_of(rel_end)
    if measured != geometric and reach is not None and other is not None and (
            _fits(geometric, rel_end, reach, other) or not _fits(-geometric, rel_end, reach, other)):
        return geometric
    if measured != geometric:
        ctx.note("Fusion stored the extrude direction two ways; the measured end of the extrude was used.")
    return measured


UNREADABLE = "A setting of this extrude could not be read from Fusion."


def _taper(deg):
    """Recipe `taperDeg` from Fusion's, or a Refusal. None (unreadable) refuses."""
    if deg is None:
        return Refusal(UNREADABLE)
    if not deg:
        return 0.0
    value = FUSION_TAPER_SIGN * deg
    if abs(value) >= MAX_TAPER_DEG:
        return Refusal("The taper of this extrude is too steep to copy.")
    return value


def _taper_quantity(ctx, item, path, taper):
    """The taper as the recipe writes it: a Quantity that may follow sizes, or None for no taper."""
    if not taper:
        values.pin(ctx, item, path, "a taper of zero cannot follow it")
        return None
    q = values.quantity(ctx, item, path, taper, dim="angle", sign=FUSION_TAPER_SIGN)
    if q.sized:
        _keep_taper_under_limit(ctx, item, q)
    return q


def _keep_taper_under_limit(ctx, item, q):
    """A taper that follows sizes should stay under MAX_TAPER_DEG either way, since Paramability refuses a steeper
    one."""
    keep_angle_within(ctx, item, q, MAX_TAPER_DEG, "lean its walls %d degrees or more" % MAX_TAPER_DEG)


def keep_angle_within(ctx, item, q, limit_deg, effect):
    """An angle that follows sizes should stay within `limit_deg` either way: the ranges of the sizes it reads are cut
    where it does not, or the sizes are marked when no cut keeps it. `effect` says what the step would do beyond the
    limit."""
    limit = Quantity(limit_deg)
    rules = [(limit.plus(q.scaled(-1.0)), 1), (limit.plus(q), 1)]
    found = kept_ranges.holding_ranges(ctx.table, rules, TAPER_MARGIN_DEG)
    why = "%s would %s" % (item.get("name", "a step"), effect)
    if found is None:
        ctx.doubt(q.reads, "at other values " + why)
    elif found:
        ctx.cut(found, why)


def _distance_quantity(ctx, item, path, raw):
    """The length of one side. The recipe writes the absolute value, so a negative parameter is written negated."""
    return values.quantity(ctx, item, path, abs(raw), sign=_sign_of(raw), absolute=True)


def _start_shift(start, frame, ctx, item, plane_q):
    """Signed distance along the sketch normal from the sketch plane to where the extrude starts, as a Quantity that
    follows sizes (an offset parameter, or a face that moves with an earlier extrude); or a Refusal.

    An offset starts from the sketch plane and moves with it. A start on a face is measured from the plane too, so the
    plane's own move (`plane_q`, along the sketch normal) comes off the face's move: the written origin adds it back."""
    if start is None:
        return Refusal(UNREADABLE)
    kind = start.get("kind", "profilePlane")
    if kind == "profilePlane":
        return Quantity(0.0)
    if kind == "offset":
        if start.get("offset") is None:
            return Refusal(UNREADABLE)
        return values.quantity(ctx, item, "start.offset", float(start["offset"]))
    if kind == "fromEntity":
        values.pin(ctx, item, "start.offset", "it sets how far %s starts from its face" % item.get("name", "a step"))
        plane = start.get("plane")
        if not plane:
            return Refusal("This extrude starts from a surface that is not flat, which is not copied yet.")
        if not _parallel(plane["normal"], frame["z"]):
            return Refusal("This extrude starts from a tilted surface, which is not copied yet.")
        shift = vec.dot(vec.sub(plane["point"], frame["origin"]), vec.unit(frame["z"]))
        moved = reach_motion.target_shift(ctx, item, "start", start, vec.unit(frame["z"]), "starts from")
        face = Quantity(shift) if moved is None or not moved.sized else moved.plus(shift - moved.n)
        if not plane_q.sized:
            return face
        if face.sized and (face.text == plane_q.text or face.core == plane_q.core):
            return Quantity(face.n - plane_q.n)
        return face.plus(plane_q.scaled(-1))
    return Refusal("This extrude starts in a way that is not copied yet.")


def _origin(frame, shift_q):
    """The sketch origin moved along its normal by the start shift: a position that may follow sizes."""
    z = vec.unit(frame["z"])
    if not shift_q.sized:
        return placement.moved_along(placement.from_frame(frame), shift_q.n, z)["origin"]
    out = []
    for o, d in zip(frame["origin"], z):
        moved = shift_q.scaled(d).plus(float(o)) if abs(d) > 1e-12 else Quantity(float(o))
        out.append(moved.json() if moved.sized else round(moved.n, 9) + 0.0)
    return out


def _reach_quantity(ctx, item, which, side, z, reach, offset, plane_q, shift_q):
    """The length of the side `which` that reaches to a face, as a Quantity that follows the face when it moves with
    sizes: the face's move less the moves of the sketch plane (`plane_q`, along the sketch normal) and of the start
    (`shift_q`, from the sketch plane). A face the copy cannot follow counts as staying (its sizes are marked)."""
    plain = Quantity(abs(reach) + float(offset))
    moved = reach_motion.target_shift(ctx, item, which, side, z) or Quantity(0.0)
    for part in (plane_q, shift_q):
        if part.sized and moved.sized and moved.core == part.core:
            moved = Quantity(moved.n - part.n)
        elif part.sized:
            moved = moved.plus(part.scaled(-1))
    if not moved.sized:
        return plain
    return moved.plus(reach - moved.n).scaled(_sign_of(reach)).plus(float(offset))


def _keep_reaches_positive(ctx, item, sides):
    """The lengths of the `sides` that follow a moving face must stay above zero. Where one would pass zero, the ranges
    are cut to where all of them stay positive, in one search, so the cut for one side does not shorten a range only
    the other side would need; their sizes are marked only when no cut keeps them."""
    reaching = [s for s in sides if s.get("reaches") and s["q"].sized]
    if all(values.stays_positive(ctx.table, s["q"]) for s in reaching):
        return
    why = "%s would reach past the face it starts from" % item.get("name", "a step")
    found = kept_ranges.holding_ranges(ctx.table, [(s["q"], 1) for s in reaching], LENGTH_TOL)
    if found:
        ctx.cut(found, why)
        return
    for side in reaching:
        if not values.stays_positive(ctx.table, side["q"]):
            ctx.doubt(side["q"].reads, why)
            side["q"] = Quantity(side["distance"])


def _farthest(box, origin, direction):
    """How far the box reaches from `origin` along `direction` (0 when it lies behind)."""
    lo, hi = box["min"], box["max"]
    farthest = 0.0
    for i in range(8):
        corner = [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]]
        farthest = max(farthest, vec.dot(vec.sub(corner, origin), direction))
    return farthest


def _reach_through(box, origin, direction):
    """A distance that clears the whole box when cutting from `origin` along `direction`."""
    return _farthest(box, origin, direction) + vec.length(vec.sub(box["max"], box["min"])) + 1.0


def _reach_of(side):
    """How far a side of a two sided extrude can reach from the sketch plane, or None when that is not known here."""
    kind = (side or {}).get("kind")
    if kind == "distance" and isinstance(side.get("distance"), (int, float)):
        return abs(float(side["distance"]))
    return math.inf if kind in ("throughAll", "all") else None


def _is_through(side):
    return side is not None and side.get("kind") in ("throughAll", "all")


def _plan(item, data, frame, shift_q, combine, ctx, plane_q):
    """The sides to extrude, as dicts {extent, sign, distance, taper}; or a Refusal.

    `sign` is the travel direction relative to the sketch normal. extent is oneSide, symmetric or through. A distance
    side that carries `direction` (+1 or -1 along the sketch normal) travels that way instead of the measured end. One
    that carries `quantity` (a `values.Quantity`) writes that for its distance instead of a parameter's.
    """
    extent_type = data.get("extent_type", "one")
    if extent_type not in ("one", "two", "symmetric"):
        return Refusal("This extrude sets its length in a way that is not copied yet.")
    shift = shift_q.n
    rel_end = data.get("end_offset")
    if rel_end is not None:
        rel_end = rel_end - shift
    z = vec.unit(frame["z"])
    origin = vec.add(frame["origin"], vec.scale(z, shift))

    def one_side(side, which, forced_sign=None, measured=True, other=None):
        kind = (side or {}).get("kind")
        taper = _taper(side.get("taper_deg", 0.0)) if side else 0.0
        if isinstance(taper, Refusal):
            return taper
        taper_q = None
        if kind in ("distance", "toEntity"):
            taper_q = _taper_quantity(ctx, item, which + ".taper_deg", taper)
        end = rel_end if measured else None
        if kind == "distance":
            raw = float(side["distance"])
            if abs(raw) <= 0:
                return Refusal("This extrude has no length.")
            sign = forced_sign if forced_sign is not None else side.get("direction")
            if sign is None:
                sign = _choose_sign(ctx, _sign_of(raw), end, abs(raw), other)
            return {"extent": "oneSide", "sign": sign, "distance": abs(raw), "taper": taper, "taper_q": taper_q,
                    "q": side.get("quantity") or _distance_quantity(ctx, item, which + ".distance", raw)}
        if kind in ("throughAll", "all"):
            positive = side.get("positive", True)
            if positive is None:
                return Refusal(UNREADABLE)
            sign = forced_sign if forced_sign is not None else _choose_sign(
                ctx, 1 if positive else -1, end, math.inf, other)
            return {"extent": "through-one", "sign": sign, "distance": None, "taper": taper,
                    "taper_q": _taper_quantity(ctx, item, which + ".taper_deg", taper), "adjusts": True}
        if kind == "toEntity":
            plane = side.get("plane")
            if not plane:
                return Refusal("This extrude ends on a surface that is not flat, which is not copied yet.")
            if not _parallel(plane["normal"], z):
                return Refusal("This extrude ends on a tilted surface, which is not copied yet.")
            reach = vec.dot(vec.sub(plane["point"], origin), z)
            if abs(reach) < SIGN_TOL:
                return Refusal("This extrude ends on the surface it starts from.")
            sign = forced_sign if forced_sign is not None else _choose_sign(
                ctx, _sign_of(reach), end, abs(reach), other)
            offset = side.get("offset", 0.0)
            if offset is None:
                return Refusal(UNREADABLE)
            values.pin(ctx, item, which + ".offset", "it sets how far %s reaches" % item.get("name", "a step"))
            distance = abs(reach) + float(offset)
            if not distance > 0:
                return Refusal("This extrude has no length.")
            return {"extent": "oneSide", "sign": sign, "distance": distance, "taper": taper,
                    "taper_q": taper_q, "adjusts": True, "reaches": True,
                    "q": _reach_quantity(ctx, item, which, side, z, reach, offset, plane_q, shift_q)}
        return Refusal("This way of setting the extrude length is not copied yet.")

    if extent_type == "symmetric":
        side = data.get("side_one")
        if _is_through(side):
            return [{"extent": "through", "sign": 1, "distance": None, "taper": 0.0}]
        sym = data.get("symmetric")
        if not sym:
            return Refusal("This extrude has no readable length.")
        taper = _taper(sym.get("taper_deg", 0.0))
        if isinstance(taper, Refusal):
            return taper
        full_length = sym.get("full_length", False)
        if full_length is None:
            return Refusal(UNREADABLE)
        factor = 1.0 if full_length else 2.0
        full = float(sym["distance"]) * factor
        if not abs(full) > 0:
            return Refusal("This extrude has no length.")
        half = _distance_quantity(ctx, item, "symmetric.distance", float(sym["distance"]))
        return [{"extent": "symmetric", "sign": 1, "distance": abs(full), "taper": taper,
                 "taper_q": _taper_quantity(ctx, item, "symmetric.taper_deg", taper),
                 "q": half.scaled(factor) if factor != 1.0 else half}]

    if extent_type == "two":
        one, two = data.get("side_one"), data.get("side_two")
        if one is None or two is None:
            return Refusal("This extrude has no readable length.")
        if _is_through(one) and _is_through(two):
            return [{"extent": "through", "sign": 1, "distance": None, "taper": 0.0}]
        if combine == "intersect":
            return Refusal("Two sided intersect extrudes are not copied yet.")
        first = one_side(one, "side_one", other=_reach_of(two))
        if isinstance(first, Refusal):
            return first
        second = one_side(two, "side_two", forced_sign=-first["sign"], measured=False)
        if isinstance(second, Refusal):
            return second
        _keep_reaches_positive(ctx, item, [first, second])
        return [first, second]

    side = one_side(data.get("side_one"), "side_one")
    if isinstance(side, Refusal):
        return side
    _keep_reaches_positive(ctx, item, [side])
    return [side]


# Points per side of the bounding box of an outline, and steps along the extrude, that the material test samples.
_SAMPLE_GRID = 7
_SAMPLE_STEPS = 48


def _outline_samples(profile):
    """Points inside the outline of `profile` (its holes left out), in its sketch plane: a grid over its box."""
    footprint = Footprint(profile)
    points = [p for curve in footprint.curves for p in polyline(curve)]
    if not points:
        return []
    lo = [min(p[0] for p in points), min(p[1] for p in points)]
    hi = [max(p[0] for p in points), max(p[1] for p in points)]
    out = []
    for i in range(_SAMPLE_GRID):
        for j in range(_SAMPLE_GRID):
            uv = [lo[0] + (hi[0] - lo[0]) * (i + 0.5) / _SAMPLE_GRID, lo[1] + (hi[1] - lo[1]) * (j + 0.5) / _SAMPLE_GRID]
            if footprint.covers(uv):
                out.append(uv)
    return out


def _meets_material(ctx, profiles, shift, sign, reach):
    """True when the outlines, carried from the start plane `sign` along their normal up to `reach`, pass through the
    part built so far."""
    for profile in profiles:
        frame = profile["frame"]
        z = vec.unit(frame["z"])
        for uv in _outline_samples(profile):
            flat = vec.add(frame["origin"], vec.add(vec.scale(frame["x"], uv[0]), vec.scale(frame["y"], uv[1])))
            for k in range(1, _SAMPLE_STEPS + 1):
                if follow.inside(ctx, vec.add(flat, vec.scale(z, shift + sign * reach * k / _SAMPLE_STEPS))):
                    return True
    return False


def _cut_toward_material(ctx, plan, data, profiles, shift, combine):
    """A cut through all to one side with no measured end face cuts on the side where its outlines meet the part:
    Fusion's stored direction is used only when both sides, or neither, hold material there."""
    box = data.get("target_box_before")
    if combine != "cut" or data.get("end_offset") is not None or not box:
        return
    reach = vec.length(vec.sub(box["max"], box["min"])) + 1.0
    for entry in plan:
        if entry["extent"] != "through-one":
            continue
        ahead = _meets_material(ctx, profiles, shift, entry["sign"], reach)
        behind = _meets_material(ctx, profiles, shift, -entry["sign"], reach)
        if behind and not ahead:
            entry["sign"] = -entry["sign"]
            ctx.note("Fusion stored the cut direction toward a side without material; the side the cut goes through "
                     "was used.")


def _box_union(box, other):
    if not box or not other:
        return box
    return {"min": [min(a, b) for a, b in zip(box["min"], other["min"])],
            "max": [max(a, b) for a, b in zip(box["max"], other["max"])]}


def _resolve_through(plan, data, origin, z, combine, box_max=None, profiles=()):
    """Give a one sided through all its distance, or a Refusal. `box_max` holds the part at every size the probe
    tried, so the cut still clears it when sizes grow.

    A tapered side keeps the same outline at each height whatever its length, so any length past the part cuts what
    Fusion's through all cuts. One whose walls lean in ends just past the part, and only while its outlines stay open
    there: they shrink by the length times the tangent of the taper (of the largest taper the copy allows when the
    taper follows sizes)."""
    for entry in plan:
        if entry["extent"] == "through" and combine not in ("cut", "intersect"):
            return Refusal("Extruding through all is only copied for cuts.")
        if entry["extent"] == "through-one":
            if combine not in ("cut", "intersect"):
                return Refusal("Extruding through all is only copied for cuts.")
            box = _box_union(data.get("target_box_before"), box_max)
            if not box:
                return Refusal("The part this cuts through could not be measured.")
            entry["extent"] = "oneSide"
            direction = vec.scale(z, entry["sign"])
            if (entry["taper"] or 0.0) > 0:
                entry["distance"] = _farthest(box, origin, direction) + THROUGH_TAPER_MARGIN_MM
                if not _stays_open(entry, profiles):
                    return Refusal("This tapered cut through all closes before it passes the part, which is not "
                                   "copied.")
            else:
                entry["distance"] = _reach_through(box, origin, direction)
    return None


def _stays_open(entry, profiles):
    """True when the side's length times the tangent of its taper is at most half the `inner_reach` of every outline,
    so the outlines are still well open at the end."""
    q = entry.get("taper_q")
    angle = MAX_TAPER_DEG if q is not None and q.sized else entry["taper"]
    shrink = entry["distance"] * math.tan(math.radians(angle))
    return all(shrink <= inner_reach(profile) / 2.0 for profile in profiles)


def inner_reach(profile, steps=48):
    """About the radius of the largest circle inside a profile's region (a little less): the largest distance to its
    outline over a grid of points inside it."""
    footprint = Footprint(profile)
    flat = [p for curve in footprint.curves for p in polyline(curve)]
    if not flat:
        return 0.0
    lo = [min(p[i] for p in flat) for i in (0, 1)]
    hi = [max(p[i] for p in flat) for i in (0, 1)]
    best = 0.0
    for a in range(1, steps):
        for b in range(1, steps):
            p = [lo[0] + (hi[0] - lo[0]) * a / steps, lo[1] + (hi[1] - lo[1]) * b / steps]
            if footprint.covers(p):
                best = max(best, footprint.nearest_curve(p)[1])
    return best


def _beyond_part(box, start, direction, length):
    """True when a cut of `length` from `start` along `direction` ends past the whole box."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    corners = ([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]] for i in range(8))
    return length > max(vec.dot(vec.sub(c, start), direction) for c in corners) + LENGTH_TOL


def _check_measured_length(plan, data, shift, start, z, combine):
    """Refuse when the measured end face is not where the planned length puts it (None when it agrees or is unknown).

    A cut that ends past the part makes no end face of its own; the face Fusion lists then is a wall it cut through,
    nearer than the planned end, and the length is not checked.
    """
    end = data.get("end_offset")
    if end is None or not plan:
        return None
    first = plan[0]
    if first["extent"] == "through" or first["distance"] is None:
        return None
    planned = first["distance"] / 2.0 if first["extent"] == "symmetric" else first["distance"]
    measured = abs(end - shift)
    if abs(measured - planned) <= LENGTH_TOL:
        return None
    if (combine == "cut" and first["extent"] == "oneSide" and measured < planned
            and _beyond_part(data.get("target_box_before"), start, vec.scale(z, first["sign"]), planned)):
        return None
    return Refusal("The measured end of this extrude does not match its length, so it is not copied.")


def _expected_leans(plan, combine):
    """Per plan entry, the leans its side walls can show along the sketch normal (see `_check_taper`)."""
    out = []
    for entry in plan:
        lean = math.sin(math.radians(entry["taper"] or 0.0)) * (-1 if combine == "cut" else 1)
        out.append([-lean, lean] if entry["extent"] == "symmetric" else [entry["sign"] * lean])
    return out


def _check_leans(plan, leans, combine):
    """Refuse when a measured side wall leans in a way no side of the plan gives, or a tapered side has no wall
    that shows its taper. A wall narrowing away from the sketch leans its outward normal along the travel; a cut
    shows the part's walls, which face the other way."""
    expected = _expected_leans(plan, combine)
    flat = [value for values in expected for value in values]
    if any(not any(abs(lean - value) <= LEAN_TOL for value in flat) for lean in leans):
        return Refusal("The taper direction does not match what was measured, so it is not copied.")
    for entry, values in zip(plan, expected):
        if entry["taper"] and not any(abs(lean - value) <= LEAN_TOL for lean in leans for value in values):
            return Refusal("The taper of this extrude could not be measured.")
    return None


def _check_taper(plan, data, combine, outlines):
    """Refuse a taper whose sign disagrees with the measured side walls (or, for one outline, the end face area),
    or that cannot be measured."""
    tapered = [entry for entry in plan if entry["taper"]]
    if not tapered:
        return None
    leans = data.get("side_leans")
    if isinstance(leans, list) and leans:
        return _check_leans(plan, leans, combine)
    if not plan[0]["taper"] or outlines != 1:
        return Refusal("The taper of this extrude could not be measured.")
    start, end = data.get("profile_area"), data.get("end_area")
    if not start or end is None or start <= 0:
        return Refusal("The direction of the taper could not be measured.")
    if abs(end - start) <= AREA_RELATIVE_TOL * start:
        return Refusal("The taper of this extrude shows no change in size, so it is not copied.")
    if (plan[0]["taper"] > 0) != (end < start):
        return Refusal("The taper direction does not match what was measured, so it is not copied.")
    return None


def _holds_free_outline(profiles):
    """True when a profile is sketch text or has a free curve (a spline)."""
    return any(p.get("text") or any(c.get("kind") == "other" for loop in p.get("loops") or []
                                    for c in loop.get("curves") or []) for p in profiles)


def _volume_refusal(data, plan, combine, profiles, thin):
    """Refuse when the part Fusion made from text or spline outlines is not the outline area times the length.

    Text outlines are sorted into outer outlines and holes by the reader, and overlapping strokes can be read as a hole,
    so the area they give is checked against the measured volume. A new body must match; a join or cut may lose volume
    to material it overlaps, so it only must not exceed the expected volume or go the wrong way. Cases whose volume
    cannot be worked out here (taper, through all, thin, intersect) are not checked. A capture without the measured
    values (made before they were read) is not checked either."""
    if "areas" not in data or not _holds_free_outline(profiles):
        return None
    if thin or combine == "intersect" or any(e["taper"] or e["distance"] is None for e in plan):
        return None
    areas, before, after = data["areas"], data.get("volume_before"), data.get("volume_after")
    if (not isinstance(areas, list) or len(areas) != len(profiles) or any(a is None for a in areas)
            or before is None or after is None):
        return Refusal("The change this extrude makes to the part could not be measured, so it is not copied.")
    expected = sum(areas) * sum(entry["distance"] for entry in plan)
    change = after - before
    tolerance = VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL
    if combine == "new":
        agrees = abs(change - expected) <= tolerance
    else:
        grows = combine == "add"
        agrees = abs(change) <= expected + tolerance and (change >= -VOLUME_ABSOLUTE_TOL if grows
                                                          else change <= VOLUME_ABSOLUTE_TOL)
    if not agrees:
        return Refusal("The result of this extrude does not match the outlines it was drawn with, so it is not copied.")
    return None


def _same_plane(profiles):
    """True when every profile frame has the first one's normal and lies in its plane."""
    first = profiles[0]["frame"]
    z = vec.unit(first["z"])
    for profile in profiles[1:]:
        other = profile["frame"]
        if not _parallel(other["z"], z) or vec.dot(vec.unit(other["z"]), z) < 0:
            return False
        if abs(vec.dot(vec.sub(other["origin"], first["origin"]), z)) > PLANE_TOL:
            return False
    return True


SAMPLE_INSET = 0.02


def _samples(footprint):
    """Sketch points just inside an outline: the middle of each curve, moved inward."""
    points = []
    for n, curve in enumerate(footprint.curves):
        mid = curve.get("mid") or [(a + b) / 2.0 for a, b in zip(curve["start"], curve["end"])]
        out = footprint.outward(n, mid)
        if out is not None:
            points.append([mid[0] - SAMPLE_INSET * out[0], mid[1] - SAMPLE_INSET * out[1]])
    return points


def _in_model(profile, uv, height):
    return vec.frame_apply(profile["frame"], [uv[0], uv[1], height])


def _bounds(points):
    """(low, high) corners of the box around 3D points."""
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def _apart(a, b):
    """True when two boxes (low, high) do not overlap."""
    return any(a[1][i] < b[0][i] or b[1][i] < a[0][i] for i in range(3))


class _Outline:
    """One outline for the order search: its footprint, where its curve ends lie and the box around its region in
    model space (grown by the touch tolerance), all worked out once."""

    def __init__(self, profile):
        self.profile = profile
        self.footprint = Footprint(profile)
        self.ends = [_in_model(profile, curve[key], 0.0) for curve in self.footprint.curves
                     for key in ("start", "end")]
        flat = [p for curve in self.footprint.curves for p in polyline(curve)]
        corners = [(x, y) for x in (min(p[0] for p in flat), max(p[0] for p in flat))
                   for y in (min(p[1] for p in flat), max(p[1] for p in flat))]
        low, high = _bounds([_in_model(profile, c, 0.0) for c in corners])
        self.box = ([v - follow.LATERAL_TOL for v in low], [v + follow.LATERAL_TOL for v in high])
        self.ends_box = _bounds(self.ends)
        self._samples = None

    def samples(self):
        if self._samples is None:
            self._samples = _samples(self.footprint)
        return self._samples

    def meets(self, other):
        """True when a curve end of this outline lies in or on `other` (both on one plane)."""
        if _apart(self.ends_box, other.box):
            return False
        low, high = other.box
        for p in self.ends:
            if any(p[i] < low[i] or p[i] > high[i] for i in range(3)):
                continue
            local = vec.frame_to_local(other.profile["frame"], p)
            uv = [local[0], local[1]]
            if other.footprint.covers(uv) or other.footprint.nearest_curve(uv)[1] <= follow.LATERAL_TOL:
                return True
        return False


def _heights(entry, shift, join=False):
    """Heights (along the sketch normal) to test for material: inside the side. A join also tests just outside both
    ends, since a tool that stands on the part's face joins it."""
    reach = entry["distance"] or 0.0
    if entry["extent"] == "symmetric":
        ends = (-reach / 2.0, reach / 2.0)
    else:
        ends = (0.0, entry["sign"] * reach)
    low, high = min(ends), max(ends)
    inset = min(SAMPLE_INSET, (high - low) / 4.0)
    found = [low + inset, (low + high) / 2.0, high - inset]
    if join:
        found += [low - SAMPLE_INSET, high + SAMPLE_INSET]
    return [shift + h for h in found]


def _touches_part(ctx, outline, entry, shift, join=False):
    """True when the tool of one outline and side reaches into the part built so far."""
    profile = outline.profile
    return any(follow.inside(ctx, _in_model(profile, uv, h))
               for h in _heights(entry, shift, join) for uv in outline.samples())


def _touching_order(ctx, units, shift, join):
    """(outline, side) pairs in an order where each one joins what is built: one that reaches into the part, or
    touches a pair already taken, comes next. Fusion adds all outlines at once, the recipe one step after the other,
    so a step that touches only a later one would stand apart for a while. The order stays Fusion's where it works.

    Both sides of one outline touch each other; outlines touch on one side when they meet in the sketch. `join` is
    true when the steps add to the part, so a tool that stands on a face of it counts as touching it.

    Candidates wait in a heap by position, so the work follows the number of outlines that really touch."""
    found = {}

    def outline(profile):
        if id(profile) not in found:
            found[id(profile)] = _Outline(profile)
        return found[id(profile)]

    profiles = [units[n][0][0] for n in range(len(units))]
    by_profile = {}
    for n, profile in enumerate(profiles):
        by_profile.setdefault(id(profile), []).append(n)
    first_of = {id(profile): profile for profile in profiles}
    touching = ([n for n, (built, entry) in enumerate(units) if _touches_part(ctx, outline(built[0]), entry, shift, join)]
                if ctx.slabs else [])
    heap = list(touching)
    heapq.heapify(heap)
    meeting = {}

    def meeting_it(pid):
        """Ids of the outlines that meet outline `pid` (a curve end of theirs lies in or on it)."""
        if pid not in meeting:
            target = outline(first_of[pid])
            meeting[pid] = [other for other in by_profile if other != pid and outline(first_of[other]).meets(target)]
        return meeting[pid]

    taken = [False] * len(units)
    order, ahead = [], 0
    for _ in units:
        pick = None
        while heap and pick is None:
            n = heapq.heappop(heap)
            pick = None if taken[n] else n
        if pick is None:
            while taken[ahead]:
                ahead += 1
            pick = ahead
        taken[pick] = True
        order.append(pick)
        pid, entry = id(profiles[pick]), units[pick][1]
        for n in by_profile[pid]:
            heapq.heappush(heap, n)
        for other in meeting_it(pid):
            for n in by_profile[other]:
                if units[n][1] is entry:
                    heapq.heappush(heap, n)
    return [units[n] for n in order]


def _parts(profile, sources):
    """(index, capture profile) of the item's profiles that make `profile`: its merged parts, or itself."""
    if "merged_from" in profile:
        return [(n, sources[n]) for n in profile["merged_from"]]
    return [(next(n for n, p in enumerate(sources) if p is profile), profile)]


def _thin_step(ctx, item, data, wall, profile):
    """`(side, thickness Quantity)` of a thin extrude's wall, or a Refusal when the measured end face does not fit the
    outline and thickness. The thickness follows its parameter and must stay above zero."""
    decided = thin_wall.decide(thin_wall.outer_curves(profile), wall, data.get("end_area"))
    if isinstance(decided, Refusal):
        return decided
    side, rounded = decided
    if rounded:
        ctx.note("Fusion keeps the corners of this wall sharp. The copy rounds them.")
    return side, values.quantity(ctx, item, "thin.thickness", wall["thickness"], absolute=True)


def _sketch_built(ctx, item, profiles, thin):
    """`(profile, (outer, inners), drawn)` per outline of sketch profiles (touching ones merged), or a Refusal."""
    if any(not isinstance(p.get("frame"), dict) for p in profiles):
        return Refusal("A sketch outline has no readable position.")
    if not _same_plane(profiles):
        return Refusal("This extrude uses outlines on different planes, which is not copied yet.")
    built = []
    for profile in outlines.merge_touching(profiles):
        outcome = loops.profile_loops(profile)
        if isinstance(outcome, Refusal):
            return outcome
        if thin and outcome[1]:
            return Refusal("A thin extrude of an outline with holes is not copied yet.")
        drawn = sketch_motion.outline(ctx, item, profile, outcome[0], outcome[1], _parts(profile, profiles))
        built.append((profile, outcome, drawn))
    sketch_motion.planes_apart(ctx, [drawn for _, _, drawn in built], item)
    return built


def _face_built(face, thin):
    """The one outline of a flat face (face_outline.py), as `_sketch_built` gives it, or a Refusal."""
    if thin and face.loops[1]:
        return Refusal("A thin extrude of an outline with holes is not copied yet.")
    return [(face.profile, face.loops, face.drawn)]


def _outlines_built(ctx, item, face, drawn, thin):
    """`(profile, (outer, inners), drawn)` per outline: the flat face first, then the sketch outlines; or a Refusal.
    Sketch outlines beside a face must lie on its plane. The face keeps its measured plane there, so the sizes that
    move a sketch plane are marked."""
    built = []
    if face is not None:
        built = _face_built(face, thin)
        if isinstance(built, Refusal) or not drawn:
            return built
    sketches = _sketch_built(ctx, item, drawn, thin)
    if isinstance(sketches, Refusal) or face is None:
        return sketches
    if not _same_plane([face.profile] + drawn):
        return Refusal("This extrude uses outlines on different planes, which is not copied yet.")
    names = [n for _, _, one in sketches if one is not None for n in sketch_motion.movers(ctx.table, one.plane)]
    if names:
        ctx.doubt(names, notes.stuck_reason("apart", item.get("name") or ""))
    return built + sketches


def handle(item, ctx):
    data = item.get("data") or {}
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Extrudes that make a new component are not copied.")
    if operation not in COMBINE:
        return Refusal("This extrude combines with the part in a way that is not copied yet.")
    thin = data.get("thin", False)
    if thin is None:
        return Refusal(UNREADABLE)
    wall = None
    if thin:
        wall = thin_wall.prepare(data)
        if isinstance(wall, Refusal):
            return wall
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This extrude has no sketch outline.")
    if thin:
        refusal = thin_wall.open_line_refusal(profiles)
        if refusal is None and len(profiles) > 1:
            refusal = Refusal("A thin extrude of several outlines is not copied yet.")
        if refusal is not None:
            return refusal
    face = face_outline.prepare(ctx, item, profiles)
    if isinstance(face, Refusal):
        return face
    drawn_ones = [p for p in profiles if not p.get("face")]
    for profile in drawn_ones:
        refusal = loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
    combine = COMBINE[operation]
    # Several outlines that Fusion made into one body touch each other, so the first makes it and the rest join.
    if combine == "new" and len(profiles) > 1 and len(item.get("bodies_after") or []) != 1:
        return Refusal("A new body from several outlines makes several bodies, which is not copied yet.")
    built = _outlines_built(ctx, item, face, drawn_ones, thin)
    if isinstance(built, Refusal):
        return built
    sources = ([face.profile] if face is not None else []) + drawn_ones
    picked = len(sources)
    profiles = [profile for profile, _, _ in built]
    first_drawn = built[0][2]
    plane_q = first_drawn.plane_shift(ctx) if first_drawn is not None else Quantity(0.0)

    first_frame = profiles[0]["frame"]
    shift_q = _start_shift(data.get("start", {"kind": "profilePlane"}), first_frame, ctx, item, plane_q)
    if isinstance(shift_q, Refusal):
        return shift_q
    shift = shift_q.n
    plan = _plan(item, data, first_frame, shift_q, combine, ctx, plane_q)
    if isinstance(plan, Refusal):
        return plan
    z0 = vec.unit(first_frame["z"])
    start = vec.add(first_frame["origin"], vec.scale(z0, shift))
    for check in (_check_measured_length(plan, data, shift, start, z0, combine),
                  _check_taper(plan, data, combine, picked),
                  _volume_refusal(data, plan, combine, sources, thin)):
        if check:
            return check
    thin_step = _thin_step(ctx, item, data, wall, profiles[0]) if thin else None
    if isinstance(thin_step, Refusal):
        return thin_step
    box_max = ctx.motion.box_max if sketch_motion.active(ctx) else None
    _cut_toward_material(ctx, plan, data, profiles, shift, combine)
    refusal = _resolve_through(plan, data, start, z0, combine, box_max, [profile for profile, _, _ in built])
    if refusal:
        return refusal
    if combine == "intersect" and (len(plan) * len(built) > 1):
        return Refusal("Intersect extrudes with several outlines are not copied yet.")

    units = [(one, entry) for one in built for entry in plan]
    if combine in ("new", "add") and len(built) > 1:
        units = _touching_order(ctx, units, shift, combine == "add")
    out = StepResult()
    for (profile, (outer, inner), drawn), entry in units:
        frame = profile["frame"]
        base = placement.moved_along(placement.from_frame(frame), shift, vec.unit(frame["z"]))
        base["origin"] = drawn.origin(ctx, shift_q) if drawn is not None else _origin(frame, shift_q)
        if drawn is not None:
            outer, inner = drawn.written(ctx)
        reverse = entry["sign"] < 0
        on = placement.reversed_of(base) if reverse else base
        pick = (lambda loop: loops.flip_y(loop)) if reverse else (lambda loop: loop)
        sketch = {"on": on, "outer": pick(outer)}
        if inner:
            sketch["inner"] = [pick(loop) for loop in inner]
        step = {
            "kind": "extrude",
            "sketch": sketch,
            "combine": combine if not out.entries else ("add" if combine == "new" else combine),
            "extent": entry["extent"],
        }
        if entry["distance"] is not None:
            step["distance"] = entry["q"].json() if entry.get("q") else round9(entry["distance"])
        if entry["taper"]:
            step["taperDeg"] = entry["taper_q"].json() if entry.get("taper_q") else round9(entry["taper"])
        placers = []
        if thin_step is not None:
            side, thickness_q = thin_step
            step["thin"] = {"thickness": thickness_q.json(), "side": side}
            placers.append(ThinWallMaker(on, entry["extent"], entry.get("q") or Quantity(entry["distance"]), profile,
                                         side, thickness_q.n))
            out.add(step, placers, repeatable=False)
            continue
        if entry["extent"] in ("oneSide", "symmetric"):
            placers.append(SlabMaker(on, entry["extent"], entry.get("q") or Quantity(entry["distance"]), profile,
                                     entry.get("taper_q") or Quantity(entry["taper"] or 0.0), drawn))
        out.add(step, placers, repeatable=not entry.get("adjusts"))
    return out
