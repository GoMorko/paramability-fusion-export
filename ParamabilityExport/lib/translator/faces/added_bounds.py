"""Bounds of the material that written steps may add and that the copy's model of the part does not hold (no placer
says where it is): a sweep within its path grown by its profile, a draft within its walk's slabs grown by its lean, a
shell that grows outward within its wall, a round or bevel within its size of the part. Used by faces/floating.py.
"""
import math

from ...capture_model import step_kinds
from ...design_model import design
from ...geometry import vec
from ...geometry.footprint import polyline
from . import material_boxes as mbox
from .slabs import Slab
from .tool_placer import ToolPlacer

# Steps of a large angle (a draft, a sweep's taper) are not bounded.
MAX_LEAN_DEG = 45.0


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    n = getattr(value, "n", None)
    return float(n) if isinstance(n, (int, float)) else None


def all_steps(steps):
    for step in steps:
        yield step
        yield from all_steps(step.get("features") or [])


def finishes(step):
    """True for a round or bevel: it changes the part only along the edges it picks."""
    return step_kinds.recipe_kind(step.get("kind")).repeat == step_kinds.FINISH


def only_removes(step):
    """True for a step that never adds material the model lacks: a hole, a shell that goes inward, a cut or intersect,
    and an offsetFaces step (whose moved faces are in the model)."""
    kind = step.get("kind")
    return (step_kinds.recipe_kind(kind).always_cuts or (kind == "shell" and not step.get("outside"))
            or kind == "offsetFaces" or step.get("combine") in ("cut", "intersect"))


def own_size(step):
    """The size of a round or bevel step, 0 for another step, or UNKNOWN."""
    if not finishes(step):
        return 0.0
    found = [number(step.get(key)) for key in ("size", "size2") if key in step]
    if not found or any(size is None for size in found):
        return mbox.UNKNOWN
    return max(abs(size) for size in found)


def finish_size(steps):
    """The largest size of a round or bevel among the written steps (0 without one), or UNKNOWN. Such a step adds
    material only that close to the part."""
    sizes = [own_size(step) for step in all_steps(steps)]
    return mbox.UNKNOWN if mbox.UNKNOWN in sizes else max(sizes + [0.0])


def modeled_ids(placers):
    """Ids of the steps whose material the placers hold."""
    out = set()
    for placer in placers:
        if isinstance(placer, Slab):
            out.update((placer.id, placer.owner))
        elif isinstance(placer, ToolPlacer):
            out.add(placer.owner)
            out |= modeled_ids(placer.placers)
    return out


def adding_slabs_box(placers):
    """The box of the material the slabs among `placers` add, or None when there is none."""
    boxes = []
    for placer in placers:
        if isinstance(placer, Slab) and placer.combine in ("new", "add"):
            boxes.append(mbox.slab_box(placer))
        elif isinstance(placer, ToolPlacer) and placer.combine in ("new", "add"):
            boxes.append(adding_slabs_box(placer.placers))
    boxes = [b for b in boxes if b is not None]
    return mbox.union(boxes) if boxes else None


def bounds(ctx, steps, placers, later):
    """The boxes of the material the steps may add that the model lacks, or UNKNOWN. Each box is grown by the size
    of the rounds and bevels written after its step (`later` for those after the whole list), which may add material
    along its edges."""
    modeled = modeled_ids(placers)
    by_id = {step.get("id"): step for step in steps}
    sizes = [own_size(step) for step in steps]
    if mbox.UNKNOWN in sizes:
        return mbox.UNKNOWN
    boxes = []
    for k, step in enumerate(steps):
        after = max(sizes[k + 1:] + [later])
        found = bound(ctx, step, placers, modeled, by_id, after)
        if found is mbox.UNKNOWN:
            return mbox.UNKNOWN
        # A tool's own list grows its boxes already.
        boxes += found if step.get("kind") == "toolBody" else [mbox.grown(box, after) for box in found]
    return boxes


def bound(ctx, step, placers, modeled, by_id, after=0.0):
    """The boxes of what `step` may add that the model lacks (none for a step whose material the model holds or that
    only removes), or UNKNOWN."""
    kind = step.get("kind")
    if only_removes(step) or finishes(step):
        return []
    if kind == "toolBody":
        tool = next((p for p in placers if isinstance(p, ToolPlacer) and p.owner == step.get("id")), None)
        return mbox.UNKNOWN if tool is None else bounds(ctx, step.get("features") or [], tool.placers, after)
    if kind == "extrude":
        return [] if step.get("id") in modeled else mbox.UNKNOWN
    if kind == "draft":
        return draft_bound(step, placers)
    if kind == "shell":
        return outside_shell_bound(step, placers)
    if kind == "sweep":
        return sweep_bound(ctx, step)
    if step_kinds.recipe_kind(kind).repeats:
        # Copies of steps the model holds are in the model too; a copy of anything else is not bounded.
        for source in step.get("of") or []:
            found = by_id.get(source)
            if found is None or bound(ctx, found, placers, modeled, by_id) != []:
                return mbox.UNKNOWN
        return []
    return mbox.UNKNOWN


def outside_shell_bound(step, placers):
    """A shell that grows outward adds its wall outside the material its walk holds, no further than its thickness."""
    thickness = number(step.get("thickness"))
    box = adding_slabs_box(placers)
    if thickness is None or box is None:
        return mbox.UNKNOWN
    return [mbox.grown(box, thickness)]


def draft_bound(step, placers):
    """A draft tilts faces of the material its walk holds: it moves them at most the size of that material's box times
    the tangent of its angle."""
    angle = number(step.get("angleDeg"))
    box = adding_slabs_box(placers)
    if angle is None or box is None or abs(angle) >= MAX_LEAN_DEG:
        return mbox.UNKNOWN
    size = math.sqrt(sum((box[1][i] - box[0][i]) ** 2 for i in range(3)))
    return [mbox.grown(box, size * math.tan(math.radians(abs(angle))))]


def arc_points(curve):
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


def path_points(path):
    out = []
    for curve in (path or {}).get("curves") or []:
        kind = curve.get("kind")
        if kind == "line":
            found = [curve.get("start"), curve.get("end")]
        elif kind == "arc":
            found = arc_points(curve)
        elif kind == "other":
            found = curve.get("samples")
        else:
            found = None
        if not found or any(not isinstance(p, list) or len(p) != 3 for p in found):
            return None
        out += found
    return out or None


def sweep_bound(ctx, step):
    """A sweep carries its profile along its path, each point at its own distance from the path: its material lies
    within the path's box grown by the farthest profile point from where the path starts (both ends when the profile
    plane holds neither), plus what a taper adds over the path's length."""
    item = ctx.item_of_step(step.get("id"))
    data = design.as_read(item).brought_data if item is not None else {}
    points = path_points(data.get("path"))
    if points is None or data.get("rail") or not data.get("profiles"):
        return mbox.UNKNOWN
    profile_points = []
    for profile in data["profiles"]:
        frame = profile.get("frame")
        flat = [p for loop in profile.get("loops") or [] for curve in loop.get("curves") or [] for p in polyline(curve)]
        if not frame or not flat:
            return mbox.UNKNOWN
        profile_points += [vec.frame_apply(frame, [p[0], p[1], 0.0]) for p in flat]
    curves = data["path"]["curves"]
    ends = [curves[0]["start"], curves[-1]["end"]]
    frame = data["profiles"][0]["frame"]
    on_plane = [end for end in ends if abs(vec.dot(vec.sub(end, frame["origin"]), vec.unit(frame["z"]))) < 1e-3]
    starts = on_plane if len(on_plane) == 1 else ends
    reach = max(vec.length(vec.sub(p, start)) for p in profile_points for start in starts)
    taper = data.get("taper_deg") or 0.0
    if not isinstance(taper, (int, float)) or abs(taper) >= MAX_LEAN_DEG:
        return mbox.UNKNOWN
    length = sum(vec.length(vec.sub(b, a)) for a, b in zip(points, points[1:]))
    reach += length * math.tan(math.radians(abs(taper)))
    return [mbox.grown(mbox.box_of(points), reach)]
