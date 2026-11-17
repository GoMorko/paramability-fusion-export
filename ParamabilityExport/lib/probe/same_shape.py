"""Two reads of one sketch compared by their shape alone: the same curves within a tolerance, in any order and either
direction, whatever their sketch entity tokens.

Fusion may give a curve a new token when it recomputes it (a projected or intersection curve), list a line the other
way round, give one projected line two tokens where profiles meet, or list the profiles in another order. None of that
changes the outline, so none of it is a flip. A curve that is gone or new, even a short one, is a change.
"""
import math

# A sketch frame whose axes differ more than this has turned: a real change, not noise.
AXIS_TOLERANCE = 1e-6

_POINTS = {"line": ("start", "end"), "arc": ("start", "end", "mid", "center"), "circle": ("center",),
           "ellipse": ("center",)}
_SIZES = {"arc": ("radius",), "circle": ("radius",), "ellipse": ("major_radius", "minor_radius")}


def _dist(a, b):
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != len(b):
        return math.inf
    try:
        return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))
    except (TypeError, ValueError):
        return math.inf


def _number_gap(a, b):
    try:
        return abs(float(a) - float(b))
    except (TypeError, ValueError):
        return math.inf


def _ends_gap(a, b):
    """The gap of the two ends of two curves, taken either way round."""
    straight = max(_dist(a.get("start"), b.get("start")), _dist(a.get("end"), b.get("end")))
    swapped = max(_dist(a.get("start"), b.get("end")), _dist(a.get("end"), b.get("start")))
    return min(straight, swapped)


def _samples_gap(a, b):
    """The gap of two sampled curves, their samples taken in either order; the ends and the middle point when the
    sample counts differ."""
    one, two = a.get("samples") or [], b.get("samples") or []
    if one and len(one) == len(two):
        forward = max(_dist(p, q) for p, q in zip(one, two))
        backward = max(_dist(p, q) for p, q in zip(one, reversed(two)))
        return min(forward, backward)
    return max(_ends_gap(a, b), _dist(a.get("mid"), b.get("mid")))


def curve_gap(a, b):
    """The largest distance between the defining points of two curves of one kind (either direction), in mm, or
    infinity for curves of different kinds."""
    kind = a.get("kind")
    if kind != b.get("kind") or a.get("type") != b.get("type"):
        return math.inf
    if kind in ("line", "arc"):
        gap = _ends_gap(a, b)
        if kind == "arc":
            gap = max(gap, _dist(a.get("mid"), b.get("mid")), _dist(a.get("center"), b.get("center")))
    elif kind in _POINTS:
        gap = max(_dist(a.get(k), b.get(k)) for k in _POINTS[kind])
    else:
        return _samples_gap(a, b)
    for key in _SIZES.get(kind, ()):
        gap = max(gap, _number_gap(a.get(key), b.get(key)))
    if kind == "ellipse":
        d1, d2 = a.get("major_dir"), b.get("major_dir")
        flipped = [-v for v in d2] if isinstance(d2, list) else d2
        gap = max(gap, min(_dist(d1, d2), _dist(d1, flipped)))
    return gap


def _centre(curves):
    """The mean of the defining points of `curves`, the same whichever way round each curve runs."""
    points = []
    for curve in curves:
        for key in _POINTS.get(curve.get("kind"), ("start", "end", "mid")):
            point = curve.get(key)
            if isinstance(point, (list, tuple)) and point:
                points.append(point)
    if not points:
        return None
    size = min(len(p) for p in points)
    return [sum(float(p[i]) for p in points) / len(points) for i in range(size)]


def _pair(left, right, gap, tolerance):
    """The largest gap of a one to one pairing of `left` with `right` where each pair is within `tolerance` (each item
    of `left` takes the nearest one left), or None when the two cannot be paired so."""
    if len(left) != len(right):
        return None
    free, worst = list(right), 0.0
    for item in left:
        best, best_gap = None, math.inf
        for at, other in enumerate(free):
            found = gap(item, other)
            if found < best_gap:
                best, best_gap = at, found
        if best is None or best_gap > tolerance:
            return None
        free.pop(best)
        worst = max(worst, best_gap)
    return worst


def _curves(loop):
    return [c for c in (loop.get("curves") or []) if isinstance(c, dict)]


def _loop_gap(tolerance):
    def gap(a, b):
        found = _pair(_curves(a), _curves(b), curve_gap, tolerance)
        return math.inf if found is None else found
    return gap


def _profile_gap(tolerance):
    loop_gap = _loop_gap(tolerance)

    def gap(a, b):
        loops_a, loops_b = a.get("loops") or [], b.get("loops") or []
        centre_a = _centre([c for loop in loops_a for c in _curves(loop)])
        centre_b = _centre([c for loop in loops_b for c in _curves(loop)])
        if len(loops_a) != len(loops_b) or _dist(centre_a, centre_b) > tolerance:
            return math.inf
        found = _pair(loops_a, loops_b, loop_gap, tolerance)
        return math.inf if found is None else found
    return gap


def _frame_gap(a, b):
    """The gap of two sketch frames: the distance of their origins, or infinity when an axis turned."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return math.inf
    if any(_dist(a.get(k), b.get(k)) > AXIS_TOLERANCE for k in ("x", "y", "z")):
        return math.inf
    return _dist(a.get("origin"), b.get("origin"))


def shape_gap(before, now, tolerance):
    """The largest distance, in mm, between the curves of two reads of one sketch (`{ frame, profiles, curves }`)
    once each profile, loop and curve of one is paired with one of the other within `tolerance`, in any order and
    either direction and whatever their tokens. None when they cannot be paired so: a curve, loop or profile is
    missing or new, a curve moved further than `tolerance`, or the sketch plane turned or moved."""
    if not isinstance(before, dict) or not isinstance(now, dict):
        return None
    worst = _frame_gap(before.get("frame"), now.get("frame"))
    if worst > tolerance:
        return None
    profiles = _pair(before.get("profiles") or [], now.get("profiles") or [], _profile_gap(tolerance), tolerance)
    if profiles is None:
        return None
    paths_a = [c for c in (before.get("curves") or {}).values() if isinstance(c, dict)]
    paths_b = [c for c in (now.get("curves") or {}).values() if isinstance(c, dict)]
    paths = _pair(paths_a, paths_b, curve_gap, tolerance)
    if paths is None:
        return None
    return max(worst, profiles, paths)
