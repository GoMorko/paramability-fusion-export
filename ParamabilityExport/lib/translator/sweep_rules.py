"""The app's rules for a sweep path that follows sizes, held at every size setting: the sizes' ranges are cut where
the rules stop holding, or the sizes are marked."""
import math
import time

from ..params.expressions import ExpressionError

from . import kept_ranges, path_curves, path_motion, path_rebuilt, range_check, sweep_reach, vec
from .sweep_marks import drawn_outline, mark_sketch_place

PATH_BREAKS = "%s would make its path touch itself, bend tighter than its outline, or turn sharply (the app refuses)"
PATH_UNCHECKED = ("%s may make its path touch itself, bend tighter than its outline, or turn sharply (the app "
                  "refuses), but there are too many settings to check them all in a reasonable time")
_FAILURES = (ExpressionError, ValueError, ZeroDivisionError, OverflowError, KeyError, TypeError)
MAX_PATH_TESTS = 3000    # distinct size settings tested for one path; past this its sizes are marked, nothing is cut
MAX_PATH_SECONDS = 20.0  # the same for the time the check takes, so it never blocks Fusion for long
PATH_STEPS = 20          # halvings that find where a range stops holding: a millionth of the range
MIN_KEPT_SHARE = 0.1     # a range cut shorter than this share of the range it had marks the size instead


class _OverBudget(Exception):
    """The rule check for a path needs more settings or time than it is given."""


def _across(profile, followed, options):
    """The direction in the outline's plane that a flat path's plane is square to (2D, the outline's frame), or None
    when every direction counts (an outline that twists about the path)."""
    if options.twisted:
        return None
    frame, normal = profile["frame"], vec.unit(followed.written["on"]["normal"])
    across = [vec.dot(normal, frame["x"]), vec.dot(normal, frame["y"])]
    size = math.hypot(*across)
    return [c / size for c in across] if abs(size - 1.0) <= 1e-6 else None


def _toward_centre(arc, frame):
    """The direction from an arc's start to its centre in the outline's frame (2D unit)."""
    inward = vec.sub(path_curves.arc_of(arc)[0], arc["start"])
    across = [vec.dot(inward, frame["x"]), vec.dot(inward, frame["y"])]
    size = math.hypot(*across)
    if size <= 1e-12:
        raise ValueError("an arc that starts at its centre")
    return [c / size for c in across]


def _keep_path_valid(ctx, item, profile, found, followed, drawn, options, form):
    """The app's rules for the path (it starts square to the outline, no sharp corner, no touching itself, the
    outline clear of the tightest bend, a closed seam, an outline kept in one direction rising) must hold at every
    size setting: the sizes' ranges are cut where they stop holding, or the sizes marked when no cut helps.

    Settings tested: the current values, the ends of the ranges (every corner for up to `MAX_CORNER_SIZES` sizes, else
    a fixed sample) and the middles of the ranges (`range_check.middles`). A size already marked is held at its value.
    When the check needs more than `MAX_PATH_TESTS` settings or `MAX_PATH_SECONDS`, the sizes are marked."""
    outer, _ = drawn.written(ctx)
    marked = ctx.doubted()
    live = [n for n in dict.fromkeys(followed.reads + sweep_reach.written_reads(outer)) if n not in marked]
    if ctx.table is None or not live:
        return
    frame = profile["frame"]
    normal, across = vec.unit(frame["z"]), _across(profile, followed, options)
    name = item.get("name", "a sweep")
    tested, answers, began = [0], {}, time.monotonic()

    def fails(setting):
        key = tuple(sorted(setting.items()))
        if key in answers:
            return answers[key]
        tested[0] += 1
        if tested[0] > MAX_PATH_TESTS or time.monotonic() - began > MAX_PATH_SECONDS:
            raise _OverBudget()
        try:
            env = range_check.size_env(ctx.table, setting)
            curves = followed.curves_at(env)
            if followed.disagrees_at(env, curves):
                answers[key] = True
            else:
                offset = vec.sub(curves[0]["start"], frame["origin"])
                reach = sweep_reach.reach_of(outer, env, [vec.dot(offset, frame["x"]), vec.dot(offset, frame["y"])],
                                             across, _toward_centre(curves[0], frame) if form == "revolve" else None)
                answers[key] = path_rebuilt.rebuilt_refusal(curves, found.closed, normal, reach, options.fixed,
                                                     leaves=found.direction) is not None
        except _FAILURES:
            answers[key] = True
        return answers[key]

    def holds(bounds, only=None):
        if only is not None:
            settings = [{only[0]: bounds[only[0]][only[1]]}]
        else:
            settings = (range_check.corners(ctx.table, live, bounds) + range_check.middles(ctx.table, live, bounds))
        return not any(fails(setting) for setting in settings)

    try:
        while live:
            kept = kept_ranges.holding_ranges_where(ctx.table, live, holds, steps=PATH_STEPS, balanced=False)
            if kept is None:
                ctx.doubt(live, "at other values " + PATH_BREAKS % name)
                return
            short = [n for n, bounds in kept.items() if _too_short(ctx.table, n, bounds)]
            if not short:
                if kept:
                    ctx.cut(kept, PATH_BREAKS % name)
                return
            ctx.doubt(short, "at other values " + PATH_BREAKS % name)
            live = [n for n in live if n not in short]
    except _OverBudget:
        ctx.doubt(live, "at other values " + PATH_UNCHECKED % name)


def _too_short(table, name, kept):
    """True when the range `kept` is a sliver of the size's range: a rule that fails as soon as the size moves."""
    size = table.sizes[table.size_name(name)]
    return kept[1] - kept[0] < MIN_KEPT_SHARE * (size["max"] - size["min"])


def follow_path(ctx, item, profile, path, found, form, options):
    """The path as `path_motion.Followed` when it follows sizes (its rules are kept over the size ranges, and its
    start on the outline's plane), else None: the caller writes it as measured."""
    if options.tapered or ctx.table is None:
        return None
    drawn = drawn_outline(ctx, item, profile)
    followed = path_motion.follow(ctx, item, path, found, form, drawn) if drawn is not None else None
    if followed is None:
        return None
    name = item.get("name", "a sweep")
    path_motion.keep_on_plane(ctx, followed, profile["frame"], drawn, name)
    mark_sketch_place(ctx, name, path, plane_follows=True)
    _keep_path_valid(ctx, item, profile, found, followed, drawn, options, form)
    return followed
