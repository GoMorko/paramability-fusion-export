"""Threads as facts: the numbers of a thread, the cylinder it sits on and where it starts.

Two Fusion items make a modeled thread: a ThreadFeature on the cylinder faces of a body, and the thread of a tapped
hole. This module reads both without a destination: the 60 degree form with its pitch, major and minor diameter and
hand (`spec_of`), the one cylinder that the faces make (`cylinder`), whether the thread is inside or outside it, how
far it runs and at which end it starts (`read_feature`), and the depth of the thread of a tapped hole (`hole_spec`,
`hole_depth`; where a hole through all comes out is `hole.through_ends`).

Every number of Fusion's thread info can be missing: a reader then gives a `Problem` and never a guess. Metric and
Unified threads are the 60 degree form; other profiles and tapered threads are a `Problem` with the cause
`THREAD_PROFILE`. A pitch outside the range a destination passes is a `Problem` with the cause `THREAD_LIMITS`. How a
destination cuts, limits or follows the thread is not here.
"""
import math
from typing import NamedTuple

from ...capture_model import gap_hints
from ...geometry import vec
from ..problem import Problem
from .. import words

FORM_ANGLE_DEG = 60.0
ANGLE_TOL_DEG = 0.01
# How far the thread diameter may differ from the cylinder it sits on, mm. A larger gap is also a unit mix-up.
DIAMETER_TOL = 0.3
END_TOL = 0.01
# Profile names that are not the 60 degree form (matched in lower case), and the ones that are.
OTHER_PROFILES = ("acme", "trapez", "whitworth", "bsp", "npt", "pipe", "buttress", "british", "dryseal", "square",
                  "tapered", "taper")
FORM_PROFILES = ("metric", "unified")
# A face of a ThreadFeature starts a thread at its end: this is the offset from that end that counts as none.
OFFSET_TOL = 1e-6


class Spec(NamedTuple):
    """The numbers of one thread: pitch, major and minor diameter in mm, and the hand."""

    pitch: float
    major: float
    minor: float
    right: bool


class Cylinder(NamedTuple):
    """The one cylinder the faces of a thread make: a point on its axis, the unit axis, the radius, the (low, high)
    span along the axis from that point, and `outward` (True when the material is inside the cylinder, None when the
    faces disagree or do not say)."""

    origin: list
    axis: list
    radius: float
    span: tuple
    outward: object


class Feature(NamedTuple):
    """What a ThreadFeature says about its thread: its `spec`, the `cylinder`, `internal` (the thread is cut into a
    hole), `full` (it runs the whole face), the set `length` (None when not set), and `start` (0 at the low end of the
    cylinder's span, 1 at the high end)."""

    spec: Spec
    cylinder: Cylinder
    internal: bool
    full: bool
    length: object
    start: int


class Depth(NamedTuple):
    """How deep the thread of a tapped hole runs: the whole hole (`full`), or `length` mm from where it starts.
    `start` is how far below the hole's position the thread starts (mm along the hole's direction, `thread_mouth`)."""

    full: bool
    length: object
    start: float = 0.0


def _profile(info, what):
    """A Problem when the thread profile is not the 60 degree form or cannot be told, else None."""
    name = (info.get("thread_type") or "").lower()
    angle = info.get("angle_deg")
    if angle is not None and abs(angle - FORM_ANGLE_DEG) > ANGLE_TOL_DEG:
        return Problem("threadProfile", words.THREAD_PROFILE, gap_hints.THREAD_PROFILE)
    if not name:
        return Problem("threadUnread", words.THREAD_KIND_UNREAD % what)
    if any(word in name for word in OTHER_PROFILES) or not any(word in name for word in FORM_PROFILES):
        return Problem("threadProfile", words.THREAD_FAMILY % (info.get("thread_type") or name),
                       gap_hints.THREAD_PROFILE)
    return None


def spec_of(info, what, major=None, minor=None, pitches=None):
    """The `Spec` of a thread info record, or a Problem. `major` and `minor` fill a diameter the info lacks.
    `pitches` is the (low, high) pitch in mm a destination copies, or None for any."""
    problem = _profile(info, what)
    if problem:
        return problem
    pitch = info.get("pitch")
    major = info.get("major_diameter") or major
    minor = info.get("minor_diameter") or minor
    right = info.get("right_hand")
    if not (pitch and major and minor) or right is None:
        return Problem("threadUnread", words.THREAD_SIZE_UNREAD % what)
    if pitches is not None and not (pitches[0] <= pitch <= pitches[1]):
        return Problem("pitch", words.THREAD_PITCH % (pitch, *pitches), gap_hints.THREAD_LIMITS)
    if not (0 < minor < major) or (major - minor) / 2.0 < 0.05 * pitch:
        return Problem("threadDepth", words.THREAD_NO_DEPTH % what)
    return Spec(float(pitch), float(major), float(minor), bool(right))


def cylinder(data):
    """The `Cylinder` of the faces of a ThreadFeature, or a Problem: a face that is not a cylinder, a face of another
    component, faces that are not one cylinder, or faces that do not touch each other."""
    faces = data.get("faces") or []
    if not faces or any(f.get("surface") != "Cylinder" for f in faces):
        return Problem("notCylinder", words.THREAD_NOT_CYLINDER, gap_hints.THREAD_PROFILE)
    if any(f.get("foreign") for f in faces):
        return Problem("foreignFace", words.THREAD_OTHER_COMPONENT, gap_hints.OTHER_COMPONENT)
    first = faces[0]
    if not (first.get("origin") and first.get("axis") and first.get("radius")):
        return Problem("cylinderUnread", words.THREAD_CYLINDER_UNREAD)
    origin, axis, radius = [float(c) for c in first["origin"]], vec.unit(first["axis"]), float(first["radius"])
    spans = []
    for face in faces:
        parallel = face.get("axis") and abs(abs(vec.dot(vec.unit(face["axis"]), axis)) - 1.0) < 1e-6
        off = vec.sub(face["origin"], origin) if face.get("origin") else None
        on_line = off is not None and vec.length(vec.sub(off, vec.scale(axis, vec.dot(off, axis)))) < 1e-3
        if not (parallel and on_line and abs(float(face.get("radius") or 0) - radius) < 1e-4 and face.get("span")):
            return Problem("notOneCylinder", words.THREAD_NOT_ONE_CYLINDER)
        shift = vec.dot(off, axis)
        low, high = face["span"]
        if vec.dot(vec.unit(face["axis"]), axis) < 0:
            low, high = -high, -low
        spans.append((low + shift, high + shift))
    spans.sort()
    reach = spans[0][1]
    for low, high in spans[1:]:
        if low > reach + 1e-3:
            return Problem("facesApart", words.THREAD_FACES_APART)
        reach = max(reach, high)
    outward = {f.get("outward") for f in faces}
    return Cylinder(origin, axis, radius, (spans[0][0], reach), outward.pop() if len(outward) == 1 else None)


def is_full(data, span, length):
    """True for a thread over the whole face, False for part of it, None when that cannot be told. Fusion's own flag
    wins; without it the set length decides."""
    full = data.get("full_length")
    if full is None and length is not None:
        full = abs(length - (span[1] - span[0])) <= 1e-3
    return full


def start_end(data, span, pitch, full):
    """0 when the thread starts at the low end of the span, 1 at the high end, or a Problem. A full length thread
    starts at the low end; a partial one at the end the faces it made touch. The faces a full length thread made,
    when measured, must reach both ends."""
    made = data.get("made_span")
    reach = pitch + 0.5
    if full:
        if made and (abs(made[0] - span[0]) > reach or abs(span[1] - made[1]) > reach):
            return Problem("startUnclear", words.THREAD_START_UNCLEAR)
        return 0
    if not made:
        return Problem("startUnread", words.THREAD_START_UNREAD)
    low, high = abs(made[0] - span[0]), abs(span[1] - made[1])
    if low <= reach and low + END_TOL < high:
        return 0
    if high <= reach and high + END_TOL < low:
        return 1
    return Problem("startUnclear", words.THREAD_START_UNCLEAR)


def read_feature(data, what, pitches=None):
    """The `Feature` of a modeled ThreadFeature (its capture `data`, `what` the step name), or the first Problem."""
    spec = spec_of(data, what, pitches=pitches)
    if isinstance(spec, Problem):
        return spec
    found = cylinder(data)
    if isinstance(found, Problem):
        return found
    internal = data.get("internal")
    if internal is None and found.outward is not None:
        internal = not found.outward
    if internal is None or (found.outward is not None and internal == found.outward):
        return Problem("insideOrOutside", words.THREAD_SIDE_UNREAD)
    if abs(2.0 * found.radius - (spec.minor if internal else spec.major)) > DIAMETER_TOL:
        return Problem("cylinderSize", words.THREAD_SIZE_MISMATCH)
    offset, length = data.get("offset"), data.get("length")
    full = is_full(data, found.span, length)
    if full is None:
        return Problem("lengthUnread", words.THREAD_LENGTH_UNREAD)
    # Fusion uses the offset only for a thread that is not full length, and may give none for a full one.
    if not full and (offset is None or abs(offset) > OFFSET_TOL):
        return Problem("offset", words.THREAD_OFFSET)
    start = start_end(data, found.span, spec.pitch, full)
    if isinstance(start, Problem):
        return start
    return Feature(spec, found, bool(internal), bool(full), length, start)


# ---- the thread of a tapped hole -------------------------------------------------------------------------------

def hole_spec(data, what, drill, pitches=None):
    """The `Spec` of the modeled thread of a tapped hole, or a Problem. `drill` is the measured bore diameter or None.
    The hole is cut at the thread's minor diameter, `spec.minor`."""
    spec = spec_of(data.get("thread") or {}, what, major=data.get("diameter"), minor=drill, pitches=pitches)
    if isinstance(spec, Problem):
        return spec
    if drill is not None and abs(drill - spec.minor) > DIAMETER_TOL:
        return Problem("holeSize", words.THREAD_HOLE_MISMATCH % what)
    return spec


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def thread_mouth(data, bore):
    """How far below its position (mm along its direction) the thread of a tapped hole starts, or None when the
    recess does not read: 0 for a simple hole, the depth of a counterbore, or for a countersink the depth where its
    cone narrows to the drilled bore (`bore`, its diameter). The recess is wider than the thread, so the thread cannot
    start above it."""
    name = data.get("hole_type", "simple")
    if name == "simple":
        return 0.0
    recess = data.get(name)
    if not isinstance(recess, dict):
        return None
    if name == "counterbore":
        depth = recess.get("depth")
        return float(depth) if _number(depth) and depth > 0 else None
    if name == "countersink":
        wide, angle = recess.get("diameter"), recess.get("angle_deg")
        if not (_number(wide) and _number(angle) and _number(bore) and 0 < angle < 180 and wide > bore > 0):
            return None
        return (wide - bore) / 2.0 / math.tan(math.radians(angle) / 2.0)
    return None


def hole_depth(data, bore=None):
    """The `Depth` of the thread of a tapped hole, or a Problem when Fusion's info does not say. The thread starts at
    the bottom of a counterbore or countersink (`thread_mouth`, with `bore` the drilled diameter), else at the top of
    the hole. The measured faces of the thread (`made_span`, depths below the hole's position) must start there, and a
    thread over part of the hole must end its length below there; a thread over part of the hole without them is a
    Problem."""
    info = data.get("thread") or {}
    full = info.get("full_length")
    made = info.get("made_span")
    reach = float(info.get("pitch") or 0.0) + 0.5
    start = thread_mouth(data, bore)
    if start is None or (made and abs(made[0] - start) > reach):
        return Problem("threadSpan", words.THREAD_HOLE_SPAN, gap_hints.THREAD_HOLE)
    if full is True:
        return Depth(True, None, start)
    if full is False and info.get("depth"):
        depth = float(info["depth"])
        if not made or abs(made[1] - start - depth) > reach:
            return Problem("threadSpan", words.THREAD_HOLE_SPAN, gap_hints.THREAD_HOLE)
        return Depth(False, depth, start)
    return Problem("depthUnread", words.THREAD_DEPTH_UNREAD, gap_hints.THREAD_HOLE)
