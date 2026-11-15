"""Where a 2D point sits against one sketch profile: inside, on an outline curve, or at a corner.

Works on the capture's profile curves (sketch 2D mm, unchained). Lines, arcs and circles are measured exactly;
ellipses are measured on a fine polyline, free curves on their dense samples.
"""
import math

from .plane2d import to_segment as _to_segment

CORNER_TOL = 1e-6
ELLIPSE_SEGMENTS = 720
ARC_SEGMENTS = 64


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _to_polyline(p, points):
    """Distance from a point to a polyline."""
    px, py = p
    best = math.inf
    for k in range(len(points) - 1):
        ax, ay = points[k]
        dx, dy = points[k + 1][0] - ax, points[k + 1][1] - ay
        size = dx * dx + dy * dy
        t = ((px - ax) * dx + (py - ay) * dy) / size if size > 0 else 0.0
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        ex, ey = px - ax - t * dx, py - ay - t * dy
        gap = ex * ex + ey * ey
        if gap < best:
            best = gap
    return math.sqrt(best)


def _angle(center, p):
    return math.atan2(p[1] - center[1], p[0] - center[0])


def arc_span(curve):
    """(start angle, signed sweep) of an arc, the sweep passing through its middle point."""
    c = curve["center"]
    a0, am, a1 = (_angle(c, curve[k]) for k in ("start", "mid", "end"))
    ccw = (a1 - a0) % (2 * math.pi)
    mid = (am - a0) % (2 * math.pi)
    return (a0, ccw) if mid <= ccw else (a0, ccw - 2 * math.pi)


def is_full(curve):
    return curve["kind"] in ("circle", "ellipse") or (
        curve["kind"] == "arc" and _dist(curve["start"], curve["end"]) <= CORNER_TOL)


def _ellipse_points(curve):
    c, d = curve["center"], curve["major_dir"]
    n = math.hypot(d[0], d[1]) or 1.0
    ux, uy = d[0] / n, d[1] / n
    a, b = curve["major_radius"], curve["minor_radius"]
    points = []
    for k in range(ELLIPSE_SEGMENTS + 1):
        t = 2 * math.pi * k / ELLIPSE_SEGMENTS
        x, y = a * math.cos(t), b * math.sin(t)
        points.append([c[0] + x * ux - y * uy, c[1] + x * uy + y * ux])
    return points


def polyline(curve):
    """Points along the curve, for the inside test."""
    kind = curve["kind"]
    if kind == "line":
        return [curve["start"], curve["end"]]
    if kind == "ellipse":
        return _ellipse_points(curve)
    if kind == "other":
        return curve["samples"]
    c, r = curve["center"], curve["radius"]
    a0, sweep = (0.0, 2 * math.pi) if is_full(curve) else arc_span(curve)
    return [[c[0] + r * math.cos(a0 + sweep * k / ARC_SEGMENTS), c[1] + r * math.sin(a0 + sweep * k / ARC_SEGMENTS)]
            for k in range(ARC_SEGMENTS + 1)]


def _box_gap(p, box):
    """Distance from a point to a box (min x, min y, max x, max y); zero inside it."""
    return math.hypot(max(box[0] - p[0], 0.0, p[0] - box[2]), max(box[1] - p[1], 0.0, p[1] - box[3]))


def curve_length(curve):
    """Length in mm of one capture curve."""
    kind = curve["kind"]
    if kind == "line":
        return _dist(curve["start"], curve["end"])
    points = polyline(curve)
    return sum(_dist(a, b) for a, b in zip(points, points[1:]))


def _nearest_on_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return [a[0] + t * dx, a[1] + t * dy], [dx, dy]


def nearest_point(curve, p):
    """(the point of the curve nearest to `p`, a unit normal of the curve there); the normal is None when unknown."""
    if curve["kind"] in ("arc", "circle"):
        c, r = curve["center"], curve["radius"]
        d = _dist(p, c)
        # Within the arc's sweep the nearest point is straight out from the centre.
        if d > 0 and abs(curve_distance(curve, p) - abs(d - r)) <= 1e-12:
            n = [(p[0] - c[0]) / d, (p[1] - c[1]) / d]
            return [c[0] + r * n[0], c[1] + r * n[1]], n
    points = [curve["start"], curve["end"]] if curve["kind"] == "line" else polyline(curve)
    best = min(zip(points, points[1:]), key=lambda ab: _to_segment(p, ab[0], ab[1]))
    point, (dx, dy) = _nearest_on_segment(p, best[0], best[1])
    size = math.hypot(dx, dy)
    return point, ([-dy / size, dx / size] if size > 0 else None)


def curve_distance(curve, p):
    """Distance in mm from a 2D point to one capture curve."""
    kind = curve["kind"]
    if kind == "line":
        return _to_segment(p, curve["start"], curve["end"])
    if kind in ("ellipse", "other"):
        return _to_polyline(p, polyline(curve))
    c, r = curve["center"], curve["radius"]
    if is_full(curve):
        return abs(_dist(p, c) - r)
    a0, sweep = arc_span(curve)
    turned = (_angle(c, p) - a0) % (2 * math.pi)
    within = turned <= sweep if sweep >= 0 else turned >= 2 * math.pi + sweep or turned == 0
    if within:
        return abs(_dist(p, c) - r)
    return min(_dist(p, curve["start"]), _dist(p, curve["end"]))


class Footprint:
    """The region one profile covers in its sketch plane (outer loop less its holes)."""

    def __init__(self, profile):
        self.curves = [curve for loop in profile.get("loops") or [] for curve in loop.get("curves") or []]
        corners = []
        for curve in self.curves:
            if is_full(curve):
                continue
            for p in (curve["start"], curve["end"]):
                if not any(_dist(p, q) <= CORNER_TOL for q in corners):
                    corners.append(list(p))
        self.corners = corners
        self._segments = []
        # Boxes of the curves that are long polylines, so `nearest_curve` can skip those that are far away.
        self._boxes = []
        for curve in self.curves:
            points = polyline(curve)
            self._segments += list(zip(points, points[1:]))
            if curve["kind"] in ("ellipse", "other"):
                self._boxes.append((min(p[0] for p in points), min(p[1] for p in points),
                                    max(p[0] for p in points), max(p[1] for p in points)))
            else:
                self._boxes.append(None)

    def nearest_curve(self, p):
        """(index of the closest curve, its distance in mm)."""
        best, best_gap = 0, math.inf
        for n, curve in enumerate(self.curves):
            box = self._boxes[n]
            if box is not None and _box_gap(p, box) >= best_gap:
                continue
            gap = curve_distance(curve, p)
            if gap < best_gap:
                best, best_gap = n, gap
        return best, best_gap

    def gaps(self, p):
        """Distance in mm from `p` to each curve, in curve order."""
        return [curve_distance(curve, p) for curve in self.curves]

    def outward(self, n, p, step=1e-4):
        """The unit normal of curve `n` at its point nearest `p`, pointing out of the region; None when unknown."""
        point, normal = nearest_point(self.curves[n], p)
        if normal is None:
            return None
        probe = [point[0] + step * normal[0], point[1] + step * normal[1]]
        return [-normal[0], -normal[1]] if self.covers(probe) else normal

    def corner_at(self, p, tol):
        """Index of the corner within `tol` of `p`, or None."""
        for n, q in enumerate(self.corners):
            if _dist(p, q) <= tol:
                return n
        return None

    def covers(self, p):
        """True when `p` lies inside the region (an odd number of outline crossings to its right)."""
        crossings = 0
        for a, b in self._segments:
            if (a[1] > p[1]) != (b[1] > p[1]):
                x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x > p[0]:
                    crossings += 1
        return crossings % 2 == 1
