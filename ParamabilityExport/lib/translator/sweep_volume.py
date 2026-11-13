"""The volume checks of a sweep: a new body must have the volume the outline and the path give, and a tapered
straight sweep tells how Fusion measures the taper from the volume it made."""
import math

from . import sweep_taper, vec
from .path_limits import STRAIGHT_DEG
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
    travels, which is the path's length less the centre's offset to the left of the path times the turn of the path.
    A mitred corner turning by t counts 2 tan(t / 2) instead of t. A twisting outline turns its centre about the path,
    so that counts only when the centre sits on the path."""
    offset = vec.sub(middle, found.start)
    if twisted:
        return area * found.length if vec.length(offset) <= CENTROID_ON_PATH_TOL else None
    normal = found.recipe["on"]["normal"]
    left = vec.dot(offset, vec.cross(normal, found.direction))
    return area * (found.length - left * (found.winding * 2.0 * math.pi + _mitre_excess(found.curves, normal)))


def _mitre_turns(curves, normal, closed=True):
    """`(turn, mitred)` summed over the sharp corners between lines of the path, each signed by its direction about
    `normal`: the corner's turn t and 2 tan(t / 2), what the outline's centre travels per mm of its offset to the
    left of the path when the outline is mitred there. On a closed path the last line meets the first."""
    turns, mitred = 0.0, 0.0
    pairs = zip(curves[-1:] + curves[:-1], curves) if closed else zip(curves, curves[1:])
    for before, after in pairs:
        if before["kind"] != "line" or after["kind"] != "line":
            continue
        a, b = vec.unit(vec.sub(before["end"], before["start"])), vec.unit(vec.sub(after["end"], after["start"]))
        turn = math.atan2(vec.length(vec.cross(a, b)), vec.dot(a, b))
        if math.degrees(turn) > STRAIGHT_DEG:
            sign = math.copysign(1.0, vec.dot(vec.cross(a, b), normal))
            turns += sign * turn
            mitred += sign * 2.0 * math.tan(turn / 2.0)
    return turns, mitred


def _mitre_excess(curves, normal):
    """What the sharp corners between lines of a closed path add to its turn when the outline is mitred there:
    2 tan(t / 2) - t for each corner turning by t, signed by its direction about `normal`."""
    turns, mitred = _mitre_turns(curves, normal)
    return mitred - turns


def _open_lines_volume(area, middle, found):
    """The volume of an outline swept along an open flat chain of lines with mitred corners: the area times the length
    its centre travels, the path's length less the centre's offset to the left of the path times 2 tan(t / 2) for
    each corner turning by t."""
    normal = found.recipe["on"]["normal"]
    left = vec.dot(vec.sub(middle, found.start), vec.cross(normal, found.direction))
    return area * (found.length - left * _mitre_turns(found.curves, normal, closed=False)[1])


def _expected_volume(profile, area, found, twisted):
    """The volume the outline sweeps along the path (area times the length its centre travels), or None when that is
    not known: a bent path counts only when it runs through the centre of the outline or, untwisted, is a chain of
    lines in one plane."""
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
    if found.kind == "flat" and not twisted and all(c["kind"] == "line" for c in found.curves):
        return _open_lines_volume(area, middle, found)
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
