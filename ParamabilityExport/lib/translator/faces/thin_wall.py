"""Thin extrudes of a closed outline: the wall they leave, which side of the outline it sits on, and its placer.

The recipe's `thin` extrude draws a wall of one thickness along one closed outline, on the `inside` of it, on the
`outside`, or `middle` (half each way). Fusion names the side with its own wall location (side one, side two or
center), and the API does not say which of side one and side two is the inside. The measured area of the end face
decides: it is the cross section of the wall, so the expected area of each candidate side is worked out from the
outline and compared with it.

The expected area of a wall of thickness `t` follows the outline with its corners. Moving a line and arc outline by
`d` adds a strip of `perimeter * d`, plus `d^2 / 2` times the turning of its arcs, plus one more term per corner: a
corner that opens a gap on the moved side (a convex corner going outward, a concave one going inward) adds a round
sector in the app and a sharp wedge when the corner is kept sharp, and a corner that overlaps removes a kite. The app
rounds, and Fusion is expected to keep corners sharp, so both are tried. Where only the sharp reading fits, the copy
has rounded corners and says so in a note.
"""
import math

from ...capture_model import gap_hints
from ...geometry.footprint import arc_span, closed_chain, curve_length, is_full, polyline
from ...package.numbers import is_number
from ..result import Refusal
from .placer import ADD, CUT, Placer
from .slabs import Slab

AREA_RELATIVE_TOL = 5e-3
AREA_ABSOLUTE_TOL = 1e-2
# A corner that turns back almost on itself has no usable wedge.
MAX_TURN = math.pi - 1e-3
CORNER_EPS = 1e-6
BAND_TOL = 1e-3

ROUND, SHARP = "round", "sharp"
SIDES = ("inside", "outside", "middle")
LOCATIONS = {"center": ("middle",), "side1": ("inside", "outside"), "side2": ("inside", "outside")}

UNREADABLE = "A setting of this thin extrude could not be read from Fusion."


def prepare(data):
    """The thin wall record of an extrude's data, or a Refusal when it cannot be copied before looking at outlines.

    A wall is copied for one outline, one thickness and a distance that runs one way or symmetric. Two sides, a
    taper, a reach to a face or through all are refused."""
    wall = data.get("thin_wall")
    if not isinstance(wall, dict) or wall.get("location") is None or not is_number(wall.get("thickness")):
        return Refusal(UNREADABLE)
    if wall["location"] not in LOCATIONS:
        return Refusal("The wall of this thin extrude sits in a way that is not copied yet.")
    if not wall["thickness"] > 0:
        return Refusal("This thin extrude has no wall thickness.")
    kind = data.get("extent_type")
    if kind == "two":
        return Refusal("A thin extrude that goes two ways is not copied yet.")
    if kind == "symmetric":
        side, taper = data.get("symmetric"), (data.get("symmetric") or {}).get("taper_deg")
        reaches = isinstance(side, dict)
    else:
        side = data.get("side_one")
        taper = (side or {}).get("taper_deg")
        reaches = isinstance(side, dict) and side.get("kind") == "distance"
    if not reaches:
        return Refusal("A thin extrude that reaches to a face or goes through is not copied yet.")
    if taper is None:
        return Refusal(UNREADABLE)
    if taper:
        return Refusal("A thin extrude with a taper is not copied.")
    return wall


def open_line_refusal(profiles):
    """A Refusal for a profile input that is not a closed sketch outline: an open line whose path was not read (a
    capture of an older add-in reads it as entities without a path)."""
    if any(p.get("kind") == "other" and "loops" not in p for p in profiles):
        return Refusal("The open line of this thin extrude could not be read, so it is not copied.",
                       cause=gap_hints.THIN_OUTLINE)
    return None


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


def decide(curves, wall, end_area):
    """`(side, rounded)` for a wall: the side of the outline it sits on (inside, outside or middle), and whether the
    copy rounds corners that Fusion keeps sharp. A Refusal when the measured end area fits no side, or fits more than
    one."""
    if not is_number(end_area) or not end_area > 0:
        return Refusal("The size of the wall of this thin extrude could not be measured, so it is not copied.")
    shape = shape_of(curves)
    if shape is None:
        return Refusal("The outline of this thin extrude is not one closed outline of lines and arcs.")
    thickness = wall["thickness"]
    found = {}
    for side in LOCATIONS[wall["location"]]:
        for corners in (ROUND, SHARP):
            expected = band_area(shape, side, thickness, corners)
            if expected > 0 and _close(end_area, expected):
                found.setdefault(side, corners)
    if len(found) > 1:
        return Refusal("The side the wall of this thin extrude sits on could not be told, so it is not copied.")
    if not found:
        return Refusal("The wall of this thin extrude does not match its outline and thickness, so it is not copied.")
    side, corners = next(iter(found.items()))
    rounded = corners == SHARP and (
        band_area(shape, side, thickness, SHARP) - band_area(shape, side, thickness, ROUND) > AREA_ABSOLUTE_TOL)
    return side, rounded


class ThinWall(Placer):
    """The wall of a thin extrude as material only: it says whether a point lies in the wall at the measured sizes.

    Its faces are not placed (`place` gives nothing), so a later pick on one of them is placed on earlier steps or its
    sizes are marked, and `opaque` makes a step on another part's sketch say it cannot check that it still meets the wall."""

    opaque = True

    def __init__(self, step_id, on, extent, length, profile, side, thickness, combine):
        self.slab = Slab(step_id, on, extent, length, profile, combine=combine)
        self.combine = combine
        reach = {"inside": (0.0, thickness), "outside": (-thickness, 0.0),
                 "middle": (-thickness / 2.0, thickness / 2.0)}[side]
        self.band = reach

    def place(self, p, edge):
        return None

    def material_at(self, p):
        if self.combine not in ("new", "add", "cut"):
            return None
        slab = self.slab
        h, uv = slab.local(p)
        low, high = slab.span
        if not low - BAND_TOL <= h <= high + BAND_TOL:
            return None
        depth = slab.depth_in(uv)[1]
        if not self.band[0] - BAND_TOL <= depth <= self.band[1] + BAND_TOL:
            return None
        return CUT if self.combine == "cut" else ADD
