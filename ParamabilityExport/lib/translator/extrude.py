"""Extrude feature handler (ExtrudeFeature): sketch profiles swept along their sketch normal.

Each profile becomes one recipe `extrude` step per side. Fusion's sign conventions are checked against the measured
`end_offset` (where the end face landed), which wins when the two disagree.
"""
from . import loops, placement, vec
from .result import Refusal

TYPES = ("ExtrudeFeature",)

# Fusion's positive taper angle narrows the walls going away from the sketch (unverified; hand test 4). The recipe
# leans walls in for a positive `taperDeg`, so the sign is 1 when the two agree and -1 when they are opposite.
FUSION_TAPER_SIGN = 1

MAX_TAPER_DEG = 45.0
MAX_INNER_LOOPS = 256
PARALLEL_TOL = 1e-9
SIGN_TOL = 1e-9
COMBINE = {"join": "add", "cut": "cut", "intersect": "intersect", "newBody": "new"}


def _n(value):
    return round(value, 9) + 0.0


def _sign_of(value):
    return -1 if value < 0 else 1


def _parallel(a, b):
    return vec.length(vec.cross(vec.unit(a), vec.unit(b))) <= PARALLEL_TOL


def _choose_sign(ctx, geometric, rel_end):
    """Direction (+1 along the sketch normal, -1 against it): the measured end face wins over the stored sign."""
    if rel_end is None or abs(rel_end) < SIGN_TOL:
        return geometric
    measured = _sign_of(rel_end)
    if measured != geometric:
        ctx.note("Fusion stored the extrude direction two ways; the measured end of the extrude was used.")
    return measured


def _taper(deg):
    """Recipe `taperDeg` from Fusion's, or a Refusal."""
    if not deg:
        return 0.0
    value = FUSION_TAPER_SIGN * deg
    if abs(value) >= MAX_TAPER_DEG:
        return Refusal("The taper of this extrude is too steep to copy.")
    return value


def _start_shift(start, frame):
    """Signed distance along the sketch normal from the sketch plane to where the extrude starts, or a Refusal."""
    kind = (start or {}).get("kind", "profilePlane")
    if kind == "profilePlane":
        return 0.0
    if kind == "offset":
        return float(start.get("offset") or 0.0)
    if kind == "fromEntity":
        plane = start.get("plane")
        if not plane:
            return Refusal("This extrude starts from a surface that is not flat, which is not copied yet.")
        if not _parallel(plane["normal"], frame["z"]):
            return Refusal("This extrude starts from a tilted surface, which is not copied yet.")
        return vec.dot(vec.sub(plane["point"], frame["origin"]), vec.unit(frame["z"]))
    return Refusal("This extrude starts in a way that is not copied yet.")


def _reach_through(box, origin, direction):
    """A distance that clears the whole box when cutting from `origin` along `direction`."""
    lo, hi = box["min"], box["max"]
    farthest = 0.0
    for i in range(8):
        corner = [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]]
        farthest = max(farthest, vec.dot(vec.sub(corner, origin), direction))
    diagonal = vec.length(vec.sub(hi, lo))
    return farthest + diagonal + 1.0


def _is_through(side):
    return side is not None and side.get("kind") in ("throughAll", "all")


def _plan(data, frame, shift, combine, ctx):
    """The sides to extrude, as dicts {extent, sign, distance, taper}; or a Refusal.

    `sign` is the travel direction relative to the sketch normal. extent is oneSide, symmetric or through.
    """
    extent_type = data.get("extent_type", "one")
    rel_end = data.get("end_offset")
    if rel_end is not None:
        rel_end = rel_end - shift
    z = vec.unit(frame["z"])
    origin = vec.add(frame["origin"], vec.scale(z, shift))

    def one_side(side, forced_sign=None, measured=True):
        kind = (side or {}).get("kind")
        taper = _taper(side.get("taper_deg") or 0.0) if side else 0.0
        if isinstance(taper, Refusal):
            return taper
        end = rel_end if measured else None
        if kind == "distance":
            raw = float(side["distance"])
            if abs(raw) <= 0:
                return Refusal("This extrude has no length.")
            sign = forced_sign if forced_sign is not None else _choose_sign(ctx, _sign_of(raw), end)
            return {"extent": "oneSide", "sign": sign, "distance": abs(raw), "taper": taper}
        if kind in ("throughAll", "all"):
            if taper:
                return Refusal("A tapered extrude through all is not copied.")
            positive = side.get("positive", True)
            sign = forced_sign if forced_sign is not None else _choose_sign(ctx, 1 if positive else -1, end)
            return {"extent": "through-one", "sign": sign, "distance": None, "taper": 0.0}
        if kind == "toEntity":
            plane = side.get("plane")
            if not plane:
                return Refusal("This extrude ends on a surface that is not flat, which is not copied yet.")
            if not _parallel(plane["normal"], z):
                return Refusal("This extrude ends on a tilted surface, which is not copied yet.")
            reach = vec.dot(vec.sub(plane["point"], origin), z)
            if abs(reach) < SIGN_TOL:
                return Refusal("This extrude ends on the surface it starts from.")
            sign = forced_sign if forced_sign is not None else _choose_sign(ctx, _sign_of(reach), end)
            distance = abs(reach) + float(side.get("offset") or 0.0)
            if not distance > 0:
                return Refusal("This extrude has no length.")
            return {"extent": "oneSide", "sign": sign, "distance": distance, "taper": taper}
        return Refusal("This way of setting the extrude length is not copied yet.")

    if extent_type == "symmetric":
        side = data.get("side_one")
        if _is_through(side):
            return [{"extent": "through", "sign": 1, "distance": None, "taper": 0.0}]
        sym = data.get("symmetric")
        if not sym:
            return Refusal("This extrude has no readable length.")
        taper = _taper(sym.get("taper_deg") or 0.0)
        if isinstance(taper, Refusal):
            return taper
        full = float(sym["distance"]) * (1.0 if sym.get("full_length") else 2.0)
        if not abs(full) > 0:
            return Refusal("This extrude has no length.")
        return [{"extent": "symmetric", "sign": 1, "distance": abs(full), "taper": taper}]

    if extent_type == "two":
        one, two = data.get("side_one"), data.get("side_two")
        if one is None or two is None:
            return Refusal("This extrude has no readable length.")
        if _is_through(one) and _is_through(two):
            return [{"extent": "through", "sign": 1, "distance": None, "taper": 0.0}]
        if combine == "intersect":
            return Refusal("Two sided intersect extrudes are not copied yet.")
        first = one_side(one)
        if isinstance(first, Refusal):
            return first
        second = one_side(two, forced_sign=-first["sign"], measured=False)
        if isinstance(second, Refusal):
            return second
        return [first, second]

    side = one_side(data.get("side_one"))
    if isinstance(side, Refusal):
        return side
    return [side]


def _resolve_through(plan, data, origin, z, combine):
    """Give a one sided through all its distance, or a Refusal."""
    for entry in plan:
        if entry["extent"] == "through" and combine not in ("cut", "intersect"):
            return Refusal("Extruding through all is only copied for cuts.")
        if entry["extent"] == "through-one":
            if combine not in ("cut", "intersect"):
                return Refusal("Extruding through all is only copied for cuts.")
            box = data.get("target_box_before")
            if not box:
                return Refusal("The part this cuts through could not be measured.")
            entry["extent"] = "oneSide"
            entry["distance"] = _reach_through(box, origin, vec.scale(z, entry["sign"]))
    return None


def _build_loops(profile, sketch_name):
    if "loops" not in profile or profile.get("face"):
        return Refusal("A flat face used as a sketch outline is not copied yet.")
    outers, inners = [], []
    for raw in profile["loops"]:
        loop = loops.loop_of(raw.get("curves") or [], sketch_name)
        if isinstance(loop, Refusal):
            return loop
        (outers if raw.get("outer") else inners).append(loop)
    if len(outers) != 1:
        where = " in %s" % sketch_name if sketch_name else ""
        return Refusal("An outline%s does not have exactly one outer loop." % where)
    if len(inners) > MAX_INNER_LOOPS:
        return Refusal("An outline has too many holes.")
    return outers[0], inners


def handle(item, ctx):
    data = item.get("data") or {}
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Extrudes that make a new component are not copied.")
    if operation not in COMBINE:
        return Refusal("This extrude combines with the part in a way that is not copied yet.")
    if data.get("thin"):
        return Refusal("Thin extrudes are not copied yet.")
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This extrude has no sketch outline.")
    if any(p.get("face") or "loops" not in p for p in profiles):
        return Refusal("A flat face used as a sketch outline is not copied yet.")
    combine = COMBINE[operation]

    built = []
    for profile in profiles:
        outcome = _build_loops(profile, profile.get("sketch", ""))
        if isinstance(outcome, Refusal):
            return outcome
        built.append((profile, outcome))

    first_frame = profiles[0]["frame"]
    shift = _start_shift(data.get("start"), first_frame)
    if isinstance(shift, Refusal):
        return shift
    plan = _plan(data, first_frame, shift, combine, ctx)
    if isinstance(plan, Refusal):
        return plan
    z0 = vec.unit(first_frame["z"])
    refusal = _resolve_through(plan, data, vec.add(first_frame["origin"], vec.scale(z0, shift)), z0, combine)
    if refusal:
        return refusal
    if combine == "intersect" and (len(plan) * len(built) > 1):
        return Refusal("Intersect extrudes with several outlines are not copied yet.")

    steps = []
    for profile, (outer, inner) in built:
        frame = profile["frame"]
        base = placement.moved_along(placement.from_frame(frame), shift, vec.unit(frame["z"]))
        for entry in plan:
            reverse = entry["sign"] < 0
            on = placement.reversed_of(base) if reverse else base
            pick = (lambda loop: loops.flip_y(loop)) if reverse else (lambda loop: loop)
            sketch = {"on": on, "outer": pick(outer)}
            if inner:
                sketch["inner"] = [pick(loop) for loop in inner]
            step = {
                "kind": "extrude",
                "sketch": sketch,
                "combine": combine if not steps else ("add" if combine == "new" else combine),
                "extent": entry["extent"],
            }
            if entry["distance"] is not None:
                step["distance"] = _n(entry["distance"])
            if entry["taper"]:
                step["taperDeg"] = _n(entry["taper"])
            steps.append(step)
    return steps
