"""The outline that the touching outlines of one revolve make together, for picks where they meet (faces/follow.py).

Fusion turns all the outlines of one revolve at once, so outlines that share a sketch curve make one solid. Its faces
come from the outer boundary of the outlines together; a shared curve makes no face. The recipe writes one revolve
step for each outline, and the placer of each step (faces/revolve_placer.py) knows only its own outline. So a wall
that runs across two outlines (the inner wall that a shell leaves along a lid and its rim) is the wall of neither.

`geometry.outlines.merge_touching` joins the outlines as an extrude does: the shared curves are left out, and the
pieces of one sketch line are joined back. The joined outline gets a placer of its own (`JoinedRevolve`), made once
the steps of all its parts are written. It is the latest placer, so a pick is placed on it first; a point it does not
place goes to the placers of the parts, as before. Its corners follow sizes through the corners of the parts
(`sketch/joined_outline.py`).

The joined outline is used only while it is the outline of the parts, at the sizes now and at every size setting over
the ranges (`range_check.corners` and `middles`, inside the ranges cut for the parts):

- no part and not the joined outline cross or touch themselves: a meeting point that slides off the end of the line
  it lies on folds the part that holds that line back on itself, and outlines that overlap give a joined outline
  that crosses itself;
- each part and the joined outline keep the way they run round: a part that turns over onto its neighbour runs
  round the other way.

Else, and for outlines with holes, two parts that move a shared corner apart, or a setting that cannot be worked out,
the revolve has no joined placer, and a pick where its outlines meet is marked as before.
"""
from ...geometry import outlines
from ...geometry.footprint import polyline
from ...params.expressions.errors import ExpressionError
from ..ranges import range_check
from ..result import Refusal
from ..sketch import loops
from ..sketch.joined_outline import joined_outline
from ..sketch.sketch_crossings import loop_crosses
from ..sketch.written_loops import profile_at, written_reads
from .revolve_placer import LENGTH_TOL_MM, RevolvePlacer, Turn

_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, KeyError, TypeError)


class JoinedRevolve:
    """The joined outline of `count` written revolve steps (`turn`, a `Turn`). Each step's maker hands over its
    placer (`made`); after the last one the placer of the joined outline is added. The steps it looks behind for
    faces it shares are those written before the first part: the parts hold its own faces."""

    def __init__(self, turn, count):
        self.turn, self.count = turn, count
        self._ctx, self._parts = None, []

    def made(self, ctx, part):
        if ctx is not self._ctx:
            self._ctx, self._parts = ctx, []
        self._parts.append(part)
        if len(self._parts) < self.count:
            return
        parts, self._ctx, self._parts = self._parts, None, []
        first = parts[0]
        joined = RevolvePlacer(first.id, first.label, self.turn, ctx.placers[:first.order], first.combine)
        joined.joins = tuple(parts)
        ctx.add_placer(joined)


def joined_revolves(ctx, profiles, turns):
    """{position of an outline in `profiles`: its `JoinedRevolve`} for the outlines of one revolve (their `Turn`s in
    `turns`) that share a curve with another and join into one outline that holds over the ranges."""
    if len(profiles) < 2:
        return {}
    found = {}
    for profile in outlines.merge_touching(profiles):
        parts = profile.get("merged_from") or []
        if len(parts) < 2:
            continue
        turn = joined_turn(ctx, profile, [turns[n] for n in parts])
        if turn is not None:
            group = JoinedRevolve(turn, len(parts))
            found.update((n, group) for n in parts)
    return found


def joined_turn(ctx, profile, parts):
    """The `Turn` of the outline `profile` joined from the outlines of `parts` (their `Turn`s, about one axis), or
    None when it may not be their outline at every size."""
    built = loops.profile_loops(profile)
    if isinstance(built, Refusal) or built[1]:
        return None
    pieces = [loops.profile_loops(part.profile) for part in parts]
    if any(isinstance(piece, Refusal) or piece[1] for piece in pieces):
        return None
    drawn = [part.outline for part in parts]
    outline = None
    if any(d is not None for d in drawn):
        if any(d is None for d in drawn):
            return None
        outline = joined_outline(ctx, profile, [built[0]], drawn)
        if outline is None:
            return None
        built = outline.preview()
        pieces = [d.preview() for d in drawn]
    if not _holds(ctx.table, built[0], [piece[0] for piece in pieces], outline):
        return None
    first = parts[0]
    return Turn(profile, outline, first.table, first.axis_point, first.axis_raw, first.axis_dir, first.back,
                first.total)


def _settings(table, written, outline):
    """The size values (by recipe name) to test the written loops at: the values now first, then the settings over
    the ranges of the sizes they read, inside the ranges cut for the outline."""
    if table is None:
        return [{}]
    reads = written_reads(*written)
    bounds = outline.bounds if outline is not None else None
    found = range_check.corners(table, reads, bounds) + range_check.middles(table, reads, bounds)
    return [range_check.recipe_size_values(table, setting) for setting in found]


def _points(curves):
    """The points of a closed chain of curves, arcs drawn as short lines."""
    points = []
    for curve in curves:
        line = polyline(curve)
        if "start" in curve and _gap(line[-1], curve["start"]) < _gap(line[0], curve["start"]):
            line = line[::-1]
        points += line if not points else line[1:]
    if len(points) > 1 and _gap(points[0], points[-1]) <= LENGTH_TOL_MM:
        points.pop()
    return points


def _gap(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _area(points):
    """The area a closed loop encloses, positive when it runs counter clockwise."""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2.0


def _holds(table, joined, parts, outline):
    """True when the written outer loop `joined` stays the outline of the written outer loops `parts` at every
    setting: no loop crosses or touches itself, and each loop keeps the way it runs round. Then the outline drawn
    through the curves of the parts that no other part shares is the outline of all of them, and no two of them
    overlap. A meeting point that slides off the end of the line it lies on folds the outline that holds that line,
    and an outline that turns over onto another one runs round the other way."""
    written = [joined] + list(parts)
    base = None
    try:
        for env in _settings(table, written, outline):
            rings = [_points(profile_at(loop, [], env)["loops"][0]["curves"]) for loop in written]
            if any(loop_crosses(ring) for ring in rings):
                return False
            turns = [_area(ring) > 0 for ring in rings]
            if base is None:
                base = turns
            elif turns != base:
                return False
    except _FAILURES:
        return False
    return True
