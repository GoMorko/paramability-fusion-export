"""A planned path written as the recipe holds it: one arc, a full circle, a flat path of 2D segments (free curves
fitted by `spline_fit`) and a 3D corners path, each with the limit checks that apply to it. Pure."""
import math

from ..package.numbers import round9

from . import spline_fit, vec
from .path_checks import (carried_reach_refusal, off_square, outline_reach, overlap_refusal, reach_refusal, seam_turn,
                          self_touch)
from .path_curves import arc_of, near, polyline, round_point, round_point2, tangents
from .path_limits import (BENDS_3D, CHAIN_TOL, CLOSED_NOT_SMOOTH, CORNER_MATCH_TOL, CROSSES, CURVATURE_SAMPLES,
                          LINE_BEND_RADIUS, MAX_POINTS, MAX_SEGMENTS, MAX_TURN_DEG, NOT_SQUARE, OFF_PLANE, PLANE_TOL,
                          SHARP_CORNER, SMOOTH_JOIN_DEG, STRAIGHT_DEG, TOO_COMPLEX, TOO_MANY)
from .path_model import PathPlan
from .result import Refusal


def arc_plan(base, curve, profile_points):
    centre, radius, normal, turn = arc_of(curve)
    refusal = reach_refusal(profile_points, curve["start"], normal, radius)
    if refusal:
        return refusal
    return PathPlan(kind="arc", axis={"point": round_point(centre), "dir": round_point(normal)}, radius=round9(radius),
                    angle_deg=round9(math.degrees(turn)), **base)


def circle_plan(ring, curves, profile_frame, profile_points):
    """A full circle: it starts where it meets the plane of the outline nearest to the outline."""
    centre, radius, normal = ring
    origin, plane = profile_frame["origin"], vec.unit(profile_frame["z"])
    u = vec.unit(vec.cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0]))
    v = vec.cross(normal, u)
    a, b = radius * vec.dot(plane, u), radius * vec.dot(plane, v)
    d = vec.dot(plane, vec.sub(origin, centre))
    size = math.hypot(a, b)
    if size <= 1e-12:
        return Refusal(NOT_SQUARE)
    if abs(d) > size + PLANE_TOL:
        return Refusal(OFF_PLANE)
    spread = math.acos(max(-1.0, min(1.0, d / size)))
    angles = [math.atan2(b, a) + spread, math.atan2(b, a) - spread]
    points = [vec.add(centre, vec.add(vec.scale(u, radius * math.cos(t)), vec.scale(v, radius * math.sin(t))))
              for t in angles]
    mean = [sum(p[i] for p in profile_points) / len(profile_points) for i in range(3)] if profile_points else origin
    at = min(range(2), key=lambda k: vec.length(vec.sub(points[k], mean)))
    start = points[at]
    direction = vec.unit(vec.cross(normal, vec.sub(start, centre)))
    if off_square(direction, plane):
        return Refusal(NOT_SQUARE)
    refusal = reach_refusal(profile_points, start, normal, radius)
    if refusal:
        return refusal
    return PathPlan(kind="circle", curves=curves, start=round_point(start), end=round_point(start),
                    direction=round_point(direction), length=round9(2 * math.pi * radius),
                    axis={"point": round_point(centre), "dir": round_point(normal)}, radius=round9(radius),
                    angle_deg=360.0)


def two_points(start, end):
    """A straight path as the corners path of its two ends."""
    return {"kind": "corners", "points": [round_point(start), round_point(end)], "bendRadius": LINE_BEND_RADIUS}


def flat_frame(given, ordered):
    """The frame of the plane all the chain's points lie in (the sketch's own when it fits), or None."""
    points = [p for c in ordered for p in polyline(c)]
    if isinstance(given, dict) and all(k in given for k in ("origin", "x", "z")):
        z = vec.unit(given["z"])
        if all(abs(vec.dot(vec.sub(p, given["origin"]), z)) <= PLANE_TOL for p in points):
            x = vec.unit(given["x"])
            return {"origin": list(given["origin"]), "x": x, "y": vec.cross(z, x), "z": z}
    a = points[0]
    b = max(points, key=lambda p: vec.length(vec.sub(p, a)))
    ab = vec.sub(b, a)
    if vec.length(ab) <= PLANE_TOL:
        return None
    x = vec.unit(ab)

    def off_line(p):
        d = vec.sub(p, a)
        return vec.length(vec.sub(d, vec.scale(x, vec.dot(d, x))))

    c = max(points, key=off_line)
    if off_line(c) <= PLANE_TOL:
        return None
    z = vec.unit(vec.cross(ab, vec.sub(c, a)))
    if any(abs(vec.dot(vec.sub(p, a), z)) > PLANE_TOL for p in points):
        return None
    return {"origin": list(a), "x": x, "y": vec.cross(z, x), "z": z}


def flat_plan(base, ordered, frame, profile_points, options, closed=False):
    def local(p):
        d = vec.sub(p, frame["origin"])
        return [vec.dot(d, frame["x"]), vec.dot(d, frame["y"])]

    segments, tightest = [], math.inf
    at = local(ordered[0]["start"])
    for number, curve in enumerate(ordered):
        end = local(ordered[0]["start"] if closed and number == len(ordered) - 1 else curve["end"])
        if curve["kind"] == "line":
            segments.append({"kind": "line", "to": round_point2(end)})
        elif curve["kind"] == "arc":
            segments.append({"kind": "arc", "through": round_point2(local(curve["mid"])), "to": round_point2(end)})
            tightest = min(tightest, arc_of(curve)[1])
        else:
            drawn = _spline_segments([local(p) for p in curve["samples"]], at, end)
            if drawn is None:
                return Refusal(TOO_COMPLEX)
            segments.extend(drawn)
            tightest = min(tightest, _spline_radius(at, drawn))
        at = end
    if len(segments) > MAX_SEGMENTS:
        return Refusal(TOO_MANY)
    if closed and seam_turn(local(ordered[0]["start"]), segments) > SMOOTH_JOIN_DEG:
        return Refusal(CLOSED_NOT_SMOOTH)
    points = [p for c in ordered for p in polyline(c)]
    if self_touch(points, closed):
        return Refusal(CROSSES)
    if not options.fixed:
        start = ordered[0]["start"]
        across = [0.0, 0.0, 0.0] if options.twisted else frame["z"]
        extra = options.growth * base["length"]
        refusal = reach_refusal(profile_points, start, across, tightest, extra)
        if refusal:
            return refusal
        refusal = overlap_refusal(points, outline_reach(profile_points, start, across) + extra, closed)
        if refusal:
            return refusal
    recipe = {
        "kind": "flat",
        "on": {"origin": round_point(frame["origin"]), "normal": round_point(frame["z"]),
               "xDir": round_point(frame["x"])},
        "start": round_point2(local(ordered[0]["start"])),
        "segments": segments,
    }
    if not closed:
        return PathPlan(kind="flat", recipe=recipe, tightest=tightest, **base)
    recipe["closed"] = True
    outline = [local(p) for p in points]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(outline, outline[1:] + outline[:1]))
    return PathPlan(kind="flat", recipe=recipe, tightest=tightest, closed=True, winding=1 if area > 0 else -1, **base)


def _spline_segments(samples, start, end):
    """Segments through the points `spline_fit` takes from the 2D `samples`; the ends are the curve's own."""
    pieces = spline_fit.fit(samples)
    if pieces is None:
        return None
    pieces[0][0], pieces[-1][-1] = list(start), list(end)
    return [{"kind": "spline", "through": [round_point2(p) for p in piece[1:-1]], "to": round_point2(piece[-1])}
            if len(piece) > 2 else {"kind": "line", "to": round_point2(piece[-1])} for piece in pieces]


def _spline_radius(at, segments):
    """Tightest bend (mm) of the app's curve through the written spline segments, as the app reads it."""
    tightest, here = math.inf, at
    for seg in segments:
        if seg["kind"] == "spline":
            curve = spline_fit.interpolate([here] + seg["through"] + [seg["to"]])
            for k in range(CURVATURE_SAMPLES):
                u = k / (CURVATURE_SAMPLES - 1)
                (vx, vy), (ax, ay) = curve.at(u, 1), curve.at(u, 2)
                speed = math.hypot(vx, vy)
                if speed > 0 and abs(vx * ay - vy * ax) > 0:
                    tightest = min(tightest, speed ** 3 / abs(vx * ay - vy * ax))
        here = seg["to"]
    return tightest


def corners_plan(base, ordered, junctions, profile_points, options):
    """Lines joined by tangent arcs, written as corner points: each line extended to where its neighbours cross it."""
    if any(turn > STRAIGHT_DEG and both_lines for turn, both_lines in junctions):
        return Refusal(SHARP_CORNER)
    kinds = [c["kind"] for c in ordered]
    if (kinds[0] != "line" or kinds[-1] != "line" or "other" in kinds or any(turn > STRAIGHT_DEG for turn, _ in junctions)
            or any(a == b == "arc" for a, b in zip(kinds, kinds[1:]))):
        return Refusal(BENDS_3D)
    points, radii, turns = [ordered[0]["start"]], [], []
    for before, arc, after in zip(ordered, ordered[1:], ordered[2:]):
        if arc["kind"] != "arc":
            continue
        _, radius, _, turn = arc_of(arc)
        if math.degrees(turn) > MAX_TURN_DEG:
            return Refusal(BENDS_3D)
        d_in, d_out = tangents(before)[1], tangents(after)[0]
        tangent = radius * math.tan(turn / 2)
        corner = vec.add(arc["start"], vec.scale(d_in, tangent))
        if not near(corner, vec.sub(arc["end"], vec.scale(d_out, tangent)), CORNER_MATCH_TOL):
            return Refusal(BENDS_3D)
        points.append(corner)
        radii.append(radius)
        turns.append((vec.unit(vec.cross(d_in, d_out)), turn))
    points.append(ordered[-1]["end"])
    if len(points) > MAX_POINTS:
        return Refusal(TOO_MANY)
    if self_touch([p for c in ordered for p in polyline(c)]):
        return Refusal(CROSSES)
    start = ordered[0]["start"]
    if not options.fixed:
        extra = options.growth * base["length"]
        refusal = carried_reach_refusal(profile_points, start, radii, turns, options.twisted, extra)
        if refusal:
            return refusal
        refusal = overlap_refusal([p for c in ordered for p in polyline(c)],
                                   max((vec.length(vec.sub(p, start)) for p in profile_points or ()), default=0.0)
                                   + extra)
        if refusal:
            return refusal
    recipe = {
        "kind": "corners",
        "points": [round_point(p) for p in points],
        "bendRadius": round9(radii[0]) if max(radii) - min(radii) <= CHAIN_TOL else [round9(r) for r in radii],
    }
    return PathPlan(kind="corners", recipe=recipe, tightest=min(radii), **base)
