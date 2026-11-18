"""How a checked revolve is written as Orca features: the sketches, the revolves and the tool bodies.

Orca turns one closed loop per sketch (`CadDocument::build_sketch_wire` takes a single wire), so each loop of an
outline is a sketch of its own, with a construction line on the axis that the revolve names (`revolve_axis_entity`):

- the outer loop is turned once per turn of the `Plan` (one revolve, or the two halves of a symmetric turn: Orca's
  `flip` turns the other way, by the same angle);
- each hole loop is turned the same way and cut away (mode Cut), on a body that holds this outline only. On a part
  that already holds material, the outline is built as a tool body (`Context.push`, outer loop New then hole cuts)
  and a Boolean then adds it, cuts it or keeps what both share (`tools.boolean`), so a hole cuts nothing else;
- several outlines are turned one by one. An intersect of several outlines first joins them in a tool body, since one
  intersect after the other would keep only what all of them share.

The shape of each outline goes into the copy's shape (`solid.Turned`); it gets a seam when Orca joins several
revolves into it (`Turned.seam`).
"""
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, EntityType, FeatureType
from ..orca_recipe.sketch import SketchEntity
from .context import Body
from .solid import ADD, CUT, INTERSECT
from .tools import OPERATIONS, boolean, feature

SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}


class Plan:
    """How every outline of one revolve turns: about the line through `point` along `axis` (unit), by `angle` (a
    `Quantity` in degrees) per Orca revolve, from the sketch plane turned `start` degrees about that line. `flips`
    holds one entry per revolve of a loop: (False,) for one turn, (False, True) for the two halves of a symmetric
    turn."""

    def __init__(self, point, axis, angle, start=0.0, flips=(False,)):
        self.point, self.axis, self.angle, self.start, self.flips = point, axis, angle, start, tuple(flips)


class Part:
    """One outline to turn: its sketch `frame`, the Orca entities of its outer loop and of each hole loop, and its
    shape (`solid.Turned`, holes included)."""

    def __init__(self, frame, outer, holes, shape):
        self.frame, self.outer, self.holes, self.shape = frame, outer, list(holes), shape


def _turned_frame(frame, point, direction, degrees):
    if not degrees:
        return frame
    return {"origin": vec.rotate(frame["origin"], direction, degrees, point),
            "x": vec.rotate(frame["x"], direction, degrees), "y": vec.rotate(frame["y"], direction, degrees),
            "z": vec.rotate(frame["z"], direction, degrees)}


def _sketch(ctx, name, part, plan, entities):
    """Add the sketch of one loop with the construction line on the axis; returns (its index, the line's index)."""
    on = _turned_frame(part.frame, plan.point, plan.axis, plan.start)
    # The turn is about the axis, so the axis has the same sketch coordinates on the turned plane.
    local = vec.frame_to_local(part.frame, plan.point)
    along = [vec.dot(plan.axis, part.frame["x"]), vec.dot(plan.axis, part.frame["y"])]
    line = SketchEntity(type=EntityType.LINE, p0=(local[0], local[1]),
                        p1=(local[0] + 10.0 * along[0], local[1] + 10.0 * along[1]), construction=True)
    made = feature(FeatureType.SKETCH, name, plane=ctx.place.plane(on["origin"], on["x"], on["y"], on["z"]),
                   entities=list(entities) + [line])
    return ctx.add(made), len(entities), made


def _revolves(ctx, name, at, axis_entity, plan, mode_of):
    """One revolve of the sketch at `at` per turn of the plan; `mode_of()` gives the mode of each."""
    out = []
    for flip in plan.flips:
        made = feature(FeatureType.REVOLVE, "%s other side" % name if flip else name, sketch_ref=at,
                       revolve_axis_entity=axis_entity, mode=mode_of(), flip=flip)
        ctx.bind(made, "revolve_angle", plan.angle, "%s angle" % made.name)
        ctx.add(made)
        ctx.has_body = True
        out.append(made)
    return out


def _outline(ctx, name, part, plan, operation):
    """The features of one outline worked by `operation` into the innermost body."""
    if part.holes and ctx.has_body:
        tool = ctx.push(Body(None, "%s tool" % name))
        try:
            out = _outline(ctx, name, part, plan, "join")
        finally:
            ctx.pop()
        out.append(boolean(ctx, tool, OPERATIONS.get(operation, BooleanMode.ADD), "%s into the part" % name))
        return out
    at, axis_entity, sketch = _sketch(ctx, "%s sketch" % name, part, plan, part.outer)
    out = [sketch]
    holes = []
    for n, hole in enumerate(part.holes):
        found = _sketch(ctx, "%s hole %d sketch" % (name, n + 1), part, plan, hole)
        holes.append(found)
        out.append(found[2])
    out += _revolves(ctx, name, at, axis_entity, plan,
                     lambda: OPERATIONS.get(operation, BooleanMode.ADD) if ctx.has_body else BooleanMode.NEW)
    for n, (hole_at, hole_axis, _) in enumerate(holes):
        out += _revolves(ctx, "%s hole %d" % (name, n + 1), hole_at, hole_axis, plan, lambda: BooleanMode.CUT)
    ctx.solid.add(SOLID_MODES[operation], part.shape)
    return out


def write(ctx, name, parts, plan, operation):
    """The Orca features of a revolve of `parts` (checked: each cut or intersect meets the part) worked into the
    innermost body by `operation` ("newBody", "join", "cut" or "intersect")."""
    if len(parts) > 1 or len(plan.flips) > 1:
        for part in parts:
            part.shape.seam = True
    names = [name if n == 0 else "%s (%d)" % (name, n + 1) for n in range(len(parts))]
    if operation == "intersect" and len(parts) > 1:
        tool = ctx.push(Body(None, "%s tool" % name))
        try:
            out = [f for part, tag in zip(parts, names) for f in _outline(ctx, tag, part, plan, "join")]
        finally:
            ctx.pop()
        out.append(boolean(ctx, tool, BooleanMode.INTERSECT, name))
        return out
    return [f for part, tag in zip(parts, names) for f in _outline(ctx, tag, part, plan, operation)]
