"""A join that would float in the copy: its new material meets only material that left out steps made.

In Fusion such a join touches the body, but the copy lacks what it sits on (a floor a left out Combine made, say). The
app's kernel then finds a separate piece and stops the whole copy. So the walk leaves the join out as a gap too.

It does so only when it can tell. The translator keeps its own model of the copied part (the placers of the written
steps, `follow.inside`). The join floats when that model holds no material at or near the join, and every written step
that adds material the model does not hold stays clear of the join by its own bounds: a sweep within its path grown by
its profile, a draft within its walk's slabs grown by its lean, a round or bevel within its size of the part (so the
join must stay that far from the model too). A step it cannot bound, a join that is not a plain extrude, or a join too
large to sample keeps the join in the copy.
"""
import math

from . import follow, step_kinds, vec
from .footprint import polyline
from .placer_makers import SlabMaker
from .slabs import Slab
from .tool_placer import ToolPlacer

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
# Steps of a large angle (a draft, a sweep's taper) are not bounded.
MAX_LEAN_DEG = 45.0

_UNKNOWN = object()


def floats(ctx, outcome):
    """True when the steps `outcome` writes form an extrude join whose material meets nothing the copy holds so far,
    after a step of this walk was left out. False when it meets the copy, or when that cannot be told."""
    if not ctx.gaps:
        return False
    slabs = _join_slabs(outcome)
    finish = _finish_size(ctx.steps) if slabs else _UNKNOWN
    if finish is _UNKNOWN:
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
    box = _union([_slab_box(slab) for slab in slabs])
    region = _grown(box, SPACING + CLEAR)
    if region is None or not _others_clear(ctx, ctx.steps, ctx.placers, region):
        return False
    if reach > NEAR:
        points += _grid(_grown(box, reach))
    return len(points) <= MAX_SAMPLES and not any(follow.inside(ctx, p) for p in points[64:])


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

def _footprint_box(slab):
    points = [p for curve in slab.footprint.curves for p in polyline(curve)]
    if not points:
        return None
    return (min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points))


def _model_point(slab, uv, h):
    """The point at sketch position `uv` and height `h` above the slab's base, in model space."""
    flat = vec.frame_apply(slab.frame, [uv[0], uv[1], 0.0])
    dz = vec.dot(slab.frame["z"], slab.axis)
    return vec.frame_apply(slab.frame, [uv[0], uv[1], (h + slab.base - vec.dot(flat, slab.axis)) / dz])


def _spread(low, high):
    """Values from `low` to `high` at most SPACING apart, both ends included."""
    count = max(1, int(math.ceil((high - low) / SPACING)))
    return [low + (high - low) * k / count for k in range(count + 1)]


def _lean(slab):
    """How far the walls of a tapered slab lean out over its length, in mm."""
    low, high = slab.span
    return abs(math.tan(math.radians(slab.taper.n))) * (high - low) if slab.taper is not None else 0.0


def _samples(slab, reach):
    """Points on the slab's faces and in layers up to `reach` outside them: the start face first, then the end face
    and the sides. None when the slab does not stand on its sketch or needs more than MAX_SAMPLES points."""
    box = _footprint_box(slab)
    if box is None or abs(vec.dot(slab.frame["z"], slab.axis)) < 1e-6:
        return None
    low, high = slab.span
    lean = _lean(slab)
    wide = reach + lean
    offsets = _spread(0.0, reach)
    us, vs = _spread(box[0] - wide, box[2] + wide), _spread(box[1] - wide, box[3] + wide)
    if len(us) * len(vs) * len(offsets) * 2 > MAX_SAMPLES:
        return None
    caps = [[u, v] for u in us for v in vs if slab.depth_in([u, v])[1] >= -wide]
    out = [_model_point(slab, uv, low - d) for d in offsets for uv in caps]
    out += [_model_point(slab, uv, high + d) for d in offsets for uv in caps]
    heights = _spread(low - reach, high + reach)
    for number, curve in enumerate(slab.footprint.curves):
        for uv in _along(curve):
            n = slab.footprint.outward(number, uv)
            if n is None:
                return None
            for d in offsets:
                at = [uv[0] + (d + lean) * n[0], uv[1] + (d + lean) * n[1]]
                out += [_model_point(slab, at, h) for h in heights]
            if len(out) > MAX_SAMPLES:
                return None
    return out


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


# ---- boxes ------------------------------------------------------------------------------------------------------

def _box_of(points):
    if not points:
        return None
    return ([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)])


def _union(boxes):
    if not boxes or any(box is None for box in boxes):
        return None
    return ([min(b[0][i] for b in boxes) for i in range(3)], [max(b[1][i] for b in boxes) for i in range(3)])


def _grown(box, by):
    return None if box is None else ([c - by for c in box[0]], [c + by for c in box[1]])


def _meets(a, b):
    return all(a[0][i] <= b[1][i] and b[0][i] <= a[1][i] for i in range(3))


def _slab_box(slab):
    """The box of a slab's solid in model space (a copy where its motion carries it)."""
    box = _footprint_box(slab)
    if box is None:
        return None
    low, high = slab.span
    lean = _lean(slab)
    corners = [_model_point(slab, [u, v], h) for u in (box[0] - lean, box[2] + lean)
               for v in (box[1] - lean, box[3] + lean) for h in (low, high)]
    if slab.is_copy:
        corners = [slab.motion.numbers(p) for p in corners]
    return _box_of(corners)


# ---- the other steps that add material --------------------------------------------------------------------------

def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    n = getattr(value, "n", None)
    return float(n) if isinstance(n, (int, float)) else None


def _all_steps(steps):
    for step in steps:
        yield step
        yield from _all_steps(step.get("features") or [])


def _finishes(step):
    """True for a round or bevel: it changes the part only along the edges it picks."""
    return step_kinds.recipe_kind(step.get("kind")).repeat == step_kinds.FINISH


def _only_removes(step):
    """True for a step that never adds material the model lacks: a hole, a shell, a cut or intersect, and an
    offsetFaces step (whose moved faces are in the model)."""
    kind = step.get("kind")
    return (step_kinds.recipe_kind(kind).always_cuts or kind == "shell" or kind == "offsetFaces"
            or step.get("combine") in ("cut", "intersect"))


def _own_size(step):
    """The size of a round or bevel step, 0 for another step, or _UNKNOWN."""
    if not _finishes(step):
        return 0.0
    found = [_number(step.get(key)) for key in ("size", "size2") if key in step]
    if not found or any(size is None for size in found):
        return _UNKNOWN
    return max(abs(size) for size in found)


def _finish_size(steps):
    """The largest size of a round or bevel among the written steps (0 without one), or _UNKNOWN. Such a step adds
    material only that close to the part."""
    sizes = [_own_size(step) for step in _all_steps(steps)]
    return _UNKNOWN if _UNKNOWN in sizes else max(sizes + [0.0])


def _modeled_ids(placers):
    """Ids of the steps whose material the placers hold."""
    out = set()
    for placer in placers:
        if isinstance(placer, Slab):
            out.update((placer.id, placer.owner))
        elif isinstance(placer, ToolPlacer):
            out.add(placer.owner)
            out |= _modeled_ids(placer.placers)
    return out


def _adding_slabs_box(placers):
    """The box of the material the slabs among `placers` add, or None when there is none."""
    boxes = []
    for placer in placers:
        if isinstance(placer, Slab) and placer.combine in ("new", "add"):
            boxes.append(_slab_box(placer))
        elif isinstance(placer, ToolPlacer) and placer.combine in ("new", "add"):
            boxes.append(_adding_slabs_box(placer.placers))
    boxes = [b for b in boxes if b is not None]
    return _union(boxes) if boxes else None


def _others_clear(ctx, steps, placers, region):
    """True when every written step of `steps` that adds material either has it in the model (`placers`) or stays
    clear of `region` by its bounds."""
    bound = _bounds(ctx, steps, placers, 0.0)
    return bound is not _UNKNOWN and all(not _meets(box, region) for box in bound)


def _bounds(ctx, steps, placers, later):
    """The boxes of the material the steps may add that the model lacks, or _UNKNOWN. Each box is grown by the size
    of the rounds and bevels written after its step (`later` for those after the whole list), which may add material
    along its edges."""
    modeled = _modeled_ids(placers)
    by_id = {step.get("id"): step for step in steps}
    sizes = [_own_size(step) for step in steps]
    if _UNKNOWN in sizes:
        return _UNKNOWN
    boxes = []
    for k, step in enumerate(steps):
        after = max(sizes[k + 1:] + [later])
        found = _bound(ctx, step, placers, modeled, by_id, after)
        if found is _UNKNOWN:
            return _UNKNOWN
        # A tool's own list grows its boxes already.
        boxes += found if step.get("kind") == "toolBody" else [_grown(box, after) for box in found]
    return boxes


def _bound(ctx, step, placers, modeled, by_id, after=0.0):
    """The boxes of what `step` may add that the model lacks (none for a step whose material the model holds or that
    only removes), or _UNKNOWN."""
    kind = step.get("kind")
    if _only_removes(step) or _finishes(step):
        return []
    if kind == "toolBody":
        tool = next((p for p in placers if isinstance(p, ToolPlacer) and p.owner == step.get("id")), None)
        return _UNKNOWN if tool is None else _bounds(ctx, step.get("features") or [], tool.placers, after)
    if kind == "extrude":
        return [] if step.get("id") in modeled else _UNKNOWN
    if kind == "draft":
        return _draft_bound(step, placers)
    if kind == "sweep":
        return _sweep_bound(ctx, step)
    if step_kinds.recipe_kind(kind).repeats:
        # Copies of steps the model holds are in the model too; a copy of anything else is not bounded.
        for source in step.get("of") or []:
            found = by_id.get(source)
            if found is None or _bound(ctx, found, placers, modeled, by_id) != []:
                return _UNKNOWN
        return []
    return _UNKNOWN


def _draft_bound(step, placers):
    """A draft tilts faces of the material its walk holds: it moves them at most the size of that material's box times
    the tangent of its angle."""
    angle = _number(step.get("angleDeg"))
    box = _adding_slabs_box(placers)
    if angle is None or box is None or abs(angle) >= MAX_LEAN_DEG:
        return _UNKNOWN
    size = math.sqrt(sum((box[1][i] - box[0][i]) ** 2 for i in range(3)))
    return [_grown(box, size * math.tan(math.radians(abs(angle))))]


# ---- sweeps -----------------------------------------------------------------------------------------------------

def _arc_points(curve):
    """Points along a 3D arc of the capture (start, mid, end, center, normal), or None."""
    keys = ("start", "mid", "end", "center", "normal")
    if any(not isinstance(curve.get(key), list) or len(curve[key]) != 3 for key in keys):
        return None
    c, normal = curve["center"], vec.unit(curve["normal"])
    u = vec.sub(curve["start"], c)
    if vec.length(u) <= 0:
        return None
    w = vec.cross(normal, u)

    def angle(p):
        d = vec.sub(p, c)
        return math.atan2(vec.dot(d, w), vec.dot(d, u)) % (2 * math.pi)

    end, mid = angle(curve["end"]) or 2 * math.pi, angle(curve["mid"])
    sweep = end if mid <= end else end - 2 * math.pi
    return [vec.rotate(curve["start"], normal, math.degrees(sweep * k / 64), c) for k in range(65)]


def _path_points(path):
    out = []
    for curve in (path or {}).get("curves") or []:
        kind = curve.get("kind")
        if kind == "line":
            found = [curve.get("start"), curve.get("end")]
        elif kind == "arc":
            found = _arc_points(curve)
        elif kind == "other":
            found = curve.get("samples")
        else:
            found = None
        if not found or any(not isinstance(p, list) or len(p) != 3 for p in found):
            return None
        out += found
    return out or None


def _sweep_bound(ctx, step):
    """A sweep carries its profile along its path, each point at its own distance from the path: its material lies
    within the path's box grown by the farthest profile point from where the path starts (both ends when the profile
    plane holds neither), plus what a taper adds over the path's length."""
    item = ctx.item_of_step(step.get("id"))
    data = (item or {}).get("data") or {}
    points = _path_points(data.get("path"))
    if points is None or data.get("rail") or not data.get("profiles"):
        return _UNKNOWN
    profile_points = []
    for profile in data["profiles"]:
        frame = profile.get("frame")
        flat = [p for loop in profile.get("loops") or [] for curve in loop.get("curves") or [] for p in polyline(curve)]
        if not frame or not flat:
            return _UNKNOWN
        profile_points += [vec.frame_apply(frame, [p[0], p[1], 0.0]) for p in flat]
    curves = data["path"]["curves"]
    ends = [curves[0]["start"], curves[-1]["end"]]
    frame = data["profiles"][0]["frame"]
    on_plane = [end for end in ends if abs(vec.dot(vec.sub(end, frame["origin"]), vec.unit(frame["z"]))) < 1e-3]
    starts = on_plane if len(on_plane) == 1 else ends
    reach = max(vec.length(vec.sub(p, start)) for p in profile_points for start in starts)
    taper = data.get("taper_deg") or 0.0
    if not isinstance(taper, (int, float)) or abs(taper) >= MAX_LEAN_DEG:
        return _UNKNOWN
    length = sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))
    reach += length * math.tan(math.radians(abs(taper)))
    return [_grown(_box_of(points), reach)]
