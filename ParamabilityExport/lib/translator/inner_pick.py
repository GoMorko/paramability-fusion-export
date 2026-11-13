"""What a picked point inside the outline of an end face moves with.

A round, a chamfer or a shell can pick an end face of an extrude by a point inside it. When the outline follows sizes,
the point moves along with one place of the outline, so it stays on the face. The centre of all outline corners is a
safe place for a face that keeps its shape, but its formula sums every corner: with corners that turn with an angle it
passes the app's formula length cap. A single corner gives a formula a few times shorter. `anchor` uses the nearest
corner whose move keeps the point inside the written outline, with room to its edges, at every size setting
`range_check` builds over the ranges of the sizes the outline reads (`corners` and `middles`); else the centre.
An edge picked inside the face comes from another step and keeps the centre (`sketch_motion.Outline._inner`).
"""
from ..params.expressions import ExpressionError, parse_formula
from ..sketch_values.motion import Stuck
from . import range_check
from .curved import combine, render
from .footprint import Footprint
from .written_loops import profile_at, written_reads

MAX_CORNERS = 3   # nearest corners tried before the centre
ROOM_SHARE = 0.25  # share of the point's distance to the outline it must keep at every setting
_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, KeyError, TypeError)


def corners(loop, raw_loop):
    """`[(uv, raw xy)]` of the corners of a polygon or profile loop (a closed profile's last point is its start)."""
    if loop["kind"] == "polygon":
        return list(zip(loop["points"], raw_loop["points"]))
    pairs = [(loop["start"], raw_loop["start"])]
    return pairs + [(s["to"], r["to"]) for s, r in zip(loop["segments"], raw_loop["segments"])][:-1]


def centre(pairs, sketch):
    """`(uv, raw xy)` of the mean of the corners `pairs`."""
    k = 1.0 / len(pairs)
    uv = [sum(p[i] for p, _ in pairs) * k for i in range(2)]
    return uv, [combine([(k, r[i]) for _, r in pairs], sketch) for i in range(2)]


class Samples:
    """The written outline of an `Outline` at the size settings over its ranges (`bounds` replaces the range of a size,
    by recipe name), worked out once. `footprints` is None when the outline cannot be worked out at a setting."""

    def __init__(self, table, written, bounds=None):
        self.table = table
        outer, inners = written
        reads = written_reads(outer, *inners)
        settings = range_check.corners(table, reads, bounds) + range_check.middles(table, reads, bounds)
        self.footprints = []
        try:
            for setting in settings:
                env = range_check.size_env(table, setting)
                self.footprints.append((env, Footprint(profile_at(outer, inners, env))))
        except _FAILURES:
            self.footprints = None

    def keeps_inside(self, base, offset, room):
        """True when the point `base` (raw xy) plus `offset` lies inside the outline, at least `room` from its edges,
        at every setting."""
        if self.footprints is None:
            return False
        qs = [render(v, self.table) for v in base]
        if any(isinstance(q, Stuck) for q in qs):
            return False
        try:
            trees = [parse_formula(q.text) if q.sized else None for q in qs]
            for env, footprint in self.footprints:
                p = [(q.n if tree is None else range_check.value_of(tree, env)) + offset[i]
                     for i, (q, tree) in enumerate(zip(qs, trees))]
                if not footprint.covers(p) or footprint.nearest_curve(p)[1] < room:
                    return False
        except _FAILURES:
            return False
        return True


def anchor(outline, footprint, uv):
    """`(uv, raw xy)` of the place of the outer loop of `outline` (a `sketch_motion.Outline`) that a point `uv` inside
    `footprint` (the captured region) moves with."""
    pairs = corners(outline.loops[0], outline.raw_loops[0])
    room = footprint.nearest_curve(uv)[1] * ROOM_SHARE
    nearest = sorted(pairs, key=lambda pair: (pair[0][0] - uv[0]) ** 2 + (pair[0][1] - uv[1]) ** 2)
    for corner_uv, raw_xy in nearest[:MAX_CORNERS]:
        if any(isinstance(v, Stuck) for v in raw_xy):
            continue
        offset = [uv[i] - corner_uv[i] for i in range(2)]
        if outline.samples().keeps_inside(raw_xy, offset, room):
            return corner_uv, raw_xy
    return centre(pairs, outline.sketch)
