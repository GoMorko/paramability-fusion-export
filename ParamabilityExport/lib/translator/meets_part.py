"""A step drawn on another component's sketch keeps meeting the part as it does at the measured sizes.

Such a step (a lid slot, a rail) follows sizes through its own sketch and lengths, and the walls of the part follow
them through theirs, but nothing ties the two together. At other sizes the step can stop short of the wall it ends
in, or come off the wall it lies on. Fusion builds that other shape too, but the steps after it (a chamfer on the
edge it made, a join that must touch) no longer find what they pick.

For points on the faces of the step, `check` looks along the face normal for the nearest faces of the part within
`REACH` mm on each side. Over the size range (every mix of the ends for up to 6 sizes, a bounded sample past that)
every such gap must keep its sign, and a face that lies on a wall must stay on it. Only flat faces parallel to the
step's face count. Where a gap does not keep its sign at some size setting, the sizes it reads may give unexpected
results past the values where it still does (`kept_ranges.holding_ranges` and `past_reasons`); a size that cannot be
brought in that way, because it would shrink to its value or because the person typed its range, cannot follow
(`Context.doubt`).
"""
from . import follow, shells, vec
from .footprint import polyline
from .kept_ranges import holding_ranges, past_reasons
from .slabs import Place, Slab
from .values import Quantity

REACH = 2.0
ON_TOL = 1e-3
INSET = 1e-2
PARALLEL_TOL = 1e-6
_EPS = 1e-9


# ---- where the part's faces cross a line ---------------------------------------------------------------------

def _candidates(ctx, q, n):
    offsets = [0.0] + [k for placer in ctx.placers for k in placer.wall_offsets]
    out = []
    for placer in ctx.placers:
        out += placer.crossings(q, n, offsets)
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
        points = polyline(curve)
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


def check(ctx, step_id, made, combine, why):
    """Mark the sizes that would make a borrowed step meet the part otherwise than at the measured sizes.
    `made` is the step's placer_makers.SlabMaker; `why` names the step for the reason."""
    if ctx.table is None or getattr(ctx.motion, "optimistic", False):
        # A first look writes the borrowed outline as numbers, so its gaps would seem to close with every size.
        return
    if any(placer.opaque for placer in ctx.placers):
        ctx.doubt(ctx.written_reads, "%s is drawn after a wall whose faces the copy cannot follow, so it cannot check "
                  "that it still meets the part" % why)
    if not (ctx.slabs or any(placer.wall_offsets for placer in ctx.placers)):
        return
    slab = Slab(step_id, made.on, made.extent, made.length, made.profile, combine=combine, taper=made.taper,
                outline=made.outline)
    if not slab.length.n > 0:
        return
    for rule in gaps(ctx, slab):
        found = holding_ranges(ctx.table, [rule], ON_TOL)
        if found is None:
            ctx.doubt(rule[0].reads, "past its value, %s would no longer meet the part the way it does now" % why)
        elif found:
            for name, reason in past_reasons(ctx.table, found, "%s may no longer meet the part" % why).items():
                ctx.doubt([name], reason)
