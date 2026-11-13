"""Where the outline of a sweep stands along its path, for picks on the sweep's faces. Pure geometry.

The outline is square to the path where it starts. Along a path in one plane it turns with the path, about the
plane's normal; an outline kept in one direction (`fixed`) does not turn. Both ways the outline at the path's end is
the outline at its start moved by one rigid move, so `end_frame` is exact. A path that leaves one plane, a twist or a
taper (the outline turns or shrinks) is not known closely enough: nothing is returned then.

`SideWalk` finds where a point on a side wall sits in the outline's own coordinates: it follows the outline along a
path of lines and tangent arcs in one plane (the outline turns about each arc's axis). Any other path has no walk.
"""
import math

from ..geometry import vec
from . import path_curves, path_limits

PLANE_TOL = 1e-3
LATERAL_TOL = 1e-3
JOIN_TOL_DEG = path_limits.SMOOTH_JOIN_DEG


def _same(v):
    return list(v)


def _plane_normal(points):
    """The unit normal of the plane all `points` lie in, None when they run in one straight line, and False when they
    do not lie in one plane."""
    first = points[0]
    far = max(points, key=lambda p: vec.length(vec.sub(p, first)))
    along = vec.sub(far, first)
    if vec.length(along) <= PLANE_TOL:
        return None
    line = vec.unit(along)

    def off_line(p):
        d = vec.sub(p, first)
        return vec.length(vec.sub(d, vec.scale(line, vec.dot(d, line))))

    apart = max(points, key=off_line)
    if off_line(apart) <= PLANE_TOL:
        return None
    normal = vec.unit(vec.cross(along, vec.sub(apart, first)))
    return normal if all(abs(vec.dot(vec.sub(p, first), normal)) <= PLANE_TOL for p in points) else False


def _carry(found, fixed):
    """The map of directions that moves the outline from the path's start to its end, or None when it is not known."""
    if fixed:
        return _same
    normal = _plane_normal(path_curves.points_along(found.curves))
    if normal is False:
        return None
    start, end = found.direction, path_curves.tangents(found.curves[-1])[1]
    if normal is None:
        return _same if vec.dot(start, end) > 0 else None
    degrees = math.degrees(math.atan2(vec.dot(vec.cross(start, end), normal), vec.dot(start, end)))
    return lambda v: vec.rotate(v, normal, degrees)


def end_frame(frame, found, fixed=False):
    """The outline's frame carried to the path's end (`found` is the path_model.PathPlan the sweep is written from),
    or None when that is not known."""
    carry = _carry(found, fixed)
    if carry is None:
        return None
    origin = vec.add(found.end, carry(vec.sub(frame["origin"], found.start)))
    return {"origin": origin, "x": carry(frame["x"]), "y": carry(frame["y"]), "z": carry(frame["z"])}


class SideWalk:
    """The outline's frame at each part of a path of lines and tangent arcs in one plane."""

    def __init__(self, frame, found, parts):
        self.at_start = vec.frame_to_local(frame, found.start)[:2]
        self.parts = parts

    @classmethod
    def of(cls, frame, found):
        """The walk along `found`, or None when the path is not lines and arcs that run on smoothly in one plane."""
        curves = found.curves
        if any(curve["kind"] not in ("line", "arc") for curve in curves):
            return None
        if _plane_normal(path_curves.points_along(curves)) is False:
            return None
        x, y, parts, last = list(frame["x"]), list(frame["y"]), [], None
        for curve in curves:
            first, end = path_curves.tangents(curve)
            if last is not None:
                axis = vec.cross(last, first)
                degrees = math.degrees(math.atan2(vec.length(axis), vec.dot(last, first)))
                if degrees > JOIN_TOL_DEG:
                    return None
                if vec.length(axis) > 1e-12:
                    x, y = vec.rotate(x, axis, degrees), vec.rotate(y, axis, degrees)
            parts.append((curve, x, y))
            if curve["kind"] == "arc":
                _, _, normal, turn = path_curves.arc_of(curve)
                x, y = vec.rotate(x, normal, math.degrees(turn)), vec.rotate(y, normal, math.degrees(turn))
            last = end
        return cls(frame, found, parts)

    def sections(self, p):
        """Where `p` sits in the outline's coordinates when seen across the path: one place for each part of the path
        that `p` can lie across."""
        out = []
        for curve, x, y in self.parts:
            found = self._across_line(curve, x, y, p) if curve["kind"] == "line" else self._across_arc(curve, x, y, p)
            if found is not None:
                out.append([self.at_start[0] + found[0], self.at_start[1] + found[1]])
        return out

    @staticmethod
    def _across_line(curve, x, y, p):
        start, end = curve["start"], curve["end"]
        run = vec.sub(end, start)
        size = vec.length(run)
        direction = vec.scale(run, 1.0 / size)
        along = vec.dot(vec.sub(p, start), direction)
        if not -LATERAL_TOL <= along <= size + LATERAL_TOL:
            return None
        off = vec.sub(p, vec.add(start, vec.scale(direction, along)))
        return vec.dot(off, x), vec.dot(off, y)

    @staticmethod
    def _across_arc(curve, x, y, p):
        centre, radius, normal, turn = path_curves.arc_of(curve)
        radial = vec.sub(p, centre)
        radial = vec.sub(radial, vec.scale(normal, vec.dot(radial, normal)))
        if vec.length(radial) <= 1e-9:
            return None
        first = vec.sub(curve["start"], centre)
        angle = math.atan2(vec.dot(vec.cross(first, radial), normal), vec.dot(first, radial)) % (2 * math.pi)
        if angle > turn + LATERAL_TOL / radius:
            return None
        angle = min(angle, turn)
        on_path = vec.add(centre, vec.scale(vec.unit(radial), radius))
        off = vec.sub(p, on_path)
        degrees = math.degrees(angle)
        return vec.dot(off, vec.rotate(x, normal, degrees)), vec.dot(off, vec.rotate(y, normal, degrees))
