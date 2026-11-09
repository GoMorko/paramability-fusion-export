"""Sketch curves to recipe loops.

The capture lists the curves of a profile loop unchained and unoriented. `loop_of` chains them end to end and names
the simplest recipe loop kind that draws the same outline: circle, ellipse, rect, polygon, or profile (lines and
arcs). Everything is in the sketch's own 2D frame, mm.
"""
import math

from .result import Refusal

CHAIN_TOL = 1e-4
RIGHT_ANGLE_TOL = 1e-6
ANGLE_TOL_DEG = 1e-6
MAX_LOOP_POINTS = 1000
MIN_AREA_MM2 = 1e-6


def _n(value):
    return round(value, 9) + 0.0


def _pt(p):
    return [_n(p[0]), _n(p[1])]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _where(sketch):
    return "An outline in %s" % sketch if sketch else "An outline"


def _oriented(curve, reverse):
    """A chain link: the curve with its start and end swapped when `reverse`. An arc keeps its mid."""
    link = dict(curve)
    if reverse:
        link["start"], link["end"] = curve["end"], curve["start"]
    return link


def _chain(curves):
    """Order and orient lines and arcs so each starts where the last ended. None when they do not close."""
    remaining = list(curves)
    first = remaining.pop(0)
    chain = [dict(first)]
    while remaining:
        tip = chain[-1]["end"]
        for position, curve in enumerate(remaining):
            if _dist(tip, curve["start"]) <= CHAIN_TOL:
                chain.append(_oriented(curve, False))
            elif _dist(tip, curve["end"]) <= CHAIN_TOL:
                chain.append(_oriented(curve, True))
            else:
                continue
            del remaining[position]
            break
        else:
            return None
    if _dist(chain[-1]["end"], chain[0]["start"]) > CHAIN_TOL:
        return None
    return chain


def _area(chain):
    """Signed area of a chained loop, with each arc drawn through its middle point (enough to tell a flat loop)."""
    points = []
    for link in chain:
        points.append(link["start"])
        if link["kind"] == "arc":
            points.append(link["mid"])
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))


def _as_rect(chain):
    """A rect loop when four lines meet at right angles, else None."""
    if len(chain) != 4 or any(link["kind"] != "line" for link in chain):
        return None
    edges = []
    for link in chain:
        dx, dy = link["end"][0] - link["start"][0], link["end"][1] - link["start"][1]
        size = math.hypot(dx, dy)
        if size <= CHAIN_TOL:
            return None
        edges.append((dx, dy, size))
    for at in range(4):
        a, b = edges[at], edges[(at + 1) % 4]
        if abs(a[0] * b[0] + a[1] * b[1]) / (a[2] * b[2]) > RIGHT_ANGLE_TOL:
            return None
    if abs(edges[0][2] - edges[2][2]) > CHAIN_TOL or abs(edges[1][2] - edges[3][2]) > CHAIN_TOL:
        return None
    theta = math.degrees(math.atan2(edges[0][1], edges[0][0]))
    turn = theta % 90.0
    if turn < ANGLE_TOL_DEG or 90.0 - turn < ANGLE_TOL_DEG:
        turn = 0.0
    along_x = abs(((theta - turn) / 180.0) - round((theta - turn) / 180.0)) < 1e-6
    width, height = (edges[0][2], edges[1][2]) if along_x else (edges[1][2], edges[0][2])
    cx = sum(link["start"][0] for link in chain) / 4.0
    cy = sum(link["start"][1] for link in chain) / 4.0
    loop = {"kind": "rect", "center": _pt([cx, cy]), "width": _n(width), "height": _n(height)}
    if turn:
        loop["angleDeg"] = _n(turn)
    return loop


def loop_of(curves, sketch=""):
    """Chain one profile loop's capture curves (sketch 2D mm) into a recipe loop dict, or a Refusal."""
    if not curves:
        return Refusal("%s has no curves." % _where(sketch))
    if any(c.get("kind") == "other" for c in curves):
        return Refusal("Curved outlines of this kind are not copied yet.")
    if len(curves) == 1 and curves[0]["kind"] in ("circle", "ellipse"):
        c = curves[0]
        if c["kind"] == "circle":
            return {"kind": "circle", "center": _pt(c["center"]), "radius": _n(c["radius"])}
        loop = {
            "kind": "ellipse", "center": _pt(c["center"]),
            "radiusX": _n(c["major_radius"]), "radiusY": _n(c["minor_radius"]),
        }
        angle = math.degrees(math.atan2(c["major_dir"][1], c["major_dir"][0]))
        if abs(angle) > ANGLE_TOL_DEG:
            loop["angleDeg"] = _n(angle)
        return loop
    if len(curves) == 1 and curves[0]["kind"] == "arc" and _dist(curves[0]["start"], curves[0]["end"]) <= CHAIN_TOL:
        c = curves[0]
        return {"kind": "circle", "center": _pt(c["center"]), "radius": _n(c["radius"])}
    if any(c.get("kind") not in ("line", "arc") for c in curves):
        return Refusal("%s is not closed." % _where(sketch))
    chain = _chain(curves)
    if chain is None or len(chain) < 3 and all(link["kind"] == "line" for link in chain):
        return Refusal("%s is not closed." % _where(sketch))
    if len(chain) > MAX_LOOP_POINTS:
        return Refusal("%s has too many segments." % _where(sketch))
    if abs(_area(chain)) <= MIN_AREA_MM2:
        return Refusal("%s has no area." % _where(sketch))
    if all(link["kind"] == "line" for link in chain):
        rect = _as_rect(chain)
        if rect:
            return rect
        return {"kind": "polygon", "points": [_pt(link["start"]) for link in chain]}
    if len(chain) < 2:
        return Refusal("%s is not closed." % _where(sketch))
    segments = []
    for link in chain:
        if link["kind"] == "line":
            segments.append({"kind": "line", "to": _pt(link["end"])})
        else:
            segments.append({"kind": "arc", "through": _pt(link["mid"]), "to": _pt(link["end"])})
    return {"kind": "profile", "start": _pt(chain[0]["start"]), "segments": segments}


def flip_y(loop):
    """The loop mirrored across the sketch x axis, for a placement whose normal is reversed."""
    def flip(p):
        return [_n(p[0]), _n(-p[1])]

    out = dict(loop)
    kind = loop["kind"]
    if kind in ("circle", "rect", "ellipse"):
        out["center"] = flip(loop["center"])
        if "angleDeg" in loop:
            out["angleDeg"] = _n(-loop["angleDeg"])
    elif kind == "polygon":
        out["points"] = [flip(p) for p in loop["points"]]
    elif kind == "profile":
        out["start"] = flip(loop["start"])
        segments = []
        for seg in loop["segments"]:
            moved = dict(seg, to=flip(seg["to"]))
            if "through" in seg:
                moved["through"] = flip(seg["through"])
            segments.append(moved)
        out["segments"] = segments
    return out


MAX_INNER_LOOPS = 256


def profile_loops(profile):
    """One capture profile's `(outer, inners)` recipe loops, or a Refusal.

    Refuses a flat face used as a profile, a curve space the reader could not decide (`space: "ambiguous"`), a profile
    without exactly one outer loop, and any loop `loop_of` refuses.
    """
    if profile.get("face") or "loops" not in profile:
        return Refusal("A flat face used as a sketch outline is not copied yet.")
    sketch = profile.get("sketch", "")
    if profile.get("space", "sketch") not in ("sketch", "model"):
        return Refusal("%s could not be placed on its plane with certainty, so it is not copied." % _where(sketch))
    outers, inners = [], []
    for raw in profile["loops"]:
        loop = loop_of(raw.get("curves") or [], sketch)
        if isinstance(loop, Refusal):
            return loop
        (outers if raw.get("outer") else inners).append(loop)
    if len(outers) != 1:
        return Refusal("%s does not have exactly one outer loop." % _where(sketch))
    if len(inners) > MAX_INNER_LOOPS:
        return Refusal("%s has too many holes." % _where(sketch))
    return outers[0], inners
