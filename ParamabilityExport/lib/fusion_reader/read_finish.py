"""Fillet, chamfer and shell features as plain dicts (docs/capture-format.md).

All three read their inputs with the timeline marker just before the item, so the edges and faces still exist in
the shape the feature was applied to. Edge and face inputs are expanded here: a face gives its edges, and a tangent
chain gives every tangentially connected edge or face, so the translator sees one flat list of picks.
A required collection that cannot be read raises, and the walk records that as a read_error for the item.
"""
from . import read_geometry as geo

_FILLET_SET_KINDS = [
    ("constantradius", "constant"),
    ("variableradius", "variable"),
    ("chordlength", "chordLength"),
    ("asymmetric", "asymmetric"),
    ("doubleradius", "asymmetric"),
]
_CONTINUITY = [("tangent", "tangent"), ("curvature", "curvature")]
_CORNER_TYPES = [("miter", "miter"), ("chamfer", "chamfer")]
_SHELL_TYPES = [("sharp", "sharp"), ("round", "rounded")]


def strict_items(collection):
    """Items of a Fusion collection; unlike geo.collection_items, an unreadable collection raises."""
    return [collection.item(i) for i in range(collection.count)]


def _named(read, enum_class, table, unreadable, unknown):
    """Map an enum member to a table value: `unreadable` when the member is gone, `unknown` for a name not in the table."""
    try:
        value = read()
    except Exception:
        return unreadable
    return geo.pick_by_text(geo.enum_name(value, enum_class), table, unknown)


def _token(entity):
    return geo.safe(lambda: entity.entityToken, "")


def _unique(entities):
    """Entities in order without repeats (by entity token; entities without a token are all kept)."""
    seen, result = set(), []
    for entity in entities:
        token = _token(entity)
        if token:
            if token in seen:
                continue
            seen.add(token)
        result.append(entity)
    return result


def _input_kind(entity):
    name = geo.type_name(entity)
    if name == "BRepEdge":
        return "edge"
    if name == "BRepFace":
        return "face"
    if name.endswith("Feature"):
        return "feature"
    return "other"


def _chain(entity, member, tangent_chain):
    """The entity, then its tangentially connected neighbours when the set asks for the whole chain."""
    found = [entity]
    if tangent_chain:
        found += geo.safe(lambda: strict_items(getattr(entity, member)), [])
    return found


def expand_edges(entities, tangent_chain):
    """(input kinds, edges) of a set input: faces give their edges, tangent chains are completed, features stay out."""
    kinds, edges = [], []
    for entity in entities:
        kind = _input_kind(entity)
        if kind not in kinds:
            kinds.append(kind)
        if kind == "edge":
            edges += _chain(entity, "tangentiallyConnectedEdges", tangent_chain)
        elif kind == "face":
            edges += geo.safe(lambda: strict_items(entity.edges), [])
    return kinds, _unique(edges)


def _edge_set(edge_set, tangent_default=True):
    tangent_chain = geo.safe(lambda: bool(edge_set.isTangentChain), tangent_default)
    kinds, edges = expand_edges(strict_items(edge_set.edges), tangent_chain)
    return {"input_kinds": kinds, "edges": [geo.edge_record(e) for e in edges]}


def _fillet_set(edge_set):
    name = geo.type_name(edge_set)
    kind = geo.pick_by_text(name, _FILLET_SET_KINDS, "other")
    entry = {"kind": kind}
    if kind == "other":
        entry["type"] = name
    if kind == "constant":
        entry["radius"] = geo.length(edge_set.radius)
        entry["continuity"] = _named(
            lambda: edge_set.continuity, "SurfaceContinuityTypes", _CONTINUITY, "other", "other")
    entry.update(_edge_set(edge_set))
    return entry


def fillet_before(feature, ctx):
    return {
        "rolling_ball": geo.safe(lambda: bool(feature.isRollingBallCorner), True),
        "sets": [_fillet_set(s) for s in strict_items(feature.edgeSets)],
    }


def _chamfer_set(edge_set):
    name = geo.type_name(edge_set)
    entry = {"kind": "other", "type": name}
    if "EqualDistance" in name:
        entry = {"kind": "equal", "distance": geo.length(edge_set.distance)}
    elif "TwoDistances" in name:
        entry = {
            "kind": "twoDistances",
            "distance": geo.length(edge_set.distanceOne),
            "distance_two": geo.length(edge_set.distanceTwo),
            "flipped": geo.safe(lambda: bool(edge_set.isFlipped), False),
        }
    elif "DistanceAndAngle" in name or "DistanceAngle" in name:
        entry = {
            "kind": "distanceAngle",
            "distance": geo.length(edge_set.distance),
            "angle_deg": geo.angle(edge_set.angle),
            "flipped": geo.safe(lambda: bool(edge_set.isFlipped), False),
        }
    entry.update(_edge_set(edge_set))
    return entry


def chamfer_before(feature, ctx):
    return {
        "corner_type": _named(lambda: feature.cornerType, "ChamferCornerTypes", _CORNER_TYPES, "chamfer", "other"),
        "sets": [_chamfer_set(s) for s in strict_items(feature.edgeSets)],
    }


def _face_record(face):
    return {"token": _token(face), "point": geo.point(face.pointOnFace)}


def shell_before(feature, ctx):
    tangent_chain = geo.safe(lambda: bool(feature.isTangentChain), False)
    bodies_input, faces = False, []
    for entity in strict_items(feature.inputEntities):
        name = geo.type_name(entity)
        if name == "BRepBody":
            bodies_input = True
        elif name == "BRepFace":
            faces += _chain(entity, "tangentiallyConnectedFaces", tangent_chain)
    return {
        "faces": [_face_record(f) for f in _unique(faces)],
        "bodies_input": bodies_input,
        "inside": geo.length(feature.insideThickness),
        "outside": geo.safe(lambda: geo.length(feature.outsideThickness), 0.0),
        "shell_type": _named(lambda: feature.shellType, "ShellTypes", _SHELL_TYPES, "sharp", "other"),
    }


# type name -> (before, after); either may be None
READERS = {
    "FilletFeature": (fillet_before, None),
    "ChamferFeature": (chamfer_before, None),
    "ShellFeature": (shell_before, None),
}
