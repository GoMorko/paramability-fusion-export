"""Holes as facts: the kind of a hole, the way it is drilled, the direction it goes and the sizes Fusion measured.

A HoleFeature stores a kind (simple, counterbore or countersink), a tap (plain, tapped or tapered tapped), a depth
(a distance, through all, or up to a face or body), a diameter, positions and a direction. The reader also measures
the cylinders and the end faces of the made hole (`side_cylinders`, `end_points`, `end_face_types`). This module
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
        return Problem("holeUnread", "This hole has no readable position or size.")
    return None


def kind_of(data):
    """The `Kind` of a hole, or a Problem for a kind that is not read or a recess the capture does not hold."""
    name = data.get("hole_type", SIMPLE)
    if name not in (SIMPLE, COUNTERBORE, COUNTERSINK):
        return Problem("holeKind", "This kind of hole is not copied yet.")
    if name == SIMPLE:
        return Kind(name, None)
    recess = data.get(name)
    if not isinstance(recess, dict) or not recess:
        return Problem("holeRecess", "This kind of hole is not copied yet.")
    return Kind(name, recess)


def tap_of(data):
    """PLAIN, TAPPED or TAPERED for the tap of a hole (a clearance hole is plain), or a Problem for another tap."""
    tap = data.get("tap_type")
    if tap in (None, "simple", "clearance"):
        return PLAIN
    if tap in (TAPPED, TAPERED):
        return tap
    return Problem("holeTap", "This kind of hole is not copied yet.")


def extent_of(data):
    """The `Extent` of a hole, or a Problem for a way to set the depth that is not read or a distance that is not
    above zero."""
    extent = data.get("extent") or {}
    kind = extent.get("kind")
    if kind not in (DISTANCE, THROUGH_ALL, TO_ENTITY):
        return Problem("holeExtent", "This way of setting the hole depth is not copied yet.")
    if kind != DISTANCE:
        return Extent(kind, None)
    depth = extent.get("depth")
    if not isinstance(depth, (int, float)) or isinstance(depth, bool) or not depth > 0:
        return Problem("holeDepth", "This hole has no depth.")
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
    """The measured diameter of the drilled bore of a tapped hole, or None. It is the widest measured cylinder that is
    not wider than the stored size: a counterbore wall is wider, and the thread's nominal size is the stored one."""
    limit = float(data["diameter"]) / 2.0 + DIAMETER_TOL
    radii = [float(c["radius"]) for c in data.get("side_cylinders") or []
             if isinstance(c, dict) and isinstance(c.get("radius"), (int, float)) and float(c["radius"]) <= limit]
    return 2.0 * max(radii) if radii else None


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
        return Problem("endUnread", "The end of this hole could not be measured.")
    if end_shape(data) != PLANE:
        return Problem("endNotFlat", "A hole that ends at a face with a drill point is not copied yet.")
    depths = [vec.dot(vec.sub(list(end), list(start)), unit) for start, end in zip(positions, ends)]
    if any(abs(d - depths[0]) > DEPTH_TOL for d in depths) or depths[0] <= 0:
        return Problem("endsDiffer", "The holes of this step end at different depths.")
    return depths[0]


def tapped_bore(data, what, pitches=None):
    """(the diameter the bore is cut at, the thread `Spec` or None) of a tapped hole, or a Problem. A cosmetic thread
    is drilled at the measured drill size and has no spec; a modeled one is cut at the thread's minor diameter."""
    if data.get("tap_type") == TAPERED:
        return Problem("taperTapped", "Tapered threads are not copied yet.", gap_hints.THREAD_PROFILE)
    modeled = data.get("thread_modeled")
    if modeled is None:
        return Problem("threadUnread", "The thread of this hole could not be read.")
    drill = drill_diameter(data)
    if not modeled:
        if drill is None:
            return Problem("drillUnread", "The drill size of this tapped hole could not be measured.")
        return drill, None
    spec = thread.hole_spec(data, what, drill, pitches)
    if isinstance(spec, Problem):
        return spec
    return spec.minor, spec
