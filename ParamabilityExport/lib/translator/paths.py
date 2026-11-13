"""The path of a sweep as the recipe holds it. Pure: no Fusion imports.

`plan` takes the path record of the capture (3D curves in the target component's coordinates) and the outline that
is swept, and returns a `PathPlan` or a `Refusal`. It

- chains the curves end to end and turns the chain so it starts on the plane of the outline (a closed chain is cut
  open where it meets that plane);
- names what the path is: a `line`, an `arc`, a full `circle`, a `flat` chain (lines, arcs and free curves in one
  plane, closed or open) or a `corners` chain (lines joined by tangent arcs, in any direction);
- writes the flat and corners forms the recipe's sweep step takes (`PathPlan.recipe`), with free curves fitted by
  `spline_fit`;
- checks what the app refuses to build: a closed path that bends in 3D or is cut at a sharp corner, a path that
  crosses itself, a sharp corner it cannot mitre (between two lines of a flat path that does not twist, taper or
  keep the outline's direction, Fusion and the app mitre it), an outline that reaches past the tightest bend, a path that does not start square
  on the outline, and for an outline kept in one direction a path that turns back past the outline's plane.

A closed flat path is written with `closed: true` and no end faces. A full circle stays a circle (a revolve) unless
a twist needs the sweep step, then it is a closed flat path of two half arcs.

A line, an arc and a circle carry the numbers that an extrude or a revolve needs instead (`direction`, `axis`,
`angle_deg`); they have no `recipe` path unless `PathOptions.as_step` asks for one (a line then becomes a two point
corners path, an arc a flat path). Coordinates stay in the capture's frame: a flat path is written as its own
placement and 2D points, a corners path as 3D points that the caller moves into the recipe frame.

This module orders, orients and classifies the path. The rest of the path code is split by concern:
`path_limits` (tolerances, caps, refusal texts), `path_model` (`PathOptions`, `PathPlan`), `path_curves` (curve
geometry, chaining), `path_checks` (the app's limits as refusals), `path_writing` (arc, circle, flat and corners
forms), `path_closed` (closed chains) and `path_rebuilt` (a path read back from written numbers).
"""
from ..geometry import vec
from ..geometry.tolerances import CHAIN_TOL
from ..package.numbers import round9

from .path_checks import corners_refusal, off_square, outline_reach, rise_refusal
from .path_closed import closed_plan, half_circles
from .path_curves import (arc_of, chain, curve_length, flip, joined_lines, near, polyline, readable, tangents, turn_deg,
                          turned_round)
from .path_limits import (BOTH_SIDES, CLOSED, NOT_ONE_CHAIN, NOT_SKETCH, NOT_SQUARE, OFF_PLANE, PLANE_TOL,
                          UNKNOWN_CURVE, UNREADABLE)
from .path_model import PathOptions, PathPlan
from .path_writing import arc_plan, circle_plan, corners_plan, flat_frame, flat_plan, two_points
from .result import Refusal


def plan(path, profile_frame, profile_points, options=None):
    """The `PathPlan` of a capture path record, or a `Refusal`.

    `profile_frame` is the outline's frame (`origin` and `z`, the plane it lies in); `profile_points` are points of
    the outline in the same coordinates (3D), used to measure how far the outline reaches from the path.
    """
    try:
        return _plan(path, profile_frame, profile_points, options or PathOptions())
    except ValueError:
        return Refusal(UNREADABLE)


def _plan(path, profile_frame, profile_points, options):
    if path.get("kind") == "other":
        return Refusal(NOT_SKETCH)
    curves = path.get("curves")
    if not isinstance(curves, list) or not curves or any(not isinstance(c, dict) for c in curves):
        return Refusal(UNREADABLE)
    if any(c.get("kind") not in ("line", "arc", "circle", "other") for c in curves):
        return Refusal(UNKNOWN_CURVE)
    if any(not readable(c) for c in curves):
        return Refusal(UNREADABLE)
    ring = _circle_of(curves)
    if ring is not None:
        if options.twisted and curves[0].get("opposed") is True:
            ring = (ring[0], ring[1], vec.scale(ring[2], -1.0))
        found_ring = circle_plan(ring, curves, profile_frame, profile_points)
        if isinstance(found_ring, Refusal) or not (options.twisted or options.tapered or options.fixed):
            return found_ring
        return closed_plan(path, half_circles(found_ring), profile_frame, profile_points, options, cut=False)
    if any(c["kind"] == "circle" for c in curves):
        return Refusal(NOT_ONE_CHAIN)
    found = chain(curves)
    if found is None:
        return Refusal(NOT_ONE_CHAIN)
    ordered, closed = found
    if closed:
        if options.twisted:
            ordered = chain([flip(c) if c.get("opposed") is True else c for c in curves])[0]
        return closed_plan(path, ordered, profile_frame, profile_points, options)
    if path.get("closed"):
        return Refusal(CLOSED)
    origin, normal = profile_frame["origin"], vec.unit(profile_frame["z"])
    oriented = _toward_plane(ordered, origin, normal, profile_points)
    if isinstance(oriented, Refusal):
        return oriented
    ordered, reversed_ = oriented
    ordered = joined_lines(ordered)
    start, end = ordered[0]["start"], ordered[-1]["end"]
    direction = tangents(ordered[0])[0]
    if off_square(direction, normal):
        return Refusal(NOT_SQUARE)
    kind = _kind_of(ordered)
    base = dict(curves=ordered, start=[round9(x) for x in start], end=[round9(x) for x in end],
                direction=[round9(x) for x in direction], length=round9(sum(curve_length(c) for c in ordered)),
                reversed=reversed_)
    if options.fixed and kind != "line":
        refusal = rise_refusal(ordered, normal)
        if refusal:
            return refusal
    if kind == "line":
        recipe = two_points(start, end) if options.as_step else None
        return PathPlan(kind="line", recipe=recipe, **base)
    if kind == "arc" and not options.as_step:
        return arc_plan(base, ordered[0], profile_points)
    return _chain_plan(base, ordered, path, profile_points, options)


def _kind_of(ordered):
    if len(ordered) == 1:
        return "line" if ordered[0]["kind"] == "line" else "arc" if ordered[0]["kind"] == "arc" else "flat"
    return "chain"


def _distances(ordered, origin, normal):
    return [vec.dot(vec.sub(p, origin), normal) for c in ordered for p in polyline(c)]


def _toward_plane(ordered, origin, normal, profile_points):
    """`(chain, reversed)` with the chain starting on the plane, or a Refusal when neither end lies on it. When both
    ends do, the one the path leaves at a right angle wins; when both leave square, the one nearest the outline."""
    first = abs(vec.dot(vec.sub(ordered[0]["start"], origin), normal)) <= PLANE_TOL
    last = abs(vec.dot(vec.sub(ordered[-1]["end"], origin), normal)) <= PLANE_TOL
    if first and last:
        square_first = not off_square(tangents(ordered[0])[0], normal)
        square_last = not off_square(tangents(ordered[-1])[1], normal)
        if square_first != square_last:
            return (ordered, False) if square_first else (turned_round(ordered), True)
        if profile_points:
            mean = [sum(p[i] for p in profile_points) / len(profile_points) for i in range(3)]
            if (vec.length(vec.sub(ordered[-1]["end"], mean)) + 1e-9
                    < vec.length(vec.sub(ordered[0]["start"], mean))):
                return turned_round(ordered), True
        return ordered, False
    if first:
        return ordered, False
    if last:
        return turned_round(ordered), True
    d = _distances(ordered, origin, normal)
    if min(d) < -PLANE_TOL and max(d) > PLANE_TOL or any(abs(x) <= PLANE_TOL for x in d):
        return Refusal(BOTH_SIDES)
    return Refusal(OFF_PLANE)


def _circle_of(curves):
    """`(centre, radius, normal)` when the curves are one full circle (a circle, or arcs of one circle that close
    up), else None."""
    if len(curves) == 1 and curves[0]["kind"] == "circle":
        c = curves[0]
        return c["center"], c["radius"], vec.unit(c["normal"])
    if not all(c["kind"] == "arc" for c in curves):
        return None
    if len(curves) == 1:
        c = curves[0]
        if not near(c["start"], c["end"]) or "normal" not in c or "center" not in c:
            return None
        return c["center"], vec.length(vec.sub(c["start"], c["center"])), vec.unit(c["normal"])
    try:
        found = [arc_of(c) for c in curves]
    except ValueError:
        return None
    centre, radius, normal, _ = found[0]
    same = all(near(centre, f[0]) and abs(f[1] - radius) <= CHAIN_TOL and abs(abs(vec.dot(normal, f[2])) - 1) <= 1e-9
               for f in found)
    if not same or chain(curves) is None or not chain(curves)[1]:
        return None
    return centre, radius, normal


def _chain_plan(base, ordered, path, profile_points, options):
    junctions = [(turn_deg(tangents(a)[1], tangents(b)[0]), a["kind"] == b["kind"] == "line")
                 for a, b in zip(ordered, ordered[1:])]
    frame = flat_frame(path.get("frame"), ordered)
    if frame is None:
        return corners_plan(base, ordered, junctions, profile_points, options)
    mitres = not (options.twisted or options.tapered or options.fixed)
    refusal = corners_refusal(ordered, outline_reach(profile_points, ordered[0]["start"], frame["z"]), mitres)
    if refusal is not None:
        return refusal
    return flat_plan(base, ordered, frame, profile_points, options)
