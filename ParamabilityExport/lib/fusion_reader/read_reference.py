"""What a plane or axis that a feature uses is, so the translator can tell whether sizes move it.

A mirror plane, a pattern axis or a construction plane can be an origin plane, a face or an edge of the part, or
construction geometry built on any of those. `reference_of` describes one such entity as a plain dict:

- `origin`: true for an origin plane or axis of the component; nothing else is read then, it never moves.
- `entity_type`: the type name (`BRepFace`, `BRepEdge`, `ConstructionPlane`, ...).
- `face_point` and `surface` (`Plane`, `Cylinder`, ...) of a face; `edge_points` of an edge.
- construction geometry also gets `token`, its plane (`point`, `normal`) or axis (`point`, `dir`), `made_by` (the
  timeline index of the feature that made it), `definition` (the type name of how it is defined) and `built_on`, the
  descriptions of the entities that definition names.

Every key is optional: a member Fusion does not give is left out, and the translator reads a missing key as unknown.
Entities of another component are left out of `built_on`.
"""
from . import read_geometry as geo
from .placement import ORIGIN_MEMBERS
from .read_solid import axis_of, construction_token

# How deep built_on goes (a plane built on a plane built on a face).
_DEPTH = 3

# Members of the definitions of construction planes and axes that hold the entities they are built on.
_BUILT_ON_MEMBERS = (
    "planarEntity", "planarEntityOne", "planarEntityTwo", "linearEntity", "tangentFace", "referencePlane",
    "edgeOne", "edgeTwo", "pointOne", "pointTwo", "pointThree", "point", "path",
    "circularFace", "edge", "face", "planeOne", "planeTwo", "entity",
)


def _is_origin(entity, name, ctx):
    """True for the origin plane or axis of the target's component."""
    component = getattr(ctx, "component", None)
    return any(geo.same_entity(entity, geo.safe(lambda: getattr(component, member), None))
               for member in ORIGIN_MEMBERS.get(name, ()))


def _built_on(entity, ctx, depth):
    """Descriptions of the entities a construction plane or axis is defined from (own component only)."""
    definition = geo.safe(lambda: entity.definition, None)
    found = []
    for member in _BUILT_ON_MEMBERS:
        source = geo.safe(lambda: getattr(definition, member), None)
        if source is None:
            continue
        source = geo.native_input(source, ctx)
        if not geo.foreign(source, ctx):
            found.append(reference_of(source, ctx, depth - 1))
    return found


def _construction(entity, name, ctx, depth):
    out = construction_token(entity)
    if name == "ConstructionPlane":
        out.update(geo.safe(lambda: geo.plane_of(entity), None) or {})
    else:
        axis = geo.safe(lambda: axis_of(entity), {})
        out.update({k: axis[k] for k in ("point", "dir") if k in axis})
    made_by = geo.safe(lambda: int(entity.timelineObject.index), None)
    if made_by is not None:
        out["made_by"] = made_by
    definition = geo.safe(lambda: geo.type_name(entity.definition), "")
    if definition and definition != "none":
        out["definition"] = definition
    if depth > 0:
        built_on = geo.safe(lambda: _built_on(entity, ctx, depth), [])
        if built_on:
            out["built_on"] = built_on
    return out


def reference_of(entity, ctx, depth=_DEPTH):
    """The description of one plane, axis, face or edge (see the module text)."""
    entity = geo.native_input(entity, ctx)
    name = geo.type_name(entity)
    if name == "none":
        return {}
    if _is_origin(entity, name, ctx):
        return {"origin": True}
    out = {"entity_type": name}
    if name == "BRepFace":
        point = geo.safe(lambda: geo.point(entity.pointOnFace), None)
        if point is not None:
            out["face_point"] = point
        surface = geo.safe(lambda: geo.type_name(entity.geometry), "")
        if surface and surface != "none":
            out["surface"] = surface
    elif name == "BRepEdge":
        points = geo.safe(lambda: geo.edge_record(entity, ctx)["points"], [])
        if points:
            out["edge_points"] = points
    elif name in ORIGIN_MEMBERS:
        out.update(_construction(entity, name, ctx, depth))
    return out


def add_reference(record, entity, ctx):
    """Adds the description of `entity` to a plane or axis `record` (keys the record already has are kept). A record
    of another component is left as it is."""
    if isinstance(record, dict) and not record.get("foreign") and not record.get("assembly"):
        for key, value in geo.safe(lambda: reference_of(entity, ctx), {}).items():
            record.setdefault(key, value)
    return record
