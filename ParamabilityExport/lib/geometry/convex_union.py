"""The area that several convex polygons cover together. Pure.

The area of the union is the sum over every set of polygons that overlap of the area they share, with the sign
of inclusion and exclusion: plus for one polygon, minus for two, plus for three and so on. A set that shares no area
is not grown further, so polygons that meet only at corners or edges (the pieces of one band) cost little.
"""

# Shared areas below this (mm2) are no overlap.
AREA_EPS = 1e-9
# Sets of overlapping polygons worked out at most; past it the area is not known.
MAX_SETS = 4096


def polygon_area(points):
    """The area of a simple polygon (its corners in order, either way round)."""
    total = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        total += a[0] * b[1] - b[0] * a[1]
    return abs(total) / 2.0


def _ccw(points):
    total = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    return list(points) if total >= 0 else list(reversed(points))


def _clip(subject, clip):
    """The part of the convex polygon `subject` inside the convex polygon `clip` (both counter-clockwise)."""
    out = list(subject)
    for a, b in zip(clip, clip[1:] + clip[:1]):
        if not out:
            break
        given, out = out, []

        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0.0

        for p, q in zip(given, given[1:] + given[:1]):
            if inside(q):
                if not inside(p):
                    out.append(_crossing(p, q, a, b))
                out.append(q)
            elif inside(p):
                out.append(_crossing(p, q, a, b))
    return out


def _crossing(p, q, a, b):
    """Where the segment p-q crosses the line through a and b."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    ex, ey = b[0] - a[0], b[1] - a[1]
    under = dx * ey - dy * ex
    if under == 0.0:
        return list(q)
    t = ((a[0] - p[0]) * ey - (a[1] - p[1]) * ex) / under
    return [p[0] + t * dx, p[1] + t * dy]


def union_area(polygons):
    """The area the convex `polygons` cover together, or None when too many of them overlap to work it out."""
    shapes = [_ccw(p) for p in polygons if len(p) >= 3]
    total, sets = 0.0, 0
    # Each entry: (shared polygon, number of polygons in the set, index of the last one).
    level = [(shape, 1, n) for n, shape in enumerate(shapes) if polygon_area(shape) > AREA_EPS]
    while level:
        grown = []
        for shared, size, last in level:
            total += polygon_area(shared) * (1.0 if size % 2 else -1.0)
            for n in range(last + 1, len(shapes)):
                found = _clip(shared, shapes[n])
                if len(found) >= 3 and polygon_area(found) > AREA_EPS:
                    sets += 1
                    if sets > MAX_SETS:
                        return None
                    grown.append((found, size + 1, n))
        level = grown
    return total
