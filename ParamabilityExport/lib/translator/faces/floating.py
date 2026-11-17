"""A join that would float in the copy: its new material meets only material that left out steps made.

In Fusion such a join touches the body, but the copy lacks what it sits on (a floor a left out Combine made, say). The
app's kernel then finds a separate piece and stops the whole copy. So the walk leaves the join out as a gap too.

It does so only when it can tell. The translator keeps its own model of the copied part (the placers of the written
steps, `follow.inside`). The join floats when that model holds no material at, near or inside the join, and every
written step that adds material the model does not hold stays clear of the join by its own bounds: a sweep within its
path grown by its profile, a draft within its walk's slabs grown by its lean, a round or bevel within its size of the
part (so the join must stay that far from the model too). Material of the model is looked for on and right next to the
join's faces, on a coarse grid through the join and the band round it, and then closely wherever the box of a step of
the model meets that band; a slab of the model with a corner inside the join keeps it (the join may enclose it). A step
it cannot bound, a join that is not a plain extrude, or a join or nearby material too large to sample keeps the join in
the copy.
"""
import math

from . import added_bounds, follow
from . import material_boxes as mbox
from ...geometry import vec
from ...geometry.footprint import polyline
from .placer_makers import SlabMaker
from .slabs import Slab

# Spacing of the sample points on and right next to the join, in mm, and how far out that dense band runs. A wall of
# the part thinner than about this can slip between the samples.
SPACING = 0.25
NEAR = 2 * SPACING
# Farther out (up to the size of the largest round), a grid of at most this many points along each side.
FAR_STEPS = 16
# More samples than this: the join is too large to check, so it stays.
MAX_SAMPLES = 20000
# How far a bounded step must stay from the join, in mm.
CLEAR = 0.5
# A gap whose body grew by more than this volume, in cubic mm, added material.
ADDED_MM3 = 1e-3


def floats(ctx, outcome):
    """True when the steps `outcome` writes form an extrude join whose material meets nothing the copy holds so far,
    after a step of this walk was left out. False when it meets the copy, or when that cannot be told."""
    if not ctx.gaps:
        return False
    slabs = _join_slabs(outcome)
    finish = added_bounds.finish_size(ctx.steps) if slabs else mbox.UNKNOWN
    if finish is mbox.UNKNOWN:
        return False
    reach = finish + SPACING / 2.0
    points = []
    for slab in slabs:
        found = _samples(slab, min(reach, NEAR))
        if found is None or len(points) + len(found) > MAX_SAMPLES:
            return False
        points += found
    # The start face first: a join that touches the part usually sits on it, so most checks end at once.
    if any(follow.inside(ctx, p) for p in points[:64]):
        return False
    box = mbox.union([mbox.slab_box(slab) for slab in slabs])
    region = mbox.grown(box, SPACING + CLEAR)
    if region is None or not _others_clear(ctx, ctx.steps, ctx.placers, region):
        return False
    band = mbox.grown(box, max(reach, NEAR))
    points += _grid(band)
    if len(points) > MAX_SAMPLES or any(follow.inside(ctx, p) for p in points[64:]):
        return False
    return _model_clear(ctx, slabs, band)


def _model_clear(ctx, slabs, band):
    """True when no material of the model lies in `band` (the join's box grown by the reach): every step of the model
    whose box meets it is sampled there SPACING apart, and a slab of the model with a corner in the join keeps the join
    whatever the samples say. False when a step's box cannot be told or the samples would be too many."""
    found = mbox.material_boxes(ctx.placers)
    if found is mbox.UNKNOWN:
        return False
    for box, corners in found:
        if not mbox.meets(box, band):
            continue
        if any(join.material_at(p) is not None for join in slabs for p in corners):
            return False
        points = _dense(mbox.overlap(box, band))
        if points is None or any(follow.inside(ctx, p) for p in points):
            return False
    return True


def sat_on(ctx, outcome):
    """Ids of the gaps of this walk a floating join sits on, by the body measured round each gap (`Gap.before` and
    `after`): the gaps that grew the body out to the join, else those that added material with the body after them
    reaching the join, else the latest gap that may have added material, else the latest gap."""
    slabs = _join_slabs(outcome)
    region = mbox.grown(mbox.union([mbox.slab_box(slab) for slab in slabs]), NEAR) if slabs else None

    def reaches(measure):
        if measure is None or region is None:
            return None
        return mbox.meets((measure["box"]["min"], measure["box"]["max"]), region)

    def added(gap):
        if gap.before is None or gap.after is None:
            return None
        return gap.after["volume"] > gap.before["volume"] + ADDED_MM3

    grew = [gap for gap in ctx.gaps if added(gap)]
    out = [gap for gap in grew if reaches(gap.after) and reaches(gap.before) is False]
    out = out or [gap for gap in grew if reaches(gap.after)]
    out = out or [gap for gap in ctx.gaps if added(gap) is not False][-1:] or ctx.gaps[-1:]
    return [gap.id for gap in out]


def _join_slabs(outcome):
    """The slabs of an outcome that only adds material with plain extrudes, or None."""
    slabs = []
    for entry in outcome.entries:
        step = entry.step
        if step.get("kind") != "extrude" or step.get("combine") != "add" or step.get("thin"):
            return None
        if len(entry.placers) != 1 or not isinstance(entry.placers[0], SlabMaker):
            return None
        made = entry.placers[0]
        slabs.append(Slab("floating_check", made.on, made.extent, made.length, made.profile, combine="add",
                          taper=made.taper))
    return slabs or None


# ---- the samples around the join --------------------------------------------------------------------------------


def _spread(low, high):
    """Values from `low` to `high` at most SPACING apart, both ends included."""
    count = max(1, int(math.ceil((high - low) / SPACING)))
    return [low + (high - low) * k / count for k in range(count + 1)]


def _samples(slab, reach):
    """Points on the slab's faces and in layers up to `reach` outside them: the start face first, then the end face
    and the sides. None when the slab does not stand on its sketch or needs more than MAX_SAMPLES points."""
    box = mbox.footprint_box(slab)
    if box is None or abs(vec.dot(slab.frame["z"], slab.axis)) < 1e-6:
        return None
    low, high = slab.span
    lean = mbox.slab_lean(slab)
    wide = reach + lean
    offsets = _spread(0.0, reach)
    us, vs = _spread(box[0] - wide, box[2] + wide), _spread(box[1] - wide, box[3] + wide)
    if len(us) * len(vs) * len(offsets) * 2 > MAX_SAMPLES:
        return None
    caps = [[u, v] for u in us for v in vs if slab.depth_in([u, v])[1] >= -wide]
    out = [mbox.model_point(slab, uv, low - d) for d in offsets for uv in caps]
    out += [mbox.model_point(slab, uv, high + d) for d in offsets for uv in caps]
    heights = _spread(low - reach, high + reach)
    for number, curve in enumerate(slab.footprint.curves):
        for uv in _along(curve):
            n = slab.footprint.outward(number, uv)
            if n is None:
                return None
            for d in offsets:
                at = [uv[0] + (d + lean) * n[0], uv[1] + (d + lean) * n[1]]
                out += [mbox.model_point(slab, at, h) for h in heights]
            if len(out) > MAX_SAMPLES:
                return None
    return out


def _dense(box):
    """Points filling a box SPACING apart, or None when they would be more than MAX_SAMPLES."""
    counts = [max(1, int(math.ceil((box[1][i] - box[0][i]) / SPACING))) for i in range(3)]
    if (counts[0] + 1) * (counts[1] + 1) * (counts[2] + 1) > MAX_SAMPLES:
        return None
    axes = [[box[0][i] + (box[1][i] - box[0][i]) * k / counts[i] for k in range(counts[i] + 1)] for i in range(3)]
    return [[x, y, z] for x in axes[0] for y in axes[1] for z in axes[2]]


def _grid(box):
    """Points filling a box, FAR_STEPS + 1 along each side (closer when that is under SPACING)."""
    axes = []
    for i in range(3):
        low, high = box[0][i], box[1][i]
        count = max(1, min(FAR_STEPS, int(math.ceil((high - low) / SPACING))))
        axes.append([low + (high - low) * k / count for k in range(count + 1)])
    return [[x, y, z] for x in axes[0] for y in axes[1] for z in axes[2]]


def _along(curve):
    """Points along a profile curve at most SPACING apart."""
    points = polyline(curve)
    out = []
    for a, b in zip(points, points[1:]):
        steps = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / SPACING)))
        out += [[a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps] for k in range(steps)]
    return out + points[-1:]


def _others_clear(ctx, steps, placers, region):
    """True when every written step of `steps` that adds material either has it in the model (`placers`) or stays
    clear of `region` by its bounds."""
    bound = added_bounds.bounds(ctx, steps, placers, 0.0)
    return bound is not mbox.UNKNOWN and all(not mbox.meets(box, region) for box in bound)
