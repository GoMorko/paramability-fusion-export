"""Which step made the geometry a later step picks, read from Fusion (docs/capture-format.md, `reach`).

When steps are left out of the copy, a later round, chamfer or shell that picks edges or faces of the left out step's
result would pick something else in the copy. For each later step that picks geometry, the marker is moved to just
before the step. Each picked face (for an edge: each face it joins) is then compared with `Feature.faces` of every
earlier candidate step: the left out steps, the steps that built the bodies a left out step takes (the tools of a
Combine, the source of a Paste, the source bodies of a pattern, and the bodies behind those, `tool_items.built_by`), and
the picking steps after the first left out step.

`Feature.faces` holds the faces a step created, but only all of them with the marker right after the step: a later
step that trims, splits, moves or replaces those faces can take them out of the list. So each candidate's list is also
read once with the marker right after it. A candidate whose list is empty, or shorter than it was right after the step,
counts as reached by every later pick, since a picked face may be one that dropped out.

The marker visits each position it needs once, from the start of the timeline to its end: right after each candidate
that a later picking step may compare, and right before each picking step. The tokens of a picked face and of a
candidate's faces are read once per position.

The answer is `{ read: true, gaps, makers: { "<item index>": [indexes of the candidates that made a picked face] },
moves }`, with `gaps` the left out steps the read was asked about, an entry for every picking step that was tested and
`moves` the number of marker moves the read made (not counting the move back), or
`{ read: false, error }` when the read failed. A step that built a body a left out step takes is reported under the
index of that left out step. A pick that cannot be found, or a candidate whose faces cannot be read, counts as reached: the safe
side for the translator.
"""
from ..capture_model import step_kinds, tool_items
from ..capture_model.gap_picks import pick_records
from ..design_edit.marker import read_marker
from . import read_geometry as geo
from .capture import MarkerError, restore_marker

# Picking steps tested and candidates read in one read; a longer list gives `read: false` (each one moves the marker).
MAX_PICKING_ITEMS = 100
MAX_CANDIDATES = 200
_FACE_ENTITY = 1  # BRepEntityTypes.BRepFaceEntityType


class ReachReadError(Exception):
    """The reach could not be read; the answer is `read: false`."""


def _natives(found):
    """The native object of each entity in a list Fusion returned."""
    return [geo.native_object(e) for e in found or []]


def _resolve(design, token):
    """The entities a token names now (a split face gives several), or []."""
    return _natives(geo.safe(lambda: design.findEntityByToken(token), None)) if token else []


def _token(entity):
    return geo.safe(lambda: entity.entityToken, None) or None


def _touches(touched, tokens, faces):
    """True when a face of `faces` is one of `touched`: by token (`tokens` are the touched tokens), else by Fusion's
    own comparison of the two objects."""
    if tokens and any(_token(face) in tokens for face in faces):
        return True
    return any(geo.same_entity(a, b) for a in touched for b in faces)


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


class _Marker:
    """The timeline marker, moved only when it must. `moves` counts the moves made. The faces a step lists are read
    once per marker position."""

    def __init__(self, timeline):
        self.timeline = timeline
        self.moves = 0
        self._at = None
        self._faces = {}

    def move(self, position):
        if self._at == position:
            return
        self.moves += 1
        geo.safe(lambda: setattr(self.timeline, "markerPosition", position), None)
        if geo.safe(lambda: self.timeline.markerPosition, None) != position:
            raise ReachReadError("The timeline marker could not be moved.")
        self._at, self._faces = position, {}

    def faces(self, index):
        """The faces the timeline item `index` created that Fusion still lists, or None when they cannot be read."""
        if index not in self._faces:
            entity = geo.safe(lambda: geo.native_object(self.timeline.item(index).entity), None)
            found = geo.safe(lambda: entity.faces, None) if entity is not None else None
            self._faces[index] = _natives(geo.collection_items(found)) if found is not None else None
        return self._faces[index]


def _tool_makers(items, gaps):
    """{ index: [left out steps] } of the steps that built the bodies a left out step takes (a Combine's tools, a
    Paste's sources, a pattern's source bodies), and the bodies behind those (`tool_items.built_by`). Faces of a
    joined, cut, pasted or patterned body may belong to the steps that made its source."""
    found, timeline = {}, list(items.values())
    for index in sorted(gaps):
        item = items.get(index)
        for record, _ in tool_items.source_records(item) if item is not None else ():
            for maker in sorted(tool_items.built_by(timeline, record, item)):
                if index not in found.setdefault(maker, []):
                    found[maker].append(index)
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


def _maybe_dropped(faces, complete):
    """True when the step's list may miss a face it made: unreadable, empty, or shorter than right after the step."""
    return faces is None or not faces or complete is None or len(faces) < complete


def _reached(design, marker, index, picks, candidates, complete, home):
    """The candidates before `index` that made, or may have made, a face the picks touch (the marker is before
    `index`)."""
    earlier = [m for m in candidates if m < index]
    touched = []
    for pick in picks:
        found = _pick_faces(design, pick, home)
        if found is None:
            return earlier
        touched.extend(found)
    tokens = {t for t in map(_token, touched) if t}
    reached = []
    for m in earlier:
        faces = marker.faces(m) if complete.get(m) is not None else None
        if _maybe_dropped(faces, complete.get(m)) or _touches(touched, tokens, faces):
            reached.append(m)
    return reached


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
    marker = _Marker(design.timeline)
    last = max(picking, default=-1)
    useful = [m for m in candidates if m < last]
    positions = sorted({m + 1 for m in useful} | set(picking))
    complete, makers = {}, {}
    for position in positions:
        marker.move(position)
        if position - 1 in useful:
            faces = marker.faces(position - 1)
            complete[position - 1] = len(faces) if faces is not None else None
        if position in picking:
            reached = _reached(design, marker, position, picking[position], useful, complete, home)
            found = list(reached)
            for m in reached:
                found.extend(c for c in tools.get(m, ()) if c < position)
            makers[str(position)] = sorted(set(found))
    return makers, marker.moves


def read_reach(design, capture, gaps):
    """The `reach` of a capture. `gaps` are the timeline indexes of the steps the first translation left out for their
    own reason (`reach_pass.left_out_indexes`); with none, nothing is read. Any failure gives `{ read: false, error }`.
    The timeline marker goes back to where it was; only a marker that cannot go back raises (MarkerError)."""
    if not gaps:
        return {"read": True, "gaps": [], "makers": {}, "moves": 0}
    timeline = marker = None
    try:
        timeline = design.timeline
        marker = read_marker(timeline)
        if marker is None:
            return {"read": False, "error": "The design has no readable timeline."}
        makers, moves = _read(design, capture, set(gaps))
        return {"read": True, "gaps": sorted(set(gaps)), "makers": makers, "moves": moves}
    except MarkerError:
        raise
    except Exception as exc:
        return {"read": False, "error": str(exc) or type(exc).__name__}
    finally:
        if marker is not None:
            restore_marker(timeline, marker)
