"""Which way a tapered sweep along a straight path leans and shrinks, read from the volume Fusion made.

Fusion does not say whether its sweep taper offsets the outline (as the recipe's taper does) or scales it, nor which
sign leans in. The two volumes differ for most outlines, so the volume of a new body tells them apart.
"""
import math

OFFSET = "offset"        # the walls move in or out by the same distance everywhere, as the recipe's taper does
FLIPPED = "flipped"      # the same, with the lean the other way round
SCALED = "scaled"        # the whole outline shrinks or grows about its middle, which the recipe cannot write
NO_FIT = "no fit"        # the volume was measured and neither the offset nor the scaled model gives it

VOLUME_TOL = 0.01        # the made volume matches a model within this share


SHARPEST_CORNER_DEG = 10.0   # a corner this sharp or sharper counts as this sharp, so the factor stays finite


def corner_factor(ring):
    """The most an outward offset moves a convex corner of the closed outline `ring` beyond its sides (1 for a smooth
    outline): the app's rule for how far a taper can grow the outline at a corner."""
    twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
    orientation = 1.0 if twice >= 0 else -1.0
    floor = math.sin(math.radians(SHARPEST_CORNER_DEG / 2.0))
    factor = 1.0
    for i in range(len(ring)):
        before, at, after = ring[i - 1], ring[i], ring[(i + 1) % len(ring)]
        ax, ay, bx, by = at[0] - before[0], at[1] - before[1], after[0] - at[0], after[1] - at[1]
        turn = math.atan2(orientation * (ax * by - ay * bx), ax * bx + ay * by)
        if turn > 0:
            factor = max(factor, 1.0 / max(floor, math.cos(turn / 2.0)))
    return factor


def _turned(points, outer):
    """The loop's points with the material on the left: counter clockwise for an outline, clockwise for a hole."""
    twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    return points if (twice > 0) == outer else points[::-1]


def section_terms(loops):
    """`(area, perimeter, corners)` of the outline with its holes out. `loops` are `(2D points, outer)`. The area
    left after an inward offset by d is `area - perimeter * d + corners * d * d`, where `corners` is the sum of
    tan(turn / 2) over the vertices (a turn is positive at a corner of the material, negative at a dent)."""
    area = perimeter = corners = 0.0
    for points, outer in loops:
        points = _turned(points, outer)
        count = len(points)
        twice = 0.0
        for i in range(count):
            before, at, after = points[i - 1], points[i], points[(i + 1) % count]
            twice += at[0] * after[1] - after[0] * at[1]
            ax, ay, bx, by = at[0] - before[0], at[1] - before[1], after[0] - at[0], after[1] - at[1]
            perimeter += math.hypot(bx, by)
            corners += math.tan(math.atan2(ax * by - ay * bx, ax * bx + ay * by) / 2.0)
        area += (1.0 if outer else -1.0) * abs(twice) / 2.0
    return area, perimeter, corners


def _offset_volume(terms, length, slope):
    area, perimeter, corners = terms
    return length * area - perimeter * slope * length ** 2 / 2.0 + corners * slope ** 2 * length ** 3 / 3.0


def _scaled_volume(terms, length, slope):
    area, perimeter, _ = terms
    if area <= 0 or perimeter <= 0:
        return None
    rate = slope * perimeter / (2.0 * area)
    return area * (length - rate * length ** 2 + rate ** 2 * length ** 3 / 3.0)


def _fits(made, expected):
    return expected is not None and abs(made - expected) <= VOLUME_TOL * max(made, expected)


# ---- where an offset closes the outline ------------------------------------------------------------------------------

RAY_FRACTIONS = (0.02, 0.25, 0.5, 0.75, 0.98)   # places along each edge from which the thickness is measured


def _ray_hit(point, direction, edge):
    """The distance from `point` along `direction` to the segment `edge`, or None when the ray misses it."""
    a, b = edge
    ex, ey = b[0] - a[0], b[1] - a[1]
    det = direction[0] * ey - direction[1] * ex
    if abs(det) < 1e-12:
        return None
    wx, wy = a[0] - point[0], a[1] - point[1]
    along = (wx * ey - wy * ex) / det
    across = (wx * direction[1] - wy * direction[0]) / det
    return along if along > 1e-9 and -1e-9 <= across <= 1.0 + 1e-9 else None


def closing_shift(loops, inward):
    """The smallest distance every wall can move (into the material when `inward`, else out of it) before an edge
    vanishes or two walls meet, or None when nothing closes. `loops` are `(2D points, outer)`. An edge shrinks at
    the rate its two corners give; the thickness is measured by rays from a few places on each edge across the
    material (inward) or the gap (outward), so a very narrow sliver between two samples can be missed."""
    sign = 1.0 if inward else -1.0
    edges, bound = [], None
    for points, outer in loops:
        points = _turned(points, outer)
        count = len(points)
        turns = []
        for i in range(count):
            before, at, after = points[i - 1], points[i], points[(i + 1) % count]
            ax, ay, bx, by = at[0] - before[0], at[1] - before[1], after[0] - at[0], after[1] - at[1]
            turns.append(math.tan(math.atan2(ax * by - ay * bx, ax * bx + ay * by) / 2.0))
        for i in range(count):
            a, b = points[i], points[(i + 1) % count]
            edges.append((a, b, len(edges) - i, count, i))
            rate = sign * (turns[i] + turns[(i + 1) % count])
            size = math.hypot(b[0] - a[0], b[1] - a[1])
            if rate > 1e-12 and size > 0:
                bound = size / rate if bound is None else min(bound, size / rate)
    for a, b, first, count, i in edges:
        size = math.hypot(b[0] - a[0], b[1] - a[1])
        if size <= 1e-12:
            continue
        direction = (-sign * (b[1] - a[1]) / size, sign * (b[0] - a[0]) / size)
        for fraction in RAY_FRACTIONS:
            point = (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
            for oa, ob, ofirst, ocount, j in edges:
                if ofirst == first and min((i - j) % count, (j - i) % count) <= 1:
                    continue
                hit = _ray_hit(point, direction, (oa, ob))
                if hit is not None:
                    bound = hit / 2.0 if bound is None else min(bound, hit / 2.0)
    return bound


def closes(loops, length, slope):
    """True when a taper of `slope` (the recipe's tangent, positive leans in) along `length` moves the walls far
    enough to close part of the outline or a hole, which the app refuses."""
    shift = abs(length * slope)
    if shift <= 0:
        return False
    bound = closing_shift(loops, slope > 0)
    return bound is not None and shift >= bound


def meaning(loops, length, made, slope):
    """How the made volume reads the taper of `slope` (the recipe's tangent) along a straight path of `length`:
    `OFFSET`, `FLIPPED` (it leans the other way), `SCALED`, `NO_FIT` when no model gives the volume, or None when it
    cannot be told. A leaning model whose offset closes the outline does not count."""
    terms = section_terms(loops)
    area, perimeter, _ = terms
    if not (area > 0 and perimeter > 0 and length > 0 and made > 0):
        return None
    for label, sign, volume in ((OFFSET, 1.0, _offset_volume), (SCALED, 1.0, _scaled_volume),
                                (FLIPPED, -1.0, _offset_volume), (SCALED, -1.0, _scaled_volume)):
        if label != SCALED and closes(loops, length, sign * slope):
            continue
        if _fits(made, volume(terms, length, sign * slope)):
            return label
    return NO_FIT
