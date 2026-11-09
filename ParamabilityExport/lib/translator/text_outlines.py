"""Sketch text as outlines: the curves of a text sorted into outer outlines and the holes inside them. Pure.

A text gives its glyph outlines as loose curves. They are chained into closed loops, and each loop is an outer
outline or a hole by how many loops contain it: an even count is an outer outline ("o" and the letters around it), an
odd count a hole of the nearest loop around it ("o" inside, the counter of "A"). Every outer outline with its holes is
one profile record, the same shape a sketch profile has, so extrudes and embosses treat text like any other outline.
"""
import math

from .footprint import polyline
from .outlines import CHAIN_TOL, closed_loops

OPEN = "open"
_VOTES = 5


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _touches(point, curve):
    return any(_dist(point, curve[k]) <= CHAIN_TOL for k in ("start", "end") if k in curve)


def _ring(loop):
    """The points of a chained loop, each curve run the way the chain goes."""
    if len(loop) == 1:
        return list(polyline(loop[0]))[:-1] or list(polyline(loop[0]))
    points = []
    for n, curve in enumerate(loop):
        line = list(polyline(curve))
        if n == 0:
            if not _touches(line[-1], loop[1]):
                line.reverse()
        elif _dist(line[0], points[-1]) > _dist(line[-1], points[-1]):
            line.reverse()
        points.extend(line[:-1])
    return points


def _area(ring):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))) / 2.0


def _inside(ring, p):
    crossings = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            crossings = not crossings
    return crossings


def _within(inner, outer):
    """True when most of the points sampled along `inner` lie inside the `outer` ring."""
    step = max(len(inner) // _VOTES, 1)
    votes = [_inside(outer, inner[k]) for k in range(0, len(inner), step)]
    return sum(votes) * 2 > len(votes)


def outlines_of(curves):
    """`[{ "loops": [{ "outer": bool, "curves": [...] }], "area": mm2 }]`, one entry per outer outline, from the 2D
    capture curves of a text; the string `OPEN` when the curves do not make closed loops."""
    loops = closed_loops(curves)
    if not loops:
        return OPEN
    rings = [_ring(loop) for loop in loops]
    areas = [_area(ring) for ring in rings]
    around = [[j for j in range(len(loops)) if j != i and areas[j] > areas[i] and _within(rings[i], rings[j])]
              for i in range(len(loops))]
    outers = [i for i in range(len(loops)) if len(around[i]) % 2 == 0]
    holes = {i: [] for i in outers}
    for i in range(len(loops)):
        if len(around[i]) % 2 == 1:
            holes[min(around[i], key=lambda j: areas[j])].append(i)
    return [{
        "loops": [{"outer": True, "curves": loops[i]}] + [{"outer": False, "curves": loops[h]} for h in holes[i]],
        "area": round(areas[i] - sum(areas[h] for h in holes[i]), 6) + 0.0,
    } for i in outers]
