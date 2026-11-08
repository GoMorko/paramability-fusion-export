"""Pattern and mirror handlers (RectangularPatternFeature, CircularPatternFeature, MirrorFeature).

The copies are read from the measured transform of every pattern element, so the spacing, the turning sense and
the copies Fusion left out come from what Fusion built, not from flags. Solid sources (extrudes, revolves, holes,
other repeats) become one `pattern` or `mirror` step. Rounds and chamfers cannot be repeated by the recipe, so the
copies get their own `round` or `bevel` step with the source's `near` points moved to each copy.
"""
import math

from . import vec
from .result import Refusal

TYPES = ("RectangularPatternFeature", "CircularPatternFeature", "MirrorFeature")

MAX_NEAR_POINTS = 32
MAX_REFERENCES = 64
MAX_COPIED_BODIES = 256

FIT_TOL_MM = 1e-4
ROTATION_TOL = 1e-9
ANGLE_TOL_DEG = 1e-6
POINT_TOL = 1e-6
FULL_TURN_DEG = 360.0

SOLID_KINDS = ("extrude", "revolve", "hole", "pattern", "mirror")
FINISH_KINDS = ("round", "bevel")
# Finish fields that would need their own transform when copied; the translator never writes them.
UNCOPYABLE_FINISH_KEYS = ("sizeEnd", "otherSize", "sizeOn", "cutAngleDeg")


def _n(value):
    return round(value, 9) + 0.0


def _vec(values):
    return [_n(v) for v in values]


# ---------------------------------------------------------------- sources


def _sources(data, ctx, what):
    """Split the source items into (solid step ids, finish steps), or a Refusal."""
    if data.get("entity_type") != "features":
        return Refusal("Patterns of faces or bodies are not copied yet.")
    indexes = data.get("sources") or []
    if not indexes:
        return Refusal("This %s has no features to copy." % what)
    by_id = {step["id"]: step for step in ctx.steps}
    solids, finishes = [], []
    for index in indexes:
        ids = ctx.steps_of(index)
        if not ids:
            return Refusal("A step this %s copies is not part of the exported body." % what)
        for step_id in ids:
            step = by_id[step_id]
            kind = step["kind"]
            if kind in FINISH_KINDS:
                if "near" not in (step.get("edges") or {}) or any(k in step for k in UNCOPYABLE_FINISH_KEYS):
                    return Refusal("A rounded or chamfered step of this %s cannot be repeated." % what)
                finishes.append(step)
            elif kind in SOLID_KINDS:
                if step.get("combine") == "intersect":
                    return Refusal("A step that trims the part cannot be repeated.")
                if step_id not in solids:
                    solids.append(step_id)
            else:
                return Refusal("A step of this %s cannot be repeated." % what)
    if len(solids) > MAX_REFERENCES:
        return Refusal("This %s repeats more than %d steps." % (what, MAX_REFERENCES))
    return solids, finishes


def _finish_copies(finishes, motions, drop_same=False):
    """Round and bevel steps for the copies. `motions` are functions that move a point to a copy.

    Whole copies are packed into a step, so the two points of a closed edge never land in different steps.
    With `drop_same` a copy whose points all lie on the source's own points is left out (an edge that maps onto
    itself is already finished).
    """
    steps = []
    for source in finishes:
        near = source["edges"]["near"]
        if not near:
            continue
        sizes = source.get("edgeSizes")
        if sizes is not None:
            sizes = list(sizes) + [source["size"]] * (len(near) - len(sizes))
        moved = []
        for motion in motions:
            points = [_vec(motion(p)) for p in near]
            if drop_same and all(any(vec.close(p, q, POINT_TOL) for q in near) for p in points):
                continue
            moved.append(points)
        per_step = max(1, MAX_NEAR_POINTS // len(near))
        for start in range(0, len(moved), per_step):
            chunk = moved[start:start + per_step]
            step = {
                "kind": source["kind"],
                "edges": {"near": [p for points in chunk for p in points]},
                "size": source["size"],
            }
            if sizes is not None:
                step["edgeSizes"] = sizes * len(chunk)
            steps.append(step)
    return steps


def _copied_bodies(steps):
    """Bodies the pattern and mirror steps made so far, counted once per referenced step."""
    total = 0
    for step in steps:
        if step.get("kind") == "mirror":
            total += len(step["of"])
        elif step.get("kind") == "pattern":
            lin = step.get("linear", {}).get("count", 1) * step.get("linear2", {}).get("count", 1)
            copies = max(lin, step.get("polar", {}).get("count", 1)) - 1 - len(step.get("skip", ()))
            total += max(copies, 0) * len(step["of"])
    return total


def _build(ctx, solids, finishes, repeat_step, motions, what, drop_same=False):
    """The repeat step (when there are solid sources) followed by the finish copies."""
    steps = []
    if solids:
        repeat_step["of"] = solids
        steps.append(repeat_step)
        if _copied_bodies(list(ctx.steps) + steps) > MAX_COPIED_BODIES:
            return Refusal("This %s makes more than %d copies in all." % (what, MAX_COPIED_BODIES))
    steps += _finish_copies(finishes, motions, drop_same)
    if not steps:
        return Refusal("This %s makes no copies." % what)
    return steps


# ---------------------------------------------------------------- elements


def _is_identity_rotation(frame):
    return (vec.close(frame["x"], [1, 0, 0], ROTATION_TOL) and vec.close(frame["y"], [0, 1, 0], ROTATION_TOL)
            and vec.close(frame["z"], [0, 0, 1], ROTATION_TOL))


def _kept_elements(data):
    """Elements that are present and not suppressed, or None when the list was not read."""
    elements = data.get("elements") or []
    if not elements:
        return None
    left_out = set(data.get("suppressed_ids") or [])
    return [e for e in elements if not e.get("suppressed") and e.get("id") not in left_out]


def _skip_places(places, total):
    """Copy numbers 1..total-1 that no kept element sits on."""
    return [n for n in range(1, total) if n not in places]


def _moves(by_place):
    """One point mover per kept copy (not the original), in copy order. Uses the measured element transform."""
    return [(lambda p, f=by_place[n]["frame"]: vec.frame_apply(f, p)) for n in sorted(by_place) if n > 0]


# ---------------------------------------------------------------- rectangular


def _axis_step(data, which, quantity):
    """Spacing along one direction, from the pattern distance and how Fusion measures it."""
    distance = abs(float(data.get("distance_" + which) or 0.0))
    kind = data.get("distance_type")
    if kind == "spacing":
        step = distance
    elif kind == "extent":
        step = distance / (quantity - 1)
    else:
        return Refusal("The spacing of this pattern could not be read.")
    if not step > 1e-9:
        return Refusal("The spacing of this pattern could not be read.")
    return step


def _solve_lattice(offset, axes):
    """Lattice indexes of an offset and the leftover distance in mm. `axes` are (unit dir, step)."""
    if len(axes) == 1:
        coords = [vec.dot(offset, axes[0][0])]
    else:
        d1, d2 = axes[0][0], axes[1][0]
        g12 = vec.dot(d1, d2)
        det = 1.0 - g12 * g12
        b1, b2 = vec.dot(offset, d1), vec.dot(offset, d2)
        coords = [(b1 - g12 * b2) / det, (b2 - g12 * b1) / det]
    indexes = [int(round(c / step)) for c, (_, step) in zip(coords, axes)]
    fitted = [0.0, 0.0, 0.0]
    for index, (direction, step) in zip(indexes, axes):
        fitted = vec.add(fitted, vec.scale(direction, index * step))
    return indexes, vec.length(vec.sub(offset, fitted))


def _lattice_axes(data):
    """The directions that have more than one copy, as dicts {dir, step, count}; or a Refusal."""
    axes = []
    for which, dir_key, qty_key in (("one", "direction_one", "quantity_one"), ("two", "direction_two", "quantity_two")):
        quantity = int(data.get(qty_key) or 1)
        if quantity < 1:
            return Refusal("This pattern has no copies.")
        if quantity == 1:
            continue
        direction = data.get(dir_key)
        if not direction or vec.length(direction) < 1e-9:
            return Refusal("The direction of this pattern could not be read.")
        step = _axis_step(data, which, quantity)
        if isinstance(step, Refusal):
            return step
        axes.append({"dir": vec.unit(direction), "step": step, "count": quantity})
    if not axes:
        return Refusal("This pattern makes no copies.")
    if len(axes) == 2 and 1.0 - vec.dot(axes[0]["dir"], axes[1]["dir"]) ** 2 < 1e-9:
        return Refusal("The two directions of this pattern run along one line.")
    return axes


def _rectangular(item, ctx):
    data = item.get("data") or {}
    sources = _sources(data, ctx, "pattern")
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    if data.get("symmetric_one") or data.get("symmetric_two"):
        return Refusal("Patterns that spread to both sides of the start are not copied yet.")
    axes = _lattice_axes(data)
    if isinstance(axes, Refusal):
        return axes
    kept = _kept_elements(data)
    if kept is None:
        return Refusal("The copies of this pattern could not be read.")

    reference = data["elements"][0]["frame"]["origin"]
    placed = []
    for element in kept:
        frame = element["frame"]
        if not _is_identity_rotation(frame):
            return Refusal("The copies of this pattern are turned, which is not copied yet.")
        indexes, residual = _solve_lattice(vec.sub(frame["origin"], reference), [(a["dir"], a["step"]) for a in axes])
        if residual > FIT_TOL_MM:
            return Refusal("The copies of this pattern do not sit on an even grid.")
        placed.append((element, indexes))

    for n, axis in enumerate(axes):
        values = [indexes[n] for _, indexes in placed]
        if any(v > 0 for v in values) and any(v < 0 for v in values):
            return Refusal("The copies of this pattern reach both sides of the first one, which is not copied yet.")
        if any(v < 0 for v in values):
            axis["dir"] = vec.scale(axis["dir"], -1)
            for _, indexes in placed:
                indexes[n] = -indexes[n]
        if any(not 0 <= indexes[n] < axis["count"] for _, indexes in placed):
            return Refusal("The copies of this pattern do not match its count.")

    columns = axes[0]["count"]
    total = columns * (axes[1]["count"] if len(axes) == 2 else 1)
    by_place = {indexes[0] + (indexes[1] * columns if len(indexes) == 2 else 0): element for element, indexes in placed}
    skip = _skip_places(by_place, total)

    pattern = {"kind": "pattern"}
    for key, axis in zip(("linear", "linear2"), axes):
        pattern[key] = {"dir": _vec(axis["dir"]), "count": axis["count"], "step": _n(axis["step"])}
    if skip:
        pattern["skip"] = skip
    return _build(ctx, solids, finishes, pattern, _moves(by_place), "pattern")


# ---------------------------------------------------------------- circular


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


def _circular(item, ctx):
    data = item.get("data") or {}
    sources = _sources(data, ctx, "pattern")
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    if data.get("symmetric"):
        return Refusal("Patterns that spread to both sides of the start are not copied yet.")
    axis = data.get("axis") or {}
    if "point" not in axis or "dir" not in axis:
        return Refusal("The turning axis of this pattern could not be read.")
    count = int(data.get("quantity") or 1)
    if count < 2:
        return Refusal("This pattern makes no copies.")
    total_deg = abs(float(data.get("total_angle_deg") or 0.0))
    full = abs(total_deg - FULL_TURN_DEG) <= ANGLE_TOL_DEG
    if not full and not 0 < total_deg < FULL_TURN_DEG:
        return Refusal("The angle of this pattern could not be read.")
    delta = FULL_TURN_DEG / count if full else total_deg / (count - 1)
    kept = _kept_elements(data)
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

    sign = next((s for s in (1, -1) if all(_copy_number(t, delta, s, count, full) is not None for _, t in turns)), 0)
    if not sign:
        return Refusal("The copies of this pattern are not spread evenly round the axis.")
    if sign < 0:
        direction = vec.scale(direction, -1)
    by_place = {_copy_number(t, delta, sign, count, full): element for element, t in turns}
    skip = _skip_places(by_place, count)

    polar = {"axisPoint": _vec(point), "axis": _vec(direction), "count": count}
    if not full:
        polar["angleDeg"] = _n((count - 1) * delta)
    pattern = {"kind": "pattern", "polar": polar}
    if skip:
        pattern["skip"] = skip
    return _build(ctx, solids, finishes, pattern, _moves(by_place), "pattern")


# ---------------------------------------------------------------- mirror


def _mirror_plane(data):
    plane = data.get("plane")
    if not plane or "point" not in plane or "normal" not in plane or vec.length(plane["normal"]) < 1e-9:
        return None
    return {"origin": _vec(plane["point"]), "normal": _vec(vec.unit(plane["normal"]))}


def _mirror(item, ctx):
    data = item.get("data") or {}
    plane = _mirror_plane(data)
    if plane is None:
        return Refusal("The mirror plane could not be read as a flat plane.")
    entity = data.get("entity_type")
    if entity == "bodies":
        if not data.get("combine"):
            return Refusal("A mirrored body is only copied when it is joined to the part.")
        if any(step["kind"] not in SOLID_KINDS for step in ctx.steps):
            return Refusal("A mirror of the whole body after a round, chamfer or shell is not copied yet.")
        solids, finishes = [step["id"] for step in ctx.steps], []
        if len(solids) > MAX_REFERENCES:
            return Refusal("This mirror repeats more than %d steps." % MAX_REFERENCES)
    elif entity == "features":
        sources = _sources(data, ctx, "mirror")
        if isinstance(sources, Refusal):
            return sources
        solids, finishes = sources
    else:
        return Refusal("Mirrors of faces are not copied yet.")
    origin, normal = plane["origin"], plane["normal"]
    return _build(ctx, solids, finishes, {"kind": "mirror", "plane": plane},
                  [lambda p: vec.reflect(p, origin, normal)], "mirror", drop_same=True)


_HANDLERS = {
    "RectangularPatternFeature": _rectangular,
    "CircularPatternFeature": _circular,
    "MirrorFeature": _mirror,
}


def handle(item, ctx):
    return _HANDLERS[item["type"]](item, ctx)
