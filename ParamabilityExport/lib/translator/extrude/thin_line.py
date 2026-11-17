"""Thin extrudes of an open line: a wall along a chain of straight sketch lines, with square ends and sharp corners.

The recipe writes it as an extrude whose outline is an `open` loop, with `thin` set to `ends: square` and
`corners: sharp` (recipe version 17). The loop runs from the first point of the line to its last, so it keeps the
direction of the line. The app puts an `inside` wall on the left of that direction (seen from the front of the
sketch, along its normal), an `outside` wall on the right, and a `middle` wall half on each side.

Fusion gives the line as a `Path` (`data.path`): its lines in path order, each with `opposed` (the path runs against
the line). The copy takes a path of one sketch whose lines run one after the other, each from the end of the one
before, none of them against the path. Arcs and free curves, and lines that run against the path, are refused: the
side Fusion puts the wall on is measured for lines that run along the path only.

The side. Fusion names it side one, side two or center. Measured on extrudes that go along the sketch normal, side
one is the left of the path direction and side two the right (`RULE`). Fusion lists no start or end faces for such an
extrude, so the copy reads the wall from the faces it made (`wall_faces`): each face must be flat and lie on a face of
the wall that a side and a direction give (`fits`). Exactly one side that Fusion's location allows, and one direction,
must fit. It must be the direction the extrude reader found, and, along the sketch normal, the side `RULE` names.
Else the step is left out.

The line at other sizes. Its points follow the probe's values for the path (`sketch_values.keys.path`). The wall
must keep its shape over the size ranges (`keep_line_valid`): each line longer than what its corners take from it,
no corner sharper than `MAX_TURN_DEG`, and no two lines that do not meet nearer than twice the wall. The ranges are
cut where it stops, or the sizes are marked.
"""
import math

from ...capture_model import gap_hints
from ...design_model.reach import sketch_sizes
from ...geometry import vec
from ...geometry.footprint import Footprint
from ...package.numbers import is_number, round9
from ...sketch_values import keys
from .. import values
from ..ranges import kept_ranges, range_check
from ..result import Refusal
from ..sketch import sketch_motion
from ..sketch.written_loops import curves_at, value, written_reads

# Two points this close (mm) are one: where a line ends and the next starts.
JOIN_TOL = 1e-4
# A line must be longer than this (mm) after its corners took their part of it.
LENGTH_TOL = 1e-3
# A corner turns by at most this. A sharper one sends the outer side of the wall far past the corner.
MAX_TURN_DEG = 150.0
# A face Fusion made lies on a face of the wall within this (mm), and its normal within this sine.
FACE_TOL = 1e-3
NORMAL_TOL = 1e-4
_FAILURES = (ArithmeticError, ValueError, KeyError, TypeError)

# The side of a wall along the sketch normal for side one and side two of Fusion (left of the path is the app's
# `inside`). For center the wall is `middle` either way.
RULE = {"side1": "inside", "side2": "outside"}
SIDES = {"center": ("middle",), "side1": ("inside", "outside"), "side2": ("inside", "outside")}
SWAPPED = {"inside": "outside", "outside": "inside", "middle": "middle"}

UNREADABLE = "The line of this thin extrude could not be read."
NOT_MATCHING = ("The wall Fusion made does not match the line, side and length of this thin extrude, so it is not "
                "copied.")
UNSURE = ("The side the wall of this thin extrude stands on could not be told from what Fusion made, so it is not "
          "copied.")
FOLDS = "the wall of %s would fold or its line cross itself"


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
    """The `Line` of a thin extrude's path record, or a Refusal."""
    path = data.get("path")
    curves = path.get("curves") if isinstance(path, dict) else None
    if not isinstance(curves, list) or not curves or not isinstance(path.get("frame"), dict):
        return Refusal(UNREADABLE)
    if any(not isinstance(c, dict) for c in curves) or path.get("closed") is None:
        return Refusal(UNREADABLE)
    if path.get("kind") != "sketch" or path.get("foreign") or path.get("truncated") or path["closed"]:
        return Refusal("The line of this thin extrude is not one open line of one sketch, so it is not copied.",
                       cause=gap_hints.THIN_OUTLINE)
    flats = [c.get("flat") for c in curves]
    if any(c.get("kind") != "line" for c in curves):
        return Refusal("A thin extrude of a line with arcs or curves is not copied yet.", cause=gap_hints.THIN_OUTLINE)
    if any(not isinstance(f, dict) or f.get("kind") != "line" for f in flats) or any(
            c.get("opposed") is None for c in curves):
        return Refusal(UNREADABLE)
    if any(c["opposed"] for c in curves):
        return Refusal("The lines of this thin extrude do not all run the same way along it, so the side of its wall "
                       "is not known.", cause=gap_hints.THIN_OUTLINE)
    points = [list(flats[0]["start"])]
    for flat in flats:
        if math.dist(flat["start"], points[-1]) > JOIN_TOL:
            return Refusal("The lines of this thin extrude do not run one after the other, so it is not copied.",
                           cause=gap_hints.THIN_OUTLINE)
        points.append(list(flat["end"]))
    return Line(path, points)


def open_loop(points):
    """The recipe's `open` loop through `points`."""
    return {"kind": "open", "start": [round9(c) for c in points[0]],
            "segments": [{"kind": "line", "to": [round9(c) for c in p]} for p in points[1:]]}


def outline(ctx, item, line):
    """`(loop, drawn)`: the written loop as numbers and its `sketch_motion.Outline` when the line follows sizes, else
    None. A line the probe did not follow keeps its numbers, and the sizes of its sketch are marked."""
    loop = open_loop(line.points)
    if not sketch_motion.active(ctx):
        sketch_motion.placement_doubts(ctx, item, line.path)
        return loop, None
    index = item.get("index")
    if keys.path(index) not in ctx.motion.curves:
        names = sketch_sizes(ctx.table, line.sketch) if line.sketch else ()
        if names:
            ctx.doubt(names, "%s copies its line from %s as measured" % (item.get("name", "a thin extrude"),
                                                                         line.sketch))
        sketch_motion.placement_doubts(ctx, item, line.path)
        return loop, None

    def raw(number, name, point):
        prefix = keys.path_curve(index, number)
        return [sketch_motion.raw(ctx, "%s%s.%d" % (prefix, name, c), float(point[c]), line.sketch) for c in range(2)]

    raw_loop = {"kind": "open", "start": raw(0, "start", line.points[0]),
                "segments": [{"kind": "line", "to": raw(n, "end", p)} for n, p in enumerate(line.points[1:])]}
    frame = line.frame
    plane = sketch_motion.raw(ctx, keys.path_plane(index), vec.dot(frame["origin"], frame["z"]), line.sketch)
    sketch_motion.placement_doubts(ctx, item, line.path, plane)
    return loop, sketch_motion.Outline(ctx, frame, [loop], [raw_loop], plane, line.sketch)


# ---- the wall as a closed outline -------------------------------------------------------------------------------

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
    nearer than twice the wall."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    if any(length <= LENGTH_TOL for length in lengths):
        return "a line of it is too short"
    dirs = [_unit(a, b) for a, b in zip(points, points[1:])]
    taken = [0.0] * (len(points) + 1)
    for k in range(1, len(points) - 1):
        a, b = dirs[k - 1], dirs[k]
        turn = math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1])
        if math.degrees(abs(turn)) > MAX_TURN_DEG:
            return "a corner of it is too sharp"
        # The side of the wall on the inside of a turn is cut short on both lines of the corner.
        taken[k] = (left if turn > 0 else right) * math.tan(abs(turn) / 2.0)
    if any(length - taken[k] - taken[k + 1] <= LENGTH_TOL for k, length in enumerate(lengths)):
        return "a line of it is shorter than its corners take"
    reach = 2.0 * max(left, right)
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


def band(points, left, right):
    """The corners of the wall as one closed outline (not repeating its first corner): along the left side from the
    start of the line, across its end, back along the right side."""
    return _side_points(points, left) + _side_points(points, -right)[::-1]


def band_profile(frame, corners):
    """A capture profile of the closed outline through `corners` in `frame`."""
    ring = corners + corners[:1]
    return {"frame": frame, "loops": [{"outer": True, "curves": [
        {"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(ring, ring[1:])]}]}


# ---- the side, from the faces Fusion made -------------------------------------------------------------------------

def _vector(v):
    return isinstance(v, list) and len(v) == 3 and all(is_number(c) for c in v)


def fits(footprint, faces, frame, start, span):
    """True when each face of `faces` (`wall_faces` records) lies on the wall whose outline is `footprint` in `frame`,
    running `span` (low, high, mm) along the sketch normal from `start`: a flat face across the normal at an end of the
    span on the outline, or a flat face along the normal on a side of the outline."""
    z = vec.unit(frame["z"])
    low, high = span
    for face in faces:
        point, normal = face.get("point"), face.get("normal")
        if face.get("surface") != "Plane" or not _vector(point) or not _vector(normal):
            return False
        h = vec.dot(vec.sub(point, start), z)
        if not low - FACE_TOL <= h <= high + FACE_TOL:
            return False
        uv = vec.frame_to_local(frame, point)[:2]
        along = vec.dot(vec.unit(normal), z)
        if abs(abs(along) - 1.0) <= NORMAL_TOL:
            on_end = min(abs(h - low), abs(h - high)) <= FACE_TOL
            if not on_end or not (footprint.covers(uv) or footprint.nearest_curve(uv)[1] <= FACE_TOL):
                return False
        elif abs(along) <= NORMAL_TOL:
            n, gap = footprint.nearest_curve(uv)
            curve = footprint.curves[n]
            d = _unit(curve["start"], curve["end"])
            across = [vec.dot(normal, frame["x"]), vec.dot(normal, frame["y"])]
            if gap > FACE_TOL or abs(across[0] * d[0] + across[1] * d[1]) > NORMAL_TOL:
                return False
        else:
            return False
    return True


def decide(line, location, thickness, faces, start, entry):
    """The side of the wall in the line's own sketch frame (`inside`, `outside` or `middle`), or a Refusal. `faces`
    are the `wall_faces` Fusion measured, `start` where the extrude starts and `entry` its planned `RecipeSide`."""
    if not isinstance(faces, list) or not faces:
        return Refusal("The wall of this thin extrude could not be measured, so it is not copied.")
    length = entry.distance
    if entry.extent == "symmetric":
        ways = [(1, (-length / 2.0, length / 2.0))]
    else:
        ways = [(1, (0.0, length)), (-1, (-length, 0.0))]
    found = []
    for side in SIDES[location]:
        corners = band(line.points, *reaches(side, thickness))
        footprint = Footprint(band_profile(line.frame, corners))
        found += [(side, way) for way, span in ways if fits(footprint, faces, line.frame, start, span)]
    if len(found) > 1:
        return Refusal(UNSURE)
    if not found:
        return Refusal(NOT_MATCHING)
    side, way = found[0]
    if entry.extent != "symmetric" and (way != entry.sign or (way > 0 and RULE.get(location, side) != side)):
        return Refusal(NOT_MATCHING)
    return side


class LineWall:
    """The wall of a thin extrude of an open line: `side` in the line's own sketch frame, `thickness` a Quantity, and
    `profile` the closed outline of the wall at the measured sizes (for the material placer)."""

    def __init__(self, side, thickness, profile):
        self.side, self.thickness, self.profile = side, thickness, profile

    def written(self, reverse):
        """The recipe's `thin`. A reversed placement mirrors the loop, so the left of the line becomes its right."""
        return {"thickness": self.thickness.json(), "side": SWAPPED[self.side] if reverse else self.side,
                "ends": "square", "corners": "sharp"}


def wall_step(ctx, item, data, wall, line, drawn, start, entry):
    """The `LineWall` of a thin extrude of an open line, or a Refusal: the side from the measured faces (`decide`),
    the thickness that follows its parameter, and the line's shape kept over the size ranges."""
    thickness = wall["thickness"]
    # The line alone first: a line that turns back on itself has no wall to compare the faces with.
    problem = line_problem(line.points, 0.0, 0.0)
    side = decide(line, wall["location"], thickness, data.get("wall_faces"), start, entry) if not problem else None
    if isinstance(side, Refusal):
        return side
    problem = problem or line_problem(line.points, *reaches(side, thickness))
    if problem:
        return Refusal("The wall of this thin extrude does not follow its line: %s." % problem,
                       cause=gap_hints.THIN_OUTLINE)
    thickness_q = values.quantity(ctx, item, "thin.thickness", thickness, absolute=True)
    if drawn is not None:
        keep_line_valid(ctx, item, drawn.preview()[0], thickness_q, side)
    return LineWall(side, thickness_q, band_profile(line.frame, band(line.points, *reaches(side, thickness))))


def keep_line_valid(ctx, item, loop, thickness_q, side):
    """Cut the ranges of the sizes that move the written `loop` or the wall thickness so the wall keeps its shape
    (`line_problem`) at every size setting tested: the corners and middles of the ranges, and inner settings for a
    formula that is more than sums and products. The sizes are marked when no cut keeps it."""
    reads = [n for n in dict.fromkeys(written_reads(loop) + tuple(thickness_q.reads)) if n not in ctx.doubted()]
    if ctx.table is None or not reads:
        return
    thickness = thickness_q.json()
    inner = any(range_check.needs_inner(text) for text in _formulas([loop, thickness]))

    def shaped(env):
        lines = curves_at(loop, env)
        points = [lines[0]["start"]] + [c["end"] for c in lines]
        return line_problem(points, *reaches(side, value(thickness, env))) is None

    def holds(bounds, only=None):
        if only is not None:
            settings = [{only[0]: bounds[only[0]][only[1]]}]
        else:
            settings = range_check.corners(ctx.table, reads, bounds) + range_check.middles(ctx.table, reads, bounds)
            if inner:
                settings += range_check.inner_settings(ctx.table, reads, bounds)
        try:
            return all(shaped(range_check.recipe_size_values(ctx.table, setting)) for setting in settings)
        except _FAILURES:
            return False

    found = kept_ranges.holding_ranges_where(ctx.table, reads, holds)
    why = FOLDS % item.get("name", "a thin extrude")
    if found is None:
        ctx.doubt(reads, "at other values " + why)
    elif found:
        ctx.cut(found, why)


def _formulas(node, out=None):
    """The formula texts of the written values in `node`."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("expr"), str):
            out.append(node["expr"])
        for item in node.values():
            _formulas(item, out)
    elif isinstance(node, list):
        for item in node:
            _formulas(item, out)
    return out
