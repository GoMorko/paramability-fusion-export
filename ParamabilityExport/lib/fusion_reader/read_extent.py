"""The extents of an extrude as plain dicts (docs/capture-format.md): where it starts, how each side ends, and the
face or plane it starts from or reaches to. The extrude and the hole reader (`read_solid`, `read_hole`) read them here.
A member that is missing reads as None or as an `other` entry, never as a plausible value.
"""
from . import read_geometry as geo
from .placement import foreign_target_ref, outline_in_target
from .read_face import face_loops


def construction_token(entity):
    """{ "token": ... } for a construction plane or axis (it names the parameters behind it), else {}."""
    if geo.type_name(entity) in ("ConstructionPlane", "ConstructionAxis"):
        token = geo.safe(lambda: entity.entityToken, "")
        if token:
            return {"token": token}
    return {}


def to_entity(definition):
    """The face or plane an extent definition goes to: `toEntity` on a `OneSideToExtentDefinition` (the extent of a
    hole up to a face), `entity` on the others."""
    if geo.type_name(definition) == "OneSideToExtentDefinition":
        return definition.toEntity
    return definition.entity


def target(definition, ctx, slot):
    """The face or plane an extrude starts from or reaches to, or a hole reaches to: its plane, its type, its token,
    and a point on a face. One of another component is marked foreign and carries its measured reference (`ref`, see
    `placement.ref_record`)."""
    entity = geo.native_input(geo.safe(lambda: to_entity(definition), None), ctx)
    found = {"plane": geo.safe(lambda: geo.plane_of(entity), None),
             "entity_type": geo.safe(lambda: geo.type_name(entity), None)}
    found.update(construction_token(entity))
    if found["entity_type"] == "BRepFace":
        found["surface"] = geo.safe(lambda: geo.surface_kind(entity), None)
        found["face_point"] = geo.safe(lambda: geo.point(entity.pointOnFace), None)
        body = geo.owner_body(entity, ctx)
        if body:
            found["body"] = body
    geo.mark_foreign(found, entity, ctx)
    if found.get("foreign"):
        foreign_target_ref(found, entity, ctx, slot)
    else:
        from .read_reference import describe_plane  # read_reference imports this module

        describe_plane(found, entity, ctx)
        if found["entity_type"] == "BRepFace":
            # The size probe finds the face again by its token and measures how it moves.
            token = geo.safe(lambda: entity.entityToken, "")
            if token:
                found["token"] = token
    return found


def extent(definition, taper_deg, ctx, slot):
    """One side of an extrude as { kind, ... }."""
    name = geo.type_name(definition)
    if "ThroughAll" in name:
        return {
            "kind": "throughAll",
            "positive": geo.safe(lambda: bool(definition.isPositiveDirection), None),
            "taper_deg": taper_deg,
        }
    if name.startswith("All"):
        return {"kind": "all"}
    if "ToEntity" in name:
        # `chained`: Fusion also stops at the faces next to the face (True) or extends the face (False). A flat face
        # that may be chained keeps its outline, which shows whether the extrude lands on that face alone; a face of
        # another component keeps it in its `ref`, in the target's coordinates.
        found = dict({"kind": "toEntity", "offset": geo.safe(lambda: geo.length(definition.offset), None),
                      "chained": geo.safe(lambda: bool(definition.isChained), None)},
                     **target(definition, ctx, slot))
        if found["chained"] is not False and found["entity_type"] == "BRepFace":
            entity = geo.safe(lambda: definition.entity, None)
            outline = geo.safe(lambda: face_loops(entity, ctx), None)
            if not found.get("foreign"):
                found["face_outline"] = outline
            elif isinstance(found.get("ref"), dict):
                found["ref"]["face_outline"] = geo.safe(lambda: outline_in_target(entity, ctx, outline), None)
        return found
    if name == "DistanceExtentDefinition":
        # Fusion can refuse the distance of a valid extrude; the step is then left out, not the whole copy stopped.
        distance = geo.safe(lambda: geo.length(definition.distance), None)
        if distance is None:
            return {"kind": "other", "type": name}
        return {"kind": "distance", "distance": distance, "taper_deg": taper_deg}
    return {"kind": "other", "type": name}


def start(feature, ctx):
    definition = feature.startExtent
    name = geo.type_name(definition)
    if "Offset" in name:
        return {"kind": "offset", "offset": geo.length(definition.offset)}
    if "Entity" in name:
        return dict({"kind": "fromEntity"}, **target(definition, ctx, "start"))
    if "ProfilePlane" in name:
        return {"kind": "profilePlane"}
    return {"kind": "other", "type": name}


def extent_distance(definition):
    """The distance parameter of a plain distance extent, else None."""
    return definition.distance if geo.type_name(definition) == "DistanceExtentDefinition" else None
