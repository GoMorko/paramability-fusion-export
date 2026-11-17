"""Where the copies of a pattern sit, from the data Fusion gives right, checked against the faces of each copy.

Each pattern element has a transform (`frame`, the move from the original to the copy), but Fusion does not always
give the right one. In a circular pattern (Fusion 2706) the transform of every copy after the original is one step
ahead, and the last copy of a full circle reads as the original. The element ids follow the real copy order (copy
`id` sits `id` steps from the original), and the faces each element made show where the copy really is. So:

- `circular_sign` places the copies of a circular pattern by their ids and finds the way they turn: from their faces,
  else from transforms that agree with the ids, else not at all when the way changes where the copies land.
- `agrees` checks a claimed place of one copy against its faces: the faces of the original (`source_faces`), moved
  to the claimed place, must land on the faces of the copy.
- `listed_places` refuses copies that share a place, and places that do not fill the count when no copy is left out.

A face is `{ "center", "area" }`: its centroid in mm and its area in mm2. A copy agrees with a place when at least
one of its faces, and at least half of the faces the place moves, land on an original face of the same area. A face
that the place leaves where it is (on the axis of a turn) tells nothing and is not counted. A copy or an original
without faces cannot be checked; the other checks still hold. Pure.
"""
import math

from ...geometry import vec
from .. import words
from ..problem import Problem, is_problem
from .repeat import FIT_TOL_MM, data_in_component, is_identity_rotation, solve_lattice

# Centroids within this distance (mm) and areas within this share of the larger one are the same face.
CENTER_TOL_MM = 1e-2
AREA_SHARE = 1e-3
# Turns (degrees) that count as the same.
TURN_TOL_DEG = 1e-6
FULL_TURN_DEG = 360.0

DISAGREE = Problem("patternFaces", words.PATTERN_FACES_DISAGREE)
SHARED = Problem("patternShared", words.PATTERN_PLACES_SHARED)
UNFILLED = Problem("patternUnfilled", words.PATTERN_PLACES_UNFILLED)
TURN_UNREAD = Problem("patternTurnUnread", words.PATTERN_TURN_UNREAD)


def _faces(value):
    """The face records of `value`, or None when there are none to compare."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(f, dict) and isinstance(f.get("center"), list) and isinstance(f.get("area"), (int, float))
               for f in value):
        return None
    return value


def source_faces(data):
    """The faces of the original of the pattern `data`, or None when they were not read."""
    return _faces(data.get("source_faces"))


def _same_face(center, area, face):
    return (vec.close(center, face["center"], CENTER_TOL_MM)
            and abs(area - face["area"]) <= AREA_SHARE * max(area, face["area"], 1.0))


def agrees(source, element, frame):
    """True when the faces of `element` sit where `frame` (a move from the original) puts the original faces `source`,
    False when they do not, None when there is nothing to compare."""
    faces = _faces(element.get("faces"))
    if source is None or faces is None:
        return None
    moved = []
    for face in source:
        center = vec.frame_apply(frame, face["center"])
        if not vec.close(center, face["center"], CENTER_TOL_MM):
            moved.append((center, face["area"]))
    if not moved:
        return None
    hits = sum(1 for face in faces if any(_same_face(c, a, face) for c, a in moved))
    return hits >= 1 and 2 * hits >= min(len(faces), len(moved))


def turn_frame(point, direction, degrees):
    """The frame of a turn by `degrees` about the axis through `point` along `direction` (right hand rule)."""
    def turned(v):
        return vec.rotate(v, direction, degrees)
    moved = vec.rotate([0.0, 0.0, 0.0], direction, degrees, point)
    return {"origin": moved, "x": turned([1.0, 0.0, 0.0]), "y": turned([0.0, 1.0, 0.0]),
            "z": turned([0.0, 0.0, 1.0])}


def left_out(data):
    """True when the user left a copy of the pattern `data` out (suppressed it)."""
    return bool(data.get("suppressed_ids")) or any(e.get("suppressed") for e in data.get("elements") or [])


def listed_places(places, count, data):
    """A Problem when two listed elements of the pattern `data` share a place, or when nothing is left out and the
    distinct places do not number `count`; else None. `places` holds one hashable place per listed element."""
    if len(set(places)) != len(places):
        return SHARED
    if not left_out(data) and len(places) != count:
        return UNFILLED
    return None


def listed_elements(raw, merged, place):
    """The elements of a rectangular pattern whose places must all differ: every element as Fusion listed it (`raw`,
    the data of the step, carried into the component frame `place`), or, when a direction spaces its copies 0 apart
    so copies sit on one another by design, the merged ones of `merged`."""
    for which in ("one", "two"):
        if int(raw.get("quantity_" + which) or 1) > 1 and abs(float(raw.get("distance_" + which) or 0.0)) < 1e-9:
            return merged["elements"]
    return data_in_component(raw, place)["elements"]


def grid_places(elements, axes, count, data):
    """`listed_places` for the elements of a rectangular pattern: each element's steps along `axes` (`(unit direction,
    step)` pairs). An element off the grid has a place of its own."""
    found = []
    for n, element in enumerate(elements):
        frame = element["frame"]
        indexes, residual = solve_lattice(frame["origin"], axes)
        on_grid = residual <= FIT_TOL_MM and is_identity_rotation(frame)
        found.append(tuple(indexes) if on_grid else ("off", n))
    return listed_places(found, count, data)


def _turn_of(frame, point, direction):
    """The signed turn of `frame` about the axis in degrees, or None when it is no turn about that axis."""
    helper = vec.cross(direction, [1.0, 0.0, 0.0])
    if vec.length(helper) < 0.5:
        helper = vec.cross(direction, [0.0, 1.0, 0.0])
    v = vec.unit(helper)
    image = vec.sub(vec.frame_apply(frame, v), frame["origin"])
    if not vec.close(vec.frame_apply(frame, point), point, CENTER_TOL_MM):
        return None
    return math.degrees(math.atan2(vec.dot(direction, vec.cross(v, image)), vec.dot(v, image)))


def _same_turn(a, b):
    gap = (a - b) % FULL_TURN_DEG
    return min(gap, FULL_TURN_DEG - gap) <= TURN_TOL_DEG * 10


def id_places(data, count):
    """The ids of the elements of a circular pattern, or a Problem when they are no copy numbers of `count` copies
    or do not fill them (`listed_places`)."""
    ids = [e.get("id") for e in data.get("elements") or []]
    if any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < count for i in ids):
        return UNFILLED
    found = listed_places(ids, count, data)
    return found if found is not None else ids


def full_turn(data):
    """True when the circular pattern `data` turns its copies a full circle."""
    return abs(abs(float(data.get("total_angle_deg") or 0.0)) - FULL_TURN_DEG) <= TURN_TOL_DEG


def circular_step(data):
    """The turn in degrees between neighbour copies of the circular pattern `data`, or None when its count or angle
    gives none."""
    count = data.get("quantity")
    total = abs(float(data.get("total_angle_deg") or 0.0))
    if not isinstance(count, int) or count < 2:
        return None
    if full_turn(data):
        return FULL_TURN_DEG / count
    return total / (count - 1) if 0.0 < total < FULL_TURN_DEG else None


def id_frames(data, kept, sign):
    """`(element, frame)` of each kept element of a one-sided circular pattern `data` other than the original, placed
    by its id and turning `sign` (+1 or -1) about the axis; None when the axis, the step or the ids cannot be read."""
    axis, delta = data.get("axis") or {}, circular_step(data)
    if delta is None or not isinstance(axis.get("point"), list) or not isinstance(axis.get("dir"), list) \
            or vec.length(axis["dir"]) < 1e-9 or is_problem(id_places(data, data["quantity"])):
        return None
    direction = vec.unit(axis["dir"])
    return [(e, turn_frame(axis["point"], direction, sign * e["id"] * delta)) for e in kept if e["id"]]


def circular_sign(data, kept, point, direction, delta):
    """+1 when copy `id` of a circular pattern turns `id * delta` degrees about `direction` (right hand rule), -1 when
    it turns the other way, or a Problem.

    The faces of the copies decide where they were read. Without them, transforms that agree with the ids decide. When
    neither tells, the way is taken only if both ways put the kept copies on the same places (a full circle with no
    copy left out)."""
    source = source_faces(data)
    open_signs, seen = [], []
    for sign in (1, -1):
        verdicts = [agrees(source, e, turn_frame(point, direction, sign * e["id"] * delta)) for e in kept]
        if False in verdicts:
            continue
        open_signs.append(sign)
        if True in verdicts:
            seen.append(sign)
    if seen:
        return seen[0]
    if not open_signs:
        return DISAGREE
    for sign in open_signs:
        turns = [_turn_of(e["frame"], point, direction) for e in kept]
        if all(t is not None and _same_turn(t, sign * e["id"] * delta) for t, e in zip(turns, kept)):
            return sign
    ahead = sorted(round((e["id"] * delta) % FULL_TURN_DEG, 6) % FULL_TURN_DEG for e in kept)
    behind = sorted(round((-e["id"] * delta) % FULL_TURN_DEG, 6) % FULL_TURN_DEG for e in kept)
    if len(open_signs) == 2 and all(_same_turn(a, b) for a, b in zip(ahead, behind)):
        return 1
    return TURN_UNREAD


def unplaced(source, elements, frames):
    """True when an element with faces agrees with none of `frames` (claimed places as moves from the original).
    `elements` and `frames` may hold any number each: every element must agree with one of the frames."""
    for element in elements:
        verdicts = [agrees(source, element, frame) for frame in frames]
        if False in verdicts and True not in verdicts:
            return True
    return False
