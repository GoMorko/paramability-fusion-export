"""The measured references (planes, axes, directions, points) of the steps that the probe reads again at every state."""
from ...params import geometry_links
from ...design_model.reach import moving_reaches

SHAPE_PLANE, SHAPE_AXIS, SHAPE_DIRECTION, SHAPE_POINT = "plane", "axis", "direction", "point"
NO_TOKEN = "it has no token to find it again"
NO_PLACE = "its place could not be brought into the part's coordinates"
_POINT_TYPES = ("SketchPoint", "BRepVertex")


def is_vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _shape(ref):
    """What of a reference is followed: a plane (point and normal), an axis (point and direction), a direction alone,
    or a point (a sketch point or vertex); None when its record has no usable geometry."""
    point, normal, direction = (is_vector(ref.get(k)) for k in ("point", "normal", "dir"))
    if point and normal:
        return SHAPE_PLANE
    if point and direction:
        return SHAPE_AXIS
    if direction:
        return SHAPE_DIRECTION
    return SHAPE_POINT if point and ref.get("type") in _POINT_TYPES else None


def own_reaches(item):
    """The faces and planes of the part that the step `item` starts from or reaches to and that may move with it
    (`translator.sizes.moving_reaches`), as measured references with `own: true`: the reader reads them in the part's
    own coordinates."""
    out = []
    for slot, record in moving_reaches(item):
        plane = record["plane"]
        ref = {"slot": slot, "type": record.get("entity_type") or "", "token": record["token"],
               "point": list(plane["point"]), "normal": list(plane["normal"]), "own": True}
        out.append({"key": geometry_links.ref_key(item.get("index"), slot), "item": item.get("index"), "slot": slot,
                    "name": item.get("name") or "", "ref": ref})
    return out


def refs(capture, items=None):
    """The measured references of the capture's steps (`params.geometry_links.item_refs`, then `own_reaches`), each
    with its `shape` and, when the probe cannot follow it, a `reason` (else empty)."""
    out, entries = [], []
    for item in (capture.get("items") or []) if items is None else items:
        entries += geometry_links.item_refs(item) + own_reaches(item)
    for entry in entries:
        ref = entry["ref"]
        shape = _shape(ref)
        reason = "" if shape else NO_PLACE
        if shape and not ref.get("token"):
            shape, reason = None, NO_TOKEN
        out.append(dict(entry, shape=shape, reason=reason))
    return out
