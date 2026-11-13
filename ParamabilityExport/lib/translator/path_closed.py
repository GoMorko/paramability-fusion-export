"""Closed sweep paths: a closed chain cut open where it meets the outline's plane, then written as a closed flat
path. A full circle that has to be a sweep step becomes two half arcs. Pure."""
import math

from ..package.numbers import round9

from . import vec
from .path_checks import off_square
from .path_curves import arc_of, curve_length, joined_lines, polyline, round_point, tangents, turn_deg
from .path_limits import (CLOSED_3D, CLOSED_AT_CORNER, CLOSED_PARALLEL, CLOSED_TAPER, NOT_SQUARE, OFF_PLANE, PLANE_TOL,
                          SHARP_CORNER, SMOOTH_JOIN_DEG, STRAIGHT_DEG)
from .path_writing import flat_frame, flat_plan
from .result import Refusal


def half_circles(ring):
    """A full circle plan as two half arcs, starting at the plan's start."""
    centre, normal = ring.axis["point"], ring.axis["dir"]
    at = [vec.rotate(ring.start, normal, deg, centre) for deg in (90, 180, 270)]
    return [dict(kind="arc", start=list(ring.start), mid=at[0], end=at[1], center=list(centre), normal=list(normal)),
            dict(kind="arc", start=at[1], mid=at[2], end=list(ring.start), center=list(centre), normal=list(normal))]


def closed_plan(path, ordered, profile_frame, profile_points, options, cut=True):
    """A closed chain as a closed flat path starting where the chain meets the outline's plane. `cut` is false for a
    chain that already starts there."""
    if options.tapered:
        return Refusal(CLOSED_TAPER)
    if options.fixed:
        return Refusal(CLOSED_PARALLEL)
    ordered = joined_lines(ordered)
    frame = flat_frame(path.get("frame"), ordered)
    if frame is None:
        return Refusal(CLOSED_3D)
    origin, normal = profile_frame["origin"], vec.unit(profile_frame["z"])
    if cut:
        ordered = _cut_at_plane(ordered, origin, normal, profile_points)
        if isinstance(ordered, Refusal):
            return ordered
    junctions = [(turn_deg(tangents(a)[1], tangents(b)[0]), a["kind"] == b["kind"] == "line")
                 for a, b in zip(ordered, ordered[1:] + ordered[:1])]
    seam = junctions.pop()
    if seam[0] > (STRAIGHT_DEG if seam[1] else SMOOTH_JOIN_DEG):
        return Refusal(CLOSED_AT_CORNER)
    if any(turn > (STRAIGHT_DEG if both_lines else SMOOTH_JOIN_DEG) for turn, both_lines in junctions):
        return Refusal(SHARP_CORNER)
    start = ordered[0]["start"]
    direction = tangents(ordered[0])[0]
    if off_square(direction, normal):
        return Refusal(NOT_SQUARE)
    base = dict(curves=ordered, start=round_point(start), end=round_point(start), direction=round_point(direction),
                length=round9(sum(curve_length(c) for c in ordered)))
    return flat_plan(base, ordered, frame, profile_points, options, closed=True)


def _cut_at_plane(ordered, origin, normal, profile_points):
    """The closed chain turned (and one curve split) so it starts where it meets the outline's plane nearest to the
    outline, or a Refusal when it never meets the plane."""
    found = _plane_crossings(ordered, origin, normal)
    if not found:
        return Refusal(OFF_PLANE)
    mean = [sum(p[i] for p in profile_points) / len(profile_points) for i in range(3)] if profile_points else origin
    index, at, fraction, point = min(found, key=lambda c: vec.length(vec.sub(c[3], mean)))
    if at == 0 and fraction == 0.0:
        return ordered[index:] + ordered[:index]
    before, after = _split(ordered[index], at, fraction, point)
    return [after] + ordered[index + 1:] + ordered[:index] + [before]


def _plane_crossings(ordered, origin, normal):
    """Where a closed chain meets a plane, as `(curve index, sample index, fraction, point)`. A crossing at a joint
    is the start of the curve after it (sample 0, fraction 0); one inside a curve has the fraction of the way from
    the sample (a line's two points, a free curve's samples) or, for an arc, along its turn."""
    found, count = [], len(ordered)

    def add(entry):
        if not any(e[0] == entry[0] and e[1] == entry[1] and abs(e[2] - entry[2]) <= 1e-9 for e in found):
            found.append(entry)

    for i, curve in enumerate(ordered):
        if curve["kind"] == "arc":
            for place, point, fraction in _arc_crossings(curve, origin, normal):
                add({"start": (i, 0, 0.0, point), "end": ((i + 1) % count, 0, 0.0, point)}.get(place)
                    or (i, 0, fraction, point))
            continue
        points = polyline(curve)
        d = [vec.dot(vec.sub(p, origin), normal) for p in points]
        for k in range(len(points) - 1):
            if abs(d[k]) <= PLANE_TOL:
                add((i, k, 0.0, points[k]))
            elif d[k] * d[k + 1] < 0 and abs(d[k + 1]) > PLANE_TOL:
                t = d[k] / (d[k] - d[k + 1])
                add((i, k, t, vec.add(points[k], vec.scale(vec.sub(points[k + 1], points[k]), t))))
        if abs(d[-1]) <= PLANE_TOL:
            add(((i + 1) % count, 0, 0.0, points[-1]))
    return found


def _arc_crossings(curve, origin, normal):
    """The places an arc meets a plane as `("start" | "end" | "inside", point, fraction of its turn)`."""
    centre, radius, axis, turn = arc_of(curve)
    u = vec.unit(vec.sub(curve["start"], centre))
    v = vec.cross(axis, u)
    a, b = radius * vec.dot(u, normal), radius * vec.dot(v, normal)
    height = vec.dot(vec.sub(centre, origin), normal)
    size = math.hypot(a, b)
    if size <= 1e-12 or abs(height) > size + PLANE_TOL:
        return []
    spread = math.acos(max(-1.0, min(1.0, -height / size)))
    tol = PLANE_TOL / radius
    out = []
    for angle in sorted({(math.atan2(b, a) + sign * spread) % (2 * math.pi) for sign in (1, -1)}):
        angle = 0.0 if angle > 2 * math.pi - tol else angle
        point = vec.add(centre, vec.add(vec.scale(u, radius * math.cos(angle)), vec.scale(v, radius * math.sin(angle))))
        if angle <= tol:
            out.append(("start", list(curve["start"]), 0.0))
        elif abs(angle - turn) <= tol:
            out.append(("end", list(curve["end"]), 1.0))
        elif angle < turn:
            out.append(("inside", point, angle / turn))
    return out


def _split(curve, at, fraction, point):
    """A curve cut in two at `point`."""
    point = list(point)
    kind = curve["kind"]
    if kind == "line":
        return dict(curve, end=point), dict(curve, start=point)
    if kind == "arc":
        centre, _, axis, turn = arc_of(curve)
        angle = math.degrees(turn * fraction)

        def at_deg(deg):
            return vec.rotate(curve["start"], axis, deg, centre)

        return (dict(curve, mid=at_deg(angle / 2), end=point),
                dict(curve, start=point, mid=at_deg((angle + math.degrees(turn)) / 2)))
    samples = [list(p) for p in curve["samples"]]
    if fraction > 0:
        first, second = samples[:at + 1] + [point], [point] + samples[at + 1:]
    else:
        first, second = samples[:at + 1], samples[at:]
    return dict(curve, samples=first, end=point, tangent_end=None), dict(curve, samples=second, start=point,
                                                                         tangent_start=None)
