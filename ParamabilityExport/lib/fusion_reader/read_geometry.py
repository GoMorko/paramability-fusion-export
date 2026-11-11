"""Fusion geometry as plain values, and the shared context of one capture read.

No adsk import at module level, so tests run it with fakes. Fusion stores lengths in cm and angles in radians; every
value leaves here in mm and degrees. Parameters that are model parameters (an object with .value) and plain numbers
are both accepted.
"""
import math

from ..package.units import cm_to_mm, rad_to_deg

_UNIT_DIGITS = 9
_MM_DIGITS = 6


def _clean(value, digits):
    return round(value, digits) + 0.0  # + 0.0 turns -0.0 into 0.0


def value_of(parameter):
    """The number inside a model parameter (.value), or the number itself."""
    return getattr(parameter, "value", parameter)


def length(parameter):
    return _clean(cm_to_mm(value_of(parameter)), _MM_DIGITS)


def angle(parameter):
    return _clean(rad_to_deg(value_of(parameter)), _MM_DIGITS)


def point(p):
    """Point3D in cm to [x, y, z] in mm."""
    return [_clean(cm_to_mm(p.x), _MM_DIGITS), _clean(cm_to_mm(p.y), _MM_DIGITS), _clean(cm_to_mm(p.z), _MM_DIGITS)]


def point3d(p):
    """[x, y, z] in mm to a Fusion Point3D in cm."""
    import adsk.core
    return adsk.core.Point3D.create(p[0] / 10.0, p[1] / 10.0, p[2] / 10.0)


def point2(p):
    """Point3D in cm to [x, y] in mm (a point in sketch space)."""
    return [_clean(cm_to_mm(p.x), _MM_DIGITS), _clean(cm_to_mm(p.y), _MM_DIGITS)]


def unit_vector(v):
    """Vector3D (any length) to a unit [x, y, z]; a zero vector stays zero."""
    x, y, z = v.x, v.y, v.z
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0:
        return [0.0, 0.0, 0.0]
    return [_clean(x / n, _UNIT_DIGITS), _clean(y / n, _UNIT_DIGITS), _clean(z / n, _UNIT_DIGITS)]


def type_name(entity):
    """The part of objectType after the last '::' ('adsk::fusion::ExtrudeFeature' gives 'ExtrudeFeature')."""
    if entity is None:
        return "none"
    text = getattr(entity, "objectType", "") or ""
    return text.split("::")[-1] or "none"


def enum_name(value, *enum_classes):
    """Name of an enum value. Strings pass through; integers are looked up in adsk.fusion / adsk.core under each
    class name given (in order); else ''."""
    if isinstance(value, str):
        return value
    try:
        import adsk.core
        import adsk.fusion
        for module, enum_class in ((m, c) for c in enum_classes for m in (adsk.fusion, adsk.core)):
            holder = getattr(module, enum_class, None)
            if holder is None:
                continue
            for name in dir(holder):
                if not name.startswith("_") and getattr(holder, name) == value:
                    return name
    except Exception:
        pass
    return ""


def pick_by_text(name, table, default):
    """First table value whose key text is inside the lower case name. Enum value names are not all verified."""
    text = (name or "").lower()
    for key, result in table:
        if key in text:
            return result
    return default


def safe(fn, default):
    """Call fn; a retired or missing member gives the default."""
    try:
        return fn()
    except Exception:
        return default


def frame_of(matrix):
    """Matrix3D to { origin, x, y, z } (unit axes, origin in mm)."""
    origin, x, y, z = matrix.getAsCoordinateSystem()
    return {"origin": point(origin), "x": unit_vector(x), "y": unit_vector(y), "z": unit_vector(z)}


def box_of(body):
    box = body.boundingBox
    return {"min": point(box.minPoint), "max": point(box.maxPoint)}


def target_volume(ctx):
    """Volume of the target body in mm3 at the current marker position, or None."""
    body = ctx.find_target()
    return safe(lambda: round(body.volume * 1000.0, 6) + 0.0, None) if body is not None else None


def volume_mm3(body):
    """Volume of a body in mm3, or None when it cannot be read."""
    return safe(lambda: round(body.volume * 1000.0, 6) + 0.0, None)


# Vertices read per body to follow a body through a Paste, a Move or a pattern.
BODY_POINTS = 8


def native_object(entity):
    """The native object of an entity seen through an occurrence, else the entity."""
    if safe(lambda: entity.assemblyContext, None) is None:
        return entity
    return safe(lambda: entity.nativeObject, None) or entity


def vertex_points(body, limit=BODY_POINTS):
    """The first `limit` vertex points of a body in mm, in the body's own coordinates and vertex order. A list with
    one vertex that cannot be read is empty, since a gap would shift the order the points are matched by."""
    vertices = safe(lambda: body.vertices, None)
    found = []
    for i in range(min(safe(lambda: int(vertices.count), 0), limit)):
        p = safe(lambda: point(vertices.item(i).geometry), None)
        if p is None:
            return []
        found.append(p)
    return found


def same_entity(a, b):
    """True when two Fusion objects are the same entity. Token text is not compared: Fusion can give one entity
    different tokens over time."""
    if a is None or b is None:
        return False
    try:
        return a is b or bool(a == b)
    except Exception:
        return False


def find_native(design, token):
    """The native entity for a token: the match without an assembly context, else the native object of the first."""
    raw = safe(lambda: design.findEntityByToken(token), None)
    found = list(raw) if raw else []
    for entity in found:
        if safe(lambda: entity.assemblyContext, None) is None:
            return entity
    if found:
        return safe(lambda: found[0].nativeObject, None)
    return None


def component_of(entity):
    """The component that owns an entity (a body, sketch, profile, plane, face or edge), or None."""
    for read in (lambda: entity.parentComponent, lambda: entity.component, lambda: entity.body.parentComponent,
                 lambda: entity.parentSketch.parentComponent, lambda: entity.sketch.parentComponent):
        component = safe(read, None)
        if component is not None:
            return component
    return None


def native_input(entity, ctx):
    """The native object of an entity of the target's component that Fusion hands over through an occurrence (a
    feature's profiles, edges and planes can come so). Native objects are in component coordinates, like the target.
    Any other entity is returned as it is."""
    if entity is None or ctx is None or safe(lambda: entity.assemblyContext, None) is None:
        return entity
    native = safe(lambda: entity.nativeObject, None)
    if native is not None and same_entity(component_of(native), ctx.component):
        return native
    return entity


def foreign(entity, ctx):
    """True when the entity is seen through an occurrence or belongs to another component than the target's.
    The target component's own entities seen through an occurrence are not foreign (see `native_input`)."""
    if entity is None or ctx is None:
        return False
    entity = native_input(entity, ctx)
    if safe(lambda: entity.assemblyContext, None) is not None:
        return True
    component = component_of(entity)
    return component is not None and not same_entity(component, ctx.component)


def mark_foreign(record, entity, ctx):
    """Adds "foreign": true to a record when its entity is foreign (see `foreign`); returns the record."""
    if isinstance(record, dict) and foreign(entity, ctx):
        record["foreign"] = True
    return record


def body_ref(body, ctx=None):
    body = native_input(body, ctx)
    return mark_foreign({"token": safe(lambda: body.entityToken, ""), "name": safe(lambda: body.name, "")}, body, ctx)


def collection_items(collection):
    """Items of a Fusion collection (count and item(i)); empty for None or a collection that cannot be read."""
    if collection is None:
        return []
    try:
        return [collection.item(i) for i in range(collection.count)]
    except Exception:
        return []


def owner_body(entity, ctx):
    """{ token, name } of the body a face or edge lies on, or None when Fusion does not give it."""
    body = safe(lambda: entity.body, None)
    found = safe(lambda: body_ref(body, ctx), None) if body is not None else None
    if not found or not (found.get("token") or found.get("name")):
        return None
    return {"token": found.get("token"), "name": found.get("name")}


def body_refs(collection, ctx=None):
    return [body_ref(b, ctx) for b in collection_items(collection)]


def plane_of(entity):
    """{ point, normal } for a ConstructionPlane or a planar BRepFace; None for anything else."""
    try:
        geometry = entity.geometry
        if type_name(geometry) != "Plane":
            return None
        return {"point": point(geometry.origin), "normal": unit_vector(geometry.normal)}
    except Exception:
        return None


def outward_normal(face):
    """Unit outward normal of a BRepFace at a point on it; raises when Fusion gives none."""
    ok, normal = face.evaluator.getNormalAtPoint(face.pointOnFace)
    if not ok:
        raise ValueError("The normal of a face could not be read.")
    return unit_vector(normal)


def surface_kind(face):
    """The surface of a BRepFace as "Plane", "Cylinder", "Cone" or "other"."""
    name = type_name(face.geometry)
    return name if name in ("Plane", "Cylinder", "Cone") else "other"


def point_at(curve, fraction):
    """Point3D at a fraction (0..1) of the parameter range of a curve or edge, or None."""
    try:
        evaluator = curve.evaluator
        ok, low, high = evaluator.getParameterExtents()
        if not ok:
            return None
        ok, p = evaluator.getPointAtParameter(low + (high - low) * fraction)
        return p if ok else None
    except Exception:
        return None


def _same_vertex(a, b):
    if a is None or b is None:
        return False
    if a is b:
        return True
    token_a = safe(lambda: a.entityToken, None)
    return token_a is not None and token_a == safe(lambda: b.entityToken, None)


def edge_fractions(closed):
    """Where an edge is measured: its middle, or 0.25 and 0.75 of a closed edge."""
    return (0.25, 0.75) if closed else (0.5,)


def edge_record(edge, ctx=None):
    """{ token, closed, points }: the middle point of an open edge; the points at 0.25 and 0.75 of a closed one."""
    edge = native_input(edge, ctx)
    closed = _same_vertex(safe(lambda: edge.startVertex, None), safe(lambda: edge.endVertex, None))
    points = []
    for fraction in edge_fractions(closed):
        p = point_at(edge, fraction)
        if p is not None:
            points.append(point(p))
    if not points and not closed:
        fallback = safe(lambda: edge.pointOnEdge, None)
        if fallback is not None:
            points.append(point(fallback))
    record = {"token": safe(lambda: edge.entityToken, ""), "closed": closed, "points": points}
    return mark_foreign(record, edge, ctx)


class ReadContext:
    """What one capture read shares: the design, the root, the target body and the component it lives in.

    The target is kept native (component coordinates): a picked body inside a component arrives as an occurrence
    proxy and `nativeObject` gives the body the timeline features work on.
    """

    def __init__(self, design, target):
        self.design = design
        self.root = design.rootComponent
        self.picked = target
        native = safe(lambda: target.nativeObject, None) if safe(lambda: target.assemblyContext, None) else None
        self.target = native or target
        self.target_ref = body_ref(self.target)
        self.component = safe(lambda: self.target.parentComponent, None) or self.root
        self.component_token = safe(lambda: self.component.entityToken, "") or ""
        self.is_root_component = same_entity(self.component, self.root)

    def find_target(self):
        """The target body (native) at the current marker position, or None when it does not exist yet.

        Looked up by token; the target's component is searched by name when the token is not found.
        """
        token = self.target_ref["token"]
        if token:
            found = safe(lambda: self.design.findEntityByToken(token), None)
            if found:
                return found[0]
        name = self.target_ref["name"]
        for body in collection_items(safe(lambda: self.component.bRepBodies, None)):
            if name and safe(lambda: body.name, None) == name:
                return body
        return None

    def target_box(self):
        body = self.find_target()
        return safe(lambda: box_of(body), None) if body is not None else None
