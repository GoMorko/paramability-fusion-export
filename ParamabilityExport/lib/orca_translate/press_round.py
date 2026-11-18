"""A Press Pull (Offset Faces) of one whole round face as Orca features: a pin, a boss or a bore whose radius changes.

Orca has no Press Pull, so the ring between the old and the new radius is built as a tool body and joined to the part
or cut from it. The shared layer decides whether the face can be moved (`design_model/steps/offset_round.py`): it goes
all the way round, both its ends are flat faces square to its axis, the new radius stays clear of the other edges of
those faces and above zero, and Fusion left a cylinder of that radius.

- The tool body: a circle on the plane of one end, extruded to the plane of the other end as a new body, less a
  smaller circle cut through all of it. Both circles sit on the axis. The circle of the new radius follows the
  distance (`r + distance` for a pin or a boss, `r - distance` for a bore). The other circle is the face's own radius
  moved by `OVERLAP_MM` into the side the Boolean already fills (material for a join, air for a cut), so the tool
  does not share a round face with the part.
- The Boolean: Add when the distance moves the face out of the material (a pin or a boss that grows, a bore that
  shrinks), Cut when it moves the face into the material (a bore that grows, a pin that shrinks).

The face's radius and the planes of its ends keep their numbers: every size read before the step is marked
(`reach.any_face_sizes`). The step is left out when the face is not on the part as the copy builds it, or when the
ring it cuts meets no material. The parameter's line tells how far the distance may go while the new radius stays
above zero, clear of the other edges of the end faces, and on the same side of the old radius. Flat faces, faces
that are not whole round faces and Press Pulls of several faces are left out with their reasons.
"""
import math

from ..capture_model import gap_hints
from ..design_model import reach
from ..design_model.problem import is_problem
from ..design_model.steps import offset_round as facts
from ..design_model.values import Quantity, number
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from . import causes, limits, tools
from .context import Body
from .skip import Skip
from .solid import ADD, Prism

# How far (mm) the circle at the face's own radius is moved into the side the Boolean already fills. It is half the
# clearance the shared layer keeps from every other edge of the end faces, so it never reaches one.
OVERLAP_MM = facts.CLEAR_MM / 2.0
# The widest ring (mm) on the material side of the face that tells whether the copy holds the face.
_PROBE_MM = 1.0
# A ring thinner than this (mm) between the old and the new radius moves nothing.
_GAP = 1e-6

_UNREAD = "The faces or the distance of this offset could not be read."
_NO_DISTANCE = "This offset has no distance."
_FLAT = "A Press Pull of a flat face is not copied to Orca yet."
_SEVERAL = "A Press Pull of more than one face is not copied to Orca yet."
_CURVED = "Offsets of curved faces are not copied yet."
_FOREIGN = "This offset moves a face of another component, which is not copied."


def _label(item):
    return item.get("name") or "the step"


def _circle(radius):
    return [{"kind": "circle", "center": [0.0, 0.0], "radius": float(radius)}]


def _frame(ring):
    """The frame of the end at the low place along the axis, its z along the axis."""
    z = ring.axis
    helper = min(([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]), key=lambda a: abs(vec.dot(a, z)))
    x = vec.unit(vec.cross(helper, z))
    return {"origin": ring.end_point(0), "x": x, "y": vec.cross(z, x), "z": list(z)}


def _ring(frame, height, inner, outer):
    """The ring between radii `inner` and `outer` about the frame's origin, from the frame's plane `height` along z."""
    return Prism(frame, [_circle(outer), _circle(inner)], 0.0, height)


def _one_face(data):
    """The one round face of the step, or a Skip."""
    distance = data.get("distance")
    faces = data.get("faces") or []
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not faces:
        return Skip(_UNREAD)
    if not math.isfinite(distance) or not abs(number(distance)) > 0:
        return Skip(_NO_DISTANCE)
    if len(faces) > 1:
        return Skip(_SEVERAL, causes.PRESS_PULL_FACES)
    face = faces[0]
    if not facts.is_round(face):
        if isinstance(face, dict) and face.get("kind") != "other" and "loops" in face:
            return Skip(_FLAT, causes.PRESS_PULL_FLAT)
        return Skip(_CURVED, gap_hints.OFFSET_CURVED)
    if face.get("foreign"):
        return Skip(_FOREIGN)
    return face


def press_pull(ctx, step):
    """The Orca features of a Press Pull (`step`, a `design.ResolvedStep`) of one whole round face, or a Skip."""
    item, data = step.brought, step.brought_data
    face = _one_face(data)
    if isinstance(face, Skip):
        return face
    distance = float(data["distance"])
    found = facts.problem(face, distance, data.get("rounds_after") or [])
    if found:
        return Skip.of(found)
    whole = facts.whole(face)
    if is_problem(whole):
        return Skip.of(whole)
    if not ctx.has_body:
        return Skip("The part this offset works on is not in the copy.", gap_hints.AFTER_GAP)
    ring, r = whole.ring, whole.ring.radius
    adds = distance > 0
    new = ring.moved_radius(distance)
    frame, height = _frame(ring), ring.span[1] - ring.span[0]
    missing = _missing(ctx, whole, frame, height, adds, new)
    if missing:
        return missing

    name = _label(item)
    moved = Quantity(r).plus(ctx.quantity(item, "distance", distance).scaled(ring.sign))
    if new > r:
        inner, outer = Quantity(r - OVERLAP_MM), moved
    else:
        inner, outer = moved, Quantity(r + OVERLAP_MM)
    ctx.doubt(tuple(reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item)),
              "%s moves a round face, and Orca keeps that face and the faces at its ends where they are now" % name)

    plane = ctx.place.plane(frame["origin"], frame["x"], frame["y"], frame["z"])
    tool = ctx.push(Body(None, name + " ring"))
    try:
        out = _tool(ctx, name, plane, height, inner, outer)
        ctx.solid.add(ADD, _ring(frame, height, inner.n, outer.n))
    finally:
        ctx.pop()
    out.append(tools.boolean(ctx, tool, BooleanMode.ADD if adds else BooleanMode.CUT, name))
    _guard(ctx, name, whole, out, new > r)
    return out


def _missing(ctx, whole, frame, height, adds, new):
    """A Skip when the copy does not hold the face: no material just on its material side for a join, or no material
    in the ring a cut removes; else None."""
    ring, r = whole.ring, whole.ring.radius
    if adds:
        if ring.sign > 0:
            probe = _ring(frame, height, r - min(_PROBE_MM, (r - whole.low) / 2.0), r)
        else:
            probe = _ring(frame, height, r, r + min(_PROBE_MM, (whole.high - r) / 2.0))
    else:
        probe = _ring(frame, height, min(r, new), max(r, new))
    if ctx.solid.meets(probe):
        return None
    gap = bool(ctx.left_out)
    return Skip("The round face of this offset is not on %s as the Orca copy builds it%s, so it is left out."
                % (ctx.body_words, " (a step before it is left out)" if gap else ""),
                gap_hints.AFTER_GAP if gap else causes.MISSES_PART)


def _tool(ctx, name, plane, height, inner, outer):
    """The outer circle extruded between the end planes as a new body, less the inner circle cut through all of it,
    on the innermost body (the tool). The radii are `Quantity`s."""
    out = []
    for label, radius, mode in (("outer", outer, BooleanMode.NEW), ("inner", inner, BooleanMode.CUT)):
        sketch = tools.feature(FeatureType.SKETCH, "%s %s sketch" % (name, label), shape=SketchShape.CIRCLE,
                               plane=plane, radius=float(radius.n))
        ref = ctx.add(sketch)
        ctx.bind(sketch, "radius", radius, "%s radius" % sketch.name)
        extrude = tools.feature(FeatureType.EXTRUDE, "%s %s" % (name, label), sketch_ref=ref, mode=mode, flip=False)
        if mode == BooleanMode.NEW:
            extrude.extrude_end, extrude.distance = ExtrudeEnd.BLIND, float(height)
        else:
            extrude.extrude_end = ExtrudeEnd.THROUGH_ALL
        ctx.add(extrude)
        ctx.has_body = True
        out += [sketch, extrude]
    return out


def _guard(ctx, name, whole, features, grows):
    """Tell how far the variables may go while the new radius stays above zero, clear of the other edges of the end
    faces and on the same side of the old radius. Past that, Orca joins or cuts the wrong ring without an error, or
    the tool body is empty."""
    sketches = [f for f in features if f.type == FeatureType.SKETCH and "radius" in f.expr]
    if not sketches:
        return
    r = whole.ring.radius

    def ok(numbers):
        radius = numbers[0]
        if (radius - r if grows else r - radius) <= _GAP:
            return limits.Stop(limits.RING_TURNS)
        found = facts.radius_problem(whole, radius)
        if found is None:
            return True
        return limits.Stop(limits.SHAPE_ZERO if found.code == facts.CLOSES else limits.RING_MEETS)

    limits.guard(ctx, [(sketches[0], "radius", "%s radius" % sketches[0].name)], ok,
                 "%s: the Orca copy cannot tell how far this may change while the round face stays clear of the "
                 "other edges" % name)


HANDLERS = {"OffsetFacesFeature": press_pull}
