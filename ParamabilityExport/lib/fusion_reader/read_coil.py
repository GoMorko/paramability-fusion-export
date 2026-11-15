"""Coil features (adsk.fusion.CoilFeature) as plain dicts (docs/capture-format.md).

Fusion's API gives an existing coil only the members every feature has: no type, section, hand, axis, base plane or
operation. The reader therefore takes what Fusion does show:
- the model parameters the coil made (Diameter, SectionSize, TaperAngle, Revolutions, Height or Pitch), by their role;
- the bodies before the coil and the bodies it made or changed, with their volumes, which tell how it combined;
- the flat end faces of the coil (the wire's section, on a plane through the axis) and a few points along the edges of
  its curved faces, which the translator fits a helix to (`translator/coil/coil_fit.py`).
Nothing here guesses: a member that cannot be read is left out, and the translator then refuses the coil.
"""
from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_face import face_loops

# Roles of the parameters of a coil: lower case, no spaces -> (capture path, unit kind).
_ROLES = {
    "diameter": ("diameter", "length"),
    "sectionsize": ("section_size", "length"),
    "taperangle": ("taper_deg", "angle"),
    "revolutions": ("revolutions", "scalar"),
    "height": ("height", "length"),
    "pitch": ("pitch", "length"),
}
MAX_PARAMETERS = 4000
MAX_BODIES = 64
# A coil has two flat end faces and up to four curved faces (a triangle section has three); more is not a coil shape.
MAX_FACES = 8
MAX_FLAT = 2
MAX_EDGES = 24
EDGE_POINTS = 16


def _made_by(parameter, feature, token):
    maker = geo.safe(lambda: parameter.createdBy, None)
    if maker is None:
        return False
    if geo.same_entity(maker, feature):
        return True
    return bool(token) and geo.safe(lambda: maker.entityToken, "") == token


def _feature_parameters(feature, ctx):
    """The model parameters this coil made, as `(roles, params)`: every role text, and the `params` map of the roles
    the translator uses."""
    component = geo.safe(lambda: feature.parentComponent, None) or ctx.component
    token = geo.safe(lambda: feature.entityToken, "")
    roles, found = [], Params()
    for number, parameter in enumerate(geo.iter_items(geo.safe(lambda: component.modelParameters, None))):
        if number >= MAX_PARAMETERS:
            break
        if not _made_by(parameter, feature, token):
            continue
        role = geo.safe(lambda: parameter.role, "") or ""
        roles.append(role)
        path = _ROLES.get(role.replace(" ", "").lower())
        if path is not None:
            found.add(path[0], lambda parameter=parameter: parameter, path[1])
    return roles, found.found


def _volumes(bodies):
    """`[{ token, volume }]` for the bodies of a collection, volume in mm3 (null when it cannot be read)."""
    out = []
    for body in geo.collection_items(bodies)[:MAX_BODIES]:
        out.append({"token": geo.safe(lambda: body.entityToken, "") or "", "name": geo.safe(lambda: body.name, "") or "",
                    "volume": geo.volume_mm3(body)})
    return out


def coil_before(feature, ctx):
    """roles, params and `volumes_before`: the bodies of the component with the marker just before the coil."""
    roles, params = _feature_parameters(feature, ctx)
    data = {"roles": roles, "volumes_before": geo.safe(lambda: _volumes(ctx.component.bRepBodies), None)}
    return with_params(data, params)


def _edge_points(edge):
    """EDGE_POINTS + 1 points (mm) along an edge, or None when it cannot be evaluated."""
    evaluator = geo.safe(lambda: edge.evaluator, None)
    extents = geo.safe(lambda: evaluator.getParameterExtents(), None)
    if not extents or not extents[0]:
        return None
    low, high = extents[1], extents[2]
    points = []
    for step in range(EDGE_POINTS + 1):
        found = geo.safe(lambda t=low + (high - low) * step / EDGE_POINTS: evaluator.getPointAtParameter(t), None)
        if not found or not found[0]:
            return None
        points.append(geo.point(found[1]))
    return points


def _face_edges(face, seen):
    """The sampled edges of one face that were not met on an earlier face (`seen` holds their tokens)."""
    found = []
    for loop in geo.collection_items(geo.safe(lambda: face.loops, None)):
        for edge in geo.collection_items(geo.safe(lambda: loop.edges, None)):
            token = geo.safe(lambda: edge.entityToken, "") or ""
            if token and token in seen:
                continue
            seen.add(token)
            points = _edge_points(edge)
            if points is not None:
                found.append(points)
    return found


def _faces(feature, ctx):
    """`{ flat, curved, edges }`: the flat faces with their outline and area, the number of curved faces, and the
    sampled edges of the curved ones; null when the faces cannot be read or are too many for a coil."""
    faces = geo.collection_items(geo.safe(lambda: feature.faces, None))
    if not faces or len(faces) > MAX_FACES:
        return None
    flat, curved, edges, seen = [], 0, [], set()
    for face in faces:
        face = geo.native_input(face, ctx)
        if geo.safe(lambda: geo.surface_kind(face), None) == "Plane":
            outline = geo.safe(lambda: face_loops(face, ctx), None)
            area = geo.safe(lambda: round(face.area * 100.0, 6) + 0.0, None)
            if outline is None or area is None:
                return None
            flat.append(dict(outline, area=area))
        else:
            curved += 1
            edges.extend(geo.safe(lambda: _face_edges(face, seen), []))
    if len(flat) > MAX_FLAT or len(edges) > MAX_EDGES:
        return None
    return {"flat": flat, "curved": curved, "edges": edges}


def coil_after(feature, ctx, data):
    """`made` (the bodies the coil made or changed, with their volumes after it) and `faces` (see `_faces`)."""
    return {"made": geo.safe(lambda: _volumes(feature.bodies), None),
            "faces": geo.safe(lambda: _faces(feature, ctx), None)}


READERS = {"CoilFeature": (coil_before, coil_after)}
