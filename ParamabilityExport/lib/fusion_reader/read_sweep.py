"""Sweep and loft features (adsk.fusion.SweepFeature, LoftFeature) as plain dicts.

Before the item: the outlines, the path (or rails, or centre line, and a sweep's guide surfaces) as curves in the target component's coordinates,
and the settings that shape the result (orientation, distances, taper, twist, section end conditions, closed). After
the item: a point and normal on each end face the feature made.

Each member is read on its own: one that cannot be read, or that this Fusion build does not have, becomes null and
the translator refuses the step.
"""
import math

from . import read_geometry as geo
from .param_refs import Params, with_params
from .read_face import face_outline
from .read_solid import operation_of
from .read_sketch import dense_samples, holds_projection, read_curve, read_outlines, sketch_reference

MAX_PATH_ENTITIES = 256
MAX_SECTIONS = 64
MAX_RAILS = 16
MAX_GUIDE_SURFACES = 16
# Item types a loft section given as a collection lists at most.
MAX_COLLECTION_TYPES = 16
_FLAT_MM = 1e-4

_ORIENTATIONS = [("perpendicular", "perpendicular"), ("parallel", "parallel")]
# "noscaling" is tested before "scale": both words are in the option name.
_SCALINGS = [("noscaling", "none"), ("stretch", "stretch"), ("scale", "scale")]
# "point..." conditions are tested before "tangent", which is also in "PointTangent".
_END_CONDITIONS = [("pointsharp", "pointSharp"), ("pointtangent", "pointTangent"), ("direction", "direction"),
                   ("tangent", "tangent"), ("smooth", "smooth"), ("free", "free")]
_POINT_TYPES = ("SketchPoint", "ConstructionPoint", "BRepVertex")


def _round(value):
    return round(value, 6) + 0.0


class _Place:
    """Maps the geometry of one curve into the target component's frame. `frame` is a sketch's `{ origin, x, y, z }`
    (mm); without one the geometry already is in that frame (a body edge). `xy` is the name `dense_samples` calls."""

    def __init__(self, frame=None):
        self.frame = frame

    def xy(self, p):
        x, y, z = geo.point(p)
        f = self.frame
        if f is None:
            return [x, y, z]
        return [_round(f["origin"][i] + f["x"][i] * x + f["y"][i] * y + f["z"][i] * z) for i in range(3)]

    def vector(self, v):
        f = self.frame
        r = [v.x, v.y, v.z] if f is None else [f["x"][i] * v.x + f["y"][i] * v.y + f["z"][i] * v.z for i in range(3)]
        size = math.sqrt(sum(c * c for c in r)) or 1.0
        return [_round(c / size) for c in r]


class _SketchPlane:
    """Reads a curve in its sketch's own 2D frame, shaped like the sketch profile reader's space."""

    @staticmethod
    def xy(p):
        return geo.point2(p)

    @staticmethod
    def direction(vector, at):
        size = math.hypot(vector.x, vector.y) or 1.0
        return [_round(vector.x / size), _round(vector.y / size)]


def _curve_record(geometry, place):
    """One curve in the component frame: line, circle, arc (with `mid`), or `other` with dense `samples`."""
    name = geo.type_name(geometry)
    if name == "Line3D":
        return {"kind": "line", "start": place.xy(geometry.startPoint), "end": place.xy(geometry.endPoint)}
    if name == "Circle3D":
        return {"kind": "circle", "center": place.xy(geometry.center), "normal": place.vector(geometry.normal),
                "radius": geo.length(geometry.radius)}
    mid = geo.point_at(geometry, 0.5) if name == "Arc3D" else None
    if mid is not None:
        return {"kind": "arc", "start": place.xy(geometry.startPoint), "end": place.xy(geometry.endPoint),
                "mid": place.xy(mid), "center": place.xy(geometry.center),
                "normal": place.vector(geometry.normal), "radius": geo.length(geometry.radius)}
    found = dense_samples(geometry, place)
    samples, truncated = found if found else ([], False)
    record = {"kind": "other", "type": name, "start": samples[0] if samples else None,
              "end": samples[-1] if samples else None, "samples": samples}
    if samples:
        record["mid"] = samples[len(samples) // 2]
    if truncated:
        record["truncated"] = True
    return record


def _is_planar(geometry):
    """True when the curve lies on its sketch plane (z = 0 in sketch space); a 3D sketch curve may not."""
    for fraction in (0.0, 0.5, 1.0):
        p = geo.point_at(geometry, fraction)
        if p is None or abs(geo.point(p)[2]) > _FLAT_MM:
            return False
    return True


def flat_record(curve):
    """A sketch curve in its sketch's own 2D plane (`read_curve`), or null for a curve off that plane or one that
    cannot be read."""
    geometry = geo.safe(lambda: curve.geometry, None)
    if geometry is None or not _is_planar(geometry):
        return None
    return geo.safe(lambda: read_curve(geometry, _SketchPlane), None)


def _ends_of(curve):
    """Start and end point of the curve `PathEntity.curve` gives (the check against the read curve), or null."""
    return geo.safe(lambda: {"start": geo.point(curve.startPoint), "end": geo.point(curve.endPoint)}, None)


def _entity_curve(item, ctx):
    """(curve record, source) of one path entity. `source` is ("sketch", sketch) for a sketch curve, ("edge", edge
    record) for a body edge, else (None, None)."""
    entity = geo.native_input(geo.safe(lambda: item.entity, None), ctx)
    name = geo.type_name(entity)
    record, source = None, (None, None)
    if name == "BRepEdge":
        record = geo.safe(lambda: _curve_record(entity.geometry, _Place()), None)
        found = geo.safe(lambda: geo.edge_record(entity, ctx), None)
        owner = geo.safe(lambda: geo.owner_body(entity, ctx), None)
        if found is not None and owner:
            found["body"] = owner
        source = ("edge", found)
    elif name.startswith("Sketch"):
        sketch = geo.safe(lambda: entity.parentSketch, None)
        frame = geo.safe(lambda: geo.frame_of(sketch.transform), None)
        geometry = geo.safe(lambda: entity.geometry, None)
        if frame is not None and geometry is not None:
            record = geo.safe(lambda: _curve_record(geometry, _Place(frame)), None)
            if record is not None:
                record["flat"] = flat_record(entity)
        source = ("sketch", sketch)
    record = record or {"kind": "other", "type": name}
    token = geo.safe(lambda: entity.entityToken, "")
    if token:
        record["entity"] = token
    record["opposed"] = geo.safe(lambda: bool(item.isOpposedToEntity), None)
    record["check"] = geo.safe(lambda: _ends_of(item.curve), None)
    geo.mark_foreign(record, entity, ctx)
    return record, source


def _listed(read, cap):
    """The first `cap` items of the collection `read()` gives; null when it cannot be read."""
    try:
        collection = read()
        return [collection.item(i) for i in range(min(int(collection.count), cap))]
    except Exception:
        return None


def path_record(path, ctx):
    """A `Path` as { closed, kind, curves, edges, truncated?, sketch?, sketch_token?, frame?, reference?, projected? },
    or None when there is none.

    `kind`: `sketch` (every entity is a curve of one sketch), `edges` (every entity is a body edge), `mixed` (both,
    or several sketches) or `other` (an entity that is neither). `curves` lists every entity in path order with its
    geometry in the target component's frame; sketch curves add `flat`, the curve in the sketch's own 2D frame
    (null for a curve off the sketch plane). `edges` holds the edge records (`token`, `points`), so a later pick
    check sees them, each with `body` (the body it lies on) when Fusion gives it. Sketch curves also carry `entity`,
    the token of the curve. `truncated` is true when the path has more than MAX_PATH_ENTITIES entities (only the
    first are read). For a sketch path, `reference` is what the sketch sits on (as on a profile; null when unreadable) and
    `projected` is true when the sketch holds projected curves or points (`read_sketch.holds_projection`, null when
    unreadable)."""
    if path is None:
        return None
    items = _listed(lambda: path, MAX_PATH_ENTITIES + 1)
    record = {"closed": geo.safe(lambda: bool(path.isClosed), None), "kind": "other",
              "curves": None, "edges": []}
    if items is None:
        return record
    if len(items) > MAX_PATH_ENTITIES:
        items = items[:MAX_PATH_ENTITIES]
        record["truncated"] = True
    curves, sketches, edges, others = [], [], [], 0
    for item in items:
        read = geo.safe(lambda: _entity_curve(item, ctx), None)
        curve, (source, found) = read if read else ({"kind": "other", "type": "none"}, (None, None))
        curves.append(curve)
        if source == "sketch" and found is not None:
            if not any(geo.same_entity(found, known) for known in sketches):
                sketches.append(found)
        elif source == "edge" and found is not None:
            edges.append(found)
        else:
            others += 1
    record["curves"] = curves
    record["edges"] = edges
    record["kind"] = _path_kind(curves, sketches, edges, others)
    if record["kind"] == "sketch":
        sketch = sketches[0]
        record["sketch"] = geo.safe(lambda: sketch.name, "") or ""
        token = geo.safe(lambda: sketch.entityToken, "")
        if token:
            record["sketch_token"] = token
        record["frame"] = geo.safe(lambda: geo.frame_of(sketch.transform), None)
        record["reference"] = geo.safe(lambda: sketch_reference(sketch, ctx), None)
        record["projected"] = holds_projection(sketch)
    if any(c.get("foreign") for c in curves):
        record["foreign"] = True
    return record


def _path_kind(curves, sketches, edges, others):
    if not curves or others:
        return "other"
    if edges and sketches:
        return "mixed"
    if edges:
        return "edges"
    return "sketch" if len(sketches) == 1 else "mixed"


def _number(read, kind="scalar"):
    """A value in mm, degrees or as is; null when it cannot be read."""
    convert = {"length": geo.length, "angle": geo.angle}.get(kind, lambda p: _round(float(geo.value_of(p))))
    return geo.safe(lambda: convert(read()), None)


def faces_made(read, ctx):
    """[{ point, normal }] for the faces `read()` gives (a collection or vector, one face or nothing); null when the
    member cannot be read."""
    try:
        raw = read()
    except Exception:
        return None
    if raw is None:
        return []
    faces = geo.collection_items(raw) if geo.is_sequence(raw) else [raw]
    faces = [geo.native_input(f, ctx) for f in faces]
    return [{"point": geo.safe(lambda: geo.point(f.pointOnFace), None),
             "normal": geo.safe(lambda: geo.outward_normal(f), None)} for f in faces]


def _common(feature, ctx):
    return {
        "operation": geo.safe(lambda: operation_of(feature.operation), None),
        "solid": geo.safe(lambda: bool(feature.isSolid), None),
        "participants": geo.safe(lambda: geo.body_refs(feature.participantBodies, ctx), None),
        "target_box_before": ctx.target_box(),
    }


def _outlines(read, ctx, before):
    """(profiles, areas) of `read()`; both null when the outlines cannot be read."""
    found = geo.safe(lambda: read_outlines(read(), ctx, before=before), None)
    return found if found else (None, None)


def _before_index(feature):
    return geo.safe(lambda: feature.timelineObject.index, None)


def _rail(feature, ctx):
    """The guide rail as a path record, null when the sweep has none, `{ "kind": "unread" }` when it cannot be read."""
    unread = {"kind": "unread"}
    try:
        rail = feature.guideRail
    except Exception:
        return unread
    return geo.safe(lambda: path_record(rail, ctx), unread)


def _guide_surfaces(feature, ctx):
    """The guide surfaces of the sweep as `[{ token, surface, body }]` (empty when it has none, at most
    MAX_GUIDE_SURFACES), or `{ "kind": "unread", "said": ... }` when Fusion does not give them."""
    try:
        raw = feature.guideSurfaces
    except Exception as exc:
        return {"kind": "unread", "said": (str(exc) or type(exc).__name__)[:200]}
    faces = [] if raw is None else geo.collection_items(raw) if geo.is_sequence(raw) else [raw]
    out = []
    for face in faces[:MAX_GUIDE_SURFACES]:
        face = geo.native_input(face, ctx)
        out.append({"token": geo.safe(lambda: face.entityToken, ""),
                    "surface": geo.safe(lambda: geo.surface_kind(face), None),
                    "body": geo.safe(lambda: geo.owner_body(face, ctx), None)})
    return out


# Settings of a sweep whose failure the capture explains in `unread`: capture key and API member.
_EXPLAINED = (("orientation", "orientation"), ("taper_deg", "taperAngle"), ("twist_deg", "twistAngle"))


def _why_unread(feature, data):
    """`{ capture key: what Fusion said }` for each setting of `_EXPLAINED` read as null: the error text of the member,
    or "none" when it gave nothing. Empty when all of them were read."""
    out = {}
    for key, member in _EXPLAINED:
        if data.get(key) is not None:
            continue
        try:
            found = getattr(feature, member)
        except Exception as exc:
            out[key] = (str(exc) or type(exc).__name__)[:200]
            continue
        out[key] = "none" if found is None else "unusable %s" % geo.type_name(found)
    return out


def sweep_before(feature, ctx):
    params = Params()
    params.add("distance_one", lambda: feature.distanceOne, "scalar")
    params.add("distance_two", lambda: feature.distanceTwo, "scalar")
    params.add("taper_deg", lambda: feature.taperAngle, "angle")
    params.add("twist_deg", lambda: feature.twistAngle, "angle")
    profiles, areas = _outlines(lambda: feature.profile, ctx, _before_index(feature))
    data = _common(feature, ctx)
    data.update({
        "profiles": profiles,
        "areas": areas,
        "path": geo.safe(lambda: path_record(feature.path, ctx), None),
        "rail": _rail(feature, ctx),
        "guide_surfaces": _guide_surfaces(feature, ctx),
        "orientation": geo.safe(lambda: geo.pick_by_text(
            geo.enum_name(feature.orientation, "SweepOrientationTypes"), _ORIENTATIONS, "other"), None),
        "distance_one": _number(lambda: feature.distanceOne),
        "distance_two": _number(lambda: feature.distanceTwo),
        "taper_deg": _number(lambda: feature.taperAngle, "angle"),
        "twist_deg": _number(lambda: feature.twistAngle, "angle"),
        "scaling": geo.safe(lambda: geo.pick_by_text(
            geo.enum_name(feature.profileScaling, "SweepProfileScalingOptions"), _SCALINGS, "other"), None),
        "extent": geo.safe(lambda: _extent_name(feature.extent), None),
    })
    unread = _why_unread(feature, data)
    if unread:
        data["unread"] = unread
    return with_params(data, params.found)


def _extent_name(raw):
    """The sweep extent setting as text (an enum name, else the object's type name), or null."""
    if raw is None:
        return None
    name = geo.enum_name(raw, "SweepFeatureExtentTypes", "FeatureExtentTypes")
    if not name and hasattr(raw, "objectType"):
        name = geo.type_name(raw)
    return name or None


def sweep_after(feature, ctx, data):
    return {"faces_after": {"start": faces_made(lambda: feature.startFaces, ctx),
                            "end": faces_made(lambda: feature.endFaces, ctx)}}


def _end_record(section, params, number):
    """`end` (the condition's kind; null when unreadable) and, where the condition has them, `angle` (degrees) and
    `weight`. Values that are model parameters also go to `params`."""
    condition = geo.safe(lambda: section.endCondition, None)
    if condition is None:
        return {"end": None}
    kind = geo.pick_by_text(geo.type_name(condition), _END_CONDITIONS, "other")
    out = {"end": kind}
    for member, unit in (("angle", "angle"), ("weight", "scalar")):
        value = _number(lambda: getattr(condition, member), unit)
        if value is not None:
            out[member] = value
            params.add("sections.%d.%s" % (number, member), lambda: getattr(condition, member), unit)
    return out


def _point_of(entity, ctx):
    """[x, y, z] of a sketch point, construction point or vertex in the component frame."""
    if geo.type_name(entity) == "SketchPoint":
        place = _Place(geo.frame_of(entity.parentSketch.transform))
        return place.xy(entity.geometry)
    return geo.point(entity.geometry)


def _section(section, number, profiles, areas, params, ctx, before):
    """One loft section as { kind, end, ... }. A profile section adds its outline to `profiles` and `areas` and holds
    its place in them as `profile`; a face section holds a face record as `face`; a point section holds `point`; a
    chain of edges or sketch curves that Fusion gives as a path holds its path record as `path`."""
    entity = geo.native_input(geo.safe(lambda: section.entity, None), ctx)
    if geo.is_sequence(entity):
        listed = geo.collection_items(entity)
        if len(listed) == 1 and geo.type_name(listed[0]) == "Profile":
            entity = geo.native_input(listed[0], ctx)  # a collection of one profile is that profile
    name = geo.type_name(entity)
    record = _end_record(section, params, number)
    if name == "Profile":
        found = geo.safe(lambda: read_outlines(entity, ctx, before=before), None)
        if found and len(found[0]) == 1:
            record.update(kind="profile", profile=len(profiles))
            profiles.extend(found[0])
            areas.extend(found[1])
            return record
    elif name == "BRepFace":
        found = geo.safe(lambda: face_outline(entity, ctx, before), None)
        if found:
            return dict(record, kind="face", face=found[0])
    elif name in _POINT_TYPES:
        point = geo.safe(lambda: _point_of(entity, ctx), None)
        if point is not None:
            return geo.mark_foreign(dict(record, kind="point", point=point), entity, ctx)
    elif name == "Path":
        found = geo.safe(lambda: path_record(entity, ctx), None)
        if found and found.get("curves"):
            return dict(record, kind="path", path=found)
        return _held_types(record, entity, name)
    elif geo.is_sequence(entity):
        return _held_types(record, entity, name)
    return dict(record, kind="other", type=name)


def _held_types(record, entity, name):
    """A section Fusion gave as a collection the copy cannot use: the types of what it holds say what Fusion gave."""
    listed = geo.safe(lambda: geo.collection_items(entity), None)
    if listed is None:
        return dict(record, kind="other", type=name)
    return dict(record, kind="other", type=name,
                items=[geo.type_name(e) for e in listed[:MAX_COLLECTION_TYPES]], count=len(listed))


def _rails(feature, ctx):
    """(rails, centerline) of `LoftFeature.centerLineOrRails`: a list of paths and null, or an empty list and the
    centre line path. Both are null when the member cannot be read."""
    try:
        holder = feature.centerLineOrRails
    except Exception:
        return None, None
    if holder is None:
        return [], None
    paths = _listed(lambda: holder, MAX_RAILS)
    if paths is None:
        return None, None
    records = [geo.safe(lambda: path_record(p, ctx), None) for p in paths]
    if geo.safe(lambda: bool(holder.isCenterLine), False) and records:
        return [], records[0]
    return records, None


def loft_before(feature, ctx):
    params = Params()
    profiles, areas, sections = [], [], None
    before = _before_index(feature)
    raw = _listed(lambda: feature.loftSections, MAX_SECTIONS)
    if raw is not None:
        sections = [_section(s, n, profiles, areas, params, ctx, before) for n, s in enumerate(raw)]
    rails, centerline = _rails(feature, ctx)
    data = _common(feature, ctx)
    data.update({
        "profiles": profiles if sections is not None else None,
        "areas": areas if sections is not None else None,
        "sections": sections,
        "rails": rails,
        "centerline": centerline,
        "closed": geo.safe(lambda: bool(feature.isClosed), None),
        "merge_tangent": geo.safe(lambda: bool(feature.isTangentEdgesMerged), None),
    })
    return with_params(data, params.found)


def loft_after(feature, ctx, data):
    return {"faces_after": {"start": faces_made(lambda: feature.startFace, ctx),
                            "end": faces_made(lambda: feature.endFace, ctx)}}


# type name -> (before, after); either may be None
READERS = {
    "SweepFeature": (sweep_before, sweep_after),
    "LoftFeature": (loft_before, loft_after),
}
