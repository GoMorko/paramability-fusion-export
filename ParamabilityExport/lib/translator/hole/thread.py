"""Modeled threads as recipe `thread` steps: a ThreadFeature on a cylinder face, and the thread of a tapped hole.

The recipe thread is a 60 degree form with a pitch, a major and a minor diameter, a hand and a length. Fusion's metric
and Unified profiles are that form; other profiles, tapered threads and anything over the recipe's caps are refused
(a gap with a hint). The numbers come from Fusion's thread info, and every one of them can be missing: the thread is
then left out, never guessed. The thread diameter is checked against the cylinder it sits on, which also catches a
unit mix-up in the read.

A ThreadFeature starts at the end of its cylinder face and runs the full face, or the set length from the end the
made thread touches. The start and the length follow the sizes that move the cylinder's end faces
(`faces/follow.py`); a size that changes the cylinder's diameter is marked, since a thread fits one diameter.
"""
from ...capture_model import gap_hints
from ...geometry import vec
from .. import values
from ..faces import follow
from ..faces.slabs import as_quantity
from ..ranges import range_check
from ..result import Refusal, StepResult
from ..step_walk import all_steps
from .. import turn_budget
from ..values import Quantity

# The recipe's thread caps (feature-recipe caps.ts): threads per recipe, turns in all, pitch range in mm.
MAX_THREADS = 8
MAX_TURNS = turn_budget.MAX_TURNS_TOTAL
MIN_PITCH, MAX_PITCH = 0.2, 10.0
FORM_ANGLE_DEG = 60.0
ANGLE_TOL_DEG = 0.01
# How far the thread diameter may differ from the cylinder it sits on, mm.
DIAMETER_TOL = 0.3
END_TOL = 0.01
# Profile names that are not the 60 degree form (matched in lower case), and the ones that are.
OTHER_PROFILES = ("acme", "trapez", "whitworth", "bsp", "npt", "pipe", "buttress", "british", "dryseal", "square",
                  "tapered", "taper")
FORM_PROFILES = ("metric", "unified")
STARTS_NOTE = "The thread starts at a standard angle, not where Fusion starts it."


class Spec:
    """The numbers of one thread: pitch, major and minor diameter in mm, and the hand."""

    def __init__(self, pitch, major, minor, right):
        self.pitch, self.major, self.minor, self.right = pitch, major, minor, right


def _profile(info, what):
    """A Refusal when the thread profile is not the 60 degree form or cannot be told, else None."""
    name = (info.get("thread_type") or "").lower()
    angle = info.get("angle_deg")
    if angle is not None and abs(angle - FORM_ANGLE_DEG) > ANGLE_TOL_DEG:
        return Refusal("A thread that is not a 60 degree thread is not copied yet.", cause=gap_hints.THREAD_PROFILE)
    if not name:
        return Refusal("The kind of thread of %s could not be read." % what)
    if any(word in name for word in OTHER_PROFILES) or not any(word in name for word in FORM_PROFILES):
        return Refusal("Only metric and Unified threads are copied, not %s." % (info.get("thread_type") or name),
                       cause=gap_hints.THREAD_PROFILE)
    return None


def spec_of(info, what, major=None, minor=None):
    """The `Spec` of a thread info record, or a Refusal. `major` and `minor` fill a diameter the info lacks."""
    problem = _profile(info, what)
    if problem:
        return problem
    pitch = info.get("pitch")
    major = info.get("major_diameter") or major
    minor = info.get("minor_diameter") or minor
    right = info.get("right_hand")
    if not (pitch and major and minor) or right is None:
        return Refusal("The size or hand of the thread of %s could not be read." % what)
    if not (MIN_PITCH <= pitch <= MAX_PITCH):
        return Refusal("A thread pitch of %g mm is not copied (0.2 to 10 mm)." % pitch, cause=gap_hints.THREAD_LIMITS)
    if not (0 < minor < major) or (major - minor) / 2.0 < 0.05 * pitch:
        return Refusal("The thread of %s has no usable depth." % what)
    return Spec(float(pitch), float(major), float(minor), bool(right))


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
    if not spec.right:
        step["hand"] = "left"
    return step


# ---- ThreadFeature ---------------------------------------------------------------------------------------------

def _cylinder(data):
    """(origin, unit axis, radius, [low, high] span, outward) of the one cylinder the faces make, or a Refusal."""
    faces = data.get("faces") or []
    if not faces or any(f.get("surface") != "Cylinder" for f in faces):
        return Refusal("A thread on a face that is not a cylinder is not copied yet.", cause=gap_hints.THREAD_PROFILE)
    first = faces[0]
    if not (first.get("origin") and first.get("axis") and first.get("radius")):
        return Refusal("The cylinder of this thread could not be read.")
    origin, axis, radius = first["origin"], vec.unit(first["axis"]), float(first["radius"])
    spans = []
    for face in faces:
        parallel = face.get("axis") and abs(abs(vec.dot(vec.unit(face["axis"]), axis)) - 1.0) < 1e-6
        off = vec.sub(face["origin"], origin) if face.get("origin") else None
        on_line = off is not None and vec.length(vec.sub(off, vec.scale(axis, vec.dot(off, axis)))) < 1e-3
        if not (parallel and on_line and abs(float(face.get("radius") or 0) - radius) < 1e-4 and face.get("span")):
            return Refusal("The faces of this thread are not one cylinder.")
        shift = vec.dot(off, axis)
        flip = vec.dot(vec.unit(face["axis"]), axis) < 0
        low, high = (-face["span"][1], -face["span"][0]) if flip else face["span"]
        spans.append((low + shift, high + shift))
    spans.sort()
    reach = spans[0][1]
    for low, high in spans[1:]:
        if low > reach + 1e-3:
            return Refusal("The faces of this thread do not touch each other.")
        reach = max(reach, high)
    outward = {f.get("outward") for f in faces}
    return origin, axis, radius, (spans[0][0], reach), (outward.pop() if len(outward) == 1 else None)


def _on_axis(origin, axis, t):
    return [round(origin[i] + axis[i] * t, 6) + 0.0 for i in range(3)]


def _is_full(data, span, length):
    """True for a thread over the whole face. Fusion's own flag wins; without it the set length decides."""
    full = data.get("full_length")
    if full is None and length is not None:
        full = abs(length - (span[1] - span[0])) <= 1e-3
    return full


def _start_end(data, span, pitch, full):
    """`0` when the thread starts at the low end of the span, `1` at the high end, or a Refusal. A full length thread
    starts at the low end; a partial one at the end the faces it made touch."""
    if full:
        return 0
    made = data.get("made_span")
    if not made:
        return Refusal("Where the thread over part of the length starts could not be read.")
    low, high = abs(made[0] - span[0]), abs(span[1] - made[1])
    reach = pitch + 0.5
    if low <= reach and low + END_TOL < high:
        return 0
    if high <= reach and high + END_TOL < low:
        return 1
    return Refusal("Where the thread over part of the length starts could not be told.")


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


def feature(item, ctx):
    """The handler of a modeled ThreadFeature (a cosmetic one is `hole.step.thread`)."""
    data = item.get("data") or {}
    what = item.get("name", "a thread")
    spec = spec_of(data, what)
    if isinstance(spec, Refusal):
        return spec
    cylinder = _cylinder(data)
    if isinstance(cylinder, Refusal):
        return cylinder
    origin, axis, radius, span, outward = cylinder
    internal = data.get("internal")
    if internal is None and outward is not None:
        internal = not outward
    if internal is None or (outward is not None and internal == outward):
        return Refusal("It could not be told whether this thread is inside or outside.")
    if abs(2.0 * radius - (spec.minor if internal else spec.major)) > DIAMETER_TOL:
        return Refusal("The size of this thread does not match its cylinder.")
    offset, length = data.get("offset"), data.get("length")
    if offset is None or abs(offset) > 1e-6:
        return Refusal("A thread that starts away from the end of its face is not copied yet.")
    full = _is_full(data, span, length)
    if full is None:
        return Refusal("How long this thread runs could not be read.")
    start = _start_end(data, span, spec.pitch, full)
    if isinstance(start, Refusal):
        return start
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
            return Refusal("The thread is longer than its face.")
    values.pin(ctx, item, "offset", "the thread of %s starts at the end of its face" % what)
    size = _limit_length(ctx, item, spec, size, 1)
    if isinstance(size, Refusal):
        return size
    if size.n / spec.pitch > MAX_TURNS:
        return Refusal("This thread has more than %d turns." % MAX_TURNS, cause=gap_hints.THREAD_LIMITS)
    ctx.note(STARTS_NOTE)
    return StepResult.of([write(where, direction, size, spec, internal)])


# ---- the thread of a tapped hole -------------------------------------------------------------------------------

def hole_spec(data, ctx, item, drill):
    """The `Spec` of the modeled thread of a tapped hole (`drill` is the measured bore diameter or None), or a
    Refusal. The hole is cut at the thread's minor diameter, `spec.minor`."""
    info = data.get("thread") or {}
    what = item.get("name", "a hole")
    spec = spec_of(info, what, major=data.get("diameter"), minor=drill)
    if isinstance(spec, Refusal):
        return spec
    if drill is not None and abs(drill - spec.minor) > DIAMETER_TOL:
        return Refusal("The thread size of %s does not match the hole that was measured." % what)
    return spec


def hole_threads(ctx, item, data, spec, points, direction, depth, through):
    """The thread steps of a tapped hole, one per position, after the hole's own steps. `depth` is the hole's depth as
    a Quantity (None for a through hole, measured from the end faces instead). A Refusal when it cannot be written."""
    info = data.get("thread") or {}
    capped = _fit_caps(ctx, len(points))
    if capped:
        return capped
    if through:
        ends = data.get("end_points") or []
        if len(ends) != len(points):
            return Refusal("The depth of this threaded hole could not be measured.")
        followed = follow.follow_points(ctx, item, ends, False, "faces")
        ends = followed if followed is not None else ends
        sizes = [_length_along(direction, p, e) for p, e in zip(points, ends)]
    else:
        sizes = [depth] * len(points)
    full = info.get("full_length")
    if full is True:
        values.handled(ctx, item, "thread.depth")
    elif full is False and info.get("depth"):
        partial = values.quantity(ctx, item, "thread.depth", float(info["depth"]), absolute=True)
        if any(partial.n > s.n + 1e-6 for s in sizes):
            return Refusal("The thread is deeper than its hole.")
        sizes = [partial] * len(points)
    else:
        return Refusal("How deep the thread of this hole runs could not be read.")
    out = []
    for point, size in zip(points, sizes):
        size = _limit_length(ctx, item, spec, size, len(points))
        if isinstance(size, Refusal):
            return size
        out.append(write(point, direction, size, spec, True))
    ctx.note(STARTS_NOTE)
    return out
