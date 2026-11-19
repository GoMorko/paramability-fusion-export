"""Thin extrudes as facts: whether the wall can be read, which side of its outline or line it stands on, and its shape.

A thin extrude draws a wall of one thickness along one closed outline or along an open line of sketch lines. Fusion
names the side with its own wall location (side one, side two or center), and the API does not say which of side one
and side two is the inside. The measured faces decide it:

- Closed outline (`closed_side`): the measured area of the end face is the cross section of the wall, so the expected
  area of each candidate side is worked out from the outline and compared with it. Moving a line and arc outline by
  `d` adds a strip of `perimeter * d`, plus `d^2 / 2` times the turning of its arcs, plus one more term per corner: a
  corner that opens a gap on the moved side (a convex corner going outward, a concave one going inward) adds a round
  sector when the corner is rounded and a sharp wedge when it is kept sharp, and a corner that overlaps removes a
  kite. Both corner kinds are tried; `rounded` says only the sharp reading fits.
- Open line (`line_side`): the line is a `Path` of lines that run one after the other along it (`line_of`). Side one
  is the left of the path direction and side two the right (`RULE`), seen from the front of the sketch, whichever way
  the extrude goes. Fusion lists no start or end faces for such an extrude, so each face it made (`wall_faces`) must
  be flat and lie on a face of the wall that a side and a direction give (`fits`). A face whose point lies off the
  wall counts only when Fusion merged it with a face of the part (`merged`). Exactly one side that Fusion's location
  allows, and one direction, must fit. It must be the extrude's direction and the side `RULE` names.

Side names: `inside` is left of the line (inward of a closed outline), `outside` right of it (outward), `middle` half
each way. A `Problem` says why a wall cannot be read; each output turns it into its own answer. Pure.
"""
import math

from ...capture_model import gap_hints
from ...geometry import vec
from ...geometry.footprint import Footprint, arc_span, closed_chain, curve_length, is_full, polyline
from ...package.numbers import is_number
from .. import words
from ..problem import Problem

# ---- the wall record ---------------------------------------------------------------------------------------------

LOCATIONS = {"center": ("middle",), "side1": ("inside", "outside"), "side2": ("inside", "outside")}

UNREADABLE = Problem("unreadable", words.THIN_UNREADABLE)
LOCATION = Problem("location", words.THIN_LOCATION)
NO_THICKNESS = Problem("no_thickness", words.THIN_NO_THICKNESS)
TWO_WAYS = Problem("two_ways", words.THIN_TWO_WAYS)
REACHES = Problem("reaches", words.THIN_REACHES)
TAPER = Problem("taper", words.THIN_TAPER)


def wall_of(data):
    """The thin wall record of an extrude's data, or a Problem when it cannot be copied before looking at outlines.

    A wall is copied for one thickness and a distance that runs one way or symmetric. Two sides, a taper, a reach to
    a face or through all give a Problem."""
    wall = data.get("thin_wall")
    if not isinstance(wall, dict) or wall.get("location") is None or not is_number(wall.get("thickness")):
        return UNREADABLE
    if wall["location"] not in LOCATIONS:
        return LOCATION
    if not wall["thickness"] > 0:
        return NO_THICKNESS
    kind = data.get("extent_type")
    if kind == "two":
        return TWO_WAYS
    if kind == "symmetric":
        side, taper = data.get("symmetric"), (data.get("symmetric") or {}).get("taper_deg")
        reaches_end = isinstance(side, dict)
    else:
        side = data.get("side_one")
        taper = (side or {}).get("taper_deg")
        reaches_end = isinstance(side, dict) and side.get("kind") == "distance"
    if not reaches_end:
        return REACHES
    if taper is None:
        return UNREADABLE
    if taper:
        return TAPER
    return wall


# ---- a closed outline: the side from the end face's area ----------------------------------------------------------

AREA_RELATIVE_TOL = 5e-3
AREA_ABSOLUTE_TOL = 1e-2
# A corner that turns back almost on itself has no usable wedge.
MAX_TURN = math.pi - 1e-3
CORNER_EPS = 1e-6

ROUND, SHARP = "round", "sharp"

UNMEASURED_AREA = Problem("unmeasured_area", words.THIN_UNMEASURED_AREA)
NOT_ONE_OUTLINE = Problem("not_one_outline", words.THIN_NOT_ONE_OUTLINE)
SIDE_UNSURE = Problem("side_unsure", words.THIN_SIDE_UNSURE)
AREA_DIFFERS = Problem("area_differs", words.THIN_AREA_DIFFERS)


def outer_curves(profile):
    for loop in profile.get("loops") or []:
        if loop.get("outer"):
            return loop.get("curves") or []
    return []


def _tangent(link, at_end):
    """The unit direction of travel of a chained line or arc at its end or its start."""
    if link["kind"] == "line":
        d = [link["end"][0] - link["start"][0], link["end"][1] - link["start"][1]]
    else:
        point = link["end"] if at_end else link["start"]
        radial = [point[0] - link["center"][0], point[1] - link["center"][1]]
        sign = 1.0 if arc_span(link)[1] >= 0 else -1.0
        d = [-sign * radial[1], sign * radial[0]]
    size = math.hypot(*d) or 1.0
    return [d[0] / size, d[1] / size]


def _signed_area(chain):
    points = []
    for link in chain:
        points += polyline(link)[:-1]
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))


def shape_of(curves):
    """(perimeter, arc turning, corner turns) of a closed outline, or None when it is not a closed chain of lines and
    arcs, one circle or one ellipse, or has a corner that doubles back.

    Turns count positive where the outline bends toward the inside (a convex corner or arc), whichever way it is
    drawn."""
    if len(curves) == 1 and (is_full(curves[0]) or curves[0]["kind"] == "ellipse"):
        return curve_length(curves[0]), 2.0 * math.pi, []
    if any(c["kind"] not in ("line", "arc") for c in curves):
        return None
    chain = closed_chain(curves)
    if chain is None:
        return None
    orient = 1.0 if _signed_area(chain) > 0 else -1.0
    perimeter = arcs = 0.0
    for link in chain:
        perimeter += curve_length(link)
        if link["kind"] == "arc":
            arcs += orient * arc_span(link)[1]
    turns = []
    for here, there in zip(chain, chain[1:] + chain[:1]):
        a, b = _tangent(here, True), _tangent(there, False)
        turn = orient * math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
        if abs(turn) > MAX_TURN:
            return None
        if abs(turn) > CORNER_EPS:
            turns.append(turn)
    return perimeter, arcs, turns


def _strip(shape, d, outward, corners):
    """The area between the outline and its copy moved by `d` (outward or inward), corners round or sharp."""
    perimeter, arcs, turns = shape
    sign = 1.0 if outward else -1.0
    area = perimeter * d + sign * d * d * arcs / 2.0
    for turn in turns:
        gap = turn if outward else -turn
        if gap > 0:
            area += d * d * (gap / 2.0 if corners == ROUND else math.tan(gap / 2.0))
        else:
            area -= d * d * math.tan(-gap / 2.0)
    return area


def band_area(shape, side, thickness, corners):
    """The area of a wall of `thickness` on `side` of the outline."""
    if side == "inside":
        return _strip(shape, thickness, False, corners)
    if side == "outside":
        return _strip(shape, thickness, True, corners)
    return _strip(shape, thickness / 2.0, True, corners) + _strip(shape, thickness / 2.0, False, corners)


def _close(measured, expected):
    return abs(measured - expected) <= AREA_RELATIVE_TOL * expected + AREA_ABSOLUTE_TOL


def area_fits(curves, side, thickness, corners, end_area):
    """True when the measured `end_area` is the area of a wall of `thickness` on `side` of the closed outline, its
    corners round or sharp (`corners`)."""
    shape = shape_of(curves)
    return shape is not None and is_number(end_area) and _close(end_area, band_area(shape, side, thickness, corners))


def closed_side(curves, wall, end_area):
    """`(side, rounded)` for a wall along a closed outline: the side of the outline it sits on (inside, outside or
    middle), and whether only the reading with sharp corners fits, so a copy with rounded corners differs. A Problem
    when the measured end area fits no side, or fits more than one."""
    if not is_number(end_area) or not end_area > 0:
        return UNMEASURED_AREA
    shape = shape_of(curves)
    if shape is None:
        return NOT_ONE_OUTLINE
    thickness = wall["thickness"]
    found = {}
    for side in LOCATIONS[wall["location"]]:
        for corners in (ROUND, SHARP):
            expected = band_area(shape, side, thickness, corners)
            if expected > 0 and _close(end_area, expected):
                found.setdefault(side, corners)
    if len(found) > 1:
        return SIDE_UNSURE
    if not found:
        return AREA_DIFFERS
    side, corners = next(iter(found.items()))
    rounded = corners == SHARP and (
        band_area(shape, side, thickness, SHARP) - band_area(shape, side, thickness, ROUND) > AREA_ABSOLUTE_TOL)
    return side, rounded


# ---- an open line: its points, its shape and its side from the faces Fusion made ----------------------------------

# Two points this close (mm) are one: where a line ends and the next starts.
JOIN_TOL = 1e-4
# A line must be longer than this (mm) after its corners took their part of it.
LENGTH_TOL = 1e-3
# A corner turns by at most this: Fusion was seen to keep corners of 90 and 135 degrees sharp, one tip where the outer
# sides meet. A sharper corner is left out until Fusion is seen to keep it sharp too (docs/hand-checks.md, T2-open).
# The tolerance allows for the rounding of the captured points.
MAX_TURN_DEG = 135.0
_TURN_TOL_DEG = 1e-3
# A face Fusion made lies on a face of the wall within this (mm), and its normal within this sine.
FACE_TOL = 1e-3
NORMAL_TOL = 1e-4

# The side of a wall along the sketch normal for side one and side two of Fusion (left of the path is `inside`). For
# center the wall is `middle` either way.
RULE = {"side1": "inside", "side2": "outside"}
SWAPPED = {"inside": "outside", "outside": "inside", "middle": "middle"}

LINE_UNREADABLE = Problem("line_unreadable", words.THIN_LINE_UNREADABLE, gap_hints.THIN_OUTLINE)
NOT_ONE_LINE = Problem("not_one_line", words.THIN_NOT_ONE_LINE, gap_hints.THIN_OUTLINE)
LINE_CURVES = Problem("line_curves", words.THIN_LINE_CURVES, gap_hints.THIN_OUTLINE)
LINE_OPPOSED = Problem("line_opposed", words.THIN_LINE_OPPOSED, gap_hints.THIN_OUTLINE)
LINE_APART = Problem("line_apart", words.THIN_LINE_APART, gap_hints.THIN_OUTLINE)
WALL_UNMEASURED = Problem("wall_unmeasured", words.THIN_WALL_UNMEASURED, gap_hints.THIN_OUTLINE)
NOT_MATCHING = Problem("not_matching", words.THIN_NOT_MATCHING, gap_hints.THIN_OUTLINE)
UNSURE = Problem("unsure", words.THIN_UNSURE, gap_hints.THIN_OUTLINE)


class Line:
    """The open line of a thin extrude: `path` the capture record and `points` the 2D corners in its sketch frame, from
    the start of the line to its end."""

    def __init__(self, path, points):
        self.path, self.points = path, points
        self.frame = path["frame"]
        self.sketch = path.get("sketch") or ""


def is_line(profiles):
    """True when the outline of an extrude is an open line (Fusion's `Path`)."""
    return len(profiles) == 1 and isinstance(profiles[0], dict) and profiles[0].get("type") == "Path"


def line_of(data):
    """The `Line` of a thin extrude's path record, or a Problem. The copy takes a path of one sketch whose lines run
    one after the other, each from the end of the one before, none of them against the path: the side Fusion puts the
    wall on is measured for lines that run along the path only."""
    path = data.get("path")
    curves = path.get("curves") if isinstance(path, dict) else None
    if not isinstance(curves, list) or not curves or not isinstance(path.get("frame"), dict):
        return LINE_UNREADABLE
    if any(not isinstance(c, dict) for c in curves) or path.get("closed") is None:
        return LINE_UNREADABLE
    if path.get("kind") != "sketch" or path.get("foreign") or path.get("truncated") or path["closed"]:
        return NOT_ONE_LINE
    flats = [c.get("flat") for c in curves]
    if any(c.get("kind") != "line" for c in curves):
        return LINE_CURVES
    if any(not isinstance(f, dict) or f.get("kind") != "line" for f in flats) or any(
            c.get("opposed") is None for c in curves):
        return LINE_UNREADABLE
    if any(c["opposed"] for c in curves):
        return LINE_OPPOSED
    points = [list(flats[0]["start"])]
    for flat in flats:
        if math.dist(flat["start"], points[-1]) > JOIN_TOL:
            return LINE_APART
        points.append(list(flat["end"]))
    return Line(path, points)


def reaches(side, thickness):
    """(left, right): how far the wall of `side` reaches to the left and the right of its line, mm."""
    return {"inside": (thickness, 0.0), "outside": (0.0, thickness),
            "middle": (thickness / 2.0, thickness / 2.0)}[side]


def _unit(a, b):
    d = [b[0] - a[0], b[1] - a[1]]
    size = math.hypot(*d)
    return [d[0] / size, d[1] / size]


def _side_points(points, offset):
    """The line moved `offset` to its left (negative: to its right), each corner where the moved lines meet."""
    dirs = [_unit(a, b) for a, b in zip(points, points[1:])]
    normals = [[-d[1], d[0]] for d in dirs]
    out = [[points[0][i] + offset * normals[0][i] for i in range(2)]]
    for k in range(1, len(points) - 1):
        n1, n2 = normals[k - 1], normals[k]
        bend = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
        out.append([points[k][i] + offset * (n1[i] + n2[i]) / bend for i in range(2)])
    out.append([points[-1][i] + offset * normals[-1][i] for i in range(2)])
    return out


def line_problem(points, left, right):
    """Why a wall reaching `left` and `right` of the line through `points` does not keep its shape, or None: a line
    no longer than what its corners take from it, a corner sharper than MAX_TURN_DEG, or two lines that do not meet
    nearer than twice the farthest the wall reaches from its line (at a corner, the outer side's sharp tip reaches its
    side's reach divided by the cosine of half the turn)."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    if any(length <= LENGTH_TOL for length in lengths):
        return "a line of it is too short"
    dirs = [_unit(a, b) for a, b in zip(points, points[1:])]
    taken = [0.0] * (len(points) + 1)
    spread = max(left, right)
    for k in range(1, len(points) - 1):
        a, b = dirs[k - 1], dirs[k]
        turn = math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
        if math.degrees(abs(turn)) > MAX_TURN_DEG + _TURN_TOL_DEG:
            return "a corner of it is too sharp"
        inner, outer = (left, right) if turn > 0 else (right, left)
        # The side of the wall on the inside of a turn is cut short on both lines of the corner; the outer side meets
        # in a tip past the corner.
        taken[k] = inner * math.tan(abs(turn) / 2.0)
        spread = max(spread, outer / math.cos(abs(turn) / 2.0))
    if any(length - taken[k] - taken[k + 1] <= LENGTH_TOL for k, length in enumerate(lengths)):
        return "a line of it is shorter than its corners take"
    reach = 2.0 * spread
    for i in range(len(points) - 1):
        for j in range(i + 2, len(points) - 1):
            if _segment_gap(points[i], points[i + 1], points[j], points[j + 1]) <= reach + LENGTH_TOL:
                return "two of its lines come too near"
    return None


def _segment_gap(a, b, c, d):
    """The least distance between the segments a-b and c-d (zero when they cross)."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0:
        return 0.0

    def to_segment(p, q, r):
        dx, dy = r[0] - q[0], r[1] - q[1]
        size = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((p[0] - q[0]) * dx + (p[1] - q[1]) * dy) / size)) if size > 0 else 0.0
        return math.hypot(p[0] - q[0] - t * dx, p[1] - q[1] - t * dy)

    return min(to_segment(a, c, d), to_segment(b, c, d), to_segment(c, a, b), to_segment(d, a, b))


def band_pieces(points, left, right):
    """The wall of `band` as one four-cornered piece per line, in line order: each piece runs along its line between
    the corners where the wall turns, so the pieces meet only along their ends."""
    lefts, rights = _side_points(points, left), _side_points(points, -right)
    return [[lefts[k], lefts[k + 1], rights[k + 1], rights[k]] for k in range(len(points) - 1)]


def band(points, left, right):
    """The corners of the wall as one closed outline (not repeating its first corner): along the left side from the
    start of the line, across its end, back along the right side."""
    return _side_points(points, left) + _side_points(points, -right)[::-1]


def band_profile(frame, corners):
    """A capture profile of the closed outline through `corners` in `frame`."""
    ring = corners + corners[:1]
    return {"frame": frame, "loops": [{"outer": True, "curves": [
        {"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(ring, ring[1:])]}]}


def _vector(v):
    return isinstance(v, list) and len(v) == 3 and all(is_number(c) for c in v)


def on_wall(footprint, face, frame, start, span):
    """True when a flat face (a `wall_faces` record) lies on the wall whose outline is `footprint` in `frame`, running
    `span` (low, high, mm) along the sketch normal from `start`: across the normal at an end of the span on the
    outline, or along the normal on a side of the outline."""
    point, normal = face["point"], face["normal"]
    z = vec.unit(frame["z"])
    low, high = span
    h = vec.dot(vec.sub(point, start), z)
    if not low - FACE_TOL <= h <= high + FACE_TOL:
        return False
    uv = vec.frame_to_local(frame, point)[:2]
    along = vec.dot(vec.unit(normal), z)
    if abs(abs(along) - 1.0) <= NORMAL_TOL:
        on_end = min(abs(h - low), abs(h - high)) <= FACE_TOL
        return on_end and (footprint.covers(uv) or footprint.nearest_curve(uv)[1] <= FACE_TOL)
    if abs(along) > NORMAL_TOL:
        return False
    n, gap = footprint.nearest_curve(uv)
    curve = footprint.curves[n]
    d = _unit(curve["start"], curve["end"])
    across = [vec.dot(normal, frame["x"]), vec.dot(normal, frame["y"])]
    return gap <= FACE_TOL and abs(across[0] * d[0] + across[1] * d[1]) <= NORMAL_TOL


def flat_face(face):
    return (isinstance(face, dict) and face.get("surface") == "Plane" and _vector(face.get("point"))
            and _vector(face.get("normal")))


def _same_plane(face, point, normal):
    """True when the flat `face` lies on the plane through `point` with the unit outward `normal`, facing the same
    way."""
    return (vec.dot(vec.unit(face["normal"]), normal) >= 1.0 - NORMAL_TOL
            and abs(vec.dot(vec.sub(face["point"], point), normal)) <= FACE_TOL)


def _wall_planes(footprint, frame, start, span):
    """`(point, unit outward normal)` of each face of the wall: one per side of its outline, and both ends."""
    z = vec.unit(frame["z"])
    out = [(vec.add(start, vec.scale(z, span[0])), vec.scale(z, -1.0)),
           (vec.add(start, vec.scale(z, span[1])), z)]
    for n, curve in enumerate(footprint.curves):
        middle = [(curve["start"][i] + curve["end"][i]) / 2.0 for i in range(2)]
        outward = footprint.outward(n, middle)
        if outward is not None:
            out.append((vec.frame_apply(frame, middle + [0.0]),
                        vec.unit([outward[0] * frame["x"][i] + outward[1] * frame["y"][i] for i in range(3)])))
    return out


def merged(footprint, face, frame, start, span, before):
    """True when a flat face Fusion lists for the wall, whose point lies off the wall, is a face of the wall that
    Fusion merged with a face of the part: it lies on the plane of a face of the target body before the step
    (`before`, `target_faces_before`) and on the plane of a face of the wall, both facing the way it faces."""
    normal = vec.unit(face["normal"])
    if not any(flat_face(other) and _same_plane(other, face["point"], normal) for other in before or []):
        return False
    return any(_same_plane(face, point, outward) for point, outward in _wall_planes(footprint, frame, start, span))


def fits(footprint, faces, frame, start, span, before=None):
    """True when each face of `faces` (`wall_faces` records) is flat and lies on the wall (`on_wall`), or is a face
    of the wall merged with a face of the part (`merged`), and at least one lies on the wall (`on_wall`)."""
    if not all(flat_face(face) for face in faces):
        return False
    on = [on_wall(footprint, face, frame, start, span) for face in faces]
    return any(on) and all(ok or merged(footprint, face, frame, start, span, before) for ok, face in zip(on, faces))


def spans(length, symmetric):
    """[(way, (low, high))]: where a wall `length` long along the sketch normal can run from its start, centred on it
    (way 0) or to either side (way +1 or -1)."""
    if symmetric:
        return [(0, (-length / 2.0, length / 2.0))]
    return [(1, (0.0, length)), (-1, (-length, 0.0))]


def line_fits(line, sides, thickness, faces, start, ways, before=None):
    """[(side, way)]: each side of `sides` and each `(way, span)` of `ways` whose wall along the open `Line` fits the
    measured `faces` (`fits`)."""
    found = []
    for side in sides:
        footprint = Footprint(band_profile(line.frame, band(line.points, *reaches(side, thickness))))
        found += [(side, way) for way, span in ways if fits(footprint, faces, line.frame, start, span, before)]
    return found


def line_side(line, location, thickness, faces, start, length, symmetric, sign, before=None):
    """The side of the wall along an open `Line` in its own sketch frame (`inside`, `outside` or `middle`), or a
    Problem. `faces` are the `wall_faces` Fusion measured, `start` the 3D point where the extrude starts, `length` its
    distance, `symmetric` True for a symmetric extrude, `sign` its direction along the sketch normal (+1 or -1) and
    `before` the faces of the target body before the step (`target_faces_before`), for faces Fusion merged."""
    if not isinstance(faces, list) or not faces:
        return WALL_UNMEASURED
    found = line_fits(line, LOCATIONS[location], thickness, faces, start, spans(length, symmetric), before)
    if len(found) > 1:
        return UNSURE
    if not found:
        return NOT_MATCHING
    side, way = found[0]
    if (not symmetric and way != sign) or RULE.get(location, side) != side:
        return NOT_MATCHING
    return side
