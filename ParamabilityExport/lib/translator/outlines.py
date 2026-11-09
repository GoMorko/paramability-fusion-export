"""The outlines of one extrude merged where they share a curve.

Fusion extrudes the region of all the profiles it is given at once: profiles that share a curve make one face, and a
taper leans the walls of that whole region. The recipe extrudes one outline per step, so profiles that share a curve
are merged first: the shared curves are left out and the rest is chained into one outer loop and its holes.
Profiles that only touch at a point, or stand apart, stay separate outlines.
"""
from .footprint import Footprint, _polyline

KEY_DIGITS = 4
CHAIN_TOL = 1e-4
FRAME_TOL = 1e-6


def _p(point):
    return tuple(round(c, KEY_DIGITS) + 0.0 for c in point)


def _key(curve):
    """A key that two copies of one sketch curve share, whichever way they run."""
    kind = curve.get("kind")
    ends = tuple(sorted([_p(curve["start"]), _p(curve["end"])])) if "start" in curve and "end" in curve else ()
    if kind == "line":
        return ("line",) + ends
    if kind in ("arc", "circle"):
        return (kind, _p(curve["center"]), round(curve["radius"], KEY_DIGITS)) + ends + (
            (_p(curve["mid"]),) if "mid" in curve else ())
    return None


def _same_frame(a, b):
    return all(abs(x - y) <= FRAME_TOL for k in ("origin", "x", "y", "z") for x, y in zip(a[k], b[k]))


def _close(a, b):
    return abs(a[0] - b[0]) <= CHAIN_TOL and abs(a[1] - b[1]) <= CHAIN_TOL


def _loops(curves):
    """The curves split into closed loops, or None when they do not close."""
    left = list(curves)
    loops = []
    while left:
        first = left.pop(0)
        if first.get("kind") in ("circle", "ellipse") or "start" not in first:
            loops.append([first])
            continue
        loop, tip, start = [first], first["end"], first["start"]
        while not _close(tip, start):
            found = next((c for c in left if "start" in c and (_close(c["start"], tip) or _close(c["end"], tip))), None)
            if found is None:
                return None
            left.remove(found)
            loop.append(found)
            tip = found["end"] if _close(found["start"], tip) else found["start"]
        loops.append(loop)
    return loops


def _area(curves):
    """The area a closed loop encloses (unsigned), drawn through the curve points."""
    points = []
    for curve in curves:
        points += _polyline(curve)
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2.0


def _merged(group):
    """One profile for a group of profiles that share curves, or None when the result is not one region."""
    counts = {}
    for profile in group:
        for loop in profile["loops"]:
            for curve in loop["curves"]:
                key = _key(curve)
                counts[key] = counts.get(key, 0) + 1
    if None in counts:
        return None
    kept, seen = [], set()
    for profile in group:
        for loop in profile["loops"]:
            for curve in loop["curves"]:
                key = _key(curve)
                if counts[key] == 1 and key not in seen:
                    seen.add(key)
                    kept.append(curve)
    loops = _loops(kept)
    if not loops:
        return None
    loops.sort(key=_area, reverse=True)
    outer = Footprint({"loops": [{"outer": True, "curves": loops[0]}]})
    for hole in loops[1:]:
        if not outer.covers(_polyline(hole[0])[len(_polyline(hole[0])) // 2]):
            return None
    merged = dict(group[0])
    merged["loops"] = [{"outer": True, "curves": loops[0]}] + [{"outer": False, "curves": hole} for hole in loops[1:]]
    return merged


def merge_touching(profiles):
    """The profiles with each group that shares a curve merged into one; unchanged where a merge does not work out."""
    if len(profiles) < 2 or any(not isinstance(p.get("loops"), list) for p in profiles):
        return profiles
    if any(not _same_frame(p["frame"], profiles[0]["frame"]) for p in profiles[1:]):
        return profiles
    keys = [{_key(c) for loop in p["loops"] for c in loop.get("curves") or []} for p in profiles]
    group_of = list(range(len(profiles)))

    def root(n):
        while group_of[n] != n:
            n = group_of[n]
        return n

    for a in range(len(profiles)):
        for b in range(a + 1, len(profiles)):
            if (keys[a] & keys[b]) - {None}:
                group_of[root(b)] = root(a)
    out, done = [], {}
    for n, profile in enumerate(profiles):
        r = root(n)
        if r in done:
            continue
        group = [profiles[m] for m in range(len(profiles)) if root(m) == r]
        merged = _merged(group) if len(group) > 1 else profile
        done[r] = True
        out += [merged] if merged is not None else group
    return out
