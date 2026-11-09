"""Extrude feature handler (ExtrudeFeature): sketch profiles swept along their sketch normal.

Profiles that share a curve are merged into one outline (outlines.py); each outline becomes one recipe `extrude` step
per side. Fusion's sign conventions are checked against the measured
`end_offset` (where the end face landed), which wins when the two disagree. With the probe's motion file the outline
and its sketch plane follow sizes (sketch_motion.py).
"""
import math

from . import follow, kept_ranges, loops, outlines, placement, sketch_motion, values, vec
from .footprint import Footprint
from .placer_makers import SlabMaker
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
COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect", "newBody": "new"}


def _n(value):
    return round(value, 9) + 0.0


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
    """A taper that follows sizes should stay under MAX_TAPER_DEG either way: the sizes it reads are marked past the
    values where it does not."""
    limit = Quantity(MAX_TAPER_DEG)
    rules = [(limit.plus(q.scaled(-1.0)), 1), (limit.plus(q), 1)]
    found = kept_ranges.holding_ranges(ctx.table, rules, TAPER_MARGIN_DEG)
    lean = "%s would lean its walls %d degrees or more" % (item.get("name", "a step"), MAX_TAPER_DEG)
    if found is None:
        ctx.doubt(q.reads, "at other values " + lean)
    elif found:
        for name, reason in kept_ranges.past_reasons(ctx.table, found, lean).items():
            ctx.doubt([name], reason)


def _distance_quantity(ctx, item, path, raw):
    """The length of one side. The recipe writes the absolute value, so a negative parameter is written negated."""
    return values.quantity(ctx, item, path, abs(raw), sign=_sign_of(raw), absolute=True)


def _start_shift(start, frame, ctx, item):
    """Signed distance along the sketch normal from the sketch plane to where the extrude starts, as a Quantity that
    follows sizes (an offset parameter, or a face that moves with an earlier extrude); or a Refusal."""
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
        plane = start.get("plane")
        if not plane:
            return Refusal("This extrude starts from a surface that is not flat, which is not copied yet.")
        if not _parallel(plane["normal"], frame["z"]):
            return Refusal("This extrude starts from a tilted surface, which is not copied yet.")
        shift = vec.dot(vec.sub(plane["point"], frame["origin"]), vec.unit(frame["z"]))
        moved = follow.target_shift(ctx, item, start, vec.unit(frame["z"]), "starts from")
        if moved is None or not moved.sized:
            return Quantity(shift)
        return moved.plus(shift - moved.n)
    return Refusal("This extrude starts in a way that is not copied yet.")


def _keep_start_with_reach(ctx, item, data, shift_q):
    """A side that reaches to a face is measured from a start that stays: a moving start is fixed then."""
    if not shift_q.sized:
        return shift_q
    if any((data.get(key) or {}).get("kind") == "toEntity" for key in ("side_one", "side_two")):
        ctx.doubt(shift_q.reads, "%s starts at a place that moves and reaches to a face, which the copy cannot follow"
                  % item.get("name", "a step"))
        return Quantity(shift_q.n)
    return shift_q


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


def _reach_quantity(ctx, item, side, z, reach, offset, plane_q):
    """The length of a side that reaches to a face, as a Quantity that follows the face when it moves with sizes:
    the face's move less the sketch plane's move (`plane_q`, along the sketch normal)."""
    plain = Quantity(abs(reach) + float(offset))
    moved = follow.target_shift(ctx, item, side, z)
    if moved is None:
        return plain
    if plane_q.sized:
        moved = moved.plus(plane_q.scaled(-1))
    if not moved.sized:
        return plain
    length = moved.plus(reach - moved.n).scaled(_sign_of(reach)).plus(float(offset))
    if not values.stays_positive(ctx.table, length):
        ctx.doubt(length.reads, "%s would reach past the face it starts from" % item.get("name", "a step"))
        return plain
    return length


def _reach_through(box, origin, direction):
    """A distance that clears the whole box when cutting from `origin` along `direction`."""
    lo, hi = box["min"], box["max"]
    farthest = 0.0
    for i in range(8):
        corner = [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]]
        farthest = max(farthest, vec.dot(vec.sub(corner, origin), direction))
    diagonal = vec.length(vec.sub(hi, lo))
    return farthest + diagonal + 1.0


def _reach_of(side):
    """How far a side of a two sided extrude can reach from the sketch plane, or None when that is not known here."""
    kind = (side or {}).get("kind")
    if kind == "distance" and isinstance(side.get("distance"), (int, float)):
        return abs(float(side["distance"]))
    return math.inf if kind in ("throughAll", "all") else None


def _is_through(side):
    return side is not None and side.get("kind") in ("throughAll", "all")


def _plan(item, data, frame, shift, combine, ctx, plane_q):
    """The sides to extrude, as dicts {extent, sign, distance, taper}; or a Refusal.

    `sign` is the travel direction relative to the sketch normal. extent is oneSide, symmetric or through. A distance
    side that carries `direction` (+1 or -1 along the sketch normal) travels that way instead of the measured end.
    """
    extent_type = data.get("extent_type", "one")
    if extent_type not in ("one", "two", "symmetric"):
        return Refusal("This extrude sets its length in a way that is not copied yet.")
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
                    "q": _distance_quantity(ctx, item, which + ".distance", raw)}
        if kind in ("throughAll", "all"):
            if taper:
                return Refusal("A tapered extrude through all is not copied.")
            positive = side.get("positive", True)
            if positive is None:
                return Refusal(UNREADABLE)
            sign = forced_sign if forced_sign is not None else _choose_sign(
                ctx, 1 if positive else -1, end, math.inf, other)
            return {"extent": "through-one", "sign": sign, "distance": None, "taper": 0.0, "adjusts": True}
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
                    "taper_q": taper_q, "adjusts": True,
                    "q": _reach_quantity(ctx, item, side, z, reach, offset, plane_q)}
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
        return [first, second]

    side = one_side(data.get("side_one"), "side_one")
    if isinstance(side, Refusal):
        return side
    return [side]


def _box_union(box, other):
    if not box or not other:
        return box
    return {"min": [min(a, b) for a, b in zip(box["min"], other["min"])],
            "max": [max(a, b) for a, b in zip(box["max"], other["max"])]}


def _resolve_through(plan, data, origin, z, combine, box_max=None):
    """Give a one sided through all its distance, or a Refusal. `box_max` holds the part at every size the probe
    tried, so the cut still clears it when sizes grow."""
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
            entry["distance"] = _reach_through(box, origin, vec.scale(z, entry["sign"]))
    return None


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


def _samples(profile):
    """Sketch points just inside a profile: the middle of each outline curve, moved inward."""
    footprint = Footprint(profile)
    points = []
    for n, curve in enumerate(footprint.curves):
        mid = curve.get("mid") or [(a + b) / 2.0 for a, b in zip(curve["start"], curve["end"])]
        out = footprint.outward(n, mid)
        if out is not None:
            points.append([mid[0] - SAMPLE_INSET * out[0], mid[1] - SAMPLE_INSET * out[1]])
    return points


def _in_model(profile, uv, height):
    return vec.frame_apply(profile["frame"], [uv[0], uv[1], height])


def _meets(a, b):
    """True when two outlines on one plane touch or overlap: a curve end of one lies in or on the other."""
    footprint = Footprint(b)
    for curve in Footprint(a).curves:
        for key in ("start", "end"):
            local = vec.frame_to_local(b["frame"], _in_model(a, curve[key], 0.0))
            uv = [local[0], local[1]]
            if footprint.covers(uv) or footprint.nearest_curve(uv)[1] <= follow.LATERAL_TOL:
                return True
    return False


def _heights(entry, shift):
    reach = entry["distance"] or 0.0
    if entry["extent"] == "symmetric":
        ends = (-reach / 2.0, reach / 2.0)
    else:
        ends = (0.0, entry["sign"] * reach)
    low, high = min(ends), max(ends)
    inset = min(SAMPLE_INSET, (high - low) / 4.0)
    return [shift + h for h in (low + inset, (low + high) / 2.0, high - inset)]


def _touches_part(ctx, profile, entry, shift):
    """True when the tool of one outline and side reaches into the part built so far."""
    return any(follow.inside(ctx, _in_model(profile, uv, h)) for uv in _samples(profile) for h in _heights(entry, shift))


def _touching_order(ctx, units, shift):
    """(outline, side) pairs in an order where each one joins what is built: one that reaches into the part, or
    touches a pair already taken, comes next. Fusion adds all outlines at once, the recipe one step after the other,
    so a step that touches only a later one would stand apart for a while. The order stays Fusion's where it works.

    Both sides of one outline touch each other; outlines touch on one side when they meet in the sketch."""
    touching = [bool(ctx.slabs) and _touches_part(ctx, built[0], entry, shift) for built, entry in units]

    def joins(n, m):
        a, first = units[n][0][0], units[n][1]
        b, second = units[m][0][0], units[m][1]
        return a is b or (first is second and _meets(a, b))

    order, left = [], list(range(len(units)))
    while left:
        pick = next((n for n in left if touching[n] or any(joins(n, m) for m in order)), left[0])
        order.append(pick)
        left.remove(pick)
    return [units[n] for n in order]


def _parts(profile, sources):
    """(index, capture profile) of the item's profiles that make `profile`: its merged parts, or itself."""
    if "merged_from" in profile:
        return [(n, sources[n]) for n in profile["merged_from"]]
    return [(next(n for n, p in enumerate(sources) if p is profile), profile)]


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
    if thin:
        return Refusal("Thin extrudes are not copied yet.")
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This extrude has no sketch outline.")
    for profile in profiles:
        refusal = loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
    combine = COMBINE[operation]
    # Several outlines that Fusion made into one body touch each other, so the first makes it and the rest join.
    if combine == "new" and len(profiles) > 1 and len(item.get("bodies_after") or []) != 1:
        return Refusal("A new body from several outlines makes several bodies, which is not copied yet.")
    if any(not isinstance(p.get("frame"), dict) for p in profiles):
        return Refusal("A sketch outline has no readable position.")
    if not _same_plane(profiles):
        return Refusal("This extrude uses outlines on different planes, which is not copied yet.")
    picked = len(profiles)
    sources = profiles
    profiles = outlines.merge_touching(profiles)

    built = []
    for profile in profiles:
        outcome = loops.profile_loops(profile)
        if isinstance(outcome, Refusal):
            return outcome
        drawn = sketch_motion.outline(ctx, item, profile, outcome[0], outcome[1], _parts(profile, sources))
        built.append((profile, outcome, drawn))
    sketch_motion.planes_apart(ctx, [drawn for _, _, drawn in built], item)
    first_drawn = built[0][2]
    plane_q = first_drawn.plane_shift(ctx) if first_drawn is not None else Quantity(0.0)

    first_frame = profiles[0]["frame"]
    shift_q = _start_shift(data.get("start", {"kind": "profilePlane"}), first_frame, ctx, item)
    if isinstance(shift_q, Refusal):
        return shift_q
    shift_q = _keep_start_with_reach(ctx, item, data, shift_q)
    shift = shift_q.n
    plan = _plan(item, data, first_frame, shift, combine, ctx, plane_q)
    if isinstance(plan, Refusal):
        return plan
    z0 = vec.unit(first_frame["z"])
    start = vec.add(first_frame["origin"], vec.scale(z0, shift))
    for check in (_check_measured_length(plan, data, shift, start, z0, combine),
                  _check_taper(plan, data, combine, picked)):
        if check:
            return check
    box_max = ctx.motion.box_max if sketch_motion.active(ctx) else None
    refusal = _resolve_through(plan, data, start, z0, combine, box_max)
    if refusal:
        return refusal
    if combine == "intersect" and (len(plan) * len(built) > 1):
        return Refusal("Intersect extrudes with several outlines are not copied yet.")

    units = [(one, entry) for one in built for entry in plan]
    if combine in ("new", "add") and len(built) > 1:
        units = _touching_order(ctx, units, shift)
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
            step["distance"] = entry["q"].json() if entry.get("q") else _n(entry["distance"])
        if entry["taper"]:
            step["taperDeg"] = entry["taper_q"].json() if entry.get("taper_q") else _n(entry["taper"])
        placers = []
        if entry["extent"] in ("oneSide", "symmetric"):
            placers.append(SlabMaker(on, entry["extent"], entry.get("q") or Quantity(entry["distance"]), profile,
                                     entry.get("taper_q") or Quantity(entry["taper"] or 0.0), drawn))
        out.add(step, placers, repeatable=not entry.get("adjusts"))
    return out
