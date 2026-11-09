"""Pattern and mirror handlers (RectangularPatternFeature, CircularPatternFeature, MirrorFeature).

The copies are read from the measured transform of every pattern element, so the spacing, the turning sense and
the copies Fusion left out come from what Fusion built, not from flags. Solid sources (extrudes, revolves, holes,
other repeats) become one `pattern` or `mirror` step. Rounds and chamfers cannot be repeated by the recipe, so the
copies get their own `round` or `bevel` step with the source's `near` points moved to each copy.

Each copy is a `follow.Motion`. A linear spacing that follows sizes moves the copied points with it, and the copies of
extrudes are handed to the walk (`_copies`), so later picks on them follow sizes too.
"""
import math

from . import follow, values, vec
from .follow import Motion
from .values import Quantity, number, numbers_of
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
# Finish fields that a copy cannot carry; the translator never writes them.
UNCOPYABLE_FINISH_KEYS = ("sizeEnd",)


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
        if any(step_id in ctx.not_repeatable for step_id in ids):
            return Refusal("A step that reaches to the part or to a face grows with the part, so its copies are not "
                           "copied yet.")
        for step_id in ids:
            step = by_id[step_id]
            kind = step["kind"]
            if kind in FINISH_KINDS:
                near = (step.get("edges") or {}).get("near")
                plain = ctx.plain_picks.get(step_id) or {"near": near, "reads": (), "written": near}
                if plain["near"] is None or any(k in step for k in UNCOPYABLE_FINISH_KEYS):
                    return Refusal("A rounded or chamfered step of this %s cannot be repeated." % what)
                finishes.append(dict(step, near=plain["near"], reads=plain["reads"], written=plain.get("written")))
            elif kind in SOLID_KINDS:
                if step.get("combine") == "intersect":
                    return Refusal("A step that trims the part cannot be repeated.")
                if step.get("combine") == "new":
                    return Refusal("A step that makes a separate body cannot be repeated.")
                if step_id not in solids:
                    solids.append(step_id)
            else:
                return Refusal("A step of this %s cannot be repeated." % what)
    if len(solids) > MAX_REFERENCES:
        return Refusal("This %s repeats more than %d steps." % (what, MAX_REFERENCES))
    return solids, finishes


def _written_points(ctx, item, source):
    """The source's pick points as written (formulas where they follow sizes). A pick that names a step is placed
    again here; when that fails, its sizes are fixed and the measured points are used."""
    if source.get("written") is not None:
        return source["written"]
    followed = follow.follow_points(ctx, item, source["near"]) if ctx.written_reads else None
    return followed if followed is not None else source["near"]


def _finish_copies(ctx, item, finishes, motions):
    """Round and bevel steps for the copies. `motions` are the follow.Motion of each copy. Each source has its
    measured points in `near` and its written points in `written`.

    A moved point that lands on one of the source's own points is dropped, with its size: that edge is already
    finished, and the point would pick a neighbouring edge of the new surface. The copies are packed whole into
    steps of at most MAX_NEAR_POINTS points; copies whose `sizeOn` turns differently get their own steps.
    """
    steps = []
    for source in finishes:
        near = source["near"]
        if not near:
            continue
        written = _written_points(ctx, item, source)
        sizes = source.get("edgeSizes")
        if sizes is not None:
            sizes = list(sizes) + [source["size"]] * (len(near) - len(sizes))
        groups = []
        for motion in motions:
            kept = [(motion.numbers(p), n) for n, p in enumerate(near)]
            kept = [(follow.cleaned_all(motion.quantities(written[n])), n) for q, n in kept
                    if not any(vec.close(q, p, POINT_TOL) for p in near)]
            if not kept:
                continue
            size_on = _vec(motion.turn_vector(source["sizeOn"])) if "sizeOn" in source else None
            if groups and groups[-1][0] == size_on and len(groups[-1][1]) + len(kept) <= MAX_NEAR_POINTS:
                groups[-1][1].extend(kept)
            else:
                groups.append((size_on, list(kept)))
        for size_on, group in groups:
            step = {"kind": source["kind"], "edges": {"near": [q for q, _ in group]}, "size": source["size"]}
            for key in ("otherSize", "cutAngleDeg"):
                if key in source:
                    step[key] = source[key]
            if size_on is not None:
                step["sizeOn"] = size_on
            if sizes is not None:
                step["edgeSizes"] = [sizes[n] for _, n in group]
            steps.append(step)
    return steps


def _kept_copy_count(step):
    """Copies a pattern step makes beyond the original, as the app counts them."""
    grid = 0
    if "linear" in step:
        grid = max(0, number(step["linear"]["count"]) * number(step.get("linear2", {}).get("count", 1)) - 1)
    turned = max(0, number(step["polar"]["count"]) - 1) if "polar" in step else 0
    return max(0, grid + turned - len(set(step.get("skip", ()))))


def _copied_bodies(steps):
    """Tool bodies the pattern and mirror steps add, counted as the app counts them.

    A step named in `of` counts once; a repeat among them counts all the bodies it makes, original included.
    """
    bodies = {}
    total = 0
    for step in steps:
        if step.get("kind") not in ("pattern", "mirror"):
            continue
        sources = sum(bodies.get(i, 1) for i in set(step["of"]))
        added = sources if step["kind"] == "mirror" else _kept_copy_count(step) * sources
        total += added
        bodies[step.get("id")] = added + sources
    return total


def _build(ctx, item, solids, finishes, repeat_step, motions, what):
    """The repeat step (when there are solid sources) followed by the finish copies."""
    steps = []
    if solids:
        repeat_step["of"] = solids
        repeat_step["_copies"] = motions
        steps.append(repeat_step)
        if _copied_bodies(list(ctx.steps) + steps) > MAX_COPIED_BODIES:
            return Refusal("This %s makes more than %d copies in all." % (what, MAX_COPIED_BODIES))
    steps += _finish_copies(ctx, item, finishes, motions)
    if not steps:
        return Refusal("This %s makes no copies." % what)
    return steps



# ---------------------------------------------------------------- elements


def _is_identity_rotation(frame):
    return (vec.close(frame["x"], [1, 0, 0], ROTATION_TOL) and vec.close(frame["y"], [0, 1, 0], ROTATION_TOL)
            and vec.close(frame["z"], [0, 0, 1], ROTATION_TOL))


def _is_identity(frame):
    return _is_identity_rotation(frame) and vec.length(frame["origin"]) <= FIT_TOL_MM


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


def _grid_motions(item, placed, axes, columns):
    """One Motion per kept copy (not the original), in copy order: the copy's place times the spacing, which may
    follow sizes. A pick on a copy keeps the counts."""
    needs = tuple(name for axis in axes for name in axis["count_q"].reads)
    by_place = {}
    for _, indexes in placed:
        number_ = indexes[0] + (indexes[1] * columns if len(indexes) == 2 else 0)
        shift = [Quantity(0.0)] * 3
        for index, axis in zip(indexes, axes):
            if index:
                shift = [s.plus(axis["step_q"].scaled(index * d)) if abs(d) > 1e-12 else s
                         for s, d in zip(shift, axis["dir"])]
        by_place[number_] = Motion(shift=shift, needs=needs, by=item.get("name", ""))
    return [by_place[n] for n in sorted(by_place) if n > 0]


# ---------------------------------------------------------------- rectangular


def _distance_kind(data):
    """How Fusion measures the pattern distance: `spacing` (between neighbours) or `extent` (first to last), or None.

    When the reader could not name it, the measured copies tell: the kind whose grid holds every kept copy.
    """
    kind = data.get("distance_type")
    if kind in ("spacing", "extent"):
        return kind
    kept = _kept_elements(data)
    if not kept:
        return None
    for guess in ("spacing", "extent"):
        axes = []
        for which in ("one", "two"):
            count = int(data.get("quantity_" + which) or 1)
            direction = data.get("direction_" + which)
            if count > 1 and direction and vec.length(direction) > 1e-9:
                distance = abs(float(data.get("distance_" + which) or 0.0))
                axes.append((vec.unit(direction), distance if guess == "spacing" else distance / (count - 1), count))
        if not axes or not all(step > 1e-9 for _, step, _ in axes):
            return None
        if len(axes) == 2 and 1.0 - vec.dot(axes[0][0], axes[1][0]) ** 2 < 1e-9:
            return None
        fits = True
        for element in kept:
            indexes, residual = _solve_lattice(element["frame"]["origin"], [(d, s) for d, s, _ in axes])
            if residual > FIT_TOL_MM or any(abs(i) >= c for i, (_, _, c) in zip(indexes, axes)):
                fits = False
                break
        if fits:
            return guess
    return None


def _axis_step(item, ctx, which, quantity, count_q, kind):
    """Spacing along one direction as a Quantity, from the pattern distance and how Fusion measures it."""
    data = item["data"]
    raw = float(data.get("distance_" + which) or 0.0)
    if kind not in ("spacing", "extent"):
        return Refusal("The spacing of this pattern could not be read.")
    distance = values.quantity(ctx, item, "distance_" + which, abs(raw), sign=-1 if raw < 0 else 1, absolute=True)
    step = distance if kind == "spacing" else distance.divided_by(_gaps(count_q))
    if not step.n > 1e-9:
        return Refusal("The spacing of this pattern could not be read.")
    return step


def _gaps(count_q):
    """The gaps between `count` copies; a count that follows sizes never gives zero gaps, so one copy divides by 1."""
    if not count_q.sized:
        return count_q.plus(-1)
    return Quantity(count_q.n - 1, "max(%s - 1, 1)" % count_q.text, count_q.reads)


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


def _lattice_axes(item, ctx):
    """The directions that have more than one copy, as dicts {dir, step, count, step_q, count_q}; or a Refusal.

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
            continue
        direction = data.get(dir_key)
        if not direction or vec.length(direction) < 1e-9:
            return Refusal("The direction of this pattern could not be read.")
        count_q = values.quantity(ctx, item, "quantity_" + which, quantity, dim="scalar", whole=True)
        step_q = _axis_step(item, ctx, which, quantity, count_q, kind)
        if isinstance(step_q, Refusal):
            return step_q
        axes.append({"dir": vec.unit(direction), "step": step_q.n, "count": quantity,
                     "step_q": step_q, "count_q": count_q})
    if not axes:
        return Refusal("This pattern makes no copies.")
    if len(axes) == 2 and 1.0 - vec.dot(axes[0]["dir"], axes[1]["dir"]) ** 2 < 1e-9:
        return Refusal("The two directions of this pattern run along one line.")
    return axes


def _keep_pattern_fixed(ctx, item, skip, finishes, counts, turns=()):
    """Copies that are left out by number, or rounds that are copied one by one, cannot follow a changed count;
    turned copies cannot follow a changed angle either. The sizes behind them become fixed numbers."""
    name = item.get("name", "a pattern")
    if skip:
        for path in counts:
            values.pin(ctx, item, path, "%s leaves copies out, so its count must stay" % name)
    if finishes:
        for path in counts + tuple(turns):
            values.pin(ctx, item, path, "the rounded or chamfered copies in %s are placed one by one" % name)



def _rectangular(item, ctx):
    data = item.get("data") or {}
    sources = _sources(data, ctx, "pattern")
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    if data.get("symmetric_one") or data.get("symmetric_two"):
        return Refusal("Patterns that spread to both sides of the start are not copied yet.")
    axes = _lattice_axes(item, ctx)
    if isinstance(axes, Refusal):
        return axes
    kept = _kept_elements(data)
    if kept is None:
        return Refusal("The copies of this pattern could not be read.")

    # Element transforms are relative to the original, so offsets are measured from the origin, and the original
    # itself must be among the elements or the lattice could be off by one place.
    if not any(_is_identity(e["frame"]) for e in data["elements"]):
        return Refusal("The original copy was not found among the copies of this pattern.")
    placed = []
    for element in kept:
        frame = element["frame"]
        if not _is_identity_rotation(frame):
            return Refusal("The copies of this pattern are turned, which is not copied yet.")
        indexes, residual = _solve_lattice(frame["origin"], [(a["dir"], a["step"]) for a in axes])
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
    steps = _build(ctx, item, solids, finishes, pattern, _grid_motions(item, placed, axes, columns), "pattern")
    if isinstance(steps, Refusal):
        return steps
    _keep_pattern_fixed(ctx, item, skip, finishes, ("quantity_one", "quantity_two"))
    for key, axis in zip(("linear", "linear2"), axes):
        pattern[key]["count"] = axis["count_q"].json() if axis["count_q"].sized else axis["count"]
        pattern[key]["step"] = axis["step_q"].json()
    return steps


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
    raw_total = float(data.get("total_angle_deg") or 0.0)
    total_deg = abs(raw_total)
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
    count_q = values.quantity(ctx, item, "quantity", count, dim="scalar", whole=True)
    angle_q = None
    if full:
        values.pin(ctx, item, "total_angle_deg", "%s turns a full circle only while its angle is a plain 360"
                   % item.get("name", "a pattern"))
    else:
        angle_q = values.quantity(ctx, item, "total_angle_deg", total_deg, dim="angle",
                                  sign=-1 if raw_total < 0 else 1, absolute=True)
    needs = count_q.reads + (angle_q.reads if angle_q is not None else ())
    motions = [Motion.turn(point, direction, n * delta, needs, item.get("name", "")) for n in sorted(by_place) if n > 0]
    steps = _build(ctx, item, solids, finishes, pattern, motions, "pattern")
    if isinstance(steps, Refusal):
        return steps
    if angle_q is not None:
        polar["angleDeg"] = angle_q.json()
    _keep_pattern_fixed(ctx, item, skip, finishes, ("quantity",), ("total_angle_deg",))
    polar["count"] = count_q.json() if count_q.sized else count
    return steps


# ---------------------------------------------------------------- mirror


def _mirror_plane(data):
    plane = data.get("plane")
    if not plane or "point" not in plane or "normal" not in plane or vec.length(plane["normal"]) < 1e-9:
        return None
    return {"origin": _vec(plane["point"]), "normal": _vec(vec.unit(plane["normal"]))}


# A whole body mirror in Fusion is "the body joined with its mirror image". The recipe instead mirrors every
# earlier step onto the finished part, which agrees only when the body lies on one side of the plane and no cutting
# tool reaches across it. The helpers below prove that, and the mirror is refused when they cannot.

SIDE_TOL_MM = 1e-4


def _side_of_plane(box, origin, normal):
    """+1 or -1 when the whole box lies on that side of the plane (within tolerance), else 0."""
    lo, hi = box["min"], box["max"]
    dists = [vec.dot(vec.sub([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]],
                             origin), normal) for i in range(8)]
    if min(dists) >= -SIDE_TOL_MM and max(dists) > SIDE_TOL_MM:
        return 1
    if max(dists) <= SIDE_TOL_MM and min(dists) < -SIDE_TOL_MM:
        return -1
    return 0


def _arc_circle_points(p0, pm, p1):
    """Corners of the square around the circle through three 2D points (a bound for any arc of that circle)."""
    ax, ay = p0
    bx, by = pm
    cx, cy = p1
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [p0, pm, p1]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    return [[ux + sx * r, uy + sy * r] for sx in (-1, 1) for sy in (-1, 1)]


def _loop_points(loop):
    """2D points whose hull contains the loop, or None for a loop kind this does not know."""
    kind = loop.get("kind")
    if kind in ("circle", "ellipse", "rect"):
        cx, cy = loop["center"]
        if kind == "circle":
            reach = loop["radius"]
        elif kind == "ellipse":
            reach = max(loop["radiusX"], loop["radiusY"])
        else:
            reach = math.hypot(loop["width"], loop["height"]) / 2
        return [[cx + sx * reach, cy + sy * reach] for sx in (-1, 1) for sy in (-1, 1)]
    if kind == "polygon":
        return [[number(c) for c in p] for p in loop["points"]]
    if kind == "profile":
        points, here = [list(loop["start"])], list(loop["start"])
        for seg in loop["segments"]:
            if "through" in seg:
                points += _arc_circle_points(here, seg["through"], seg["to"])
            points.append(list(seg["to"]))
            here = list(seg["to"])
        return points
    return None


def _placed(on, point2):
    """A sketch point in model coordinates (the sketch y axis is normal x xDir)."""
    y_dir = vec.cross(on["normal"], on["xDir"])
    return vec.add(vec.add(on["origin"], vec.scale(on["xDir"], point2[0])), vec.scale(y_dir, point2[1]))


def _cut_reach(step):
    """(points, margin) with every point of the cutting tool within `margin` mm of one of `points`; None when
    the tool is not bounded by a known rule (through cuts, other loop kinds)."""
    step = numbers_of(step)
    kind = step["kind"]
    if kind == "hole":
        axis = vec.unit(step["direction"])
        if step.get("depth") is None:
            return None
        radius = max([number(step["diameter"])]
                     + [number(step.get(k, {}).get("diameter", 0)) for k in ("counterbore", "countersink")]) / 2
        end = vec.add(step["origin"], vec.scale(axis, number(step["depth"])))
        return [step["origin"], end], radius
    sketch = step.get("sketch") or {}
    on = {k: (vec.unit(v) if k != "origin" else [number(c) for c in v]) for k, v in sketch["on"].items()}
    outline = _loop_points(sketch["outer"])
    if outline is None:
        return None
    if kind == "revolve":
        axis_point = _placed(on, step["axis"]["point"])
        axis_dir = vec.unit(vec.add(vec.scale(on["xDir"], step["axis"]["dir"][0]),
                                    vec.scale(vec.cross(on["normal"], on["xDir"]), step["axis"]["dir"][1])))
        points, margin = [], 0.0
        for q in outline:
            p = _placed(on, q)
            along = vec.dot(vec.sub(p, axis_point), axis_dir)
            points.append(vec.add(axis_point, vec.scale(axis_dir, along)))
            margin = max(margin, vec.length(vec.sub(p, points[-1])))
        return points, margin
    if kind == "extrude":
        extent = step.get("extent")
        distance = number(step.get("distance"))
        if extent not in ("oneSide", "symmetric") or distance is None:
            return None
        low, high = (0.0, distance) if extent == "oneSide" else (-distance / 2, distance / 2)
        margin = distance * math.tan(math.radians(abs(number(step.get("taperDeg", 0.0)))))
        points = [vec.add(_placed(on, q), vec.scale(on["normal"], h)) for q in outline for h in (low, high)]
        return points, margin
    return None


def _cuts(step, by_id):
    """True when the step (or a step it repeats) removes material."""
    if step["kind"] in ("pattern", "mirror"):
        return any(_cuts(by_id[i], by_id) for i in step["of"])
    return step["kind"] == "hole" or step.get("combine") in ("cut", "intersect")


def _body_mirror_problem(data, plane, steps):
    """A plain reason when mirroring every earlier step would not equal the body joined with its image, else None."""
    box = data.get("target_box_before")
    if not box:
        return "The part could not be measured before this mirror."
    origin, normal = plane["origin"], plane["normal"]
    side = _side_of_plane(box, origin, normal)
    if not side:
        return "A mirror of the whole body is only copied when the body lies on one side of the plane."
    by_id = {step["id"]: step for step in steps}
    for step in steps:
        if step.get("combine") == "intersect" or step["kind"] in ("pattern", "mirror") and _cuts(step, by_id):
            return "A mirror of the whole body is not copied when a cut is repeated or the part is trimmed."
        if not _cuts(step, by_id):
            continue
        reach = _cut_reach(step)
        if reach is None:
            return "A mirror of the whole body is not copied when a cut has no measurable end."
        points, margin = reach
        if min(side * vec.dot(vec.sub(p, origin), normal) for p in points) - margin < -SIDE_TOL_MM:
            return "A mirror of the whole body is not copied when a cut reaches across the mirror plane."
    return None


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
        problem = _body_mirror_problem(data, plane, ctx.steps)
        if problem:
            return Refusal(problem)
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
    motion = Motion.mirror(plane["origin"], plane["normal"], item.get("name", ""))
    return _build(ctx, item, solids, finishes, {"kind": "mirror", "plane": plane}, [motion], "mirror")


_HANDLERS = {
    "RectangularPatternFeature": _rectangular,
    "CircularPatternFeature": _circular,
    "MirrorFeature": _mirror,
}


def handle(item, ctx):
    return _HANDLERS[item["type"]](item, ctx)
