"""Thin walls along an open line that has arcs: the band Fusion makes, its checks and its exact area. Pure.

The line is a list of pieces in path order (`thin.Line.pieces`): capture curves in the sketch's own 2D frame, each
turned to run along the path, a line `{kind, start, end}` or an arc `{kind, start, mid, end, center, radius}`.

Fusion's wall moves each piece by the reach of the wall on each side: a line to a parallel line, an arc to an arc about
the same centre whose radius is less or more by the reach. Where two lines meet, the moved lines meet in a sharp
corner, as for a line of lines only (`thin.band`). Where an arc meets a line or another arc, only a tangent joint is
copied: the moved pieces then meet end to end. At any other joint next to an arc Fusion may fill or round the corner,
so the step is left out. The ends are square.

An arc turns by at most half a circle. Then two pieces that meet at a tangent joint lie on the two sides of the line
square to the path at the joint, so their walls meet only along it, and the band is one outline when pieces that do
not meet stay apart by more than the wall reaches.

Fusion lists no end faces for such a wall, so the size is checked on the part (`size_problem`): the part's volume must
change by the band's exact area (`band_area`, lines and arc segments) times the length.
"""
import math

from ...capture_model import gap_hints
from ...geometry.footprint import arc_span
from ...package.numbers import is_number
from .. import words
from ..problem import Problem
from . import thin

# A line or an arc must be longer than this (mm), also after its corners took their part of it, and a moved arc must
# keep a radius longer than this.
LENGTH_TOL = thin.LENGTH_TOL
# The turn between a piece and an arc next to it (degrees) that still counts as a tangent joint. The tolerance allows
# for the rounding of the captured points.
TANGENT_TOL_DEG = 1e-3
# An arc turns by at most this (degrees).
MAX_SWEEP_DEG = 180.0
# The most a corner between two lines turns (degrees), as for a line of lines only.
MAX_TURN_DEG = thin.MAX_TURN_DEG
_TURN_TOL_DEG = 1e-3
# The points on an arc for the distance between pieces.
_ARC_STEPS = 64
# The part's volume changed by the band's volume within this share of it plus this (mm3), as for a rib.
VOLUME_RELATIVE_TOL = 1e-4
VOLUME_ABSOLUTE_TOL = 1e-2

VOLUME_UNMEASURED = Problem("arc_volume_unmeasured", words.THIN_ARC_UNMEASURED, gap_hints.THIN_OUTLINE)
VOLUME_DIFFERS = Problem("arc_volume_differs", words.THIN_ARC_VOLUME, gap_hints.THIN_OUTLINE)


def _shape(code, text):
    return Problem(code, text, gap_hints.THIN_OUTLINE)


TOO_SHORT = _shape("arc_piece_too_short", "a piece of it is too short")
ARC_TOO_WIDE = _shape("arc_turns_too_far", "an arc of it turns more than half a circle")
ARC_CORNER = _shape("arc_corner", "it has a corner next to an arc")
CORNER_TOO_SHARP = _shape("arc_corner_too_sharp", "a corner of it is too sharp")
WALL_TOO_THICK = _shape("arc_wall_too_thick", "the wall is thicker than the radius of an arc of it")
LINE_TOO_SHORT = _shape("arc_line_too_short", "a line of it is shorter than its corners take")
PIECES_TOO_NEAR = _shape("arc_pieces_too_near", "two of its pieces come too near")


def sweep(arc):
    """The signed turn of an arc along the path (radians, positive to the left)."""
    return arc_span(arc)[1]


def _unit(d):
    size = math.hypot(*d)
    return [d[0] / size, d[1] / size]


def direction(piece, at_end):
    """The unit direction of travel of a piece at its end or its start."""
    if piece["kind"] == "line":
        return _unit([piece["end"][0] - piece["start"][0], piece["end"][1] - piece["start"][1]])
    point, centre = piece["end" if at_end else "start"], piece["center"]
    sign = 1.0 if sweep(piece) >= 0 else -1.0
    return _unit([-sign * (point[1] - centre[1]), sign * (point[0] - centre[0])])


def _turn(a, b):
    u, v = direction(a, True), direction(b, False)
    return math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])


def _length(piece):
    if piece["kind"] == "line":
        return math.dist(piece["start"], piece["end"])
    return abs(sweep(piece)) * piece["radius"]


def _moved(piece, offset):
    """The piece moved `offset` to its left (to its right when below zero), or None when an arc would not keep a
    radius longer than LENGTH_TOL. The left of an arc that turns left is toward its centre."""
    if piece["kind"] == "line":
        u = direction(piece, False)
        n = [-u[1], u[0]]
        return {"kind": "line", "start": [piece["start"][i] + offset * n[i] for i in range(2)],
                "end": [piece["end"][i] + offset * n[i] for i in range(2)]}
    centre = piece["center"]
    radius = piece["radius"] - (1.0 if sweep(piece) >= 0 else -1.0) * offset
    if radius <= LENGTH_TOL:
        return None

    def out(point):
        d = _unit([point[0] - centre[0], point[1] - centre[1]])
        return [centre[0] + radius * d[0], centre[1] + radius * d[1]]

    return {"kind": "arc", "start": out(piece["start"]), "mid": out(piece["mid"]), "end": out(piece["end"]),
            "center": list(centre), "radius": radius}


def _meet(a, b):
    """Where the lines through the line pieces `a` and `b` cross, or None when they are parallel."""
    u, v = direction(a, False), direction(b, False)
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) <= 1e-12:
        return None
    p, q = a["start"], b["start"]
    t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / cross
    return [p[0] + t * u[0], p[1] + t * u[1]]


def side_of(pieces, offset):
    """The pieces of the line moved `offset` to its left (to its right when below zero), in path order: two moved
    lines meet where they cross, and a piece after an arc or before one starts where the one before ends (a tangent
    joint). None when an arc does not keep a radius."""
    moved = [_moved(piece, offset) for piece in pieces]
    if any(piece is None for piece in moved):
        return None
    for a, b in zip(moved, moved[1:]):
        hit = _meet(a, b) if a["kind"] == b["kind"] == "line" else None
        if hit is not None:
            a["end"], b["start"] = hit, list(hit)
        else:
            b["start"] = list(a["end"])
    return moved


def _reversed(piece):
    out = dict(piece, start=piece["end"], end=piece["start"])
    return out


def band_curves(pieces, left, right):
    """The wall reaching `left` and `right` of the line as one closed outline of capture curves: along the left side
    from the start of the line, across its end, back along the right side, across its start. None when an arc does
    not keep a radius."""
    lefts, rights = side_of(pieces, left), side_of(pieces, -right)
    if lefts is None or rights is None:
        return None
    back = [_reversed(piece) for piece in reversed(rights)]
    return (lefts + [{"kind": "line", "start": list(lefts[-1]["end"]), "end": list(rights[-1]["end"])}] + back
            + [{"kind": "line", "start": list(rights[0]["start"]), "end": list(lefts[0]["start"])}])


def band_area(curves):
    """The exact area of a closed outline of lines and arcs: the polygon of their ends plus the segment each arc adds
    or takes away."""
    total = 0.0
    for curve in curves:
        a, b = curve["start"], curve["end"]
        total += 0.5 * (a[0] * b[1] - b[0] * a[1])
        if curve["kind"] == "arc":
            turn = sweep(curve)
            total += 0.5 * curve["radius"] ** 2 * (turn - math.sin(turn))
    return abs(total)


def _points(piece):
    """Points along a piece and how far its chords may lie from it (mm)."""
    if piece["kind"] == "line":
        return [piece["start"], piece["end"]], 0.0
    start, turn = arc_span(piece)
    centre, radius = piece["center"], piece["radius"]
    points = [[centre[0] + radius * math.cos(start + turn * k / _ARC_STEPS),
               centre[1] + radius * math.sin(start + turn * k / _ARC_STEPS)] for k in range(_ARC_STEPS + 1)]
    return points, radius * (1.0 - math.cos(turn / (2.0 * _ARC_STEPS)))


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


def _gap(a, b):
    """The least distance between two pieces, never more than the true distance."""
    (pa, ea), (pb, eb) = _points(a), _points(b)
    return min(_segment_gap(p, q, r, s) for p, q in zip(pa, pa[1:]) for r, s in zip(pb, pb[1:])) - ea - eb


def check(pieces, left, right):
    """The Problem (a code and a short reason) why a wall reaching `left` and `right` of the line of `pieces` is not the band copied here, or None: a piece
    too short, an arc that turns more than half a circle, a joint next to an arc that is not tangent, a corner of two
    lines sharper than MAX_TURN_DEG, an arc whose moved radius reaches zero, a line shorter than its corners take, or
    two pieces that do not meet nearer than twice the farthest the wall reaches from its line. None when the
    band is the one copied here."""
    for piece in pieces:
        if _length(piece) <= LENGTH_TOL:
            return TOO_SHORT
        if piece["kind"] == "arc" and math.degrees(abs(sweep(piece))) > MAX_SWEEP_DEG + _TURN_TOL_DEG:
            return ARC_TOO_WIDE
    spread = max(left, right)
    for a, b in zip(pieces, pieces[1:]):
        turn = math.degrees(_turn(a, b))
        if "arc" in (a["kind"], b["kind"]):
            if abs(turn) > TANGENT_TOL_DEG:
                return ARC_CORNER
            continue
        if abs(turn) > MAX_TURN_DEG + _TURN_TOL_DEG:
            return CORNER_TOO_SHARP
        # The outer side of a corner of two lines meets in a tip past the corner.
        outer = right if turn > 0 else left
        spread = max(spread, outer / math.cos(math.radians(abs(turn)) / 2.0))
    for offset in (left, -right):
        moved = side_of(pieces, offset)
        if moved is None:
            return WALL_TOO_THICK
        for piece, now in zip(pieces, moved):
            if piece["kind"] == "line":
                if math.dist(now["start"], now["end"]) <= LENGTH_TOL:
                    return LINE_TOO_SHORT
                u, v = direction(piece, False), direction(now, False)
                if u[0] * v[0] + u[1] * v[1] <= 0:
                    return LINE_TOO_SHORT
    reach = 2.0 * spread
    for i in range(len(pieces)):
        for j in range(i + 2, len(pieces)):
            if _gap(pieces[i], pieces[j]) <= reach + LENGTH_TOL:
                return PIECES_TOO_NEAR
    return None


def problem(pieces, left, right):
    """The short reason `check` gives, or None."""
    found = check(pieces, left, right)
    return None if found is None else found.words


def volume_change(item, data):
    """How much the step changed the volume of the body the walk builds (mm3, below zero when it took material
    away), or None when it was not measured. The data's `volume_before` and `volume_after` stand when the walk read
    them on its own body (`roles.seen_on`), else the item's `target_before` and `target_after`. A new body grows from
    nothing: its volume after the step is the change."""
    if "volume_before" in data or "volume_after" in data:
        before, after = data.get("volume_before"), data.get("volume_after")
    else:
        before = (item.get("target_before") or {}).get("volume_mm3")
        after = (item.get("target_after") or {}).get("volume_mm3")
    if data.get("operation") == "newBody":
        # The body is new: it grows from nothing, whatever body was measured before the step.
        before = 0.0
    if not is_number(before) or not is_number(after):
        return None
    return after - before


def size_problem(item, data, curves, length):
    """A Problem when the volume of the part did not change by the area of the band `curves` times `length` (more
    for a new body or a join, less for a cut), else None. A join or a cut that overlaps the part changes it by less,
    so it is left out too."""
    change = volume_change(item, data)
    if change is None:
        return VOLUME_UNMEASURED
    expected = band_area(curves) * length
    made = -change if data.get("operation") == "cut" else change
    if data.get("operation") not in ("newBody", "join", "cut") or abs(made - expected) > (
            VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL):
        return VOLUME_DIFFERS
    return None
