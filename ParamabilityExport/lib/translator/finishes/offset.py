"""Offset faces handler (OffsetFacesFeature, press pull).

Every flat face the item moves becomes one `near` point inside the face, and the item one `offsetFaces` step with the
distance as Fusion gives it (mm, positive moves the face out of the material). The app moves each face along its
normal and lets the faces around it extend or shrink to meet it, so leaning side walls and faces that touch each other
need no special case. A whole round face (a pin, a boss or a bore) gets a point halfway along it, and the step then
needs recipe version 17 (finishes/offset_round.py). Other curved faces and moves that were not measured are refused.
"""
import math

from ..faces import follow
from ...design_model.values import Quantity, number
from ...geometry import vec
from ...geometry.footprint import Footprint
from ..faces.placer_makers import MovedFacesMaker
from ..result import NewerStep, Refusal, StepResult
from ..values import quantity, stays_positive
from . import offset_round


MOVE_TOL_MM = 1e-3
NORMAL_TOL = 1e-6
# The pick point search: a grid over the outline's bounding box.
GRID = 24
# The outline centroid is kept while its clearance is at least this share of the best clearance on the grid.
CENTROID_SHARE = 0.5


def _moved_as_read(face, distance, after):
    """True when a face Fusion left after the step lies on the face's plane moved by `distance` along its normal."""
    frame = face["frame"]
    for found in after:
        if vec.dot(found["normal"], frame["z"]) < 1.0 - NORMAL_TOL:
            continue
        if abs(vec.dot(vec.sub(found["point"], frame["origin"]), frame["z"]) - distance) <= MOVE_TOL_MM:
            return True
    return False


def _face_refusal(face, distance, after, rounds_after):
    if offset_round.is_round(face):
        return offset_round.refusal(face, distance, rounds_after)
    if face.get("kind") == "other" or "loops" not in face:
        return Refusal("Offsets of curved faces are not copied yet.")
    if not _moved_as_read(face, distance, after):
        return Refusal("The offset of this step could not be measured, so it is not copied.")
    return None


def _extent(curve):
    """Points that bound a curve: its ends, plus the box of a circle, ellipse or arc, or the samples of a free curve."""
    if curve["kind"] == "other" and curve.get("samples"):
        return list(curve["samples"])
    if curve["kind"] in ("circle", "ellipse"):
        r = curve["radius"] if curve["kind"] == "circle" else max(curve["major_radius"], curve["minor_radius"])
        cx, cy = curve["center"]
        return [[cx - r, cy - r], [cx + r, cy + r]]
    points = [curve["start"], curve["end"]]
    if curve["kind"] == "arc":
        (cx, cy), r = curve["center"], curve["radius"]
        points += [[cx - r, cy - r], [cx + r, cy + r]]
    return points


def _centroid(footprint):
    """The mean of the outline's corner points and circle centres."""
    points = []
    for curve in footprint.curves:
        points.append(curve["center"] if curve["kind"] in ("circle", "ellipse") else curve["start"])
    return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]


def _clearance(footprint, uv):
    """How far a point lies inside the face, from its closest outline curve; -1 outside the face."""
    return min(footprint.gaps(uv)) if footprint.covers(uv) else -1.0


def inside_point(face, cache=None):
    """A point (u, v) in the face's own plane that lies inside the face, away from its edges and holes; None when the
    search finds none. With a `cache` dict the result is kept there for the face record (the same dict), since every
    walk over one capture asks again."""
    kept = cache.get(id(face)) if cache is not None else None
    if kept is None or kept[0] is not face:
        kept = (face, _search(face))
        if cache is not None:
            cache[id(face)] = kept
    return None if kept[1] is None else list(kept[1])


def _search(face):
    footprint = Footprint(face)
    if not footprint.curves:
        return None
    box = [p for curve in footprint.curves for p in _extent(curve)]
    low = [min(p[k] for p in box) for k in (0, 1)]
    high = [max(p[k] for p in box) for k in (0, 1)]
    best, best_gap = None, 0.0
    for i in range(GRID):
        for j in range(GRID):
            uv = [low[k] + (high[k] - low[k]) * (n + 0.5) / GRID for k, n in ((0, i), (1, j))]
            gap = _clearance(footprint, uv)
            if gap > best_gap:
                best, best_gap = uv, gap
    if best is None:
        return None
    centre = _centroid(footprint)
    return centre if _clearance(footprint, centre) >= CENTROID_SHARE * best_gap else best


def _near_point(face, cache):
    """The face's pick point in model space (`origin + u x + v y`), or None when no point lies inside the face."""
    uv = inside_point(face, cache)
    if uv is None:
        return None
    frame = face["frame"]
    return [round(frame["origin"][i] + uv[0] * frame["x"][i] + uv[1] * frame["y"][i], 9) + 0.0 for i in range(3)]


def _distance(ctx, item, distance, rounds):
    """The distance as a number or a formula over the sizes. A size that could bring it to zero, or make a round face
    (`rounds`) run into other edges of its end faces, stays fixed."""
    q = quantity(ctx, item, "distance", distance)
    name = item.get("name") or "a step"
    if q.sized and not stays_positive(ctx.table, q if distance > 0 else q.scaled(-1)):
        ctx.doubt(q.reads, "the offset of %s could reach zero" % name)
        q = Quantity(q.n)
    elif q.sized and not offset_round.clear_over_range(ctx.table, rounds, q):
        ctx.doubt(q.reads, "the round face that %s moves could close or run into other faces" % name)
        q = Quantity(q.n)
    return q.json()


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    if data.get("read_error"):
        return Refusal("This step could not be read from Fusion.")
    distance = data.get("distance")
    faces = data.get("faces") or []
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not faces:
        return Refusal("The faces or the distance of this offset could not be read.")
    if not math.isfinite(distance) or not abs(number(distance)) > 0:
        return Refusal("This offset has no distance.")
    after, rounds_after = data.get("faces_after") or [], data.get("rounds_after") or []
    for face in faces:
        refusal = _face_refusal(face, distance, after, rounds_after)
        if refusal:
            return refusal
    cache = ctx.cache.setdefault(__name__, {})
    points = [offset_round.near_point(face) if offset_round.is_round(face) else _near_point(face, cache)
              for face in faces]
    if any(p is None for p in points):
        return Refusal("A face of this offset has no room for a pick point, so it is not copied.")
    rounds = [face for face in faces if offset_round.is_round(face)]
    selector = follow.faces(ctx, item, [{"point": p} for p in points])
    step = {"kind": "offsetFaces", "faces": selector, "distance": _distance(ctx, item, distance, rounds)}
    out = StepResult()
    out.add(NewerStep.of(step, offset_round.VERSION) if rounds else step, [MovedFacesMaker(faces)])
    return out
