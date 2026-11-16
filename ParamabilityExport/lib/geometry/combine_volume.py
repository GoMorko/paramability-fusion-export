"""Volume checks for a Combine.

For tool steps written one by one, the capture can hold the volume of the exported body before and after the Combine (`volume_before`,
`volume_after`). A cut can remove, and a join can add, at most what the written tool steps fill together, so a
change bigger than the sum of the step volumes shows a tool the steps do not reproduce. The sum is an upper bound
(overlapping steps count twice), so this catches a missing or too small tool, never a too big one. A tool whose
volume cannot be worked out exactly (revolve, taper, thin wall, curves other than lines, arcs and circles) skips the
check.

For a tool built in a step of its own, the reader measured each tool body (`volume`), so the change is compared with
those volumes (`exceeds_tools`).

An intersect of several tools keeps what every tool holds or what any tool holds. `intersect_model` matches the volume
after the Combine to the two measured candidates.
"""
import math

from .footprint import closed_chain

REL_TOL = 2e-3
ABS_TOL_MM3 = 1.0
# Two measured volumes are the same when they differ by less than this (mm3) or by this share of the larger one.
SAME_VOLUME_MM3 = 1e-3
SAME_VOLUME_RELATIVE = 1e-6


def _loop_area(loop):
    """Area of one closed outline in sketch units, or None for a curve this does not model. Lines and arcs are put in
    order first (`footprint.closed_chain`): the capture lists the curves of a loop in any order and direction."""
    curves = list(loop.get("curves") or [])
    if curves and all(c.get("kind") in ("line", "arc") for c in curves):
        curves = closed_chain(curves)
        if curves is None:
            return None
    total = 0.0
    for curve in curves:
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


def profile_area(profile):
    """The area of a profile record (outer loops less holes, in sketch units squared), or None when it has no loops
    or a curve this does not model."""
    if not profile.get("loops"):
        return None
    area = 0.0
    for loop in profile["loops"]:
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
        found = profile_area(profile)
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


def _over(value, limit):
    return value > limit + max(ABS_TOL_MM3, REL_TOL * max(limit, value))


def exceeds_tools(combine, data):
    """True when the part after the Combine cannot come from its measured tool bodies: a cut or a join changes the
    part by at most the sum of the tools, and an intersect ends at most as big as the smallest tool (the sum of them
    when it keeps what any tool holds). False when a volume it needs was not measured."""
    before, after = data.get("volume_before"), data.get("volume_after")
    volumes = [tool.get("volume") for tool in data.get("tools") or []]
    if after is None or not volumes or None in volumes:
        return False
    if combine == "intersect":
        return _over(after, sum(volumes) if data.get("intersect_model") == "any" else min(volumes))
    return before is not None and _over(abs(after - before), sum(volumes))


def same_volume(a, b):
    return abs(a - b) <= max(SAME_VOLUME_MM3, SAME_VOLUME_RELATIVE * max(abs(a), abs(b)))


def intersect_model(measured, volume_after):
    """"every", "any" or "unknown": which candidate of `measured` the volume after the Combine matches. When both match
    it is "every". A candidate that was not measured is null and matches nothing."""
    if not measured or volume_after is None:
        return "unknown"
    for name in ("every", "any"):
        if measured.get(name) is not None and same_volume(measured[name], volume_after):
            return name
    return "unknown"


def rule_unproven(measured):
    """True when the measured candidates cannot show which rule Fusion used: they are equal, or one is missing."""
    every, some = (measured or {}).get("every"), (measured or {}).get("any")
    return every is None or some is None or same_volume(every, some)
