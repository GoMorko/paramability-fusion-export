"""Sketch text as outlines: the curves of a text sorted into outer outlines and the holes inside them. Pure.

A text gives its glyph outlines as loose curves. They are chained into closed loops, and each loop is an outer
outline or a hole by how many loops contain it: an even count is an outer outline ("o" and the letters around it), an
odd count a hole of the nearest loop around it ("o" inside, the counter of "A"). Every outer outline with its holes is
one profile record, the same shape a sketch profile has, so extrudes and embosses treat text like any other outline.
The count only means something when loops nest cleanly. Loops that cross each other (a font that draws a letter from
overlapping strokes) are not sorted at all: `OVERLAP` is returned instead.
"""
import math

from .footprint import polyline
from .outlines import closed_loops
from .tolerances import CHAIN_TOL

OPEN = "open"
OVERLAP = "overlap"
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


def _box(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_meet(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _contains_box(outer, inner):
    return (outer[0] - CHAIN_TOL <= inner[0] and outer[1] - CHAIN_TOL <= inner[1]
            and inner[2] <= outer[2] + CHAIN_TOL and inner[3] <= outer[3] + CHAIN_TOL)


def _turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _cross(a, b, c, d):
    """True when the segments a-b and c-d cross at a point inside both. Touching ends and overlapping runs along one
    line do not count."""
    t1, t2, t3, t4 = _turn(a, b, c), _turn(a, b, d), _turn(c, d, a), _turn(c, d, b)
    return t1 * t2 < 0 and t3 * t4 < 0


def _segments_near(ring, box):
    """The segments of a ring whose own box meets `box`."""
    out = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if min(a[0], b[0]) <= box[2] and max(a[0], b[0]) >= box[0] and min(a[1], b[1]) <= box[3] \
                and max(a[1], b[1]) >= box[1]:
            out.append((a, b))
    return out


def _cross_each_other(ring_a, box_a, ring_b, box_b):
    """True when a segment of one ring crosses a segment of the other."""
    near_a, near_b = _segments_near(ring_a, box_b), _segments_near(ring_b, box_a)
    return any(_cross(a, b, c, d) for a, b in near_a for c, d in near_b)


def _overlapping(rings, boxes):
    """True when two loops cross. Loops whose boxes do not meet are never compared, so a long text stays cheap."""
    order = sorted(range(len(rings)), key=lambda i: boxes[i][0])
    for n, i in enumerate(order):
        for j in order[n + 1:]:
            if boxes[j][0] > boxes[i][2]:
                break
            if _boxes_meet(boxes[i], boxes[j]) and _cross_each_other(rings[i], boxes[i], rings[j], boxes[j]):
                return True
    return False


def outlines_of(curves):
    """`[{ "loops": [{ "outer": bool, "curves": [...] }], "area": mm2 }]`, one entry per outer outline, from the 2D
    capture curves of a text; the string `OPEN` when the curves do not make closed loops and `OVERLAP` when two loops
    cross each other."""
    loops = closed_loops(curves)
    if not loops:
        return OPEN
    rings = [_ring(loop) for loop in loops]
    boxes = [_box(ring) for ring in rings]
    if _overlapping(rings, boxes):
        return OVERLAP
    areas = [_area(ring) for ring in rings]
    around = [[j for j in range(len(loops)) if j != i and areas[j] > areas[i] and _contains_box(boxes[j], boxes[i])
               and _within(rings[i], rings[j])] for i in range(len(loops))]
    outers = [i for i in range(len(loops)) if len(around[i]) % 2 == 0]
    holes = {i: [] for i in outers}
    for i in range(len(loops)):
        if len(around[i]) % 2 == 1:
            holes[min(around[i], key=lambda j: areas[j])].append(i)
    return [{
        "loops": [{"outer": True, "curves": loops[i]}] + [{"outer": False, "curves": loops[h]} for h in holes[i]],
        "area": round(areas[i] - sum(areas[h] for h in holes[i]), 6) + 0.0,
    } for i in outers]
