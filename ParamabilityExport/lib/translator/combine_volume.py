"""Volume check for a Combine whose tool steps are written one by one.

The capture can hold the volume of the exported body before and after the Combine (`volume_before`,
`volume_after`). A cut can remove, and a join can add, at most what the written tool steps fill together, so a
change bigger than the sum of the step volumes shows a tool the steps do not reproduce. The sum is an upper bound
(overlapping steps count twice), so this catches a missing or too small tool, never a too big one. A tool whose
volume cannot be worked out exactly (revolve, taper, thin wall, curves other than lines, arcs and circles) skips the
check.
"""
import math

REL_TOL = 2e-3
ABS_TOL_MM3 = 1.0


def _loop_area(loop):
    """Area of one closed outline in sketch units, or None for a curve this does not model."""
    total = 0.0
    for curve in loop.get("curves") or []:
        kind = curve.get("kind")
        if kind == "circle":
            total += math.pi * curve["radius"] ** 2
        elif kind == "line":
            (x0, y0), (x1, y1) = curve["start"], curve["end"]
            total += 0.5 * (x0 * y1 - x1 * y0)
        elif kind == "arc":
            total += _arc_term(curve)
        else:
            return None
    return abs(total)


def _arc_term(curve):
    """The share of one arc in the area integral 1/2 * (x dy - y dx) along the outline."""
    cx, cy = curve["center"]
    r = curve["radius"]
    (x0, y0), (x1, y1), (xm, ym) = curve["start"], curve["end"], curve["mid"]
    a0, a1, am = (math.atan2(y - cy, x - cx) for y, x in ((y0, x0), (y1, x1), (ym, xm)))
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi
    return 0.5 * (r * r * sweep + cx * (y1 - y0) - cy * (x1 - x0))


def _profile_area(profile):
    area = 0.0
    for loop in profile.get("loops") or []:
        found = _loop_area(loop)
        if found is None:
            return None
        area += found if loop.get("outer") else -found
    return area


def _length(data):
    """The distance an extrude reaches along its sketch normal, or None when it is not a plain distance."""
    kind = data.get("extent_type")
    one, two, mid = data.get("side_one"), data.get("side_two"), data.get("symmetric")
    if kind == "one" and one and one.get("kind") == "distance" and not one.get("taper_deg"):
        return abs(one["distance"])
    if kind == "symmetric" and mid and not mid.get("taper_deg"):
        return abs(mid["distance"]) * (1 if mid.get("full_length") else 2)
    if (kind == "two" and one and two and one.get("kind") == two.get("kind") == "distance"
            and not one.get("taper_deg") and not two.get("taper_deg")):
        return abs(one["distance"]) + abs(two["distance"])
    return None


def step_volume(item):
    """Volume in mm3 of the body a plain extrude item fills, or None (also for any item that is not an extrude: only
    an extrude has an `extent_type`)."""
    data = item.get("data") or {}
    if data.get("thin") or not data.get("profiles"):
        return None
    length = _length(data)
    if length is None:
        return None
    area = 0.0
    for profile in data["profiles"]:
        found = _profile_area(profile)
        if found is None:
            return None
        area += found
    return area * length


def tool_volume(items):
    """Summed volume of the tool items, or None when any of them cannot be worked out."""
    total = 0.0
    for item in items:
        found = step_volume(item)
        if found is None:
            return None
        total += found
    return total


def exceeds(data, items):
    """True when the Combine changed the body by more than the tool items can fill. False when the capture holds no
    volumes or a tool volume cannot be worked out."""
    before, after = data.get("volume_before"), data.get("volume_after")
    if before is None or after is None:
        return False
    filled = tool_volume(items)
    if filled is None:
        return False
    change = abs(after - before)
    return change > filled + max(ABS_TOL_MM3, REL_TOL * max(filled, change))
