"""The handler of an extrude feature: checks it and writes one recipe extrude step per outline and side."""
from ...package.numbers import round9
from .. import face_outline, gap_hints, loops, placement, sketch_motion, thin_wall, vec
from ..placer_makers import SlabMaker, ThinWallMaker
from ..result import Refusal, StepResult
from ..values import Quantity
from .built import outlines_built, thin_wall_step
from .checks import check_measured_length, check_taper, volume_refusal
from .common import COMBINE, UNREADABLE
from .material import cut_toward_material
from .order import touching_order
from .plan import plan_sides
from .reach import sketch_origin, start_shift
from .through import resolve_through


def handle(item, ctx):
    data = item.get("data") or {}
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
    if thin:
        refusal = thin_wall.open_line_refusal(profiles)
        if refusal is None and len(profiles) > 1:
            refusal = Refusal("A thin extrude of several outlines is not copied yet.", cause=gap_hints.THIN_OUTLINE)
        if refusal is not None:
            return refusal
    face = face_outline.prepare(ctx, item, profiles)
    if isinstance(face, Refusal):
        return face
    drawn_ones = [p for p in profiles if not p.get("face")]
    for profile in drawn_ones:
        refusal = loops.outline_refusal(profile)
        if refusal is not None:
            return refusal
    combine = COMBINE[operation]
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
    shift_q = start_shift(data.get("start", {"kind": "profilePlane"}), first_frame, ctx, item, plane_q)
    if isinstance(shift_q, Refusal):
        return shift_q
    shift = shift_q.n
    plan = plan_sides(item, data, first_frame, shift_q, combine, ctx, plane_q)
    if isinstance(plan, Refusal):
        return plan
    z0 = vec.unit(first_frame["z"])
    start = vec.add(first_frame["origin"], vec.scale(z0, shift))
    # A cut through all may turn to the side its outlines meet the part on: the taper check reads that side's walls.
    cut_toward_material(ctx, plan, data, profiles, shift, combine)
    for check in (check_measured_length(plan, data, shift, start, z0, combine),
                  check_taper(plan, data, combine, picked),
                  volume_refusal(data, plan, combine, sources, thin)):
        if check:
            return check
    thin_step = thin_wall_step(ctx, item, data, wall, profiles[0]) if thin else None
    if isinstance(thin_step, Refusal):
        return thin_step
    box_max = ctx.motion.box_max if sketch_motion.active(ctx) else None
    refusal = resolve_through(ctx, plan, data, start, z0, combine, box_max, profiles, item,
                               [drawn for _, _, drawn in built])
    if refusal:
        return refusal
    if combine == "intersect" and (len(plan) * len(built) > 1):
        return Refusal("Intersect extrudes with several outlines are not copied yet.")

    units = [(one, entry) for one in built for entry in plan]
    if combine in ("new", "add") and len(built) > 1:
        units = touching_order(ctx, units, shift, combine == "add")
    out = StepResult()
    for (profile, (outer, inner), drawn), entry in units:
        frame = profile["frame"]
        base = placement.moved_along(placement.from_frame(frame), shift, vec.unit(frame["z"]))
        base["origin"] = drawn.origin(ctx, shift_q) if drawn is not None else sketch_origin(frame, shift_q)
        if drawn is not None:
            outer, inner = drawn.written(ctx)
        reverse = entry["sign"] < 0
        on = placement.reversed_of(base) if reverse else base
        pick = (lambda loop: loops.flip_y(loop)) if reverse else (lambda loop: loop)
        sketch = {"on": on, "outer": pick(outer)}
        if inner:
            sketch["inner"] = [pick(loop) for loop in inner]
        step = {
            "kind": "extrude",
            "sketch": sketch,
            "combine": combine if not out.entries else ("add" if combine == "new" else combine),
            "extent": entry["extent"],
        }
        if entry["distance"] is not None:
            step["distance"] = entry["q"].json() if entry.get("q") else round9(entry["distance"])
        if entry["taper"]:
            step["taperDeg"] = entry["taper_q"].json() if entry.get("taper_q") else round9(entry["taper"])
        placers = []
        if thin_step is not None:
            side, thickness_q = thin_step
            step["thin"] = {"thickness": thickness_q.json(), "side": side}
            placers.append(ThinWallMaker(on, entry["extent"], entry.get("q") or Quantity(entry["distance"]), profile,
                                         side, thickness_q.n))
            out.add(step, placers, repeatable=False)
            continue
        if entry["extent"] in ("oneSide", "symmetric"):
            placers.append(SlabMaker(on, entry["extent"], entry.get("q") or Quantity(entry["distance"]), profile,
                                     entry.get("taper_q") or Quantity(entry["taper"] or 0.0), drawn))
        out.add(step, placers, repeatable=not entry.get("adjusts"))
    return out
