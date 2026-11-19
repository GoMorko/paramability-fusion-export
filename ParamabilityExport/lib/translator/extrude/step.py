"""The handler of an extrude feature: checks it and writes one recipe extrude step per outline and side.

Fusion keeps the part where it meets either side of a two sided intersect. Both sides are then written as one tool
body (a new body and a join) that the part intersects (`_intersect_tool`)."""
from ...capture_model import gap_hints
from ...design_model.loops import flip_y
from ...design_model.values import Quantity
from ...geometry import vec
from ...package.numbers import round9
from .. import placement
from ..combine.tool_walk import MAX_DEPTH
from ..faces import thin_wall
from ..faces.placer_makers import SlabMaker, ThinWallMaker
from ..faces.tool_placer import ToolMaker
from ..result import Refusal, StepResult
from ..sketch import face_outline, loops, sketch_motion
from . import thin_line
from .built import outlines_built, thin_wall_step
from .checks import check_measured_length, check_taper, volume_refusal
from .common import COMBINE, UNREADABLE
from .material import cut_toward_material
from .order import touching_order
from .plan import plan_sides
from .reach import sketch_origin, start_shift
from .through import resolve_through


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Extrudes that make a new component are not copied.", cause=gap_hints.NEW_COMPONENT)
    if operation not in COMBINE:
        return Refusal("This extrude combines with the part in a way that is not copied yet.")
    thin = data.get("thin", False)
    if thin is None:
        return Refusal(UNREADABLE)
    wall = None
    if thin:
        wall = thin_wall.prepare(data)
        if isinstance(wall, Refusal):
            return wall
    profiles = data.get("profiles") or []
    if not profiles:
        return Refusal("This extrude has no sketch outline.")
    line = None
    if thin and thin_line.is_line(profiles):
        line = thin_line.line_of(data)
        if isinstance(line, Refusal):
            return line
    elif thin:
        refusal = thin_wall.open_line_refusal(profiles)
        if refusal is None and len(profiles) > 1:
            refusal = Refusal("A thin extrude of several outlines is not copied yet.", cause=gap_hints.THIN_OUTLINE)
        if refusal is not None:
            return refusal
    combine = COMBINE[operation]
    if line is not None:
        loop, drawn = thin_line.outline(ctx, item, line)
        face, drawn_ones, built = None, [line.path], [(line.path, (loop, []), drawn)]
    else:
        face = face_outline.prepare(ctx, item, profiles)
        if isinstance(face, Refusal):
            return face
        drawn_ones = [p for p in profiles if not p.get("face")]
        for profile in drawn_ones:
            refusal = loops.outline_refusal(profile)
            if refusal is not None:
                return refusal
        # Several outlines that Fusion made into one body touch each other, so the first makes it and the rest join.
        if combine == "new" and len(profiles) > 1 and len(item.get("bodies_after") or []) != 1:
            return Refusal("A new body from several outlines makes several bodies, which is not copied yet.")
        built = outlines_built(ctx, item, face, drawn_ones, thin)
        if isinstance(built, Refusal):
            return built
    sources = ([face.profile] if face is not None else []) + drawn_ones
    picked = len(sources)
    profiles = [profile for profile, _, _ in built]
    first_drawn = built[0][2]
    plane_q = first_drawn.plane_shift(ctx) if first_drawn is not None else Quantity(0.0)

    first_frame = profiles[0]["frame"]
    shift_q = start_shift(data, first_frame, ctx, item, plane_q)
    if isinstance(shift_q, Refusal):
        return shift_q
    shift = shift_q.n
    plan = plan_sides(item, data, first_frame, shift_q, ctx, plane_q)
    if isinstance(plan, Refusal):
        return plan
    z0 = vec.unit(first_frame["z"])
    start = vec.add(first_frame["origin"], vec.scale(z0, shift))
    # A cut through all may turn to the side its outlines meet the part on: the taper check reads that side's walls.
    cut_toward_material(ctx, plan, data, profiles, shift, combine)
    for check in (check_measured_length(plan, data, start, z0, combine),
                  check_taper(plan, data, operation, picked),
                  volume_refusal(data, plan, operation, sources, thin)):
        if check:
            return check
    if line is not None:
        thin_step = thin_line.wall_step(ctx, item, data, wall, line, first_drawn, start, plan[0])
    else:
        thin_step = thin_wall_step(ctx, item, data, wall, profiles[0]) if thin else None
    if isinstance(thin_step, Refusal):
        return thin_step
    box_max = ctx.motion.box_max if sketch_motion.active(ctx) else None
    refusal = resolve_through(ctx, plan, data, start, z0, combine, box_max, profiles, item,
                               [drawn for _, _, drawn in built])
    if refusal:
        return refusal
    if combine == "intersect" and len(built) > 1:
        return Refusal("Intersect extrudes with several outlines are not copied yet.")
    both = combine == "intersect" and len(plan) > 1
    if both and ctx.depth + 1 > MAX_DEPTH:
        return Refusal("The tool body for both sides of this intersect would be nested too deep to copy.")
    written = "new" if both else combine

    units = [(one, entry) for one in built for entry in plan]
    if written in ("new", "add") and len(built) > 1:
        units = touching_order(ctx, units, shift, combine == "add")
    out = StepResult()
    for (profile, (outer, inner), drawn), entry in units:
        frame = profile["frame"]
        base = placement.moved_along(placement.from_frame(frame), shift, vec.unit(frame["z"]))
        base["origin"] = drawn.origin(ctx, shift_q) if drawn is not None else sketch_origin(frame, shift_q)
        if drawn is not None:
            outer, inner = drawn.written(ctx)
        if isinstance(thin_step, thin_line.ArcWall):
            outer = thin_step.loop
        reverse = entry.sign < 0
        on = placement.reversed_of(base) if reverse else base
        pick = flip_y if reverse else (lambda loop: loop)
        sketch = {"on": on, "outer": pick(outer)}
        if inner:
            sketch["inner"] = [pick(loop) for loop in inner]
        recipe_step = {
            "kind": "extrude",
            "sketch": sketch,
            "combine": written if not out.entries else ("add" if written == "new" else written),
            "extent": entry.extent,
        }
        if entry.distance is not None:
            recipe_step["distance"] = entry.q.json() if entry.q else round9(entry.distance)
        if entry.taper:
            recipe_step["taperDeg"] = entry.taper_q.json() if entry.taper_q else round9(entry.taper)
        placers = []
        if isinstance(thin_step, thin_line.LineWall):
            # The placer holds the wall as the closed outline it fills, all of it inside that outline.
            recipe_step["thin"] = thin_step.written(reverse)
            placers.append(ThinWallMaker(on, entry.extent, entry.q or Quantity(entry.distance), thin_step.profile,
                                         "inside", thin_step.thickness.n))
            out.add(recipe_step, placers, repeatable=False)
            continue
        if isinstance(thin_step, thin_line.ArcWall):
            # A wall along a line with arcs is written as a plain extrude of its closed outline.
            placers.append(SlabMaker(on, entry.extent, entry.q or Quantity(entry.distance), thin_step.profile,
                                     Quantity(0.0), None))
            out.add(recipe_step, placers, repeatable=False)
            continue
        if thin_step is not None:
            side, thickness_q = thin_step
            recipe_step["thin"] = {"thickness": thickness_q.json(), "side": side}
            placers.append(ThinWallMaker(on, entry.extent, entry.q or Quantity(entry.distance), profile,
                                         side, thickness_q.n))
            out.add(recipe_step, placers, repeatable=False)
            continue
        if entry.extent in ("oneSide", "symmetric"):
            placers.append(SlabMaker(on, entry.extent, entry.q or Quantity(entry.distance), profile,
                                     entry.taper_q or Quantity(entry.taper or 0.0), drawn))
        out.add(recipe_step, placers, repeatable=not entry.adjusts)
    return _intersect_tool(ctx, item, out) if both else out


def _intersect_tool(ctx, item, sides):
    """One `toolBody` step that holds the steps of both sides (`sides`, a new body and a join) and that the part
    intersects."""
    held = ctx.child({"name": item.get("name")}, "%st%s_" % (ctx.id_prefix, item["index"]), depth=ctx.depth + 1)
    held.add_steps(item, sides)
    out = StepResult()
    out.add({"kind": "toolBody", "combine": "intersect", "features": held.steps}, [ToolMaker(held)],
            repeatable=all(entry.repeatable for entry in sides.entries))
    return out
