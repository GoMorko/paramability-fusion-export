"""The sweep's own settings (twist, taper, direction, rail, extent): what the copy refuses, the values it writes
and the sizes it pins."""
import math

from ...capture_model import gap_hints
from . import sweep_taper
from .. import values
from ..extrude import MAX_TAPER_DEG, keep_angle_within
from ..result import Refusal
from .sweep_limits import (
    BOTH_WAYS_TWIST, GUIDE_SURFACE, GUIDE_SURFACE_LIKELY, MAX_TAPER_STATIONS, MAX_TWIST_DEG, OTHER_KIND,
    PARALLEL_AND_SHAPE, PART_OF_PATH, RAIL, RAIL_UNREADABLE, TAPER_CURVES, TAPER_STATIONS, TAPER_STEEP,
    TWIST_AND_TAPER, TWIST_LONG, UNREADABLE, ZERO_TOL,
)
from .sweep_outline import loop_polygon
from ..values import Quantity


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def settings_refusal(data):
    """A Refusal for a setting the copy does not follow (a twist with a taper or a fixed direction, a taper that is
    too steep, guide rail or guide surface, other kinds, part of the path)."""
    guided = _guide_surface_refusal(data)
    if guided is not None:
        return guided
    rail = data.get("rail")
    if isinstance(rail, dict) and rail.get("kind") == "unread":
        return Refusal(RAIL_UNREADABLE)
    if rail is not None:
        return Refusal(RAIL, cause=gap_hints.SWEEP_KIND)
    twist, taper = data.get("twist_deg"), data.get("taper_deg")
    one, two = data.get("distance_one"), data.get("distance_two")
    if not (is_number(twist) and is_number(taper) and is_number(one)) or data.get("orientation") is None:
        return Refusal(_unread_reason(data))
    if data["orientation"] not in ("perpendicular", "parallel"):
        return Refusal(OTHER_KIND)
    if abs(twist) > ZERO_TOL and abs(taper) > ZERO_TOL:
        return Refusal(TWIST_AND_TAPER, cause=gap_hints.SWEEP_KIND)
    if data["orientation"] == "parallel" and (abs(twist) > ZERO_TOL or abs(taper) > ZERO_TOL):
        return Refusal(PARALLEL_AND_SHAPE)
    if abs(taper) >= MAX_TAPER_DEG:
        return Refusal(TAPER_STEEP, cause=gap_hints.TAPER_STEEP)
    if abs(twist) > MAX_TWIST_DEG:
        return Refusal(TWIST_LONG, cause=gap_hints.TWIST_LONG)
    return _coverage_refusal(data, one, two, twist)


def _guide_surface_refusal(data):
    """A Refusal for a sweep with a guide surface. When the capture does not say (an older capture, or Fusion would
    not give the guide surfaces), Fusion's answer for the other settings tells: on such a sweep it fails the
    orientation with an InternalValidationError and gives no twist and no taper."""
    guide = data.get("guide_surfaces")
    if isinstance(guide, list):
        return Refusal(GUIDE_SURFACE, cause=gap_hints.GUIDE_SURFACE) if guide else None
    said = data.get("unread") or {}
    if (all(key in said for key in ("orientation", "twist_deg", "taper_deg"))
            and "InternalValidationError" in str(said["orientation"])):
        return Refusal(GUIDE_SURFACE_LIKELY, cause=gap_hints.GUIDE_SURFACE)
    return None


def _coverage_refusal(data, one, two, twist):
    """A Refusal unless the sweep covers its whole path once. Along a closed path a second side that also runs the
    whole way (`distance_two` 1, Fusion's default there) makes the same ring, unless it twists."""
    if abs(one - 1.0) > ZERO_TOL:
        return Refusal(PART_OF_PATH, cause=gap_hints.PART_OF_PATH)
    if not is_number(two) or abs(two) <= ZERO_TOL:
        return None
    if abs(two - 1.0) > ZERO_TOL or (data.get("path") or {}).get("closed") is not True:
        return Refusal(PART_OF_PATH, cause=gap_hints.PART_OF_PATH)
    return Refusal(BOTH_WAYS_TWIST) if abs(twist) > ZERO_TOL else None


_SETTING_WORDS = (("orientation", "orientation"), ("twist_deg", "twist"), ("taper_deg", "taper"),
                  ("distance_one", "length along its path"))


def _unread_reason(data):
    """The refusal text for settings read as null, naming them (and what Fusion said, when the capture has it)."""
    missing = [words for key, words in _SETTING_WORDS
               if (data.get(key) is None if key == "orientation" else not is_number(data.get(key)))]
    if not missing:
        return UNREADABLE
    named = missing[0] if len(missing) == 1 else "%s and %s" % (", ".join(missing[:-1]), missing[-1])
    said = sorted(set((data.get("unread") or {}).values()))
    tail = " (Fusion said: %s)" % "; ".join(said) if said else ""
    return "Fusion did not give the %s of this sweep%s, so it is not copied." % (named, tail)


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
