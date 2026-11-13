"""The outline of a sweep: the one profile, its points and its centroid. Pure."""
from ..sketch import loops
from ...geometry import vec
from ...geometry.footprint import is_full, polyline
from ..result import Refusal
from .sweep_limits import FACE_OUTLINE, SEVERAL_OUTLINES, UNREADABLE


def profile_points(profile):
    """Points along every curve of the outline, in the coordinates of the part."""
    frame = profile["frame"]
    return [vec.frame_apply(frame, [u, v, 0.0]) for loop in profile.get("loops") or []
            for curve in loop.get("curves") or [] for u, v in polyline(curve)]


def loop_polygon(curves):
    """The points of one outline loop in order, or None when its curves do not close."""
    if len(curves) == 1 and is_full(curves[0]):
        return polyline(curves[0])[:-1]
    chain = loops.closed_chain(curves)
    return None if chain is None else [p for link in chain for p in polyline(link)[:-1]]


def centroid(profile):
    """The centre of the area of the outline (holes taken out) in its sketch plane, or None when a loop is open."""
    area = cx = cy = 0.0
    for loop in profile.get("loops") or []:
        points = loop_polygon(loop.get("curves") or [])
        if not points or len(points) < 3:
            return None
        twice = part_x = part_y = 0.0
        for a, b in zip(points, points[1:] + points[:1]):
            cross = a[0] * b[1] - b[0] * a[1]
            twice += cross
            part_x += (a[0] + b[0]) * cross
            part_y += (a[1] + b[1]) * cross
        if abs(twice) <= 1e-12:
            return None
        weight = 1.0 if loop.get("outer") else -1.0
        size = abs(twice) / 2.0
        area += weight * size
        cx += weight * size * part_x / (3.0 * twice)
        cy += weight * size * part_y / (3.0 * twice)
    return [cx / area, cy / area] if area > 1e-12 else None


def outline_of(data):
    """The one outline profile, or a Refusal."""
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        return Refusal(UNREADABLE)
    if not profiles:
        return Refusal("This sweep has no sketch outline.")
    if len(profiles) > 1:
        return Refusal(SEVERAL_OUTLINES)
    profile = profiles[0]
    if not isinstance(profile, dict):
        return Refusal(UNREADABLE)
    if profile.get("face"):
        return Refusal(FACE_OUTLINE)
    refusal = loops.outline_refusal(profile)
    if refusal is not None:
        return refusal
    if not isinstance(profile.get("frame"), dict):
        return Refusal("A sketch outline has no readable position.")
    return profile


def outline_shapes(profile):
    """The loops of the outline as `(2D points, outer)`, or None when one does not close."""
    shapes = []
    for loop in profile.get("loops") or []:
        points = loop_polygon(loop.get("curves") or [])
        if not points or len(points) < 3:
            return None
        shapes.append((points, bool(loop.get("outer"))))
    return shapes
