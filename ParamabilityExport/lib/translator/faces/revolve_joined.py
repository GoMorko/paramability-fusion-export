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
the ranges (`range_check.corners` and `middles`, inside the ranges cut for the parts, and for each size alone a
setting between each two places where a corner passes the line of an edge, `_between`):

- no part and not the joined outline cross or touch themselves: a meeting point that slides off the end of the line
  it lies on folds the part that holds that line back on itself, and outlines that overlap give a joined outline
  that crosses itself;
- each part and the joined outline keep the way they run round: a part that turns over onto its neighbour runs
  round the other way.

Else, and for outlines with holes, outlines on both sides of the axis, two parts that move a shared corner apart, or
a setting that cannot be worked out, the revolve has no joined placer, and a pick where its outlines meet is marked
as before. A shell that opens a face of the joined outline opens the curves of the parts along it too
(faces/shells.py), so a part never reads an opened face as a closed one.
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
from .slabs import LATERAL_TOL

_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, KeyError, TypeError)
# Most places for one size where a corner passes the line of an edge; past it the outline is not checked closely
# enough, and there is no joined outline.
MAX_BETWEEN = 256


class JoinedRevolve:
    """The joined outline of `count` written revolve steps (`turn`, a `Turn`). The maker of each step hands over its
    placer with its place among the parts (`made`). Once every place is filled in one walk, the placer of the joined
    outline is added. The steps it looks behind for faces it shares are those written before the first part: the
    parts hold its own faces."""

    def __init__(self, turn, count):
        self.turn, self.count = turn, count
        self._ctx, self._parts = None, {}

    def made(self, ctx, at, part):
        if ctx is not self._ctx or at in self._parts:
            self._ctx, self._parts = ctx, {}
        self._parts[at] = part
        if set(self._parts) != set(range(self.count)):
            return
        parts = tuple(self._parts[n] for n in range(self.count))
        self._ctx, self._parts = None, {}
        first = min(parts, key=lambda placer: placer.order)
        joined = RevolvePlacer(first.id, first.label, self.turn, ctx.placers[:first.order], first.combine)
        joined.joins = parts
        ctx.add_placer(joined)


def joined_revolves(ctx, profiles, turns):
    """{position of an outline in `profiles`: (its `JoinedRevolve`, its place among the parts)} for the outlines of
    one revolve (their `Turn`s in `turns`) that share a curve with another and join into one outline that holds over
    the ranges."""
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
            found.update((n, (group, at)) for at, n in enumerate(parts))
    return found


def joined_turn(ctx, profile, parts):
    """The `Turn` of the outline `profile` joined from the outlines of `parts` (their `Turn`s, about one axis), or
    None when it may not be their outline at every size."""
    built = loops.profile_loops(profile)
    if isinstance(built, Refusal) or built[1] or _across_axis(profile, parts):
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


def _across_axis(profile, parts):
    """True when the joined outline reaches both sides of the axis, or two parts share a line on the axis: outlines
    on the two sides of the axis turn into the same solid, and the placer reads one side only."""
    first = parts[0]
    a, d = first.axis_point, first.axis_dir

    def across(uv):
        return (uv[0] - a[0]) * -d[1] + (uv[1] - a[1]) * d[0]

    reach = [across(q) for loop in profile["loops"] for curve in loop["curves"] for q in polyline(curve)]
    if reach and max(reach) > LATERAL_TOL and min(reach) < -LATERAL_TOL:
        return True
    on_axis = {}
    for part in parts:
        for curve in part.footprint.curves:
            if curve["kind"] == "line" and all(abs(across(curve[end])) <= LATERAL_TOL for end in ("start", "end")):
                key = tuple(sorted((round(curve[e][0], 4), round(curve[e][1], 4)) for e in ("start", "end")))
                on_axis[key] = on_axis.get(key, 0) + 1
    return any(count > 1 for count in on_axis.values())


def _settings(table, written, outline):
    """The size values (by recipe name) to test the written loops at: the values now first, then the settings over
    the ranges of the sizes they read, inside the ranges cut for the outline."""
    if table is None:
        return [{}]
    reads = written_reads(*written)
    bounds = outline.bounds if outline is not None else None
    found = range_check.corners(table, reads, bounds) + range_check.middles(table, reads, bounds)
    between = _between(table, written, reads, bounds)
    if between is None:
        return None
    return [range_check.recipe_size_values(table, setting) for setting in found + between]


def _ends(table, name, bounds):
    """(low, high) of the size `name` (a recipe name), the cut range when `bounds` has one; None without a range."""
    size = table.sizes.get(name) or {}
    if bounds and name in bounds:
        return tuple(bounds[name])
    return (size["min"], size["max"]) if "min" in size and "max" in size else None


def _corners_at(written, env):
    """The corners of each written loop at `env`, in order."""
    return [[curve["start"] for curve in profile_at(loop, [], env)["loops"][0]["curves"] if "start" in curve]
            for loop in written]


def _side(p, a, b):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _roots(values, low, high):
    """The places strictly inside (low, high) where the quadratic through the three values at low, middle and high
    is zero."""
    f0, f1, f2 = values
    half = (high - low) / 2.0
    # f(t) = c2 t^2 + c1 t + f1 with t = (x - middle) / half, from t = -1, 0, 1.
    c2, c1 = (f0 + f2) / 2.0 - f1, (f2 - f0) / 2.0
    scale = max(abs(f0), abs(f1), abs(f2), 1e-12)
    if abs(c2) <= 1e-12 * scale:
        ts = [-f1 / c1] if abs(c1) > 1e-12 * scale else []
    else:
        disc = c1 * c1 - 4.0 * c2 * f1
        ts = [] if disc < 0 else [(-c1 + sign * disc ** 0.5) / (2.0 * c2) for sign in (1.0, -1.0)]
    middle = (low + high) / 2.0
    return [middle + t * half for t in ts if -1.0 < t < 1.0]


def _between(table, written, reads, bounds):
    """More settings, one size moved at a time with the others at their values now: halfway between the places
    where a corner of a loop passes the line of an edge of that loop. A corner moves along a line with one size, or
    along a curve when its formula holds a product, so such a test is a quadratic in that size; a crossing that
    starts and ends between the corners and middles of the ranges then has a setting inside it. None when there are
    more than MAX_BETWEEN such places for one size."""
    out = []
    for name in dict.fromkeys(table.size_name(r) for r in reads):
        ends = _ends(table, name, bounds) if name is not None else None
        if ends is None or not ends[0] < ends[1]:
            continue
        low, high = ends
        at = [_corners_at(written, range_check.recipe_size_values(table, {name: v}))
              for v in (low, (low + high) / 2.0, high)]
        places = set()
        for loop in range(len(written)):
            rings = [corners[loop] for corners in at]
            n = len(rings[0])
            for i in range(n):
                for j in range(n):
                    if i in (j, (j + 1) % n):
                        continue
                    values = [_side(ring[i], ring[j], ring[(j + 1) % n]) for ring in rings]
                    places.update(_roots(values, low, high))
        if len(places) > MAX_BETWEEN:
            return None
        cuts = [low] + sorted(places) + [high]
        out += [{name: (x + y) / 2.0} for x, y in zip(cuts, cuts[1:]) if places]
    return out


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
        settings = _settings(table, written, outline)
        if settings is None:
            return False
        for env in settings:
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
