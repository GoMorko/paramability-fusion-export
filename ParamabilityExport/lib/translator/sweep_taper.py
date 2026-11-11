"""Which way a tapered sweep along a straight path leans and shrinks, read from the volume Fusion made.

Fusion does not say whether its sweep taper offsets the outline (as the recipe's taper does) or scales it, nor which
sign leans in. The two volumes differ for most outlines, so the volume of a new body tells them apart.
"""
import math

OFFSET = "offset"        # the walls move in or out by the same distance everywhere, as the recipe's taper does
FLIPPED = "flipped"      # the same, with the lean the other way round
SCALED = "scaled"        # the whole outline shrinks or grows about its middle, which the recipe cannot write

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


def meaning(loops, length, made, slope):
    """How the made volume reads the taper of `slope` (the recipe's tangent) along a straight path of `length`:
    `OFFSET`, `FLIPPED` (it leans the other way), `SCALED`, or None when no model fits or the offset would close the
    outline."""
    terms = section_terms(loops)
    area, perimeter, _ = terms
    if not (area > 0 and perimeter > 0 and length > 0 and made > 0):
        return None
    if abs(slope) * length >= 2.0 * area / perimeter:
        return None
    for label, sign, volume in ((OFFSET, 1.0, _offset_volume), (SCALED, 1.0, _scaled_volume),
                                (FLIPPED, -1.0, _offset_volume), (SCALED, -1.0, _scaled_volume)):
        if _fits(made, volume(terms, length, sign * slope)):
            return label
    return None
