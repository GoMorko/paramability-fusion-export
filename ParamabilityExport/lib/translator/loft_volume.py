"""The volume of a ruled loft between two parallel outlines made of straight lines, with the corners paired the way
the app's kernel pairs them. A new body Fusion made with another pairing has another volume. Pure."""
import math

from ..geometry import vec
from .sweep_limits import VOLUME_ABSOLUTE_TOL, VOLUME_RELATIVE_TOL
from .sweep_outline import loop_polygon

PARALLEL_TOL = 1e-6
TIE_TOL = 1e-9   # start shifts whose cost differs by less than this share of the best one pair the same way


def _ring(profile):
    """The corners of the outline's one loop in the part's coordinates, or None when the outline is not a single loop
    of straight lines."""
    loops = profile.get("loops") or []
    if len(loops) != 1 or not loops[0].get("outer"):
        return None
    curves = loops[0].get("curves") or []
    if len(curves) < 3 or any(curve.get("kind") != "line" for curve in curves):
        return None
    points = loop_polygon(curves)
    if not points or len(points) < 3:
        return None
    return [vec.frame_apply(profile["frame"], [u, v, 0.0]) for u, v in points]


def _mean(points):
    return [sum(p[i] for p in points) / len(points) for i in range(3)]


def _area(points, frame):
    """The signed area of a ring seen along the normal of `frame` (counter clockwise is positive)."""
    flat = [(vec.dot(vec.sub(p, frame["origin"]), frame["x"]), vec.dot(vec.sub(p, frame["origin"]), frame["y"]))
            for p in points]
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(flat, flat[1:] + flat[:1])) / 2.0


def _wound(points, frame, heading):
    """The ring running counter clockwise about the loft's heading, keeping its first corner first."""
    counter = vec.dot(frame["z"], heading) >= 0
    return points if (_area(points, frame) > 0) == counter else [points[0]] + points[:0:-1]


def _shifts(first, second):
    """The shifts of `second` (corner `i + shift` meets corner `i` of `first`) that lie closest together, each ring
    taken about its own centre."""
    a = [vec.sub(p, _mean(first)) for p in first]
    b = [vec.sub(p, _mean(second)) for p in second]
    n = len(a)
    costs = [sum(vec.length(vec.sub(b[(i + s) % n], a[i])) ** 2 for i in range(n)) for s in range(n)]
    best = min(costs)
    return [s for s, cost in enumerate(costs) if cost <= best + TIE_TOL * max(best, 1.0)]


def ruled_volumes(profiles):
    """The volumes the kernel's ruled loft between two outlines of straight lines has, one for each pairing it may
    choose, or None when that is not known: outlines of other curves, with openings, of different corner counts, or
    in planes that are not parallel."""
    if len(profiles) != 2:
        return None
    rings = [_ring(p) for p in profiles]
    if any(r is None for r in rings) or len(rings[0]) != len(rings[1]):
        return None
    frames = [p["frame"] for p in profiles]
    if vec.length(vec.cross(vec.unit(frames[0]["z"]), vec.unit(frames[1]["z"]))) > PARALLEL_TOL:
        return None
    base = {"origin": frames[0]["origin"], "x": vec.unit(frames[0]["x"]), "y": vec.unit(frames[0]["y"]),
            "z": vec.unit(frames[0]["z"])}
    heading = vec.sub(_mean(rings[1]), _mean(rings[0]))
    height = abs(vec.dot(heading, base["z"]))
    if height <= PARALLEL_TOL:
        return None
    heading = vec.unit(heading)
    first, second = (_wound(r, f, heading) for r, f in zip(rings, frames))
    n = len(first)
    ends = abs(_area(first, base)) + abs(_area(second, base))
    volumes = []
    for shift in _shifts(first, second):
        middle = [vec.scale(vec.add(first[i], second[(i + shift) % n]), 0.5) for i in range(n)]
        volumes.append(height / 6.0 * (ends + 4.0 * abs(_area(middle, base))))
    return volumes


def matches(volumes, made):
    """True when the measured volume `made` is one of the candidate `volumes`."""
    return any(abs(made - v) <= VOLUME_RELATIVE_TOL * v + VOLUME_ABSOLUTE_TOL for v in volumes)
