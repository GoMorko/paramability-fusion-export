"""Small 2D helpers on (x, y) points: distance to a segment, a point inside a closed ring, and an arc drawn as points
the way the app draws one."""
import math

# Chords the app draws an arc of an outline with (cad-kernel `sketchGeometry.ts`, `ARC_SAMPLES`).
ARC_CHORDS = 16


def to_segment(p, a, b):
    """Distance from `p` to the segment from `a` to `b` (to `a` when the two are one point)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = 0.0 if size <= 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def to_ring(p, ring):
    """Distance from `p` to the closed polyline `ring`."""
    return min((to_segment(p, a, b) for a, b in zip(ring, ring[1:] + ring[:1])), default=math.inf)


def inside_ring(p, ring):
    """True when `p` lies inside the closed polygon `ring` (even-odd rule; a point on an edge may go either way)."""
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def arc_points(a, m, b, chords=ARC_CHORDS):
    """Points along the arc from `a` through `m` to `b`, both ends included, as the app samples it: `chords` equal
    steps of angle. The chord `[a, b]` when the three are in a line."""
    d = 2.0 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < 1e-12:
        return [a, b]
    sq = [p[0] * p[0] + p[1] * p[1] for p in (a, m, b)]
    cx = (sq[0] * (m[1] - b[1]) + sq[1] * (b[1] - a[1]) + sq[2] * (a[1] - m[1])) / d
    cy = (sq[0] * (b[0] - m[0]) + sq[1] * (a[0] - b[0]) + sq[2] * (m[0] - a[0])) / d
    r = math.hypot(a[0] - cx, a[1] - cy)
    t0, t1 = math.atan2(a[1] - cy, a[0] - cx), math.atan2(b[1] - cy, b[0] - cx)
    counter = (m[0] - a[0]) * (b[1] - m[1]) - (m[1] - a[1]) * (b[0] - m[0]) > 0
    turn = (t1 - t0) % (2 * math.pi) if counter else -((t0 - t1) % (2 * math.pi))
    return [a] + [[cx + r * math.cos(t0 + turn * i / chords), cy + r * math.sin(t0 + turn * i / chords)]
                  for i in range(1, chords)] + [b]
