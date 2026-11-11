"""Which step made the geometry a later step picks, read from Fusion (docs/capture-format.md, `reach`).

When steps are left out of the copy, a later round, chamfer or shell that picks edges or faces of the left out step's
result would pick something else in the copy. For each later step that picks geometry, the marker is moved to just
before the step. Each picked face (for an edge: each face it joins) is then compared with `Feature.faces` of every
earlier candidate step: the left out steps, the steps that made the tool bodies of a left out Combine, and the picking
steps after the first left out step.

`Feature.faces` holds the faces a step created, but only all of them with the marker right after the step: a later
step that trims, splits, moves or replaces those faces can take them out of the list. So each candidate's list is also
read once with the marker right after it. A candidate whose list is empty, or shorter than it was right after the step,
counts as reached by every later pick, since a picked face may be one that dropped out.

The answer is `{ read: true, gaps, makers: { "<item index>": [indexes of the candidates that made a picked face] } }`,
with `gaps` the left out steps the read was asked about and an entry for every picking step that was tested, or
`{ read: false, error }` when the read failed. A step that made a tool body of a left out Combine is reported under the
Combine's index. A pick that cannot be found, or a candidate whose faces cannot be read, counts as reached: the safe
side for the translator.
"""
from ..design_edit.marker import read_marker
from ..translator import step_kinds, tool_items
from ..translator.gaps import pick_records
from . import read_geometry as geo
from .capture import MarkerError, restore_marker

# Picking steps tested and candidates read in one read; a longer list gives `read: false` (each one moves the marker).
MAX_PICKING_ITEMS = 100
MAX_CANDIDATES = 200
# How many tool bodies deep the steps that made a left out Combine's tools are followed.
MAX_TOOL_DEPTH = 3
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
    """The faces the timeline item `index` created that Fusion still lists, or None when they cannot be read."""
    entity = geo.safe(lambda: geo.native_object(timeline.item(index).entity), None)
    faces = geo.safe(lambda: entity.faces, None) if entity is not None else None
    return _natives(geo.collection_items(faces)) if faces is not None else None


def _move(timeline, position):
    geo.safe(lambda: setattr(timeline, "markerPosition", position), None)
    if geo.safe(lambda: timeline.markerPosition, None) != position:
        raise ReachReadError("The timeline marker could not be moved.")


def _tool_makers(items, gaps):
    """{ index: [left out Combines] } of the steps that made the tool bodies of each left out Combine, also of the
    tools of a Combine among those steps. The faces of a joined or cut tool belong to the steps that made it."""
    found = {}

    def follow(combine, before, owner_index, depth):
        if depth > MAX_TOOL_DEPTH:
            return
        tools = (combine.get("data") or {}).get("tools") if isinstance(combine.get("data"), dict) else None
        for tool in tools if isinstance(tools, list) else []:
            if not isinstance(tool, dict):
                continue
            for item in tool_items.chain(list(items.values()), tool, before):
                found.setdefault(item["index"], [])
                if owner_index not in found[item["index"]]:
                    found[item["index"]].append(owner_index)
                follow(item, item["index"], owner_index, depth + 1)

    for index in sorted(gaps):
        item = items.get(index)
        if item is not None:
            follow(item, index, index, 1)
    return found


def _candidates(items, indexes):
    """The timeline indexes among `indexes` that may have made a picked face. An item that makes no body (a sketch,
    construction geometry) makes no faces and is left out."""
    found = []
    for index in sorted(set(indexes)):
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


def _complete_counts(timeline, candidates):
    """{ index: how many faces the step lists with the marker right after it, or None when unreadable }."""
    counts = {}
    for index in candidates:
        _move(timeline, index + 1)
        faces = _maker_faces(timeline, index)
        counts[index] = len(faces) if faces is not None else None
    return counts


def _maybe_dropped(faces, complete):
    """True when the step's list may miss a face it made: unreadable, empty, or shorter than right after the step."""
    return faces is None or not faces or complete is None or len(faces) < complete


def _reached(design, timeline, index, picks, candidates, complete, home):
    """The candidates before `index` that made, or may have made, a face the picks touch (the marker is before
    `index`)."""
    earlier = [m for m in candidates if m < index]
    faces = {m: _maker_faces(timeline, m) for m in earlier}
    touched = []
    for pick in picks:
        found = _pick_faces(design, pick, home)
        if found is None:
            return earlier
        touched.extend(found)
    return [m for m in earlier if _maybe_dropped(faces[m], complete.get(m))
            or any(_same(a, b) for a in touched for b in faces[m])]


def _read(design, capture, gaps):
    items = {i["index"]: i for i in capture.get("items") or []
             if isinstance(i, dict) and isinstance(i.get("index"), int)}
    picking = _picking_items(items, gaps)
    if len(picking) > MAX_PICKING_ITEMS:
        raise ReachReadError("More than %d later steps pick geometry." % MAX_PICKING_ITEMS)
    tools = _tool_makers(items, gaps)
    candidates = _candidates(items, set(gaps) | set(picking) | set(tools))
    if len(candidates) > MAX_CANDIDATES:
        raise ReachReadError("More than %d steps may have made the faces later steps pick." % MAX_CANDIDATES)
    home = (capture.get("target") or {}).get("token") or ""
    timeline = design.timeline
    complete = _complete_counts(timeline, candidates)
    makers = {}
    for index in sorted(picking):
        _move(timeline, index)
        reached = _reached(design, timeline, index, picking[index], candidates, complete, home)
        found = list(reached)
        for m in reached:
            found.extend(c for c in tools.get(m, ()) if c < index)
        makers[str(index)] = sorted(set(found))
    return makers


def read_reach(design, capture, gaps):
    """The `reach` of a capture. `gaps` are the timeline indexes of the steps the first translation left out for their
    own reason (`reach_pass.left_out_indexes`); with none, nothing is read. The timeline marker goes back to where it
    was; MarkerError when it cannot."""
    if not gaps:
        return {"read": True, "gaps": [], "makers": {}}
    timeline = design.timeline
    marker = read_marker(timeline)
    if marker is None:
        return {"read": False, "error": "The design has no readable timeline."}
    try:
        makers = _read(design, capture, set(gaps))
        reach = {"read": True, "gaps": sorted(set(gaps)), "makers": makers}
    except MarkerError:
        raise
    except Exception as exc:
        reach = {"read": False, "error": str(exc) or type(exc).__name__}
    finally:
        restore_marker(timeline, marker)
    return reach
