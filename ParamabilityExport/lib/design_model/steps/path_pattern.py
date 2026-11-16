"""Path patterns (PathPatternFeature) on one straight line, one arc or one circle: the plain pattern each one equals.

A path pattern on a straight line moves each copy along the line by its distance, and a copy that turns with the path
does not turn on a line, so it is a rectangular pattern of one direction. A path pattern on an arc or a circle whose
copies turn with the path carries each copy round the centre of the arc, so it is a circular pattern about the axis of
the arc; the distance along the arc gives the angle (distance / radius). On a round path, copies that keep the
original's direction slide without a turn, which no plain pattern does. A path of another curve or of more than one
curve, and a pattern that spreads copies to both sides of its start point, are not read here.

`room` holds how far the copies can run along the path from the place where the distance is counted from (the start
point) before they pass an end of the path: toward the path's end and toward its start. On a closed path both are the
length of the path. What Fusion does with copies past an end is not known, so the outputs keep the copies within it.

`run_of` says which way the measured copies run along the path. Fusion counts the distance toward the path's end, or
toward its start when the direction is flipped; copies that run the other way show that the path was not read as
Fusion sees it. Pure.
"""
import math
from dataclasses import dataclass
from typing import Optional

from ...capture_model import gap_hints
from ...geometry import vec
from .. import words
from ..problem import Problem

# Lengths (mm) that count as the same, and the smallest radius or length read as a curve.
LENGTH_TOL_MM = 1e-4

UNREAD = Problem("pathUnread", words.PATH_PATTERN_UNREAD, gap_hints.PATH_PATTERN)
CURVE = Problem("pathCurve", words.PATH_PATTERN_CURVE, gap_hints.PATH_PATTERN)
BOTH_SIDES = Problem("pathBothSides", words.PATH_PATTERN_BOTH_SIDES, gap_hints.PATH_PATTERN)
SLIDES = Problem("pathSlides", words.PATH_PATTERN_SLIDES, gap_hints.PATH_PATTERN)


@dataclass(frozen=True)
class PathLayout:
    """A path pattern read as the plain pattern it equals.

    kind: `line` or `round` (an arc or a circle).
    direction: for a line, the unit direction from the path's start to its end.
    axis: for a round path, `{ "point": centre, "dir": unit }`, turning positively from the path's start to its end.
    radius: for a round path, its radius in mm.
    room: `(toward the end, toward the start)` in mm along the path from the start point.
    """

    kind: str
    room: tuple
    direction: Optional[list] = None
    axis: Optional[dict] = None
    radius: Optional[float] = None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(_number(c) for c in value)


def _line(curve, opposed, start):
    a, b = curve.get("start"), curve.get("end")
    if not (_point(a) and _point(b)) or vec.length(vec.sub(b, a)) <= LENGTH_TOL_MM:
        return UNREAD
    if opposed:
        a, b = b, a
    length = vec.length(vec.sub(b, a))
    return PathLayout("line", (length * (1.0 - start), length * start), direction=vec.unit(vec.sub(b, a)))


def _round(curve, opposed, start):
    centre, normal, radius = curve.get("center"), curve.get("normal"), curve.get("radius")
    if not (_point(centre) and _point(normal) and _number(radius)) or radius <= LENGTH_TOL_MM \
            or vec.length(normal) < 1e-9:
        return UNREAD
    normal = vec.unit(normal)
    if curve["kind"] == "circle":
        length = 2.0 * math.pi * radius
        room, turning = (length, length), normal
    else:
        a, mid = curve.get("start"), curve.get("mid")
        if not (_point(a) and _point(mid)):
            return UNREAD
        u, w = vec.sub(a, centre), vec.sub(mid, centre)
        side = vec.dot(normal, vec.cross(u, w))
        half = math.atan2(abs(side), vec.dot(u, w))
        if half <= 1e-9:
            return UNREAD
        # The arc runs from its start through its middle; that sense is the path's unless the path is opposed.
        turning = normal if side > 0 else vec.scale(normal, -1.0)
        length = 2.0 * half * radius
        room = (length * (1.0 - start), length * start)
    if opposed:
        turning = vec.scale(turning, -1.0)
        room = (room[1], room[0])
    return PathLayout("round", room, axis={"point": list(centre), "dir": turning}, radius=float(radius))


def layout(data):
    """The `PathLayout` of the data of a path pattern, or a `Problem`."""
    path = data.get("path")
    if not isinstance(path, dict) or not isinstance(path.get("curves"), list):
        return UNREAD
    curves = path["curves"]
    if len(curves) != 1 or not isinstance(curves[0], dict) or path.get("truncated") \
            or curves[0].get("kind") not in ("line", "arc", "circle"):
        return CURVE
    symmetric, along, start = data.get("symmetric"), data.get("along_path"), data.get("start_point")
    opposed = curves[0].get("opposed")
    if symmetric is None or not isinstance(opposed, bool) or not _number(start) or not 0.0 <= start <= 1.0:
        return UNREAD
    if symmetric:
        return BOTH_SIDES
    if curves[0]["kind"] == "line":
        return _line(curves[0], opposed, start)
    if along is None:
        return UNREAD
    if not along:
        return SLIDES
    return _round(curves[0], opposed, start)


def turn_deg(found, frame):
    """The turn in degrees, from -180 to 180, of the element `frame` about the axis of the round `PathLayout` `found`,
    positive along the path. It is read from where the frame carries a point of the circle, so a frame that is no turn
    about that axis still gives a number: the outputs check the copies against the pattern they write."""
    centre, turning = found.axis["point"], found.axis["dir"]
    ahead = vec.cross(turning, [1.0, 0.0, 0.0])
    if vec.length(ahead) < 0.5:
        ahead = vec.cross(turning, [0.0, 1.0, 0.0])
    arm = vec.scale(vec.unit(ahead), found.radius)
    moved = vec.sub(vec.frame_apply(frame, vec.add(centre, arm)), centre)
    return math.degrees(math.atan2(vec.dot(turning, vec.cross(arm, moved)), vec.dot(arm, moved)))


def run_of(found, frame):
    """Which way the copy of the element `frame` runs along the path of the `PathLayout` `found`: 1 toward the
    path's end, -1 toward its start, 0 for a copy that does not move along it or (on a round path) turns half a
    circle, which runs both ways."""
    if found.kind == "line":
        along = vec.dot(frame["origin"], found.direction)
        if abs(along) <= LENGTH_TOL_MM:
            return 0
    else:
        along = turn_deg(found, frame)
        if abs(along) <= 1e-6 or abs(abs(along) - 180.0) <= 1e-6:
            return 0
    return 1 if along > 0 else -1
