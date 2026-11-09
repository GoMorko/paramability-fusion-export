"""Where a 2D point sits against one sketch profile: inside, on an outline curve, or at a corner.

Works on the capture's profile curves (sketch 2D mm, unchained). Lines, arcs and circles are measured exactly;
ellipses are measured on a fine polyline.
"""
import math

CORNER_TOL = 1e-6
ELLIPSE_SEGMENTS = 720
ARC_SEGMENTS = 64


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _to_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    if size <= 0:
        return _dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return _dist(p, [a[0] + t * dx, a[1] + t * dy])


def _angle(center, p):
    return math.atan2(p[1] - center[1], p[0] - center[0])


def _arc_span(curve):
    """(start angle, signed sweep) of an arc, the sweep passing through its middle point."""
    c = curve["center"]
    a0, am, a1 = (_angle(c, curve[k]) for k in ("start", "mid", "end"))
    ccw = (a1 - a0) % (2 * math.pi)
    mid = (am - a0) % (2 * math.pi)
    return (a0, ccw) if mid <= ccw else (a0, ccw - 2 * math.pi)


def _is_full(curve):
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


def _polyline(curve):
    """Points along the curve, for the inside test."""
    kind = curve["kind"]
    if kind == "line":
        return [curve["start"], curve["end"]]
    if kind == "ellipse":
        return _ellipse_points(curve)
    c, r = curve["center"], curve["radius"]
    a0, sweep = (0.0, 2 * math.pi) if _is_full(curve) else _arc_span(curve)
    return [[c[0] + r * math.cos(a0 + sweep * k / ARC_SEGMENTS), c[1] + r * math.sin(a0 + sweep * k / ARC_SEGMENTS)]
            for k in range(ARC_SEGMENTS + 1)]


def curve_distance(curve, p):
    """Distance in mm from a 2D point to one capture curve."""
    kind = curve["kind"]
    if kind == "line":
        return _to_segment(p, curve["start"], curve["end"])
    if kind == "ellipse":
        points = _ellipse_points(curve)
        return min(_to_segment(p, a, b) for a, b in zip(points, points[1:]))
    c, r = curve["center"], curve["radius"]
    if _is_full(curve):
        return abs(_dist(p, c) - r)
    a0, sweep = _arc_span(curve)
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
            if _is_full(curve):
                continue
            for p in (curve["start"], curve["end"]):
                if not any(_dist(p, q) <= CORNER_TOL for q in corners):
                    corners.append(list(p))
        self.corners = corners
        self._segments = []
        for curve in self.curves:
            points = _polyline(curve)
            self._segments += list(zip(points, points[1:]))

    def nearest_curve(self, p):
        """(index of the closest curve, its distance in mm)."""
        best = min(range(len(self.curves)), key=lambda n: curve_distance(self.curves[n], p))
        return best, curve_distance(self.curves[best], p)

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
