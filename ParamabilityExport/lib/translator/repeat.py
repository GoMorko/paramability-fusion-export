"""Pattern and mirror handlers (RectangularPatternFeature, CircularPatternFeature, MirrorFeature).

The copies are read from the measured transform of every pattern element, so the spacing, the turning sense and
the copies Fusion left out come from what Fusion built, not from flags. Solid sources (extrudes, revolves, holes,
other repeats) become one `pattern` or `mirror` step. Rounds and chamfers cannot be repeated by the recipe, so the
copies get their own `round` or `bevel` step with the source's `near` points moved to each copy.

A direction that spreads copies to both sides of the original is written as a forward and a backward part that both
start at the original (`symmetric.py`); the pattern then becomes one one-sided grid for each choice of a part per
direction, and a place that two grids share is made by the first.

Each copy is a `follow.Motion`. A linear spacing that follows sizes moves the copied points with it, and the copies of
extrudes are handed to the walk (`placer_makers.CopiesMaker`), so later picks on them follow sizes too.

A mirror plane or a turning axis that sits on a face or edge of the part moves when a size moves that face or edge
(`follow.place_plane`): its origin or axis point is then written as a formula, and the copies move with it. One that
cannot be followed fixes the sizes written so far. A plane or axis of another component moves as the probe measured
it (`ref_motion`).
"""
import math
from itertools import product

from ..package.numbers import round9
from ..params.expressions import ExpressionError, evaluate
from . import follow, range_check, ref_motion, symmetric, values, vec
from .vec import POINT_TOL
from .step_kinds import FINISH, SOLID, recipe_kind
from .follow import Motion
from .picks import MAX_NEAR_POINTS
from .values import Quantity, Sized, number, numbers_of, reads_in
from .placer_makers import CopiesMaker
from .result import Refusal, StepResult

MAX_REFERENCES = 64
MAX_COPIED_BODIES = 256

FIT_TOL_MM = 1e-4
ROTATION_TOL = 1e-9
ANGLE_TOL_DEG = 1e-6
FULL_TURN_DEG = 360.0

# Finish fields that a copy cannot carry; the translator never writes them.
UNCOPYABLE_FINISH_KEYS = ("sizeEnd",)


def _vec(values):
    return [round9(v) for v in values]


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
            repeat = recipe_kind(step["kind"]).repeat
            if repeat == FINISH:
                near = (step.get("edges") or {}).get("near")
                plain = ctx.plain_picks.get(step_id) or {"near": near, "reads": (), "written": near}
                if plain["near"] is None or any(k in step for k in UNCOPYABLE_FINISH_KEYS):
                    return Refusal("A rounded or chamfered step of this %s cannot be repeated." % what)
                finishes.append(dict(step, near=plain["near"], reads=plain["reads"], written=plain.get("written")))
            elif repeat == SOLID:
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
        if not recipe_kind(step.get("kind")).repeats:
            continue
        sources = sum(bodies.get(i, 1) for i in set(step["of"]))
        added = sources if step["kind"] == "mirror" else _kept_copy_count(step) * sources
        total += added
        bodies[step.get("id")] = added + sources
    return total


def _build(ctx, item, solids, finishes, repeat_steps, what):
    """The repeat steps (when there are solid sources) followed by the finish copies. `repeat_steps` are
    `(step, motions)`: a step and the Motions of the copies it makes. The finish copies use every Motion."""
    out = StepResult()
    if solids:
        for repeat_step, owned in repeat_steps:
            repeat_step["of"] = solids
            out.add(repeat_step, [CopiesMaker(owned)])
        if _copied_bodies(list(ctx.steps) + out.steps) > MAX_COPIED_BODIES:
            return Refusal("This %s makes more than %d copies in all." % (what, MAX_COPIED_BODIES))
    motions = [motion for _, owned in repeat_steps for motion in owned]
    out.extend(StepResult.of(_finish_copies(ctx, item, finishes, motions)).entries)
    if not out.entries:
        return Refusal("This %s makes no copies." % what)
    return out


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


def _grid_motions(item, placed, axes):
    """`(signed steps, Motion)` for each kept copy except the original, in copy order (the first direction running
    fastest): the copy's place times the spacing, which may follow sizes. A pick on a copy of an ordinary direction
    needs its count to keep that copy. In a symmetric direction the places move when the count changes, so a pick
    on a copy off the middle keeps the sizes behind the count."""
    name = item.get("name", "")
    out = []
    for _, indexes in placed:
        if not any(indexes):
            continue
        shift = [Quantity(0.0)] * 3
        needs, requires = [], []
        for index, axis in zip(indexes, axes):
            if not index:
                continue
            shift = [s.plus(axis["step_q"].scaled(index * d)) if abs(d) > 1e-12 else s
                     for s, d in zip(shift, axis["dir"])]
            if not axis["count_q"].sized:
                continue
            if axis["symmetric"]:
                needs += axis["count_q"].reads
            else:
                requires.append((axis["count_q"], index + 1, name))
        out.append((tuple(indexes), Motion(shift=shift, needs=needs, by=name, requires=requires)))
    return sorted(out, key=lambda entry: entry[0][::-1])


def _parts(axes):
    """Each direction as the parts that start at the original: one for an ordinary direction, a forward and a backward
    one for a symmetric direction (`symmetric.py`). A part has its direction, `sign` (+1 forward, -1 backward) and
    its number and Quantity of copies, the original included."""
    for axis in axes:
        step = {"axis": axis}
        if not axis["symmetric"]:
            axis["parts"] = [dict(step, dir=axis["dir"], sign=1, count=axis["count"], count_q=axis["count_q"])]
            continue
        back_q, forward_q = symmetric.part_counts(axis["count_q"], axis["back"], axis["forward"])
        axis["parts"] = [dict(step, dir=axis["dir"], sign=1, count=axis["forward"] + 1, count_q=forward_q),
                         dict(step, dir=vec.scale(axis["dir"], -1), sign=-1, count=axis["back"] + 1, count_q=back_q)]


def _grids(axes, present):
    """The one-sided grids that together make the pattern: one for each choice of a part in every direction.

    Returns a list of `(parts, skip, left_out)`. `skip` lists the grid's copy numbers to leave out: the places with no
    measured copy, and (when no count of the grid follows sizes, so the numbers stay put) the places another grid
    already makes. `left_out` holds the first kind only. A grid that makes no copy is dropped, unless it is the
    only one or a count of it can grow."""
    grids = []
    choices = list(product(*(range(len(axis["parts"])) for axis in axes)))
    for choice in choices:
        parts = [axis["parts"][c] for axis, c in zip(axes, choice)]
        columns = parts[0]["count"]
        total = columns * (parts[1]["count"] if len(parts) == 2 else 1)
        fixed = not any(part["count_q"].sized for part in parts)
        skip, left_out = [], []
        for number_ in range(1, total):
            steps = [number_ % columns, number_ // columns][:len(parts)]
            if tuple(part["sign"] * step for part, step in zip(parts, steps)) not in present:
                skip.append(number_)
                left_out.append(number_)
            elif fixed and any(part["sign"] < 0 and not step for part, step in zip(parts, steps)):
                skip.append(number_)
        if len(choices) > 1 and len(skip) == total - 1 and fixed:
            continue
        grids.append((parts, skip, left_out))
    return grids


def _owner(grids, signed):
    """Index of the first grid that makes the copy at `signed` steps (a part per direction by the sign of the step)."""
    for n, (parts, _, _) in enumerate(grids):
        if all((part["sign"] > 0) == (step >= 0) for part, step in zip(parts, signed)):
            return n
    return 0


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
                reach = _extent_sides(data, which)
                axes.append((vec.unit(direction), distance if guess == "spacing" else distance * reach / (count - 1),
                             count))
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


def _extent_sides(data, which):
    """How many times the extent distance is spanned by a direction: a symmetric direction reaches the distance on
    both sides of the original (2), an ordinary one runs from the first copy to the last (1)."""
    return 2 if data.get("symmetric_" + which) else 1


def _axis_step(item, ctx, which, quantity, count_q, kind):
    """Spacing along one direction as a Quantity, from the pattern distance and how Fusion measures it."""
    data = item["data"]
    raw = float(data.get("distance_" + which) or 0.0)
    if kind not in ("spacing", "extent"):
        return Refusal("The spacing of this pattern could not be read.")
    distance = values.quantity(ctx, item, "distance_" + which, abs(raw), sign=-1 if raw < 0 else 1, absolute=True)
    if kind == "extent":
        step = distance.scaled(_extent_sides(data, which)).divided_by(_gaps(count_q))
    else:
        step = distance
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
            values.pin(ctx, item, "quantity_" + which, "a count of one copy cannot follow it")
            values.handled(ctx, item, "distance_" + which)
            continue
        direction = data.get(dir_key)
        if not direction or vec.length(direction) < 1e-9:
            return Refusal("The direction of this pattern could not be read.")
        place = data.get(dir_key + "_place")
        if isinstance(place, dict) and place.get("assembly"):
            ref_motion.check_direction(ctx, item, place, "spreads copies along")
        count_q = values.quantity(ctx, item, "quantity_" + which, quantity, dim="scalar", whole=True)
        step_q = _axis_step(item, ctx, which, quantity, count_q, kind)
        if isinstance(step_q, Refusal):
            return step_q
        axes.append({"dir": vec.unit(direction), "step": step_q.n, "count": quantity, "step_q": step_q,
                     "count_q": count_q, "symmetric": bool(data.get("symmetric_" + which)), "which": which})
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



def _symmetric_reach(axes, data):
    """Sets `back` and `forward` (steps behind and ahead of the original) on each symmetric direction from every
    measured copy, suppressed ones too; returns a Refusal when they do not follow the rule of `symmetric.py`."""
    places = [[] for _ in axes]
    for element in data["elements"]:
        frame = element["frame"]
        if not _is_identity_rotation(frame):
            continue
        indexes, residual = _solve_lattice(frame["origin"], [(a["dir"], a["step"]) for a in axes])
        if residual <= FIT_TOL_MM:
            for n, index in enumerate(indexes):
                places[n].append(index)
    for axis, found in zip(axes, places):
        if not axis["symmetric"]:
            continue
        reach = symmetric.reach(found, axis["count"])
        if reach is None:
            return Refusal("The copies of this pattern do not spread to both sides of the first one by the rule that "
                           "was expected.")
        axis["back"], axis["forward"] = reach
    return None


def rectangular(item, ctx):
    data = item.get("data") or {}
    sources = _sources(data, ctx, "pattern")
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    axes = _lattice_axes(item, ctx)
    if isinstance(axes, Refusal):
        return axes
    kept = _kept_elements(data)
    if kept is None:
        return Refusal("The copies of this pattern could not be read.")

    # Element transforms are relative to the original, so offsets are measured from the origin, and the original
    # itself must be among the elements or the lattice could be off by one place.
    if not any(_is_identity(e["frame"]) for e in data["elements"]):
        if any(axis["symmetric"] for axis in axes):
            return Refusal("The original sits between two copies of this pattern, which is not copied yet.")
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

    reach = _symmetric_reach(axes, data)
    if isinstance(reach, Refusal):
        return reach
    for n, axis in enumerate(axes):
        if axis["symmetric"]:
            continue
        steps = [indexes[n] for _, indexes in placed]
        if any(v > 0 for v in steps) and any(v < 0 for v in steps):
            return Refusal("The copies of this pattern reach both sides of the first one, but the pattern is not set to "
                           "spread to both sides.")
        if any(v < 0 for v in steps):
            axis["dir"] = vec.scale(axis["dir"], -1)
            for _, indexes in placed:
                indexes[n] = -indexes[n]
        if any(not 0 <= indexes[n] < axis["count"] for _, indexes in placed):
            return Refusal("The copies of this pattern do not match its count.")
    for axis in axes:
        if axis["symmetric"]:
            symmetric.check_even_unseen(ctx, item, axis["count_q"], axis["count"])
    _parts(axes)

    grids = _grids(axes, {tuple(indexes) for _, indexes in placed})
    moves = _grid_motions(item, placed, axes)
    owned = [[] for _ in grids]
    for signed, motion in moves:
        owned[_owner(grids, signed)].append(motion)
    left_out = any(left for _, _, left in grids)
    steps = []
    for (parts, skip, _), motions in zip(grids, owned):
        step = {"kind": "pattern"}
        for key, part in zip(("linear", "linear2"), parts):
            step[key] = {"dir": _vec(part["dir"]), "count": part["count"], "step": round9(part["axis"]["step"])}
        if skip:
            step["skip"] = skip
        steps.append((step, motions))
    result = _build(ctx, item, solids, finishes, steps, "pattern")
    if isinstance(result, Refusal):
        return result
    _keep_pattern_fixed(ctx, item, left_out, finishes, ("quantity_one", "quantity_two"))
    for (parts, skip, _), (step, _) in zip(grids, steps):
        for key, part in zip(("linear", "linear2"), parts):
            # A skip list names copies by number, so the app wants a fixed count beside it.
            sized = part["count_q"].sized and not skip
            step[key]["count"] = part["count_q"].json() if sized else part["count"]
            step[key]["step"] = part["axis"]["step_q"].json()
    return result


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


UNIT_DIRECTIONS = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


def _axis_shift(ctx, item, axis, direction):
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


def _turn_motion(point, moved, direction, angle, needs, by):
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


def _symmetric_circular(item, ctx, setup):
    """A circular pattern that turns copies to both sides of the original: a part turning one way and a part turning
    the other, both from the original (`symmetric.py`). `setup` holds what `circular` has read."""
    count, delta, point, direction, turns = (setup[key] for key in ("count", "delta", "point", "direction", "turns"))
    steps = [(element, _signed_copy(turn, delta, count)) for element, turn in turns]
    if any(k is None for _, k in steps):
        return Refusal("The copies of this pattern are not spread evenly round the axis.")
    every = []
    for element in setup["data"]["elements"]:
        turn = _turn_about(element["frame"], direction)
        if turn is not None and vec.close(vec.frame_apply(element["frame"], point), point, FIT_TOL_MM):
            k = _signed_copy(turn, delta, count)
            if k is not None:
                every.append(k)
    if 0 not in every:
        return Refusal("The original sits between two copies of this pattern, which is not copied yet.")
    reach = symmetric.reach(every, count)
    if reach is None:
        return Refusal("The copies of this pattern do not spread to both sides of the first one by the rule that was "
                       "expected.")
    back, forward = reach
    count_q, angle_q = setup["count_q"], setup["angle_q"]
    symmetric.check_even_unseen(ctx, item, count_q, count)
    back_q, forward_q = symmetric.part_counts(count_q, back, forward)
    moved = _axis_shift(ctx, item, setup["axis"], direction)
    present = {k for _, k in steps}
    needs = count_q.reads + angle_q.reads
    name = item.get("name", "")
    motions = {k: _turn_motion(point, moved, direction, k * delta, needs, name) for k in sorted(present) if k}
    parts = []
    for sign, part_count, part_q in ((1, forward + 1, forward_q), (-1, back + 1, back_q)):
        skip = [n for n in range(1, part_count) if sign * n not in present]
        if part_count == 1 and not part_q.sized:
            continue
        parts.append((sign, part_count, part_q, skip))
    built = []
    for sign, part_count, part_q, skip in parts:
        polar = {"axisPoint": _vec(point), "axis": _vec(vec.scale(direction, sign)), "count": part_count,
                 "angleDeg": round9((part_count - 1) * delta)}
        step = {"kind": "pattern", "polar": polar}
        if skip:
            step["skip"] = skip
        built.append((step, [m for k, m in motions.items() if (k > 0) == (sign > 0)]))
    result = _build(ctx, item, setup["solids"], setup["finishes"], built, "pattern")
    if isinstance(result, Refusal):
        return result
    left_out = any(skip for *_, skip in parts)
    _keep_pattern_fixed(ctx, item, left_out, setup["finishes"], ("quantity",), ("total_angle_deg",))
    for (sign, part_count, part_q, skip), (step, _) in zip(parts, built):
        polar = step["polar"]
        if any(q.sized for q in moved):
            polar["axisPoint"] = [q.plus(c).json() if q.sized else round9(c) for q, c in zip(moved, point)]
        side = angle_q.times(part_q.plus(-1.0)).divided_by(_gaps(count_q))
        polar["angleDeg"] = side.json()
        polar["count"] = part_q.json() if part_q.sized and not skip else part_count
    return result


def circular(item, ctx):
    data = item.get("data") or {}
    sources = _sources(data, ctx, "pattern")
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

    moved = _axis_shift(ctx, item, axis, direction)
    polar = {"axisPoint": _vec(point), "axis": _vec(direction), "count": count}
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
    motions = [_turn_motion(point, moved, direction, n * delta, needs, item.get("name", ""))
               for n in sorted(by_place) if n > 0]
    steps = _build(ctx, item, solids, finishes, [(pattern, motions)], "pattern")
    if isinstance(steps, Refusal):
        return steps
    if any(q.sized for q in moved):
        polar["axisPoint"] = [q.plus(c).json() if q.sized else round9(c) for q, c in zip(moved, point)]
    if angle_q is not None:
        polar["angleDeg"] = angle_q.json()
    _keep_pattern_fixed(ctx, item, skip, finishes, ("quantity",), ("total_angle_deg",))
    polar["count"] = count_q.json() if count_q.sized and not skip else count
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


def _cut_reach(step, as_numbers=numbers_of):
    """(points, margin) with every point of the tool within `margin` mm of one of `points`; None when the tool is
    not bounded by a known rule (through cuts, other loop kinds). `as_numbers` turns the step's formulas into numbers
    (the measured ones by default)."""
    step = as_numbers(step)
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
    kind = recipe_kind(step["kind"])
    if kind.repeats:
        return any(_cuts(by_id[i], by_id) for i in step["of"])
    return kind.always_cuts or step.get("combine") in ("cut", "intersect")


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
        if step.get("combine") == "intersect" or recipe_kind(step["kind"]).repeats and _cuts(step, by_id):
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


def _mirror_plane_at(plane, shift):
    """The plane as written and the shift it was given: with a sized `shift` (how far the plane moves along its normal)
    the origin becomes formulas and the shift is returned; with none the plane and None."""
    normal, origin = plane["normal"], plane["origin"]
    if not shift.sized:
        return plane, None
    moved = [shift.scaled(c).plus(o).json() if abs(c) > 1e-9 else o for o, c in zip(origin, normal)]
    return dict(plane, origin=moved), shift


def _mirror_motion(plane, shift, name):
    """The Motion of a mirror across `plane`; a plane that moves along its normal by `shift` moves the copies twice
    as far."""
    base = Motion.mirror(plane["origin"], plane["normal"], name)
    if shift is None:
        return base
    return Motion(base.rows, [shift.scaled(2.0 * c).plus(base.shift[i].n) if abs(c) > 1e-9 else base.shift[i]
                              for i, c in enumerate(plane["normal"])], by=name)


def _evaluated(env):
    """A function that turns every formula of a written value into its number at the sizes `env`."""
    def convert(node):
        if isinstance(node, Sized):
            return evaluate(node["expr"], env)
        if isinstance(node, dict):
            return {k: convert(v) for k, v in node.items()}
        if isinstance(node, list):
            return [convert(v) for v in node]
        return node
    return convert


def _step_reads(step, by_id):
    """The Fusion names a step reads, with those of the steps it repeats."""
    found = list(reads_in(step))
    for source in step.get("of") or ():
        if source in by_id:
            found += _step_reads(by_id[source], by_id)
    return tuple(dict.fromkeys(found))


def _reach_or_none(step, as_numbers):
    if recipe_kind(step["kind"]).repeats:
        return None
    try:
        return _cut_reach(step, as_numbers)
    except (KeyError, TypeError, IndexError):
        return None


def _slack(steps, origin, normal, side, as_numbers):
    """How far the tools of the steps stay on `side` of the plane, in mm (negative when one reaches across); None
    when no step has a known reach."""
    worst = None
    for step in steps:
        reach = _reach_or_none(step, as_numbers)
        if reach is None:
            continue
        points, margin = reach
        here = min(side * vec.dot(vec.sub(p, origin), normal) for p in points) - margin
        worst = here if worst is None else min(worst, here)
    return worst


def _keep_one_side(ctx, item, plane, steps, side):
    """The body lies on one side of the plane at the current sizes. Mirroring every step equals the body joined with
    its image only while that holds, so each corner of the size ranges is tried too: a step that reaches across the
    plane there, or whose reach is unknown, marks the sizes it reads. The reach of a tool is a bound, so a corner
    only counts when it is worse than the current sizes."""
    table = ctx.table
    reads = tuple(dict.fromkeys(reads_in(steps) + reads_in(plane)))
    if table is None or not reads:
        return
    by_id = {step["id"]: step for step in steps}
    name = item.get("name", "a mirror")
    unknown = [step for step in steps if _reach_or_none(step, numbers_of) is None]
    for step in unknown:
        ctx.doubt(_step_reads(step, by_id), "%s mirrors the whole part, and %s cannot be checked to stay on one side "
                  "of the plane" % (name, step.get("label") or "a step"))
    known = [step for step in steps if all(step is not other for other in unknown)]
    names = {table.size_name(read): read for read in reads}
    why = "%s mirrors the whole part, and at some sizes the part would reach across the plane" % name
    current = None
    for setting in range_check.corners(table, reads):
        try:
            as_numbers = _evaluated(range_check.size_env(table, setting))
            slack = _slack(known, as_numbers(plane["origin"]), plane["normal"], side, as_numbers)
        except (ExpressionError, ValueError, ZeroDivisionError, OverflowError):
            ctx.doubt(reads, "%s mirrors the whole part, and its sizes cannot be tried at the ends of their ranges"
                      % name)
            return
        if not setting:
            current = slack
        elif slack is not None and slack < min(-SIDE_TOL_MM, (current if current is not None else 0.0) - SIDE_TOL_MM):
            ctx.doubt([names[n] for n in setting if n in names], why)


def mirror(item, ctx):
    data = item.get("data") or {}
    plane = _mirror_plane(data)
    if plane is None:
        return Refusal("The mirror plane could not be read as a flat plane.")
    shift = follow.place_plane(ctx, item, data["plane"], plane["normal"], "mirrors across")
    written, moved = _mirror_plane_at(plane, shift if shift is not None else Quantity(0.0))
    entity = data.get("entity_type")
    if entity == "bodies":
        if not data.get("combine"):
            return Refusal("A mirrored body is only copied when it is joined to the part.")
        if any(recipe_kind(step["kind"]).repeat != SOLID for step in ctx.steps):
            return Refusal("A mirror of the whole body after a round, chamfer or shell is not copied yet.")
        problem = _body_mirror_problem(data, plane, ctx.steps)
        if problem:
            return Refusal(problem)
        _keep_one_side(ctx, item, written, ctx.steps, _side_of_plane(data["target_box_before"], plane["origin"],
                                                                     plane["normal"]))
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
    motion = _mirror_motion(plane, moved, item.get("name", ""))
    return _build(ctx, item, solids, finishes, [({"kind": "mirror", "plane": written}, [motion])], "mirror")
