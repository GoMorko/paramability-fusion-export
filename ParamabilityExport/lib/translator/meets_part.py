"""A step drawn on another component's sketch keeps meeting the part as it does at the measured sizes.

Such a step (a lid slot, a rail) follows sizes through its own sketch and lengths, and the walls of the part follow
them through theirs, but nothing ties the two together. At other sizes the step can stop short of the wall it ends
in, or come off the wall it lies on. Fusion builds that other shape too, but the steps after it (a chamfer on the
edge it made, a join that must touch) no longer find what they pick.

For points on the faces of the step, `check` looks along the face normal for the nearest faces of the part within
`REACH` mm on each side. Over the size range (every mix of the ends for up to 6 sizes, a bounded sample past that)
every such gap must keep its sign, and a face that lies on a wall must stay on it. Only flat faces parallel to the
step's face count. Where a gap does not keep its sign, the ranges of the sizes it reads are shortened toward their values until it does
(`kept_ranges.shortened`, `Context.narrow`); a size whose range would shrink to its value, or whose range the person
typed, cannot follow (`Context.fix`). When the walk keeps sizes free (loose mode), the ranges stay as Fusion builds
them and the sizes are listed as doubtful past those values instead.
"""
import math

from . import follow, shells, vec
from .footprint import _polyline
from .kept_ranges import shortened
from .slabs import Place, Slab
from .values import Quantity

REACH = 2.0
ON_TOL = 1e-3
INSET = 1e-2
PARALLEL_TOL = 1e-6
_EPS = 1e-9


# ---- where the part's faces cross a line ---------------------------------------------------------------------

def _crossings_2d(a, d, segments, offsets):
    """Parameters t where a + t * d crosses one of the segments, or a copy of it moved sideways by an offset."""
    out = []
    for p, q in segments:
        e = [q[0] - p[0], q[1] - p[1]]
        size = math.hypot(*e)
        if size <= _EPS:
            continue
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) <= _EPS:
            continue
        side = [-e[1] / size, e[0] / size]
        for k in offsets:
            p0 = [p[0] + k * side[0], p[1] + k * side[1]]
            w = [p0[0] - a[0], p0[1] - a[1]]
            t = (w[0] * e[1] - w[1] * e[0]) / den
            s = (w[0] * d[1] - w[1] * d[0]) / den
            if -1e-6 <= s <= 1 + 1e-6:
                out.append(t)
    return out


def _slab_crossings(slab, q, n, offsets):
    """Parameters t where q + t * n may cross a face of `slab` (an end face, a side, or one moved in by an offset)."""
    h0, uv0 = slab.local(q)
    h1, uv1 = slab.local(vec.add(q, n))
    dh, duv = h1 - h0, [uv1[0] - uv0[0], uv1[1] - uv0[1]]
    out = []
    if abs(dh) > _EPS:
        low, high = slab.span
        out += [(at - h0) / dh for at in (low, high) for at in (at + k for k in offsets)]
        out += [(at - h0) / dh for at in (low, high) for at in (at - k for k in offsets)]
    if math.hypot(*duv) > _EPS:
        segments = []
        for curve in slab.footprint.curves:
            points = _polyline(curve)
            segments += list(zip(points, points[1:]))
        out += _crossings_2d(uv0, duv, segments, offsets)
    return out


def _candidates(ctx, q, n):
    offsets = [0.0] + [k * s.thickness.n for s in ctx.shells for k in (1.0, -1.0)]
    out = []
    for slab in ctx.slabs:
        out += _slab_crossings(slab, q, n, offsets)
    for moved in getattr(ctx, "moved_faces", ()):
        for frame, _ in moved.faces:
            dz = vec.dot(n, frame["z"])
            if abs(dz) > _EPS:
                for k in (0.0, moved.distance.n):
                    out.append((vec.dot(vec.sub(frame["origin"], q), frame["z"]) + k) / dz)
    return sorted({round(t, 9) for t in out if -REACH <= t <= REACH})


def _walls(ctx, q, n):
    """(t below zero, t above zero, on): the nearest places along q + t * n where the part starts or stops, within
    REACH; `on` is True when the part starts or stops right at q."""
    def held(t):
        return follow.inside(ctx, vec.add(q, vec.scale(n, t)))

    ts = sorted({t for t in [-REACH, REACH] + _candidates(ctx, q, n) if abs(t) > ON_TOL} | {0.0})
    spans = [(a, b, held((a + b) / 2.0)) for a, b in zip(ts, ts[1:]) if b - a > 2 * _EPS]
    below = above = None
    on = False
    for (_, at, before), (_, _, after) in zip(spans, spans[1:]):
        if before == after:
            continue
        if abs(at) <= _EPS:
            on = True
        elif at < 0:
            below = at
        elif above is None:
            above = at
    return below, above, on


# ---- the gaps as formulas --------------------------------------------------------------------------------------

def _along(quantities, n):
    total = Quantity(0.0)
    for q, c in zip(quantities, n):
        if abs(c) > _EPS:
            total = total.plus(q.scaled(c))
    return total


def _normal(place, p):
    """The unit normal of the flat face a Place lies on, or None (an edge, a curved wall, a moved face)."""
    if isinstance(place, shells.InnerPlace):
        return place.single
    if type(place) is not Place:
        return None
    slab = place.slab
    if place.which in ("start", "end"):
        return slab.motion.turn_vector(slab.axis)
    _, uv = slab.local(p)
    return slab.lateral(uv, slab.footprint.nearest_curve(uv)[0])


def _gap(ctx, slab, q, n, t):
    """The gap from the step's face at q to the part's face at q + t * n along n, as a Quantity; None unless that face
    is flat and parallel to the step's face. On such faces a point that slides along the face (a side point following
    a length) does not change the gap."""
    own = slab.place(q, False)
    wall_point = vec.add(q, vec.scale(n, t))
    wall = follow.locate(ctx, wall_point)
    if own is None or own.blocked or wall is None or wall.blocked:
        return None
    m = _normal(wall, wall_point)
    if m is None or abs(abs(vec.dot(m, n)) - 1.0) > PARALLEL_TOL:
        return None
    return _along(wall.quantities(wall_point), n).plus(_along(own.quantities(q), n).scaled(-1.0))


def _model_point(slab, uv, h):
    flat = vec.frame_apply(slab.frame, [uv[0], uv[1], 0.0])
    dz = vec.dot(slab.frame["z"], slab.axis)
    return vec.frame_apply(slab.frame, [uv[0], uv[1], (h + slab.base - vec.dot(flat, slab.axis)) / dz])


def _samples(slab):
    """(point, outward normal) on the step's faces: inside each end face near each curve, and on the sides at
    mid height."""
    low, high = slab.span
    out = []
    for n, curve in enumerate(slab.footprint.curves):
        points = _polyline(curve)
        mid = points[len(points) // 2]
        outward = slab.footprint.outward(n, mid)
        if outward is None:
            continue
        inner = [mid[0] - INSET * outward[0], mid[1] - INSET * outward[1]]
        out.append((_model_point(slab, inner, high), list(slab.axis)))
        out.append((_model_point(slab, inner, low), vec.scale(slab.axis, -1.0)))
        side = slab.lateral(mid, n)
        if side is not None and slab.taper is None:
            out.append((_model_point(slab, mid, (low + high) / 2.0), side))
    return out


def gaps(ctx, slab):
    """(gap Quantity, 0 or its sign at the measured sizes) for each nearby face of the part the step meets, where a
    gap moves with sizes."""
    out = []
    for q, n in _samples(slab):
        below, above, on = _walls(ctx, q, n)
        for t, sign in ((below, -1.0), (above, 1.0), (0.0 if on else None, 0.0)):
            if t is None:
                continue
            gap = _gap(ctx, slab, q, n, t)
            if gap is not None and gap.sized:
                out.append((gap, sign))
    return out


def check(ctx, step_id, slab_data, combine, why):
    """Shorten or fix the sizes that would make a borrowed step meet the part otherwise than at the measured sizes.
    `slab_data` is the step's `_slab` hand over; `why` names the step for the reason."""
    if ctx.table is None or not (ctx.slabs or ctx.shells) or getattr(ctx.motion, "optimistic", False):
        # A first look writes the borrowed outline as numbers, so its gaps would seem to close with every size.
        return
    slab = Slab(step_id, slab_data["on"], slab_data["extent"], slab_data["length"], slab_data["profile"],
                combine=combine, taper=slab_data.get("taper"), outline=slab_data.get("outline"))
    if not slab.length.n > 0:
        return
    for rule in gaps(ctx, slab):
        found = shortened(ctx.table, [rule], ON_TOL)
        if found is None:
            ctx.fix(rule[0].reads, "past its value, %s would no longer meet the part the way it does now" % why)
        elif found:
            ctx.narrow_or_doubt(found, "past that, %s would no longer meet the part the way it does now" % why,
                                "%s may no longer meet the part" % why)
