"""Offset faces handler (OffsetFacesFeature, press pull).

Every flat face the item moves becomes one `near` point inside the face, and the item one `offsetFaces` step with the
distance as Fusion gives it (mm, positive moves the face out of the material). The app moves each face along its
normal and lets the faces around it extend or shrink to meet it, so leaning side walls and faces that touch each other
need no special case. Curved faces and moves that were not measured are refused.
"""
import math
from collections import OrderedDict

from . import follow, vec
from .footprint import Footprint
from .result import Refusal
from .values import Quantity, number, quantity, stays_positive

TYPES = ("OffsetFacesFeature",)

MOVE_TOL_MM = 1e-3
NORMAL_TOL = 1e-6
# The pick point search: a grid over the outline's bounding box.
GRID = 24
# The outline centroid is kept while its clearance is at least this share of the best clearance on the grid.
CENTROID_SHARE = 0.5
# The search is repeated by every walk over one capture, so the latest results are kept by face record.
CACHE_SIZE = 256
_cache = OrderedDict()


def _moved_as_read(face, distance, after):
    """True when a face Fusion left after the step lies on the face's plane moved by `distance` along its normal."""
    frame = face["frame"]
    for found in after:
        if vec.dot(found["normal"], frame["z"]) < 1.0 - NORMAL_TOL:
            continue
        if abs(vec.dot(vec.sub(found["point"], frame["origin"]), frame["z"]) - distance) <= MOVE_TOL_MM:
            return True
    return False


def _face_refusal(face, distance, after):
    if face.get("kind") == "other" or "loops" not in face:
        return Refusal("Offsets of curved faces are not copied yet.")
    if not _moved_as_read(face, distance, after):
        return Refusal("The offset of this step could not be measured, so it is not copied.")
    return None


def _extent(curve):
    """Points that bound a curve: its ends, plus the box of a circle, ellipse or arc."""
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


def inside_point(face):
    """A point (u, v) in the face's own plane that lies inside the face, away from its edges and holes; None when the
    search finds none. The result is kept for the face record (the same dict)."""
    kept = _cache.get(id(face))
    if kept is None or kept[0] is not face:
        kept = (face, _search(face))
        _cache[id(face)] = kept
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
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


def _near_point(face):
    """The face's pick point in model space (`origin + u x + v y`), or None when no point lies inside the face."""
    uv = inside_point(face)
    if uv is None:
        return None
    frame = face["frame"]
    return [round(frame["origin"][i] + uv[0] * frame["x"][i] + uv[1] * frame["y"][i], 9) + 0.0 for i in range(3)]


def _distance(ctx, item, distance):
    """The distance as a number or a formula over the sizes; a size that could bring it to zero stays fixed."""
    q = quantity(ctx, item, "distance", distance)
    if q.sized and not stays_positive(ctx.table, q if distance > 0 else q.scaled(-1)):
        ctx.fix(q.reads, "the offset of %s could reach zero" % (item.get("name") or "a step"))
        q = Quantity(q.n)
    return q.json()


def handle(item, ctx):
    data = item.get("data") or {}
    if data.get("read_error"):
        return Refusal("This step could not be read from Fusion.")
    distance = data.get("distance")
    faces = data.get("faces") or []
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not faces:
        return Refusal("The faces or the distance of this offset could not be read.")
    if not math.isfinite(distance) or not abs(number(distance)) > 0:
        return Refusal("This offset has no distance.")
    after = data.get("faces_after") or []
    for face in faces:
        refusal = _face_refusal(face, distance, after)
        if refusal:
            return refusal
    points = [_near_point(face) for face in faces]
    if any(p is None for p in points):
        return Refusal("A face of this offset has no room for a pick point, so it is not copied.")
    selector = follow.faces(ctx, item, [{"point": p} for p in points])
    return [{"kind": "offsetFaces", "faces": selector, "distance": _distance(ctx, item, distance)}]
