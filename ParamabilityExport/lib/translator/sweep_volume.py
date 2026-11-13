"""The volume checks of a sweep: a new body must have the volume the outline and the path give, and a tapered
straight sweep tells how Fusion measures the taper from the volume it made."""
import math

from . import sweep_taper, vec
from .result import Refusal
from .sweep_limits import CENTROID_ON_PATH_TOL, NOT_MATCHING, VOLUME_ABSOLUTE_TOL, VOLUME_RELATIVE_TOL, ZERO_TOL
from .sweep_outline import centroid
from .sweep_settings import is_number


def made_volume(item, data):
    """The volume of the body a new body sweep made, or None when it was not measured. A walk of a tool body lists
    its own `volume_after` (null when not measured); otherwise the body of the capture is the one made."""
    if "volume_after" in data:
        return data["volume_after"]
    return (item.get("target_after") or {}).get("volume_mm3")


def _axis_distance(point, axis):
    along = vec.sub(point, axis["point"])
    direction = vec.unit(axis["dir"])
    return vec.length(vec.sub(along, vec.scale(direction, vec.dot(along, direction))))


def _closed_volume(area, middle, found, twisted):
    """The volume of an outline swept once round a closed flat path (Pappus): the area times the length its centre
    travels, which is the path's length less the centre's offset towards the inside times the turn of the path. A
    twisting outline turns its centre about the path, so that counts only when the centre sits on the path."""
    offset = vec.sub(middle, found.start)
    if twisted:
        return area * found.length if vec.length(offset) <= CENTROID_ON_PATH_TOL else None
    inward = vec.dot(offset, vec.cross(found.recipe["on"]["normal"], found.direction)) * found.winding
    return area * (found.length - inward * 2.0 * math.pi)


def _expected_volume(profile, area, found, twisted):
    """The volume the outline sweeps along the path (area times the length its centre travels), or None when that is
    not known: a bent path counts only when it runs through the centre of the outline."""
    centre = centroid(profile)
    if centre is None:
        return None
    middle = vec.frame_apply(profile["frame"], [centre[0], centre[1], 0.0])
    if found.closed:
        return _closed_volume(area, middle, found, twisted)
    if found.kind == "line":
        return area * found.length
    if found.kind in ("arc", "circle"):
        return area * math.radians(found.angle_deg) * _axis_distance(middle, found.axis)
    if vec.length(vec.sub(middle, found.start)) <= CENTROID_ON_PATH_TOL:
        return area * found.length
    return None


def _rise(profile, found):
    """How far the path moves along the outline's normal, taken in the direction the path leaves it."""
    normal = vec.unit(profile["frame"]["z"])
    facing = normal if vec.dot(normal, found.direction) >= 0 else vec.scale(normal, -1.0)
    return vec.dot(vec.sub(found.end, found.start), facing)


def volume_refusal(item, data, combine, profile, found):
    """A Refusal when a new body does not have the volume the outline and the path give; None when it does, or when
    it cannot be told. A taper changes the volume, so it is not told here. An outline kept in one direction moves along
    its normal, so the volume is its area times the rise of the path along that normal."""
    areas = data.get("areas")
    parallel = data["orientation"] == "parallel"
    if abs(data["taper_deg"]) > ZERO_TOL or combine != "new":
        return None
    if not isinstance(areas, list) or len(areas) != 1 or not is_number(areas[0]) or areas[0] <= 0:
        return None
    made = made_volume(item, data)
    if parallel:
        expected = areas[0] * _rise(profile, found)
    else:
        expected = _expected_volume(profile, areas[0], found, abs(data["twist_deg"]) > ZERO_TOL)
    if made is None or expected is None:
        return None
    if abs(made - expected) > VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL:
        return Refusal(NOT_MATCHING)
    return None


def taper_lean(item, shapes, data, combine, found, slope):
    """The taper's meaning read from the volume of a new body along a straight path: `OFFSET`, `FLIPPED` (it leans the
    other way), `SCALED`, `NO_FIT` (no model gives the volume), or None when it cannot be told."""
    areas, made = data.get("areas"), made_volume(item, data)
    if (shapes is None or found.kind != "line" or combine != "new" or made is None or not isinstance(areas, list)
            or len(areas) != 1):
        return None
    return sweep_taper.meaning(shapes, found.length, made, slope)
