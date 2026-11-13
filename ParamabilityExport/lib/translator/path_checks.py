"""Limits the app puts on a sweep path, as refusals: a path touching itself, two parts too close, an outline
reaching past a bend, a sharp corner it cannot mitre, a path that stops rising, and the turn at a closed path's seam.
Pure."""
import math

from ..capture_model import gap_hints
from ..geometry import vec
from . import spline_fit
from .path_curves import arc_of, curve_length, polyline, tangents, turn_deg
from .path_limits import (CORNER_TOO_TIGHT, MAX_MITRE_DEG, MAX_OVERLAP_SAMPLES, MIN_RISE, OVERLAP, OVERLAP_CLEAR_SHARE, OVERLAP_CORNER_DEG,
                          OVERLAP_MAX_CORNER_DEG, OVERLAP_STEP_SHARE, REACH_SHARE, SHARP_CORNER, SMOOTH_JOIN_DEG,
                          SQUARE_TOL_DEG, STRAIGHT_DEG, TOUCH_TOL, TURNS_BACK)
from .result import Refusal


def off_square(direction, normal):
    """True when the path direction is more than `SQUARE_TOL_DEG` away from the outline's normal."""
    return math.degrees(math.asin(min(1.0, vec.length(vec.cross(direction, normal))))) > SQUARE_TOL_DEG


def _directions(curve):
    """Unit directions of travel along a curve: the tangent at the ends and at every arc sample, and between the samples
    of a free curve (its end tangents replace the first and last)."""
    kind = curve["kind"]
    if kind == "arc":
        centre, _, normal, _ = arc_of(curve)
        return [vec.unit(vec.cross(normal, vec.sub(p, centre))) for p in polyline(curve)]
    first, last = tangents(curve)
    if kind == "line":
        return [first, last]
    points = polyline(curve)
    steps = [vec.unit(vec.sub(b, a)) for a, b in zip(points, points[1:]) if vec.length(vec.sub(b, a)) > 1e-12]
    return [first] + steps + [last]


def rise_refusal(ordered, normal):
    """A Refusal when the path stops moving along the outline's normal (facing the way the path leaves), which an
    outline kept in one direction needs it to do at every point. The tangent is tested, as the app does."""
    first = tangents(ordered[0])[0]
    facing = normal if vec.dot(normal, first) >= 0 else vec.scale(normal, -1.0)
    for curve in ordered:
        if any(vec.dot(d, facing) < MIN_RISE for d in _directions(curve)):
            return Refusal(TURNS_BACK)
    return None


def seam_turn(start, segments):
    """Degrees the direction of travel turns where the last written 2D segment meets the first, as the app reads the
    segments."""
    def curve(at, segment):
        a, b = [at[0], at[1], 0.0], [segment["to"][0], segment["to"][1], 0.0]
        if segment["kind"] == "arc":
            return dict(kind="arc", start=a, mid=[segment["through"][0], segment["through"][1], 0.0], end=b)
        return dict(kind="line", start=a, end=b)

    def directions(at, segment):
        if segment["kind"] != "spline":
            return tangents(curve(at, segment))
        fitted = spline_fit.interpolate([at] + segment["through"] + [segment["to"]])
        return tuple(vec.unit([*fitted.at(u, 1), 0.0]) for u in (0.0, 1.0))

    before = segments[-2]["to"] if len(segments) > 1 else start
    return turn_deg(directions(before, segments[-1])[1], directions(start, segments[0])[0])


def sharp_corner(before, after):
    """`(turn in degrees, both lines)` where `before` meets `after` when the join is a sharp corner, else None."""
    turn, both_lines = turn_deg(tangents(before)[1], tangents(after)[0]), before["kind"] == after["kind"] == "line"
    return (turn, both_lines) if turn > (STRAIGHT_DEG if both_lines else SMOOTH_JOIN_DEG) else None


def corners_refusal(ordered, reach, mitres, closed=False):
    """A Refusal for a sharp corner of the chain the app cannot build. A corner between two lines is mitred when
    `mitres` is true: it may not turn back past `MAX_MITRE_DEG`, and its mitre takes the outline's `reach` across the
    path's plane times tan(turn / 2) of straight path on both sides, so a line between two corners needs room for
    both mitres. Any other sharp corner is refused. On a closed chain the last curve meets the first."""
    count = len(ordered)
    pairs = [((i - 1) % count, i) for i in range(count)] if closed else [(i, i + 1) for i in range(count - 1)]
    needs = [0.0] * count
    for before, after in pairs:
        found = sharp_corner(ordered[before], ordered[after])
        if found is None:
            continue
        turn, both_lines = found
        if not (mitres and both_lines) or turn > MAX_MITRE_DEG:
            return Refusal(SHARP_CORNER, cause=gap_hints.SHARP_CORNER)
        need = reach * math.tan(math.radians(turn) / 2.0)
        needs[before] += need
        needs[after] += need
    for curve, need in zip(ordered, needs):
        length = curve_length(curve)
        if need > 0 and length < need:
            return Refusal(CORNER_TOO_TIGHT % (need, length))
    return None


def outline_reach(profile_points, start, normal):
    """How far the outline reaches from the path start across the plane whose unit `normal` is taken out."""
    reach = 0.0
    for p in profile_points or ():
        d = vec.sub(p, start)
        reach = max(reach, vec.length(vec.sub(d, vec.scale(normal, vec.dot(d, normal)))))
    return reach


def reach_refusal(profile_points, start, normal, radius, extra=0.0):
    """A Refusal when the outline (grown by `extra`) reaches across the path's plane as far as the tightest bend's
    radius."""
    if not profile_points or radius == math.inf:
        return None
    return bend_refusal(outline_reach(profile_points, start, normal) + extra, radius)


def axis_reach_refusal(profile_points, start, centre, radius):
    """A Refusal when the outline reaches the axis of an arc or circle path. Only the reach toward the centre counts:
    an outline on the outer side of the arc can be as wide as it likes, since a revolve about the axis builds it."""
    if not profile_points:
        return None
    toward = vec.unit(vec.sub(centre, start))
    return bend_refusal(max(vec.dot(vec.sub(p, start), toward) for p in profile_points), radius)


def bend_refusal(reach, radius):
    """A Refusal when an outline reaching `reach` from the path reaches the centre of a bend of `radius`."""
    if radius != math.inf and reach >= radius * REACH_SHARE:
        return Refusal("The outline reaches %.2f mm from the path, but the path bends in a radius of %.2f mm."
                       % (reach, radius))
    return None


def carried_reach_refusal(profile_points, start, radii, turns, twisted=False, extra=0.0):
    """The outline is carried along the bends, turning with each; at a bend only the part of a point's offset in
    that bend's plane counts against its radius. A twisting outline counts with its whole radius."""
    if not profile_points:
        return None
    carried = [vec.sub(p, start) for p in profile_points]
    for radius, (axis, turn) in zip(radii, turns):
        reach = max(vec.length(o if twisted else vec.sub(o, vec.scale(axis, vec.dot(o, axis)))) for o in carried)
        reach += extra
        if reach >= radius * REACH_SHARE:
            return Refusal("The outline reaches %.2f mm from the path, but the path bends in a radius of %.2f mm."
                           % (reach, radius))
        carried = [vec.rotate(o, axis, math.degrees(turn)) for o in carried]
    return None


def overlap_refusal(points, reach, closed=False):
    """A Refusal when two parts of the path that are far apart along it pass closer than twice the outline's reach:
    the swept shape would run into itself. Pairs on the two arms of one corner are left to the corner's mitre. On a
    closed path (the last point is the first) the distance along it runs the short way round."""
    points = _distinct(points)
    if not reach > 0 or len(points) < 3:
        return None
    total = sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))
    step = max(reach * OVERLAP_STEP_SHARE, total / MAX_OVERLAP_SAMPLES)
    samples, corners, along = [(points[0], 0.0)], [], 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        span = vec.length(vec.sub(b, a))
        parts = max(1, int(math.ceil(span / step)))
        for k in range(1, parts + 1):
            samples.append((vec.add(a, vec.scale(vec.sub(b, a), k / parts)), along + span * k / parts))
        along += span
        if i + 1 < len(points):
            turn = turn_deg(vec.unit(vec.sub(b, a)), vec.unit(vec.sub(points[i + 1], b)))
            if turn > OVERLAP_CORNER_DEG:
                corners.append((along, math.tan(math.radians(min(turn, OVERLAP_MAX_CORNER_DEG)) / 2)))
    apart, needed = math.pi * reach, 2 * reach * OVERLAP_CLEAR_SHARE
    if closed:
        corners += [(at + total, fold) for at, fold in corners]

    def covered(low, high):
        for at, fold in corners:
            mitre = 2 * reach * max(1.0, fold)
            if low < at < high and at - low <= mitre and high - at <= mitre:
                return True
        return False

    cells = {}
    for n, (point, _) in enumerate(samples):
        cells.setdefault(tuple(int(math.floor(c / needed)) for c in point), []).append(n)
    for i, (point, at) in enumerate(samples):
        cell = tuple(int(math.floor(c / needed)) for c in point)
        near = sorted(j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                      for j in cells.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()) if j > i)
        for j in near:
            direct = samples[j][1] - at
            if min(direct, total - direct if closed else direct) <= apart:
                continue
            gap = vec.length(vec.sub(point, samples[j][0]))
            if gap < needed and not covered(at, samples[j][1]) and not (closed and covered(samples[j][1], at + total)):
                return Refusal(OVERLAP % (gap, reach))
    return None


def _distinct(points):
    """The points without repeats of the one before."""
    out = [points[0]]
    for p in points[1:]:
        if vec.length(vec.sub(p, out[-1])) > 1e-9:
            out.append(p)
    return out


def _thinned(points):
    """The points without those closer than a few touch distances to the one before, keeping the last."""
    step = 3 * TOUCH_TOL
    out = [points[0]]
    for p in points[1:]:
        if vec.length(vec.sub(p, out[-1])) > step:
            out.append(p)
        elif len(out) > 1:
            out[-1] = p
        else:
            out.append(p)
    return out


def self_touch(points, closed=False):
    """True when two parts of the polyline that are not neighbours cross or come within `TOUCH_TOL`. On a closed
    polyline the first and last parts are neighbours."""
    points = _thinned(points)
    segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    lows = [min(a[0], b[0]) for a, b in segments]
    highs = [max(a[0], b[0]) for a, b in segments]
    order = sorted(range(len(segments)), key=lambda i: lows[i])
    for n, i in enumerate(order):
        for j in order[n + 1:]:
            if lows[j] > highs[i] + TOUCH_TOL:
                break
            neighbours = abs(i - j) <= 1 or (closed and abs(i - j) == len(segments) - 1)
            if not neighbours and _segment_gap(*segments[i], *segments[j]) <= TOUCH_TOL:
                return True
    return False


def _segment_gap(p1, q1, p2, q2):
    """Smallest distance between segments p1-q1 and p2-q2."""
    d1, d2, r = vec.sub(q1, p1), vec.sub(q2, p2), vec.sub(p1, p2)
    a, e, f = vec.dot(d1, d1), vec.dot(d2, d2), vec.dot(d2, r)
    c, b = vec.dot(d1, r), vec.dot(d1, d2)
    denom = a * e - b * b
    s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom > 1e-18 else 0.0
    t = (b * s + f) / e if e > 1e-18 else 0.0
    if t < 0.0:
        t, s = 0.0, min(1.0, max(0.0, -c / a)) if a > 1e-18 else 0.0
    elif t > 1.0:
        t, s = 1.0, min(1.0, max(0.0, (b - c) / a)) if a > 1e-18 else 0.0
    near1, near2 = vec.add(p1, vec.scale(d1, s)), vec.add(p2, vec.scale(d2, t))
    return vec.length(vec.sub(near1, near2))
