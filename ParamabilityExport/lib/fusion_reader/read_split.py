"""Split Body features as plain dicts (docs/capture-format.md).

Before the item: the bodies it splits, each with its box and volume, and what it splits with (`tool`): a plane (a
construction plane or a flat face, with what it is built on, like a mirror plane), a body, or something else (a curved
face, a sketch curve). After the item: the pieces Fusion lists for the feature, each with its box and volume, and for
a split by a solid body whether the piece lies inside that body.
"""
import math

from ..timing.timer import span_on
from . import read_geometry as geo, read_intersect
from .read_repeat import plane_record

# How far (mm) a point on a face of a piece is moved into the piece before the tool body is asked whether it holds it.
INSIDE_STEP_MM = 0.01
# Faces of a piece tried before the inside test gives up.
MAX_FACES = 16
# The share of a piece's volume that a temporary intersect with the tool keeps: past the upper bound the piece lies
# inside the tool, under the lower one outside it.
INSIDE_SHARE = 0.999
OUTSIDE_SHARE = 0.001


def _state(body, ctx):
    """`{ token, name, box, volume }` of a body at the current marker position."""
    record = geo.body_ref(body, ctx)
    record["box"] = geo.safe(lambda: geo.box_of(geo.native_input(body, ctx)), None)
    record["volume"] = geo.volume_mm3(geo.native_input(body, ctx))
    return record


def _tool(entity, ctx):
    name = geo.type_name(entity)
    if name == "BRepBody":
        body = _state(entity, ctx)
        return {"kind": "body", "body": body, "solid": geo.safe(lambda: bool(entity.isSolid), None)}
    if name in ("ConstructionPlane", "BRepFace"):
        plane = geo.safe(lambda: plane_record(entity, ctx), None)
        if plane and "point" in plane and "normal" in plane:
            return {"kind": "plane", "plane": plane}
        return {"kind": "surface", "type": geo.safe(lambda: geo.type_name(entity.geometry), "other")}
    return {"kind": "other", "type": name}


def split_before(feature, ctx):
    with span_on(ctx, "split"):
        return _split_before(feature, ctx)


def _split_before(feature, ctx):
    tool = geo.native_input(feature.splittingTool, ctx)
    # A tool body of another component comes through an occurrence: its place is kept for the read after the split.
    ctx.held[("split tool", geo.safe(lambda: tool.entityToken, None))] = geo.safe(lambda: tool.assemblyContext, None)
    return {
        "tool": _tool(tool, ctx),
        "extended": geo.safe(lambda: bool(feature.isSplittingToolExtended), None),
        "bodies": [_state(b, ctx) for b in geo.collection_items(feature.splitBodies)],
    }


def _probe(face, tool):
    """True or False when a point just inside the face's body lies inside or outside `tool`; None when unknown."""
    ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
    size = math.sqrt(normal.x ** 2 + normal.y ** 2 + normal.z ** 2) if ok else 0.0
    if not size:
        return None
    at = geo.point(face.pointOnFace)
    inward = [at[0] - normal.x / size * INSIDE_STEP_MM, at[1] - normal.y / size * INSIDE_STEP_MM,
              at[2] - normal.z / size * INSIDE_STEP_MM]
    name = geo.enum_name(tool.pointContainment(geo.point3d(inward)), "PointContainment").lower()
    if "inside" in name:
        return True
    if "outside" in name:
        return False
    return None


def _by_intersect(piece, tool):
    """Whether `piece` lies inside `tool`, from the volume left of a temporary copy of the piece intersected with a
    temporary copy of the tool (nothing is added to the design); None when the volume is not about all or none of it.
    A boolean that reports failure counts as empty, as in `read_intersect`."""
    whole = geo.volume_mm3(piece)
    if not whole:
        return None
    manager, types = read_intersect.brep_tools()
    shared = manager.copy(piece)
    kept = geo.volume_mm3(shared) if manager.booleanOperation(
        shared, manager.copy(tool), types.IntersectionBooleanType) else 0.0
    if kept is None:
        return None
    if kept >= whole * INSIDE_SHARE:
        return True
    return False if kept <= whole * OUTSIDE_SHARE else None


def inside(piece, tool):
    """Whether the body `piece` lies inside the body `tool`: tried on its faces in turn, then by a temporary intersect
    when no face tells; None when neither does."""
    for face in geo.collection_items(geo.safe(lambda: piece.faces, None))[:MAX_FACES]:
        found = geo.safe(lambda: _probe(face, tool), None)
        if found is not None:
            return found
    return geo.safe(lambda: _by_intersect(piece, tool), None)


def _tool_body(feature, ctx, tool):
    """The solid tool body at the current marker position. Fusion gives a feature's splitting tool only while the
    marker sits before the feature, so once it is computed the body is looked up by the token read before it, seen
    through the same occurrence as then (a body of another component sits where its occurrence puts it)."""
    body = geo.native_input(geo.safe(lambda: feature.splittingTool, None), ctx)
    if body is not None:
        return body
    token = (tool.get("body") or {}).get("token")
    if not token:
        return None
    occurrence = ctx.held.get(("split tool", token))
    if occurrence is None:
        return geo.find_native(ctx.design, token)
    for found in geo.safe(lambda: list(ctx.design.findEntityByToken(token)), None) or []:
        if geo.same_entity(geo.safe(lambda: found.assemblyContext, None), occurrence):
            return found
    native = geo.find_native(ctx.design, token)
    return geo.safe(lambda: native.createForAssemblyContext(occurrence), None) if native is not None else None


def split_after(feature, ctx, data):
    with span_on(ctx, "split"):
        return _split_after(feature, ctx, data)


def _split_after(feature, ctx, data):
    """pieces: every body the feature lists once computed. A split by a solid body says per piece whether it lies
    inside that body (`inside`, null when it cannot tell)."""
    tool = data.get("tool") or {}
    by_body = None
    if tool.get("kind") == "body" and tool.get("solid"):
        by_body = _tool_body(feature, ctx, tool)
    pieces = []
    for body in geo.collection_items(feature.bodies):
        record = _state(body, ctx)
        if by_body is not None:
            record["inside"] = inside(geo.native_input(body, ctx), by_body)
        elif tool.get("kind") == "body" and tool.get("solid"):
            record["inside"] = None
        pieces.append(record)
    return {"pieces": pieces}


# type name -> (before, after); either may be None
READERS = {
    "SplitBodyFeature": (split_before, split_after),
}
