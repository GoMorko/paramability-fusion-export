"""The taper of an extrude: Fusion's angle as the recipe writes it, and the limit that keeps it under the steepest lean."""
from .. import kept_ranges, values
from ...capture_model import gap_hints
from ..result import Refusal
from ..values import Quantity
from .common import UNREADABLE


# Fusion's positive taper angle widens the walls going away from the sketch (the API reference says it tapers
# outward, and measured side walls agree). The recipe leans walls in for a positive `taperDeg`, so the two are opposite.
# A tapered extrude is only copied when the measured end face area (`end_area` against `profile_area`) agrees.
FUSION_TAPER_SIGN = -1
MAX_TAPER_DEG = 45.0
TAPER_MARGIN_DEG = 0.01


def taper_degrees(deg):
    """Recipe `taperDeg` from Fusion's, or a Refusal. None (unreadable) refuses."""
    if deg is None:
        return Refusal(UNREADABLE)
    if not deg:
        return 0.0
    value = FUSION_TAPER_SIGN * deg
    if abs(value) >= MAX_TAPER_DEG:
        return Refusal("The taper of this extrude is too steep to copy.", cause=gap_hints.TAPER_STEEP)
    return value


def taper_quantity(ctx, item, path, taper):
    """The taper as the recipe writes it: a Quantity that may follow sizes, or None for no taper."""
    if not taper:
        values.pin(ctx, item, path, "a taper of zero cannot follow it")
        return None
    q = values.quantity(ctx, item, path, taper, dim="angle", sign=FUSION_TAPER_SIGN)
    if q.sized:
        _keep_taper_under_limit(ctx, item, q)
    return q


def _keep_taper_under_limit(ctx, item, q):
    """A taper that follows sizes should stay under MAX_TAPER_DEG either way, since Paramability refuses a steeper
    one."""
    keep_angle_within(ctx, item, q, MAX_TAPER_DEG, "lean its walls %d degrees or more" % MAX_TAPER_DEG)


def keep_angle_within(ctx, item, q, limit_deg, effect):
    """An angle that follows sizes should stay within `limit_deg` either way: the ranges of the sizes it reads are cut
    where it does not, or the sizes are marked when no cut keeps it. `effect` says what the step would do beyond the
    limit."""
    limit = Quantity(limit_deg)
    rules = [(limit.plus(q.scaled(-1.0)), 1), (limit.plus(q), 1)]
    found = kept_ranges.holding_ranges(ctx.table, rules, TAPER_MARGIN_DEG)
    why = "%s would %s" % (item.get("name", "a step"), effect)
    if found is None:
        ctx.doubt(q.reads, "at other values " + why)
    elif found:
        ctx.cut(found, why)
