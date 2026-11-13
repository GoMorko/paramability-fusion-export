"""Checks of the planned extrude against what Fusion measured: its length, its side walls and the volume it made."""
import math

from ...geometry import vec
from ..result import Refusal
from .common import LENGTH_TOL


AREA_RELATIVE_TOL = 1e-6
# Sine of the wall lean: about 0.006 degrees.
LEAN_TOL = 1e-4
VOLUME_RELATIVE_TOL = 0.01
VOLUME_ABSOLUTE_TOL = 1e-3


def _beyond_part(box, start, direction, length):
    """True when a cut of `length` from `start` along `direction` ends past the whole box."""
    if not box:
        return False
    lo, hi = box["min"], box["max"]
    corners = ([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]] for i in range(8))
    return length > max(vec.dot(vec.sub(c, start), direction) for c in corners) + LENGTH_TOL


def check_measured_length(plan, data, shift, start, z, combine):
    """Refuse when the measured end face is not where the planned length puts it (None when it agrees or is unknown).

    A cut that ends past the part makes no end face of its own; the face Fusion lists then is a wall it cut through,
    nearer than the planned end, and the length is not checked.
    """
    end = data.get("end_offset")
    if end is None or not plan:
        return None
    first = plan[0]
    if first.extent == "through" or first.distance is None:
        return None
    planned = first.distance / 2.0 if first.extent == "symmetric" else first.distance
    measured = abs(end - shift)
    if abs(measured - planned) <= LENGTH_TOL:
        return None
    if (combine == "cut" and first.extent == "oneSide" and measured < planned
            and _beyond_part(data.get("target_box_before"), start, vec.scale(z, first.sign), planned)):
        return None
    return Refusal("The measured end of this extrude does not match its length, so it is not copied.")


def _expected_leans(plan, combine):
    """Per plan entry, the leans its side walls can show along the sketch normal (see `check_taper`)."""
    out = []
    for entry in plan:
        lean = math.sin(math.radians(entry.taper or 0.0)) * (-1 if combine == "cut" else 1)
        out.append([-lean, lean] if entry.extent == "symmetric" else [entry.sign * lean])
    return out


def check_leans(plan, leans, combine):
    """Refuse when a measured side wall leans in a way no side of the plan gives, or a tapered side has no wall
    that shows its taper. A wall narrowing away from the sketch leans its outward normal along the travel; a cut
    shows the part's walls, which face the other way."""
    expected = _expected_leans(plan, combine)
    flat = [value for values in expected for value in values]
    if any(not any(abs(lean - value) <= LEAN_TOL for value in flat) for lean in leans):
        return Refusal("The taper direction does not match what was measured, so it is not copied.")
    for entry, values in zip(plan, expected):
        if entry.taper and not any(abs(lean - value) <= LEAN_TOL for lean in leans for value in values):
            return Refusal("The taper of this extrude could not be measured.")
    return None


def check_taper(plan, data, combine, outlines):
    """Refuse a taper whose sign disagrees with the measured side walls (or, for one outline, the end face area),
    or that cannot be measured."""
    tapered = [entry for entry in plan if entry.taper]
    if not tapered:
        return None
    leans = data.get("side_leans")
    if isinstance(leans, list) and leans:
        return check_leans(plan, leans, combine)
    if not plan[0].taper or outlines != 1:
        return Refusal("The taper of this extrude could not be measured.")
    start, end = data.get("profile_area"), data.get("end_area")
    if not start or end is None or start <= 0:
        return Refusal("The direction of the taper could not be measured.")
    if abs(end - start) <= AREA_RELATIVE_TOL * start:
        return Refusal("The taper of this extrude shows no change in size, so it is not copied.")
    if (plan[0].taper > 0) != (end < start):
        return Refusal("The taper direction does not match what was measured, so it is not copied.")
    return None


def _holds_free_outline(profiles):
    """True when a profile is sketch text or has a free curve (a spline)."""
    return any(p.get("text") or any(c.get("kind") == "other" for loop in p.get("loops") or []
                                    for c in loop.get("curves") or []) for p in profiles)


def volume_refusal(data, plan, combine, profiles, thin):
    """Refuse when the part Fusion made from text or spline outlines is not the outline area times the length.

    Text outlines are sorted into outer outlines and holes by the reader, and overlapping strokes can be read as a hole,
    so the area they give is checked against the measured volume. A new body must match; a join or cut may lose volume
    to material it overlaps, so it only must not exceed the expected volume or go the wrong way. Cases whose volume
    cannot be worked out here (taper, through all, thin, intersect) are not checked. A capture without the measured
    values (made before they were read) is not checked either."""
    if "areas" not in data or not _holds_free_outline(profiles):
        return None
    if thin or combine == "intersect" or any(e.taper or e.distance is None for e in plan):
        return None
    areas, before, after = data["areas"], data.get("volume_before"), data.get("volume_after")
    if (not isinstance(areas, list) or len(areas) != len(profiles) or any(a is None for a in areas)
            or before is None or after is None):
        return Refusal("The change this extrude makes to the part could not be measured, so it is not copied.")
    expected = sum(areas) * sum(entry.distance for entry in plan)
    change = after - before
    tolerance = VOLUME_RELATIVE_TOL * expected + VOLUME_ABSOLUTE_TOL
    if combine == "new":
        agrees = abs(change - expected) <= tolerance
    else:
        grows = combine == "add"
        agrees = abs(change) <= expected + tolerance and (change >= -VOLUME_ABSOLUTE_TOL if grows
                                                          else change <= VOLUME_ABSOLUTE_TOL)
    if not agrees:
        return Refusal("The result of this extrude does not match the outlines it was drawn with, so it is not copied.")
    return None
