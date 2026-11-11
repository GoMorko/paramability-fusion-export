"""Which step made the geometry a later step picks, read from Fusion (docs/capture-format.md, `reach`).

When steps are left out of the copy, a later round, chamfer or shell that picks edges or faces of the left out step's
result would pick something else in the copy. For each later step that picks geometry, the marker is moved to just
before the step. Each picked face (for an edge: each face it joins) is then compared with `Feature.faces` of every
earlier candidate step. `Feature.faces` holds the faces a step created, and they are all there with the marker before
the next step.

The answer is `{ read: true, makers: { "<item index>": [indexes of the candidates that made a picked face] } }`, with
an entry for every picking step that was tested, or `{ read: false, error }` when the read failed. A pick that cannot
be found, or a candidate whose faces cannot be read, counts as reached: the safe side for the translator.
"""
from ..design_edit.marker import read_marker
from ..translator import step_kinds
from ..translator.gaps import pick_records
from . import read_geometry as geo
from .capture import MarkerError, restore_marker

# Picking steps tested in one read; a longer list gives `read: false` (each one moves the marker).
MAX_PICKING_ITEMS = 100
_FACE_ENTITY = 1  # BRepEntityTypes.BRepFaceEntityType


class ReachReadError(Exception):
    """The reach could not be read; the answer is `read: false`."""


def _natives(found):
    """The native object of each entity in a list Fusion returned."""
    return [geo.native_object(e) for e in found or []]


def _resolve(design, token):
    """The entities a token names now (a split face gives several), or []."""
    return _natives(geo.safe(lambda: design.findEntityByToken(token), None)) if token else []


def _same(a, b):
    if geo.same_entity(a, b):
        return True
    token = geo.safe(lambda: a.entityToken, None)
    return bool(token) and token == geo.safe(lambda: b.entityToken, None)


def _face_type():
    try:
        import adsk.fusion
        return adsk.fusion.BRepEntityTypes.BRepFaceEntityType
    except Exception:
        return _FACE_ENTITY


def _faces_at_point(design, record, home):
    """The faces at the point the record gives (`face_point`, or `point` for a listed face), on the body it names or
    else on the target body `home` (a token). None when the body or point is missing."""
    point = record.get("face_point") or record.get("point")
    body_ref = record.get("body")
    bodies = _resolve(design, (body_ref.get("token") if isinstance(body_ref, dict) else None) or home)
    if not bodies or not isinstance(point, list):
        return None
    component = geo.component_of(bodies[0])
    found = geo.safe(lambda: component.findBRepUsingPoint(geo.point3d(point), _face_type()), None)
    return _natives(geo.collection_items(found)) or None


def _pick_faces(design, pick, home):
    """The faces a picked geometry touches: its own for a face or a face point, the ones it joins for an edge. None
    when the pick cannot be found."""
    record = pick["record"]
    found = _resolve(design, record.get("token"))
    if pick["kind"] == "edge":
        faces = [f for e in found for f in _natives(geo.collection_items(geo.safe(lambda: e.faces, None)))]
    else:
        faces = found or _faces_at_point(design, record, home) or []
    return faces or None


def _maker_faces(timeline, index):
    """The faces the timeline item `index` created, or None when they cannot be read."""
    entity = geo.safe(lambda: geo.native_object(timeline.item(index).entity), None)
    faces = geo.safe(lambda: entity.faces, None) if entity is not None else None
    return _natives(geo.collection_items(faces)) if faces is not None else None


def _candidates(items, gaps, picking):
    """Timeline indexes that may have made a picked face: the left out steps and the picking steps after the first
    one. An item that makes no body (a sketch, construction geometry) makes no faces and is left out."""
    found = []
    for index in sorted(set(gaps) | set(picking)):
        item = items.get(index)
        if item is None or not step_kinds.makes_no_body(item.get("type")):
            found.append(index)
    return found


def _picking_items(items, gaps):
    """{ index: picks } of the items after the first left out step that pick geometry. Left out steps are not tested,
    since they are not copied."""
    first, found = min(gaps), {}
    for index, item in items.items():
        picks = pick_records(item) if index > first and index not in gaps else []
        if picks:
            found[index] = picks
    return found


def _reached(design, timeline, index, picks, candidates, home):
    """The candidates before `index` that made a face the picks touch (the marker is before `index`)."""
    earlier = [m for m in candidates if m < index]
    faces = {m: _maker_faces(timeline, m) for m in earlier}
    touched = []
    for pick in picks:
        found = _pick_faces(design, pick, home)
        if found is None:
            return earlier
        touched.extend(found)
    return [m for m in earlier if faces[m] is None or any(_same(a, b) for a in touched for b in faces[m])]


def _read(design, capture, gaps):
    items = {i["index"]: i for i in capture.get("items") or []
             if isinstance(i, dict) and isinstance(i.get("index"), int)}
    picking = _picking_items(items, gaps)
    if len(picking) > MAX_PICKING_ITEMS:
        raise ReachReadError("More than %d later steps pick geometry." % MAX_PICKING_ITEMS)
    candidates = _candidates(items, gaps, picking)
    home = (capture.get("target") or {}).get("token") or ""
    timeline = design.timeline
    makers = {}
    for index in sorted(picking):
        timeline.markerPosition = index
        if timeline.markerPosition != index:
            raise ReachReadError("The timeline marker could not be moved.")
        makers[str(index)] = _reached(design, timeline, index, picking[index], candidates, home)
    return makers


def read_reach(design, capture, gaps):
    """The `reach` of a capture. `gaps` are the timeline indexes of the steps the first translation left out; with
    none, nothing is read. The timeline marker goes back to where it was; MarkerError when it cannot."""
    if not gaps:
        return {"read": True, "makers": {}}
    timeline = design.timeline
    marker = read_marker(timeline)
    if marker is None:
        return {"read": False, "error": "The design has no readable timeline."}
    try:
        makers = _read(design, capture, set(gaps))
        reach = {"read": True, "makers": makers}
    except MarkerError:
        raise
    except Exception as exc:
        reach = {"read": False, "error": str(exc) or type(exc).__name__}
    finally:
        restore_marker(timeline, marker)
    return reach
