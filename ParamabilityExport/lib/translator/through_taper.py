"""Whether a tapered cut through all stays open until it passes the part.

A cut through all whose walls lean in is written as a one sided cut that ends just past the part (`extrude`). Over
that length each wall moves in by the length times the tangent of the lean. Once an outline has no room left the cut
closes before it passes the part, which Fusion's through all never does. The taper and the outlines may follow sizes,
so `keep_open` checks the cut at the settings `range_check` builds over their ranges and cuts the ranges where it
closes.
"""
import math
import time

from ..params.expressions.errors import ExpressionError
from ..params.expressions.evaluation import evaluate
from . import kept_ranges, range_check
from ..geometry.footprint import Footprint, polyline
from .written_loops import profile_at, written_reads

CLOSES = "%s would close before it passes the part"
MAX_OPEN_TESTS = 3000    # distinct size settings tested for one cut; past this the cut is left out
MAX_OPEN_SECONDS = 20.0  # the same for the time the check takes
OPEN_STEPS = 20          # halvings that find where a range stops holding: a millionth of the range
_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, KeyError, TypeError)
# Grid sizes `inner_reach` tries in turn, coarse first.
_REACH_GRIDS = (8, 16, 32, 48)


def inner_reach(profile, enough=math.inf):
    """About the radius of the largest circle inside a profile's region (a little less): the largest distance to its
    outline over a grid of points inside it. Finer grids are tried only while the reach stays under `enough`."""
    footprint = Footprint(profile)
    flat = [p for curve in footprint.curves for p in polyline(curve)]
    if not flat:
        return 0.0
    lo = [min(p[i] for p in flat) for i in (0, 1)]
    hi = [max(p[i] for p in flat) for i in (0, 1)]
    best = 0.0
    for steps in _REACH_GRIDS:
        for a in range(1, steps):
            for b in range(1, steps):
                p = [lo[0] + (hi[0] - lo[0]) * a / steps, lo[1] + (hi[1] - lo[1]) * b / steps]
                if footprint.covers(p):
                    best = max(best, footprint.nearest_curve(p)[1])
                    if best >= enough:
                        return best
    return best


def _open(profile, distance, lean):
    """True when the outline, its walls leaning in by `lean` degrees, still has room left after `distance`: each wall
    moves in by `distance * tan(lean)`, so the outline closes once that passes the radius of its largest inner
    circle (`inner_reach`)."""
    if lean <= 0.0:
        return True
    shrink = distance * math.tan(math.radians(lean))
    return inner_reach(profile, shrink) >= shrink


def stays_open(profiles, distance, lean):
    """True when every outline, its walls leaning in by `lean` degrees, still has room left after `distance`."""
    return all(_open(profile, distance, lean) for profile in profiles)


class _OverBudget(Exception):
    """The check needs more settings or time than it is given."""


def keep_open(ctx, item, entry, profiles, outlines, max_lean):
    """True when the one sided cut `entry` (its fixed `distance`, its lean in `taper` or the formula `taper_q`) stays
    open at every size setting, the ranges of the sizes behind the taper and the outlines cut where it would close
    (`ctx.cut`); False when it closes at the sizes now, no cut keeps it open, or the check cannot be made in its
    budget. `outlines` are the `sketch_motion.Outline` of `profiles` (None for an outline that follows no size); each
    is worked out as the recipe writes it. The lean is taken at most `max_lean`, where the taper's own range ends."""
    q = entry.get("taper_q")
    sized = q is not None and q.sized
    shapes = [drawn.preview() if drawn is not None else None for drawn in outlines]
    shapes += [None] * (len(profiles) - len(shapes))
    reads = list(dict.fromkeys(tuple(q.reads if sized else ()) + written_reads(
        *[loop for shape in shapes if shape is not None for loop in [shape[0]] + list(shape[1])])))
    distance, table = entry["distance"], ctx.table
    if table is None or not reads:
        return stays_open(profiles, distance, min(max(entry["taper"] or 0.0, 0.0), max_lean))
    answers, began = {}, time.monotonic()

    def open_at(setting):
        key = tuple(sorted(setting.items()))
        if key not in answers:
            if len(answers) >= MAX_OPEN_TESTS or time.monotonic() - began > MAX_OPEN_SECONDS:
                raise _OverBudget()
            try:
                env = range_check.size_env(table, setting)
                lean = evaluate(q.text, env) if sized else (entry["taper"] or 0.0)
                lean = min(lean, max_lean)
                answers[key] = all(_open(profile if shape is None else profile_at(shape[0], shape[1], env),
                                         distance, lean) for profile, shape in zip(profiles, shapes))
            except _FAILURES:
                answers[key] = False
        return answers[key]

    def holds(bounds, only=None):
        if only is not None:
            settings = [{only[0]: bounds[only[0]][only[1]]}]
        else:
            settings = range_check.corners(table, reads, bounds) + range_check.middles(table, reads, bounds)
        return all(open_at(setting) for setting in settings)

    try:
        kept = kept_ranges.holding_ranges_where(table, reads, holds, steps=OPEN_STEPS)
    except _OverBudget:
        return False
    if kept is None:
        return False
    if kept:
        ctx.cut(kept, CLOSES % ((item or {}).get("name") or "a tapered cut"))
    return True
