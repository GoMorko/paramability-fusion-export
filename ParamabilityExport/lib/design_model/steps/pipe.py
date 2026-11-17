"""What a pipe step is, read from the capture for any destination: its section as an outline and where that outline
sits. Pure.

Fusion builds a pipe as a sweep of a drawn section (live check PI1 in `docs/hand-checks.md`):
- the section sits at the start of the path, square to the path and centred on it. The start is the start of the
  first curve of the path, run the way the path runs (`opposed` turns the curve round);
- `section_size` is the diameter of a circle section (the side of a square, the height of a triangle);
- a hollow pipe's wall goes inward from that size: `section_thickness` 2 on a diameter of 10 leaves a hole of 6;
- `distance_one` is the share of the path the pipe covers (1 is the whole path). `distance_two` runs the other way
  round a closed path; Fusion gives none for an open path.

Only a circle section is read as an outline: the API does not say which way a square or triangle section turns about
the path. How Fusion builds a pipe at a sharp corner of its path is not known (a sweep mitres it), so a path with one
gives a problem too (`corner_problem`). A `Problem` (`design_model/problem.py`) says why the pipe cannot be read.
"""
import math

from ...capture_model import gap_hints
from ...geometry import vec
from ...package.numbers import is_number
from ..paths.curves import flip, near, readable, tangents, turn_deg
from ..paths.tolerances import SMOOTH_JOIN_DEG, STRAIGHT_DEG
from ..problem import Problem
from .. import words

ZERO_TOL = 1e-6

SECTION_KIND = Problem("section_kind", words.PIPE_SECTION_KIND, gap_hints.PIPE)
SECTION_UNREAD = Problem("section_unread", words.PIPE_SECTION_UNREAD)
COVER_UNREAD = Problem("cover_unread", words.PIPE_COVER_UNREAD)
PART_OF_PATH = Problem("part_of_path", words.PIPE_PART_OF_PATH, gap_hints.PIPE_PART_OF_PATH)
PATH_UNREAD = Problem("path_unread", words.PIPE_PATH_UNREAD)
START_UNREAD = Problem("start_unread", words.PIPE_START_UNREAD)
SHARP_CORNER = Problem("sharp_corner", words.PIPE_SHARP_CORNER, gap_hints.SHARP_CORNER)


def _length(value):
    """True for a finite length above zero."""
    return is_number(value) and math.isfinite(value) and value > ZERO_TOL


def section_problem(data):
    """The problem of a pipe whose section is not a circle, or whose size, wall or cover of the path cannot be read
    or is not the whole path. None when the section and the cover are plain."""
    section = data.get("section")
    if section in ("square", "triangular"):
        return SECTION_KIND
    if section != "circular":
        return SECTION_UNREAD
    size, hollow, wall = data.get("section_size"), data.get("hollow"), data.get("section_thickness")
    if not _length(size) or not isinstance(hollow, bool):
        return SECTION_UNREAD
    if hollow and (not _length(wall) or 2.0 * wall >= size - ZERO_TOL):
        return SECTION_UNREAD
    return cover_problem(data)


def cover_problem(data):
    """The problem of a pipe that does not run once along its whole path: `distance_one` must be 1 and
    `distance_two` absent or 0."""
    one, two = data.get("distance_one"), data.get("distance_two")
    if not is_number(one) or data.get("distance_two_unread") or not (two is None or is_number(two)):
        return COVER_UNREAD
    if abs(one - 1.0) > ZERO_TOL or (two is not None and abs(two) > ZERO_TOL):
        return PART_OF_PATH
    return None


def radii(data):
    """`(outer, inner)` radii of the section in mm; inner is None for a solid pipe. Read `section_problem` first."""
    outer = data["section_size"] / 2.0
    return outer, (outer - data["section_thickness"] if data["hollow"] else None)


def _across(direction):
    """A unit vector square to `direction`."""
    other = [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 1.0, 0.0]
    return vec.unit(vec.cross(direction, other))


def _joint_start(first, second):
    """The end of the first curve that the second curve does not touch, as the curve run from it, or None when both
    or neither ends touch it."""
    touches = [any(near(first[end], second[k]) for k in ("start", "end") if k in second) for end in ("start", "end")]
    if touches == [False, True]:
        return first
    if touches == [True, False]:
        return flip(first)
    return None


def start_of(path):
    """`(point, direction)`: where the section sits and the unit direction the path leaves it in, or a Problem.

    A circle section carried along a path makes the same shape from either end, and round a closed path from any
    point, so the start only names the end faces (the sweep's end face check reads them). A full circle starts at a
    point square to its normal. When Fusion does not say which way the first curve runs, an open path of several
    curves starts at the end of the first curve that the second does not touch, and one curve at its own start."""
    curves = path.get("curves") if isinstance(path, dict) else None
    if not isinstance(curves, list) or not curves or not all(isinstance(c, dict) for c in curves):
        return PATH_UNREAD
    first = curves[0]
    if first.get("kind") == "circle":
        if not readable(first) or len(curves) != 1:
            return PATH_UNREAD
        normal = vec.unit(first["normal"])
        across = _across(normal)
        return vec.add(first["center"], vec.scale(across, first["radius"])), vec.unit(vec.cross(normal, across))
    if first.get("kind") not in ("line", "arc", "other") or not readable(first):
        return PATH_UNREAD
    opposed = first.get("opposed")
    if isinstance(opposed, bool):
        run = flip(first) if opposed else first
    elif len(curves) > 1 and path.get("closed") is False:
        run = _joint_start(first, curves[1]) if readable(curves[1]) and curves[1].get("kind") != "circle" else None
    else:
        run = first
    if run is None:
        return START_UNREAD
    return list(run["start"]), tangents(run)[0]


def section_profile(data, start):
    """The section as a profile record (the shape a sketch profile has in the capture) on the plane square to the
    path at `start` (`start_of`), centred on the path, and its area in mm2. Read `section_problem` first."""
    point, direction = start
    z = vec.unit(direction)
    x = _across(z)
    frame = {"origin": [float(c) for c in point], "x": x, "y": vec.cross(z, x), "z": z}
    outer, inner = radii(data)
    loops = [{"outer": True, "curves": [{"kind": "circle", "center": [0.0, 0.0], "radius": outer}]}]
    area = math.pi * outer * outer
    if inner is not None:
        loops.append({"outer": False, "curves": [{"kind": "circle", "center": [0.0, 0.0], "radius": inner}]})
        area -= math.pi * inner * inner
    return {"frame": frame, "space": "sketch", "loops": loops}, area


def corner_problem(curves, closed):
    """`SHARP_CORNER` when the planned path (`PathPlan.curves`, in order) turns sharply where two parts meet, or where
    a closed path meets itself; else None. Two lines meet sharply above `STRAIGHT_DEG`, a curve and its neighbour above
    `SMOOTH_JOIN_DEG`, as the app takes them."""
    pairs = list(zip(curves, curves[1:])) + ([(curves[-1], curves[0])] if closed and len(curves) > 1 else [])
    for before, after in pairs:
        limit = STRAIGHT_DEG if before["kind"] == after["kind"] == "line" else SMOOTH_JOIN_DEG
        if turn_deg(tangents(before)[1], tangents(after)[0]) > limit:
            return SHARP_CORNER
    return None
