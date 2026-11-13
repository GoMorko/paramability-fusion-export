"""Fillet, chamfer, shell and draft features as plain dicts (docs/capture-format.md).

All four read their inputs with the timeline marker just before the item, so the edges and faces still exist in
the shape the feature was applied to. Edge and face inputs are expanded here: a face gives its edges, and a tangent
chain gives every tangentially connected edge or face, so the translator sees one flat list of picks. A fillet or
chamfer set also keeps how its edges were picked: the faces it was given (`faces`), whether it follows tangent
chains (`tangent_chain`), and on each picked edge of a chain `seed`, so the copy can pick the same way.
A required collection that cannot be read raises, and the walk records that as a read_error for the item.

A chamfer with two distances, or a distance and an angle, also records at each edge point the outward normals of
the edge's two faces (`sides`, before) and the normal of the chamfer face nearest to it (`cut_normals`, after). The
API does not say which face takes the first distance; the chamfer face tells, since it leans towards the face with
the longer distance.
"""
import math

from . import read_geometry as geo
from .param_refs import Params, with_params

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
    """Items of a Fusion collection or vector; unlike geo.collection_items, an unreadable one raises."""
    return geo.sequence_items(collection)


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
    """(input kinds, edges, faces, seeds) of a set input: faces give their edges, tangent chains are completed,
    features stay out. `faces` are the face inputs; `seeds` the tokens of the edge inputs."""
    kinds, edges, faces, seeds = [], [], [], set()
    for entity in entities:
        kind = _input_kind(entity)
        if kind not in kinds:
            kinds.append(kind)
        if kind == "edge" and _token(entity):
            seeds.add(_token(entity))
        if kind == "edge":
            edges += _chain(entity, "tangentiallyConnectedEdges", tangent_chain)
        elif kind == "face":
            faces.append(entity)
            edges += geo.safe(lambda: strict_items(entity.edges), [])
    return kinds, _unique(edges), _unique(faces), seeds


def _edge_set(edge_set, ctx, tangent_default=True, sides=False):
    tangent_chain = geo.safe(lambda: bool(edge_set.isTangentChain), tangent_default)
    kinds, edges, faces, seeds = expand_edges(strict_items(edge_set.edges), tangent_chain)
    records = [geo.edge_record(e, ctx) for e in edges]
    if sides:
        for record, edge in zip(records, edges):
            found = geo.safe(lambda: _edge_sides(geo.native_input(edge, ctx), record), None)
            if found:
                record["sides"] = found
    out = {"input_kinds": kinds, "edges": records, "tangent_chain": tangent_chain}
    if tangent_chain:
        for record, edge in zip(records, edges):
            if _token(edge) in seeds:
                record["seed"] = True
    if faces:
        out["faces"] = [geo.safe(lambda: _face_record(f, ctx), None) for f in faces]
        if any(face is None for face in out["faces"]):
            del out["faces"]
    return out


def _normal_at(face, point):
    ok, normal = face.evaluator.getNormalAtPoint(point)
    if not ok:
        raise ValueError("The normal of a face could not be read.")
    return geo.unit_vector(normal)


def _edge_sides(edge, record):
    """Per measured point of the edge, the outward normals of its two faces; None when they cannot be read."""
    faces = strict_items(edge.faces)
    if len(faces) != 2:
        return None
    points = [geo.point_at(edge, f) for f in geo.edge_fractions(record["closed"])]
    if any(p is None for p in points) or len(points) != len(record["points"]):
        return None
    return [[_normal_at(face, p) for face in faces] for p in points]


def _fillet_set(edge_set, ctx):
    name = geo.type_name(edge_set)
    kind = geo.pick_by_text(name, _FILLET_SET_KINDS, "other")
    entry = {"kind": kind}
    if kind == "other":
        entry["type"] = name
    if kind == "constant":
        entry["radius"] = geo.length(edge_set.radius)
        entry["continuity"] = _named(
            lambda: edge_set.continuity, "SurfaceContinuityTypes", _CONTINUITY, "other", "other")
    entry.update(_edge_set(edge_set, ctx))
    return entry


def _set_params(edge_sets, members):
    """params of edge sets: `members` maps a capture field to (set member name, kind)."""
    found = Params()
    for n, edge_set in enumerate(edge_sets):
        for field, (member, kind) in members.items():
            found.add("sets.%d.%s" % (n, field), lambda: getattr(edge_set, member), kind)
    return found.found


def fillet_before(feature, ctx):
    edge_sets = strict_items(feature.edgeSets)
    return with_params({
        "rolling_ball": geo.safe(lambda: bool(feature.isRollingBallCorner), True),
        "sets": [_fillet_set(s, ctx) for s in edge_sets],
    }, _set_params(edge_sets, {"radius": ("radius", "length")}))


def _chamfer_set(edge_set, ctx):
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
    entry.update(_edge_set(edge_set, ctx, sides=entry["kind"] in UNEVEN_KINDS))
    return entry


UNEVEN_KINDS = ("twoDistances", "distanceAngle")


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _cut_normal(faces, p):
    """The normal of the face of `faces` nearest to point `p` (mm), at the point nearest to `p`; None when none
    can be measured. A face whose nearest point lies on it wins over one where it lies past its edges."""
    point = geo.point3d(p)
    best = None
    for face in faces:
        evaluator = face.evaluator
        ok, parameter = evaluator.getParameterAtPoint(point)
        if not ok:
            continue
        ok, nearest = evaluator.getPointAtParameter(parameter)
        found, normal = evaluator.getNormalAtParameter(parameter)
        if not ok or not found:
            continue
        key = (not geo.safe(lambda: bool(evaluator.isParameterOnFace(parameter)), False),
               _distance(geo.point(nearest), p))
        if best is None or key < best[0]:
            best = (key, geo.unit_vector(normal))
    return best[1] if best else None


def chamfer_after(feature, ctx, data):
    """cut_normals on each measured edge of an uneven set: the chamfer face normal near each of its points."""
    faces = [geo.native_input(f, ctx) for f in geo.collection_items(geo.safe(lambda: feature.faces, None))]
    if not faces:
        return {}
    for entry in data.get("sets") or []:
        if entry.get("kind") not in UNEVEN_KINDS:
            continue
        for record in entry.get("edges") or []:
            if "sides" not in record:
                continue
            normals = [geo.safe(lambda: _cut_normal(faces, p), None) for p in record["points"]]
            if all(n is not None for n in normals):
                record["cut_normals"] = normals
    return {"sets": data.get("sets") or []}


def _chamfer_params(edge_sets):
    found = Params()
    for n, edge_set in enumerate(edge_sets):
        name = geo.type_name(edge_set)
        prefix = "sets.%d." % n
        if "EqualDistance" in name:
            found.add(prefix + "distance", lambda: edge_set.distance)
        elif "TwoDistances" in name:
            found.add(prefix + "distance", lambda: edge_set.distanceOne)
            found.add(prefix + "distance_two", lambda: edge_set.distanceTwo)
        elif "DistanceAndAngle" in name or "DistanceAngle" in name:
            found.add(prefix + "distance", lambda: edge_set.distance)
            found.add(prefix + "angle_deg", lambda: edge_set.angle, "angle")
    return found.found


def chamfer_before(feature, ctx):
    edge_sets = strict_items(feature.edgeSets)
    return with_params({
        "corner_type": _named(lambda: feature.cornerType, "ChamferCornerTypes", _CORNER_TYPES, "chamfer", "other"),
        "sets": [_chamfer_set(s, ctx) for s in edge_sets],
    }, _chamfer_params(edge_sets))


def _face_record(face, ctx):
    face = geo.native_input(face, ctx)
    return geo.mark_foreign({"token": _token(face), "point": geo.point(face.pointOnFace)}, face, ctx)


def shell_before(feature, ctx):
    tangent_chain = geo.safe(lambda: bool(feature.isTangentChain), False)
    bodies_input, faces, foreign_body = False, [], False
    for entity in strict_items(feature.inputEntities):
        name = geo.type_name(entity)
        if name == "BRepBody":
            bodies_input = True
            foreign_body = foreign_body or geo.foreign(entity, ctx)
        elif name == "BRepFace":
            faces += _chain(entity, "tangentiallyConnectedFaces", tangent_chain)
    data = {
        "faces": [_face_record(f, ctx) for f in _unique(faces)],
        "bodies_input": bodies_input,
        "inside": geo.length(feature.insideThickness),
        "outside": geo.safe(lambda: geo.length(feature.outsideThickness), 0.0),
        "shell_type": _named(lambda: feature.shellType, "ShellTypes", _SHELL_TYPES, "sharp", "other"),
    }
    if foreign_body:
        data["foreign"] = True
    return with_params(data, Params().add("inside", lambda: feature.insideThickness).found)


def _drafted_face(face, ctx):
    """A face a draft leans: its point and token like a shell face, with its box."""
    record = _face_record(face, ctx)
    record["box"] = geo.safe(lambda: geo.box_of(geo.native_input(face, ctx)), None)
    return record


def draft_before(feature, ctx):
    """The faces (tangent chains completed), the plane that gives the pull direction, the angle definition and the
    target's volume. `draftDefinition` is an `AngleExtentDefinition` (one angle; `symmetric` leans the faces away
    from the plane on both sides) or a `TwoSidesAngleExtentDefinition` (`angle_two_deg` for the second side)."""
    from .read_repeat import plane_record  # read_repeat reads collections with this module
    tangent_chain = geo.safe(lambda: bool(feature.isTangentChain), False)
    faces = []
    for face in strict_items(feature.inputFaces):
        faces += _chain(face, "tangentiallyConnectedFaces", tangent_chain)
    definition = feature.draftDefinition
    two = geo.type_name(definition) == "TwoSidesAngleExtentDefinition"
    first = (lambda: definition.angleOne) if two else (lambda: definition.angle)
    data = {
        "faces": [_drafted_face(f, ctx) for f in _unique(faces)],
        "tangent_chain": tangent_chain,
        "plane": geo.safe(lambda: plane_record(feature.plane, ctx), None),
        "flipped": geo.safe(lambda: bool(feature.isDirectionFlipped), None),
        "two_angles": two,
        "symmetric": False if two else geo.safe(lambda: bool(definition.isSymmetric), None),
        "angle_deg": geo.angle(first()),
        "angle_two_deg": geo.angle(definition.angleTwo) if two else None,
        "volume_before": geo.target_volume(ctx),
        "volume_after": None,
    }
    found = Params().add("angle_deg", first, "angle")
    if two:
        found.add("angle_two_deg", lambda: definition.angleTwo, "angle")
    return with_params(data, found.found)


def draft_after(feature, ctx, data):
    return {"volume_after": geo.target_volume(ctx)}


# type name -> (before, after); either may be None
READERS = {
    "FilletFeature": (fillet_before, None),
    "ChamferFeature": (chamfer_before, chamfer_after),
    "ShellFeature": (shell_before, None),
    "DraftFeature": (draft_before, draft_after),
}
