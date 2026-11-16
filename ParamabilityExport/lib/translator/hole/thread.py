"""Modeled threads as recipe `thread` steps: a ThreadFeature on a cylinder face, and the thread of a tapped hole.

The recipe thread is a 60 degree form with a pitch, a major and a minor diameter, an optional pitch diameter, a hand
and a length. Fusion's metric and Unified profiles are that form; other profiles, tapered threads and anything over
the recipe's caps are refused (a gap with a hint). The numbers, the cylinder and the end the thread starts at are read by the shared layer
(`design_model/steps/thread.py`); a read problem there becomes a refusal here (`refusal`). Every number can be
missing: the thread is then left out, never guessed.

A ThreadFeature starts at the end of its cylinder face and runs the full face, or the set length from the end the
made thread touches. The start and the length follow the sizes that move the cylinder's end faces
(`faces/follow.py`); a size that changes the cylinder's diameter is marked, since a thread fits one diameter.
"""
from ...capture_model import gap_hints
from ...design_model.problem import Problem
from ...design_model import edges, reach as reach_sizes
from ...design_model.steps import hole as hole_facts, thread as facts
from ...design_model.values import Quantity
from ...geometry import vec
from ...design_model import words as shared
from .. import values
from ..faces import follow
from ..faces.slabs import as_quantity
from ..ranges import range_check
from ..result import Refusal, StepResult
from ..step_walk import all_steps
from .. import turn_budget

# The recipe's thread caps (feature-recipe caps.ts): threads per recipe, turns in all, pitch range in mm.
MAX_THREADS = 8
MAX_TURNS = turn_budget.MAX_TURNS_TOTAL
MIN_PITCH, MAX_PITCH = 0.2, 10.0
PITCHES = (MIN_PITCH, MAX_PITCH)
STARTS_NOTE = "The thread starts at a standard angle, not where Fusion starts it."


def refusal(problem):
    """The Refusal of a read problem of the shared layer."""
    return Refusal(problem.words, cause=problem.cause)


def _thread_steps(ctx):
    return [s for s in all_steps(ctx.steps) if s.get("kind") == "thread"]


def _fit_caps(ctx, count):
    """A Refusal when `count` more threads pass the recipe's thread count, else None."""
    if ctx.outer is not None:
        return Refusal("A thread cannot be copied inside a tool body.")
    if len(_thread_steps(ctx)) + count > MAX_THREADS:
        return Refusal("The recipe holds at most %d threads." % MAX_THREADS, cause=gap_hints.THREAD_LIMITS)
    return None


def _limit_length(ctx, item, spec, length, count):
    """`length` (a Quantity) kept within the turns left for the recipe's threads, at every size. A Refusal when the
    turns already pass the cap at the current values; a length that can pass it at some size is written as its number
    and its sizes are marked."""
    room = turn_budget.left(ctx) / count * spec.pitch
    if length.n > room + 1e-9:
        return Refusal("The threads of the part pass %d turns in all." % MAX_TURNS, cause=gap_hints.THREAD_LIMITS)
    return values.stays_below(ctx, item, length, room, "the thread of %s could pass %d turns at some sizes"
                              % (item.get("name", "a step"), MAX_TURNS))


def write(origin, direction, length, spec, internal):
    """One recipe `thread` step. `origin` and `length` are written numbers or formulas."""
    step = {"kind": "thread", "axis": {"origin": list(origin), "dir": [round(c, 9) + 0.0 for c in direction]},
            "length": length.json() if isinstance(length, Quantity) else length,
            "diameter": round(spec.major, 6), "pitch": round(spec.pitch, 6), "minorDiameter": round(spec.minor, 6),
            "internal": bool(internal)}
    if spec.pitch_diameter:
        # Dropped again by the translator when the recipe is older than `translate.PITCH_DIAMETER_VERSION`.
        step["pitchDiameter"] = round(spec.pitch_diameter, 6)
    if not spec.right:
        step["hand"] = "left"
    return step


# ---- ThreadFeature ---------------------------------------------------------------------------------------------

def _on_axis(origin, axis, t):
    return [round(origin[i] + axis[i] * t, 6) + 0.0 for i in range(3)]


def _radius_moves(ctx, item, axis, centre, side):
    """Marks the sizes that change the cylinder's diameter: its wall point moves differently from its axis point."""
    if side is None or centre is None:
        return
    reads = []
    flat = all(abs(c) < 1e-9 or abs(abs(c) - 1.0) < 1e-9 for c in axis)
    for i in range(3):
        a, b = as_quantity(side[i]), as_quantity(centre[i])
        if flat and abs(axis[i]) > 0.5:
            continue
        if not (a.sized or b.sized):
            continue
        diff = a.plus(b.scaled(-1))
        if flat and diff.sized:
            span = range_check.sweep(ctx.table, diff.text, diff.reads) if ctx.table is not None else None
            if span is not None and not span.failed and abs(span.low - diff.n) < 1e-6 and abs(span.high - diff.n) < 1e-6:
                continue
        reads += list(diff.reads if diff.sized else ()) + (list(a.reads) + list(b.reads) if not flat else [])
    if reads:
        ctx.doubt(tuple(dict.fromkeys(reads)), "the thread of %s fits one diameter, and these sizes change the diameter "
                  "of its cylinder" % item.get("name", "a step"))


def _length_along(axis, start, end):
    """The distance from `start` to `end` along the unit `axis` as a Quantity (positions are numbers or formulas)."""
    total = Quantity(0.0)
    for i in range(3):
        if abs(axis[i]) > 1e-9:
            total = total.plus(as_quantity(end[i]).plus(as_quantity(start[i]).scaled(-1)).scaled(axis[i]))
    return total


def feature(ctx, step):
    """The handler of a modeled ThreadFeature (a cosmetic one is `hole.step.thread`)."""
    item, data = step.brought, step.brought_data
    what = item.get("name", "a thread")
    found = facts.read_feature(data, what, PITCHES)
    if isinstance(found, Problem):
        return refusal(found)
    spec, (origin, axis, radius, span, outward) = found.spec, found.cylinder
    internal, full, length, start = found.internal, found.full, found.length, found.start
    capped = _fit_caps(ctx, 1)
    if capped:
        return capped

    low, high = _on_axis(origin, axis, span[0]), _on_axis(origin, axis, span[1])
    ends = [low, high] if start == 0 else [high, low]
    direction = axis if start == 0 else [-c for c in axis]
    centres = follow.follow_points(ctx, item, ends, False, "faces")
    side = follow.follow_points(ctx, item, [data["faces"][0]["face_point"]], False, "faces") \
        if data["faces"][0].get("face_point") else None
    where, far = (centres if centres is not None else ends)
    _radius_moves(ctx, item, axis, where if centres is not None else None, side[0] if side else None)
    if full:
        values.handled(ctx, item, "length")
        size = _length_along(direction, where, far) if centres is not None else Quantity(span[1] - span[0])
    else:
        size = values.quantity(ctx, item, "length", length, absolute=True)
        if size.n > span[1] - span[0] + 1e-3:
            return Refusal(shared.THREAD_LONGER_THAN_FACE)
    values.pin(ctx, item, "offset", "the thread of %s starts at the end of its face" % what)
    size = _limit_length(ctx, item, spec, size, 1)
    if isinstance(size, Refusal):
        return size
    if size.n / spec.pitch > MAX_TURNS:
        return Refusal("This thread has more than %d turns." % MAX_TURNS, cause=gap_hints.THREAD_LIMITS)
    ctx.note(STARTS_NOTE)
    return StepResult.of([write(where, direction, size, spec, internal)])


# ---- the thread of a tapped hole -------------------------------------------------------------------------------

def _below(point, direction, start):
    """`point` (numbers or formulas) moved `start` (a Quantity) along the unit `direction`."""
    if not start.n and not start.sized:
        return list(point)
    out = []
    for c, d in zip(point, direction):
        out.append(as_quantity(c).plus(start.scaled(d)).json() if abs(d) > 1e-9 else c)
    return out


def _through_lengths(ctx, item, data, points, direction, full):
    """The length from each position to where its bore leaves the part (`hole.through_ends`), as Quantities, or a
    Refusal. The lengths follow the sizes only in a plain part that is as thick wherever the holes can go
    (`edges.even_sizes`). Elsewhere a size that moves a hole or the part around it can make the bore come out at
    another face (under a boss, through a second wall), so the lengths are numbers and, for a thread over the whole
    hole (`full`), those sizes are marked (`reach.hole_end_sizes`)."""
    ends = hole_facts.through_ends(data, direction)
    if isinstance(ends, Problem):
        return refusal(ends)
    if ctx.table is not None and edges.even_sizes(ctx.table, ctx.capture["items"], item, data) is None:
        names = reach_sizes.hole_end_sizes(ctx.table, ctx.capture["items"], item, data) if full else []
        if names:
            ctx.doubt(names, "the thread of %s runs through the part as thick as it is now, and a size that moves the "
                      "hole or the part around it can make the hole come out at another face"
                      % item.get("name", "a hole"))
        return [Quantity(abs(vec.dot(vec.sub(e, list(p)), direction))) for p, e in zip(data["positions"], ends)]
    followed = follow.follow_points(ctx, item, ends, False, "faces")
    ends = followed if followed is not None else ends
    return [_length_along(direction, p, e) for p, e in zip(points, ends)]


def hole_threads(ctx, item, data, spec, points, direction, depth, through, start):
    """The thread steps of a tapped hole, one per position, after the hole's own steps. `depth` is the hole's depth as
    a Quantity (None for a through hole, measured to where its bore leaves the part instead, `hole.through_ends`). `start` is where the thread starts
    below each position, as a Quantity: the bottom of a counterbore or countersink (`facts.thread_mouth`), else zero.
    A Refusal when it cannot be written."""
    capped = _fit_caps(ctx, len(points))
    if capped:
        return capped
    reach = facts.hole_depth(data, spec.minor)
    if isinstance(reach, Problem):
        return refusal(reach)
    if abs(reach.start - start.n) > 1e-6:
        return refusal(Problem("threadSpan", shared.THREAD_HOLE_SPAN, gap_hints.THREAD_HOLE))
    if through:
        sizes = _through_lengths(ctx, item, data, points, direction, reach.full)
        if isinstance(sizes, Refusal):
            return sizes
    else:
        sizes = [depth] * len(points)
    sizes = [size.plus(start.scaled(-1)) for size in sizes]
    if reach.full:
        values.handled(ctx, item, "thread.depth")
    else:
        partial = values.quantity(ctx, item, "thread.depth", reach.length, absolute=True)
        if any(partial.n > s.n + 1e-6 for s in sizes):
            return Refusal(shared.THREAD_DEEPER_THAN_HOLE)
        sizes = [partial] * len(points)
    out = []
    for point, size in zip(points, sizes):
        size = _limit_length(ctx, item, spec, size, len(points))
        if isinstance(size, Refusal):
            return size
        out.append(write(_below(point, direction, start), direction, size, spec, True))
    ctx.note(STARTS_NOTE)
    return out
