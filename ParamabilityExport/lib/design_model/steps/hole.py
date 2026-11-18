"""Holes as facts: the kind of a hole, the way it is drilled, the direction it goes and the sizes Fusion measured.

A HoleFeature stores a kind (simple, counterbore or countersink), a tap (plain, tapped or tapered tapped), a depth
(a distance, through all, or up to a face or body), a diameter, positions and a direction. The reader also measures
the cylinders of the made hole with where each starts and ends (`side_cylinders`), and its flat or pointed end faces
(`end_points`, `end_face_types`). This module
reads those without a destination. Where the stored and the measured values disagree, the measured ones win and the
reader says so as a fact (`Direction.flipped`, `size_differs`).

A reader returns its record, or a `Problem` when the hole cannot be read. How a destination cuts the hole, places it
on a sketch or follows sizes is not here. The thread of a tapped hole is in `steps/thread.py`.
"""
from typing import NamedTuple

from ...capture_model import gap_hints
from ...geometry import vec
from ..problem import Problem
from . import thread
from .. import words

SIMPLE, COUNTERBORE, COUNTERSINK = "simple", "counterbore", "countersink"
PLAIN, TAPPED, TAPERED = "plain", "tapped", "taperTapped"
DISTANCE, THROUGH_ALL, TO_ENTITY = "distance", "throughAll", "toEntity"
CONE, PLANE, MIXED = "cone", "plane", "mixed"
# A measured end counts as behind its position when it is further back than this along the direction, mm.
BEHIND_TOL = 1e-3
# How far a measured cylinder may differ from the stored diameter, mm.
DIAMETER_TOL = 1e-3
# Measured depths of the holes of one step agree within this, mm.
DEPTH_TOL = 1e-4
# A measured cylinder is on a hole's axis line when its axis is along the hole within this (1 less the cosine) and
# its origin within this distance of the line, mm.
AXIS_TOL = 1e-6
LINE_TOL = 1e-3


class Kind(NamedTuple):
    """The kind of a hole and its recess: `name` is SIMPLE, COUNTERBORE or COUNTERSINK; `recess` is the counterbore or
    countersink record of the capture, None for a simple hole."""

    name: str
    recess: object


class Extent(NamedTuple):
    """How deep a hole goes: `kind` is DISTANCE, THROUGH_ALL or TO_ENTITY; `depth` is the distance in mm, None for
    the other two."""

    kind: str
    depth: object


class Direction(NamedTuple):
    """The unit direction of a hole into the material. `flipped` is True when it is the stored direction turned round
    because a measured end of the hole lies behind its position."""

    unit: list
    flipped: bool


def placed(data):
    """A Problem when the hole has no readable position, direction or diameter, else None."""
    direction, positions, diameter = data.get("direction"), data.get("positions"), data.get("diameter")
    if not (isinstance(direction, (list, tuple)) and positions and isinstance(diameter, (int, float))
            and not isinstance(diameter, bool) and diameter > 0):
        return Problem("holeUnread", words.HOLE_UNREAD)
    return None


def kind_of(data):
    """The `Kind` of a hole, or a Problem for a kind that is not read or a recess the capture does not hold."""
    name = data.get("hole_type", SIMPLE)
    if name not in (SIMPLE, COUNTERBORE, COUNTERSINK):
        return Problem("holeKind", words.HOLE_KIND)
    if name == SIMPLE:
        return Kind(name, None)
    recess = data.get(name)
    if not isinstance(recess, dict) or not recess:
        return Problem("holeRecess", words.HOLE_KIND)
    return Kind(name, recess)


def tap_of(data):
    """PLAIN, TAPPED or TAPERED for the tap of a hole (a clearance hole is plain), or a Problem for another tap."""
    tap = data.get("tap_type")
    if tap in (None, "simple", "clearance"):
        return PLAIN
    if tap in (TAPPED, TAPERED):
        return tap
    return Problem("holeTap", words.HOLE_KIND)


def extent_of(data):
    """The `Extent` of a hole, or a Problem for a way to set the depth that is not read or a distance that is not
    above zero."""
    extent = data.get("extent") or {}
    kind = extent.get("kind")
    if kind not in (DISTANCE, THROUGH_ALL, TO_ENTITY):
        return Problem("holeExtent", words.HOLE_EXTENT)
    if kind == TO_ENTITY and "offset" in extent:
        # An offset of the face or plane is not followed: only the end measured on the part is.
        offset = extent["offset"]
        if not _number(offset) or abs(offset) > DEPTH_TOL:
            return Problem("holeOffset", words.HOLE_TO_OFFSET)
    if kind != DISTANCE:
        return Extent(kind, None)
    depth = extent.get("depth")
    if not isinstance(depth, (int, float)) or isinstance(depth, bool) or not depth > 0:
        return Problem("holeDepth", words.HOLE_NO_DEPTH)
    return Extent(kind, float(depth))


def _ends(data):
    return [e for e in data.get("end_points") or [] if isinstance(e, (list, tuple))]


def direction_of(data):
    """The `Direction` of a hole (`placed` is None). The stored direction is turned round when a measured end lies
    behind the position it belongs to."""
    unit = vec.unit(list(data["direction"]))
    positions = data["positions"]
    for at, end in enumerate(_ends(data)):
        start = positions[min(at, len(positions) - 1)]
        if vec.dot(vec.sub(list(end), list(start)), unit) < -BEHIND_TOL:
            return Direction(vec.scale(unit, -1.0), True)
    return Direction(unit, False)


def drill_diameter(data):
    """The measured diameter of the drilled bore of a tapped hole, or None: the narrowest measured cylinder (a
    counterbore wall is wider). Fusion drills a tapped hole at the thread's minor diameter, which can be wider than
    the stored size, so the stored size does not limit it."""
    radii = [float(c["radius"]) for c in data.get("side_cylinders") or []
             if isinstance(c, dict) and _number(c.get("radius")) and c["radius"] > 0]
    return 2.0 * min(radii) if radii else None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _exit_depth(cylinders, position, unit):
    """How far along `unit` from `position` the farthest end of the measured cylinders on the hole's axis line lies,
    or None when none of them has a measured span."""
    far = None
    for c in cylinders:
        origin, axis, span = c.get("origin"), c.get("axis"), c.get("span")
        if not (isinstance(origin, (list, tuple)) and isinstance(axis, (list, tuple)) and isinstance(span, (list, tuple))
                and len(span) == 2 and all(_number(s) for s in span) and vec.length(axis) > 0):
            continue
        axis = vec.unit(list(axis))
        off = vec.sub(list(origin), list(position))
        if abs(abs(vec.dot(axis, unit)) - 1.0) > AXIS_TOL \
                or vec.length(vec.sub(off, vec.scale(unit, vec.dot(off, unit)))) > LINE_TOL:
            continue
        for s in span:
            depth = vec.dot(vec.add(off, vec.scale(axis, float(s))), unit)
            far = depth if far is None else max(far, depth)
    return far


def bore_exits(data, unit):
    """The points where the bores of a hole leave the part, one per position, or None when a position has no measured
    cylinder with a span on its axis line. Each is the farthest end, along the hole's direction `unit`, of the
    measured side cylinders on that hole's axis line (`side_cylinders` with their `span`). Fusion's end faces do not
    say it: a hole through all has no bottom, and Fusion lists the faces of a modeled thread among them."""
    cylinders = [c for c in data.get("side_cylinders") or [] if isinstance(c, dict)]
    depths = [_exit_depth(cylinders, p, unit) for p in data["positions"]]
    if any(d is None or d <= DEPTH_TOL for d in depths):
        return None
    return [vec.add(list(p), vec.scale(unit, d)) for p, d in zip(data["positions"], depths)]


def through_ends(data, unit):
    """The points where the bores of a tapped hole through all leave the part, one per position (`bore_exits`), or a
    Problem. The faces of the modeled thread (`made_span`, depths below the first position) must be measured and must
    reach as deep as the deepest bore when the thread runs the whole hole, within a pitch and half a millimetre."""
    positions = data["positions"]
    ends = bore_exits(data, unit)
    if ends is None:
        return Problem("endsUnread", words.THREAD_HOLE_ENDS_UNREAD, gap_hints.THREAD_HOLE)
    info = data.get("thread") or {}
    made = info.get("made_span")
    if data.get("thread_modeled"):
        if not (isinstance(made, (list, tuple)) and len(made) == 2):
            return Problem("endsUnread", words.THREAD_HOLE_ENDS_UNREAD, gap_hints.THREAD_HOLE)
        deepest = max(vec.dot(vec.sub(e, list(positions[0])), unit) for e in ends)
        if info.get("full_length") is True and abs(made[1] - deepest) > float(info.get("pitch") or 0.0) + 0.5:
            return Problem("threadSpan", words.THREAD_HOLE_SPAN, gap_hints.THREAD_HOLE)
    return ends


def size_differs(data, count, diameter):
    """True when the measured cylinders of a hole disagree with its `diameter` or with the number of holes (`count`).
    A counterbore wall is not counted. False when nothing was measured."""
    cylinders = [c for c in data.get("side_cylinders") or [] if isinstance(c, dict)]
    if not cylinders:
        return False
    bore = data.get("counterbore")
    if bore:
        cylinders = [c for c in cylinders if abs(2 * c["radius"] - bore["diameter"]) > DIAMETER_TOL] or cylinders
    return len(cylinders) != count or any(abs(2 * c["radius"] - diameter) > DIAMETER_TOL for c in cylinders)


def end_shape(data):
    """The measured shape of the end of a hole: CONE for a drill point, PLANE for a flat end, MIXED when both, None
    when it was not measured."""
    measured = set(data.get("end_face_types") or [])
    if not measured:
        return None
    if measured == {CONE}:
        return CONE
    if measured == {PLANE}:
        return PLANE
    return MIXED


def reach_depth(data, unit):
    """The measured depth of a hole that ends at a face or body, in mm along `unit`, or a Problem. The hole must have
    a measured flat end for each position, and all of them at the same depth."""
    positions, ends = data["positions"], _ends(data)
    if len(ends) != len(positions):
        return Problem("endUnread", words.HOLE_END_UNREAD)
    if end_shape(data) != PLANE:
        return Problem("endNotFlat", words.HOLE_DRILL_POINT)
    depths = [vec.dot(vec.sub(list(end), list(start)), unit) for start, end in zip(positions, ends)]
    if any(abs(d - depths[0]) > DEPTH_TOL for d in depths) or depths[0] <= 0:
        return Problem("endsDiffer", words.HOLE_ENDS_DIFFER)
    return depths[0]


def tapped_bore(data, what, pitches=None):
    """(the diameter the bore is cut at, the thread `Spec` or None) of a tapped hole, or a Problem. A cosmetic thread
    is drilled at the measured drill size and has no spec; a modeled one is cut at the thread's minor diameter."""
    if data.get("tap_type") == TAPERED:
        return Problem("taperTapped", words.THREAD_TAPERED, gap_hints.THREAD_PROFILE)
    modeled = data.get("thread_modeled")
    if modeled is None:
        return Problem("threadUnread", words.HOLE_THREAD_UNREAD)
    drill = drill_diameter(data)
    if not modeled:
        if drill is None:
            return Problem("drillUnread", words.HOLE_DRILL_UNREAD)
        minor = (data.get("thread") or {}).get("minor_diameter")
        if _number(minor) and abs(drill - minor) > thread.DIAMETER_TOL:
            return Problem("holeSize", words.THREAD_HOLE_MISMATCH % what)
        return drill, None
    spec = thread.hole_spec(data, what, drill, pitches)
    if isinstance(spec, Problem):
        return spec
    return spec.minor, spec
