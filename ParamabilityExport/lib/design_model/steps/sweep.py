"""What a sweep step is, read from the capture for any destination: the points and loops of its outline, the volume
a new body must have from the outline and the path, and the end face it must have where the planned path ends
(`design_model.paths`). A result that does not match is the problem `MISMATCH`; each destination turns it into its
own refusal. Pure."""
import math

from ...geometry import vec
from ...geometry.footprint import closed_chain, is_full, polyline
from ...package.numbers import is_number
from ..paths.curves import tangents
from ..paths.tolerances import SQUARE_TOL_DEG, STRAIGHT_DEG
from ..problems import Problem

ZERO_TOL = 1e-6
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3
CENTROID_ON_PATH_TOL = 0.01   # the path runs through the outline's centroid when it starts this close to it (mm)
END_PLANE_TOL = 1e-3      # a made end face lies this close to the plane square to the path end (mm)
REACH_TOLERANCE = 0.01    # share of the outline's reach a point of the end face may lie beyond (arcs are sampled)

NOT_MATCHING = "The result of this sweep does not match its outline and path, so it is not copied yet."
END_UNCHECKED = "The end of the path of %s could not be checked against the shape Fusion made."
# The problem of a sweep whose new body or end face does not match its outline and path.
MISMATCH = Problem("not_matching", NOT_MATCHING)


# ---- the outline ---------------------------------------------------------------------------------------------------

def profile_points(profile):
    """Points along every curve of the outline, in the coordinates of the part."""
    frame = profile["frame"]
    return [vec.frame_apply(frame, [u, v, 0.0]) for loop in profile.get("loops") or []
            for curve in loop.get("curves") or [] for u, v in polyline(curve)]


def loop_polygon(curves):
    """The points of one outline loop in order, or None when its curves do not close."""
    if len(curves) == 1 and is_full(curves[0]):
        return polyline(curves[0])[:-1]
    chain = closed_chain(curves)
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


def outline_shapes(profile):
    """The loops of the outline as `(2D points, outer)`, or None when one does not close."""
    shapes = []
    for loop in profile.get("loops") or []:
        points = loop_polygon(loop.get("curves") or [])
        if not points or len(points) < 3:
            return None
        shapes.append((points, bool(loop.get("outer"))))
    return shapes


# ---- the volume of a new body --------------------------------------------------------------------------------------

def made_volume(item, data):
    """The volume of the body a new body sweep made, or None when it was not measured. A walk of a tool body lists
    its own `volume_after` (null when not measured); otherwise the body of the capture is the one made."""
    if "volume_after" in data:
        return data["volume_after"]
    return (item.get("target_after") or {}).get("volume_mm3")


def _axis_distance(point, axis):
    along = vec.sub(point, axis["point"])
    direction = vec.unit(axis["dir"])
    return vec.length(vec.sub(along, vec.scale(direction, vec.dot(along, direction))))


def _closed_volume(area, middle, found, twisted):
    """The volume of an outline swept once round a closed flat path (Pappus): the area times the length its centre
    travels, which is the path's length less the centre's offset to the left of the path times the turn of the path.
    A mitred corner turning by t counts 2 tan(t / 2) instead of t. A twisting outline turns its centre about the path,
    so that counts only when the centre sits on the path."""
    offset = vec.sub(middle, found.start)
    if twisted:
        return area * found.length if vec.length(offset) <= CENTROID_ON_PATH_TOL else None
    normal = found.recipe["on"]["normal"]
    left = vec.dot(offset, vec.cross(normal, found.direction))
    return area * (found.length - left * (found.winding * 2.0 * math.pi + _mitre_excess(found.curves, normal)))


def _mitre_turns(curves, normal, closed=True):
    """`(turn, mitred)` summed over the sharp corners between lines of the path, each signed by its direction about
    `normal`: the corner's turn t and 2 tan(t / 2), what the outline's centre travels per mm of its offset to the
    left of the path when the outline is mitred there. On a closed path the last line meets the first."""
    turns, mitred = 0.0, 0.0
    pairs = zip(curves[-1:] + curves[:-1], curves) if closed else zip(curves, curves[1:])
    for before, after in pairs:
        if before["kind"] != "line" or after["kind"] != "line":
            continue
        a, b = vec.unit(vec.sub(before["end"], before["start"])), vec.unit(vec.sub(after["end"], after["start"]))
        turn = math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b))
        if math.degrees(turn) > STRAIGHT_DEG:
            sign = math.copysign(1.0, vec.dot(vec.cross(a, b), normal))
            turns += sign * turn
            mitred += sign * 2.0 * math.tan(turn / 2.0)
    return turns, mitred


def _mitre_excess(curves, normal):
    """What the sharp corners between lines of a closed path add to its turn when the outline is mitred there:
    2 tan(t / 2) - t for each corner turning by t, signed by its direction about `normal`."""
    turns, mitred = _mitre_turns(curves, normal)
    return mitred - turns


def _open_lines_volume(area, middle, found):
    """The volume of an outline swept along an open flat chain of lines with mitred corners: the area times the length
    its centre travels, the path's length less the centre's offset to the left of the path times 2 tan(t / 2) for
    each corner turning by t."""
    normal = found.recipe["on"]["normal"]
    left = vec.dot(vec.sub(middle, found.start), vec.cross(normal, found.direction))
    return area * (found.length - left * _mitre_turns(found.curves, normal, closed=False)[1])


def _expected_volume(profile, area, found, twisted):
    """The volume the outline sweeps along the path (area times the length its centre travels), or None when that is
    not known: a bent path counts only when it runs through the centre of the outline or, untwisted, is a chain of
    lines in one plane."""
    centre = centroid(profile)
    if centre is None:
        return None
    middle = vec.frame_apply(profile["frame"], [centre[0], centre[1], 0.0])
    if found.closed:
        return _closed_volume(area, middle, found, twisted)
    if found.kind == "line":
        return area * found.length
    if found.kind in ("arc", "circle"):
        return area * math.radians(found.angle_deg) * _axis_distance(middle, found.axis)
    if vec.length(vec.sub(middle, found.start)) <= CENTROID_ON_PATH_TOL:
        return area * found.length
    if found.kind == "flat" and not twisted and all(c["kind"] == "line" for c in found.curves):
        return _open_lines_volume(area, middle, found)
    return None


def _rise(profile, found):
    """How far the path moves along the outline's normal, taken in the direction the path leaves it."""
    normal = vec.unit(profile["frame"]["z"])
    facing = normal if vec.dot(normal, found.direction) >= 0 else vec.scale(normal, -1.0)
    return vec.dot(vec.sub(found.end, found.start), facing)


def volume_problem(item, data, combine, profile, found):
    """`MISMATCH` when a new body does not have the volume the outline and the path give; None when it
    does, or when it cannot be told. A taper changes the volume, so it is not told here. An outline kept in one
    direction moves along its normal, so the volume is its area times the rise of the path along that normal."""
    areas = data.get("areas")
    parallel = data["orientation"] == "parallel"
    if abs(data["taper_deg"]) > ZERO_TOL or combine != "new":
        return None
    if not isinstance(areas, list) or len(areas) != 1 or not is_number(areas[0]) or areas[0] <= 0:
        return None
    made = made_volume(item, data)
    if parallel:
        expected = areas[0] * _rise(profile, found)
    else:
        expected = _expected_volume(profile, areas[0], found, abs(data["twist_deg"]) > ZERO_TOL)
    if made is None or expected is None:
        return None
    if abs(made - expected) > VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL:
        return MISMATCH
    return None


# ---- the end face --------------------------------------------------------------------------------------------------

def _readable(faces):
    """The faces with a point and a normal, or None when the list is missing or one face lacks either."""
    if not isinstance(faces, list):
        return None
    for face in faces:
        if not isinstance(face, dict) or not _vector(face.get("point")) or not _vector(face.get("normal")):
            return None
    return faces


def _vector(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)


def _end_facing(profile, found, fixed):
    """The unit normal the end face has: square to the path's end, or the outline's own normal when it keeps its
    direction."""
    if fixed:
        return vec.unit(profile["frame"]["z"])
    return tangents(found.curves[-1])[1]


def end_check(data, combine, profile, found, points, fixed, tapered):
    """`(problem or None, note or None)`: `MISMATCH` when a made end face is not where the planned path
    ends (not on the plane square to it, not facing along it, or, for a new body's one end face, beyond the outline's
    reach from the path end); a note text (`END_UNCHECKED`) when the faces were not readable. The volume check cannot
    see a path that starts at the wrong end or leaves the wrong way, since those keep the volume; the end face does.
    Nothing for a path with no end face (closed, a full circle) or for a capture without them."""
    faces = data.get("faces_after")
    if found.closed or found.kind == "circle" or not isinstance(faces, dict) or "end" not in faces:
        return None, None
    ends = _readable(faces["end"])
    if ends is None:
        return None, END_UNCHECKED
    if not ends:
        return None, None
    facing = _end_facing(profile, found, fixed)
    for face in ends:
        normal = vec.unit(face["normal"])
        if math.degrees(math.asin(min(1.0, vec.length(vec.cross(normal, facing))))) > SQUARE_TOL_DEG:
            return MISMATCH, None
        if abs(vec.dot(vec.sub(face["point"], found.end), facing)) > END_PLANE_TOL:
            return MISMATCH, None
    if combine == "new" and not tapered and len(ends) == 1 and points:
        reach = max(vec.length(vec.sub(p, found.start)) for p in points)
        if vec.length(vec.sub(ends[0]["point"], found.end)) > reach * (1.0 + REACH_TOLERANCE) + END_PLANE_TOL:
            return MISMATCH, None
    return None, None
