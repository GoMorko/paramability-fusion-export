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


def enum_name(value, enum_class):
    """Name of an enum value. Strings pass through; integers are looked up in adsk.fusion / adsk.core; else ''."""
    if isinstance(value, str):
        return value
    try:
        import adsk.core
        import adsk.fusion
        for module in (adsk.fusion, adsk.core):
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


def body_ref(body):
    return {"token": safe(lambda: body.entityToken, ""), "name": safe(lambda: body.name, "")}


def collection_items(collection):
    """Items of a Fusion collection (count and item(i)); empty for None or a collection that cannot be read."""
    if collection is None:
        return []
    try:
        return [collection.item(i) for i in range(collection.count)]
    except Exception:
        return []


def body_refs(collection):
    return [body_ref(b) for b in collection_items(collection)]


def plane_of(entity):
    """{ point, normal } for a ConstructionPlane or a planar BRepFace; None for anything else."""
    try:
        geometry = entity.geometry
        if type_name(geometry) != "Plane":
            return None
        return {"point": point(geometry.origin), "normal": unit_vector(geometry.normal)}
    except Exception:
        return None


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


def edge_record(edge):
    """{ token, closed, points }: the middle point of an open edge; the points at 0.25 and 0.75 of a closed one."""
    closed = _same_vertex(safe(lambda: edge.startVertex, None), safe(lambda: edge.endVertex, None))
    points = []
    for fraction in ((0.25, 0.75) if closed else (0.5,)):
        p = point_at(edge, fraction)
        if p is not None:
            points.append(point(p))
    if not points and not closed:
        fallback = safe(lambda: edge.pointOnEdge, None)
        if fallback is not None:
            points.append(point(fallback))
    return {"token": safe(lambda: edge.entityToken, ""), "closed": closed, "points": points}


class ReadContext:
    """What one capture read shares: the design, the root component and the picked body."""

    def __init__(self, design, target):
        self.design = design
        self.root = design.rootComponent
        self.target = target
        self.target_ref = body_ref(target)

    def find_target(self):
        """The picked body at the current marker position, or None when it does not exist yet.

        Looked up by token; the root component's bodies are searched by name when the token is not found.
        """
        token = self.target_ref["token"]
        if token:
            found = safe(lambda: self.design.findEntityByToken(token), None)
            if found:
                return found[0]
        name = self.target_ref["name"]
        for body in collection_items(safe(lambda: self.root.bRepBodies, None)):
            if name and safe(lambda: body.name, None) == name:
                return body
        return None

    def target_box(self):
        body = self.find_target()
        return safe(lambda: box_of(body), None) if body is not None else None
