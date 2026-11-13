"""Rectangular patterns (RectangularPatternFeature).

The measured copies are placed on a grid of up to two directions. A direction that spreads to both sides of the
original becomes a forward and a backward part (`symmetric.py`), and the pattern one one-sided grid for each choice of
a part per direction. When a count follows sizes, every copy any count can make gets its own rounds and chamfers,
kept by a `when` on the count.
"""
import math
from itertools import product

from ..geometry import vec
from ..package.numbers import round9
from . import range_check, symmetric, values
from .follow import Motion
from .repeat_build import build, finish_copies, keep_pattern_fixed, round_vec
from .repeat_elements import FIT_TOL_MM, in_component, is_identity, is_identity_rotation, kept_elements
from .repeat_lattice import lattice_axes, solve_lattice
from .repeat_sources import split_sources
from .result import Refusal, StepResult
from .values import Quantity

# Most copies whose rounds and chamfers are written one by one for every count a size may give (`_counted_finishes`).
MAX_COUNTED_COPIES = 64


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
        back_q, forward_q = symmetric.part_counts(axis["count_q"], axis["back"], axis["forward"],
                                                    axis.get("side", 0))
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


def _part_reach(ctx, part):
    """How many copies a part may make over the size ranges, the original included, or None when that cannot be
    told. A count that follows no size makes the copies it has now."""
    count_q = part["count_q"]
    if not count_q.sized:
        return part["count"]
    span = range_check.sweep(ctx.table, count_q.text, count_q.reads) if ctx.table is not None else None
    if span is None or span.failed or span.high is None:
        return None
    return int(math.floor(span.high + 1e-9))


def _counted_finishes(ctx, item, finishes, grids, axes):
    """The round and bevel steps of every copy a pattern may make at any size setting, each kept by a `when` that
    asks for the counts that make that copy: a copy n steps along a part needs a count of n + 1 or more. So the rounds
    and chamfers follow the count, as Fusion repeats them with each copy. None when a count of the pattern follows
    sizes in a way the copies cannot be listed (a skip list, an unknown range, or more than MAX_COUNTED_COPIES)."""
    if not finishes or ctx.table is None or not any(p["count_q"].sized for parts, _, _ in grids for p in parts):
        return None
    if any(skip for _, skip, _ in grids):
        return None
    name = item.get("name", "")
    seen, copies = set(), []
    for parts, _, _ in grids:
        reach = [_part_reach(ctx, part) for part in parts]
        if None in reach:
            return None
        for steps in product(*(range(r) for r in reach)):
            signed = tuple(part["sign"] * n for part, n in zip(parts, steps))
            if not any(steps) or signed in seen:
                continue
            seen.add(signed)
            shift = [Quantity(0.0)] * 3
            needs = []
            for part, n in zip(parts, steps):
                if n:
                    shift = [q.plus(part["axis"]["step_q"].scaled(n * d)) if abs(d) > 1e-12 else q
                             for q, d in zip(shift, part["dir"])]
                    if part["count_q"].sized:
                        needs.append("%s >= %d" % (values.wrapped(part["count_q"].text), n + 1))
            copies.append((" && ".join(needs), Motion(shift=shift, by=name)))
    if len(copies) > MAX_COUNTED_COPIES:
        return None
    steps = []
    for when, motion in copies:
        for step in finish_copies(ctx, item, finishes, [motion]):
            if when:
                step["when"] = when
            steps.append(step)
    return steps


def _symmetric_reach(axes, data):
    """Sets `back` and `forward` (steps behind and ahead of the original) on each symmetric direction from every
    measured copy, suppressed ones too; returns a Refusal when they do not follow the rule of `symmetric.py`."""
    places = [[] for _ in axes]
    for element in data["elements"]:
        frame = element["frame"]
        if not is_identity_rotation(frame):
            continue
        indexes, residual = solve_lattice(frame["origin"], [(a["dir"], a["step"]) for a in axes])
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


def _tried_places(axes, axis):
    """`places_at` of `symmetric.extra_side` for a direction: the signed steps of the copies the probe read at a try,
    on the grid that the sizes of that try give. None when the copies do not sit on that grid or the count read differs
    from the one the formulas give."""
    def places_at(env, read, count):
        steps = [symmetric.value_at(a["step_q"], env) for a in axes]
        counts = read.get("count") or []
        if None in steps or any(s <= 1e-9 for s in steps) or len(counts) < 2:
            return None
        if counts[0 if axis["which"] == "one" else 1] != count:
            return None
        found = []
        for element in read.get("elements") or []:
            frame = element["frame"]
            if not is_identity_rotation(frame):
                return None
            indexes, residual = solve_lattice(frame["origin"], [(a["dir"], s) for a, s in zip(axes, steps)])
            if residual > FIT_TOL_MM:
                return None
            found.append(indexes[axes.index(axis)])
        return found
    return places_at


def rectangular(item, ctx, sources=None):
    """`sources` is `(solid step ids, finish steps)` when the caller wrote what the pattern repeats."""
    item = in_component(item, ctx, merge=True)
    data = item.get("data") or {}
    sources = split_sources(data, ctx, "pattern") if sources is None else sources
    if isinstance(sources, Refusal):
        return sources
    solids, finishes = sources
    axes = lattice_axes(item, ctx)
    if isinstance(axes, Refusal):
        return axes
    kept = kept_elements(data)
    if kept is None:
        return Refusal("The copies of this pattern could not be read.")

    # Element transforms are relative to the original, so offsets are measured from the origin, and the original
    # itself must be among the elements or the lattice could be off by one place.
    if not any(is_identity(e["frame"]) for e in data["elements"]):
        if any(axis["symmetric"] for axis in axes):
            return Refusal("The original sits between two copies of this pattern, which is not copied yet.")
        return Refusal("The original copy was not found among the copies of this pattern.")
    placed = []
    for element in kept:
        frame = element["frame"]
        if not is_identity_rotation(frame):
            return Refusal("The copies of this pattern are turned, which is not copied yet.")
        indexes, residual = solve_lattice(frame["origin"], [(a["dir"], a["step"]) for a in axes])
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
            axis["side"] = symmetric.extra_side(ctx, item, axis["count_q"], axis["count"],
                                                (axis["back"], axis["forward"]), _tried_places(axes, axis),
                                                default=symmetric.FUSION_EXTRA_SIDE * axis["sign"])
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
            step[key] = {"dir": round_vec(part["dir"]), "count": part["count"], "step": round9(part["axis"]["step"])}
        if skip:
            step["skip"] = skip
        steps.append((step, motions))
    counted = _counted_finishes(ctx, item, finishes, grids, axes) if solids else None
    result = build(ctx, item, solids, [] if counted is not None else finishes, steps, "pattern")
    if isinstance(result, Refusal):
        return result
    if counted is not None:
        result.extend(StepResult.of(counted).entries)
    keep_pattern_fixed(ctx, item, left_out, [] if counted is not None else finishes, ("quantity_one", "quantity_two"))
    for (parts, skip, _), (step, _) in zip(grids, steps):
        for key, part in zip(("linear", "linear2"), parts):
            # A skip list names copies by number, so the app wants a fixed count beside it.
            sized = part["count_q"].sized and not skip
            step[key]["count"] = part["count_q"].json() if sized else part["count"]
            step[key]["step"] = part["axis"]["step_q"].json()
    return result
