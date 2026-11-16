"""The sweep's own settings (twist, taper, direction, rail, extent): what the copy refuses, the values it writes
and the sizes it pins."""
import math

from ...capture_model import gap_hints
from ...design_model.steps.sweep import cover_problem, loop_polygon, runs_both_ways, settings_problem
from ...design_model.values import Quantity
from . import sweep_taper
from .. import values
from ..extrude import MAX_TAPER_DEG, keep_angle_within
from ..result import Refusal
from ..paths import path_limits
from .sweep_limits import (
    BOTH_WAYS_TWIST, MAX_TAPER_STATIONS, MAX_TWIST_DEG, PARALLEL_AND_SHAPE, TAPER_CURVES, TAPER_STATIONS, TAPER_STEEP,
    TWIST_AND_TAPER, TWIST_LONG, ZERO_TOL,
)


def settings_refusal(data):
    """A Refusal for a setting the recipe copy does not follow: what the shared reader finds
    (`design_model.steps.sweep.settings_problem`: a guide rail or surface, a setting that could not be read, other
    kinds), then a twist with a taper or a fixed direction, a taper that is too steep, a twist of more than ten turns,
    and part of the path."""
    problem = settings_problem(data)
    if problem is not None:
        return path_limits.refusal(problem)
    twist, taper = data["twist_deg"], data["taper_deg"]
    if abs(twist) > ZERO_TOL and abs(taper) > ZERO_TOL:
        return Refusal(TWIST_AND_TAPER, cause=gap_hints.SWEEP_KIND)
    if data["orientation"] == "parallel" and (abs(twist) > ZERO_TOL or abs(taper) > ZERO_TOL):
        return Refusal(PARALLEL_AND_SHAPE)
    if abs(taper) >= MAX_TAPER_DEG:
        return Refusal(TAPER_STEEP, cause=gap_hints.TAPER_STEEP)
    if abs(twist) > MAX_TWIST_DEG:
        return Refusal(TWIST_LONG, cause=gap_hints.TWIST_LONG)
    problem = cover_problem(data)
    if problem is not None:
        return path_limits.refusal(problem)
    return Refusal(BOTH_WAYS_TWIST) if runs_both_ways(data) and abs(twist) > ZERO_TOL else None


def pin_settings(ctx, item, data, closed):
    """Values the copy writes as fixed settings: a size that moves one is marked. A twist or taper that is set is
    written as a value that can follow sizes instead (`angle_value`), except a twist along a closed path, which has to
    stay whole turns."""
    name = item.get("name", "a sweep")
    for path, what in (("twist_deg", "twist"), ("taper_deg", "taper"), ("distance_one", "length along its path"),
                       ("distance_two", "length along its path")):
        if path in ("twist_deg", "taper_deg") and abs(data.get(path) or 0.0) > ZERO_TOL and not (
                closed and path == "twist_deg"):
            continue
        values.pin(ctx, item, path, "it sets the %s of %s, which the copy keeps as it is now" % (what, name))


def angle_value(ctx, item, path, fusion_deg, sign, follows=True):
    """The twist or taper as the recipe writes it, a Quantity that follows sizes when its parameter does (unless
    `follows` is false: then it is the plain number, and `pin_settings` marks the sizes behind it)."""
    if abs(fusion_deg) <= ZERO_TOL:
        return None
    if not follows:
        return Quantity(sign * fusion_deg)
    q = values.quantity(ctx, item, path, sign * fusion_deg, dim="angle", sign=sign)
    if q.sized:
        limit, effect = ((MAX_TAPER_DEG, "lean its walls %d degrees or more" % MAX_TAPER_DEG) if path == "taper_deg"
                         else (MAX_TWIST_DEG, "twist more than %d degrees" % MAX_TWIST_DEG))
        keep_angle_within(ctx, item, q, limit, effect)
    return q


def taper_growth(profile, taper_deg):
    """How far the walls can lean out per mm of path for a taper of `taper_deg` either way, corners of the outline
    included."""
    if abs(taper_deg) <= ZERO_TOL:
        return 0.0
    outer = next((loop for loop in profile.get("loops") or [] if loop.get("outer")), None)
    ring = loop_polygon(outer.get("curves") or []) if outer else None
    factor = sweep_taper.corner_factor(ring) if ring else 1.0
    return math.tan(math.radians(abs(taper_deg))) * factor


def taper_path_refusal(found):
    """A Refusal when the path cannot carry a taper: free curves, or more parts than the recipe builds through."""
    parts = found.recipe["segments"] if found.recipe["kind"] == "flat" else found.curves
    if found.recipe["kind"] == "flat" and any(segment["kind"] == "spline" for segment in parts):
        return Refusal(TAPER_CURVES)
    return Refusal(TAPER_STATIONS) if len(parts) + 1 > MAX_TAPER_STATIONS else None
