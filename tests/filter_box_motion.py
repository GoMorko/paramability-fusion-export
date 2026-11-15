"""A motion file for a FilterBox capture, written by hand from how its sketches are drawn.

The capture holds no probe states, so the motion is what the probe fits for this geometry:
- BoxBase: a rectangle centred on the origin, `FilterBox_width_mm` by `FilterBox_depth_mm`.
- BoxSidesSupports: the outer wall at half the box size, the inner wall one wall thickness in, round supports
  (radius 1.25) centred on the wall middle and placed 2.75 mm from the inner wall. Where a support crosses a wall,
  the point moves by a square root of the wall thickness along the wall, so the probe marks that coordinate stuck.
- PipeInsertTop: circles at the origin and moved by `FilterBox__PipeTop_offsetFromCenter_mm`; their crossing points
  sit at half the offset, and move along x by a square root of the offset (stuck).
The sketch curves of every profile are measured too (`curves`): wall lines by their offset, arcs by centre and radius.
"""
from tests import context  # noqa: F401

import math

from lib.sketch_values.motion import Affine, Motion, Stuck
from lib.translator.sketch.loops import profile_loops

W, D = "FilterBox_width_mm", "FilterBox_depth_mm"
WALL = "_Filter__Wall_thickness_mm"
PIPE = "FilterBox__PipeTop_offsetFromCenter_mm"
HALF_W, HALF_D, WALL0, PIPE0 = 17.2, 17.2, 1.25, 0.05
SUPPORT_FROM_WALL = 2.75
SUPPORT_R = 1.25
TOL = 1e-4
WALLS = (HALF_W, HALF_W - WALL0)


def _side(v, half, size, sketch):
    """A coordinate across one pair of walls: on the outer or inner wall, else kept from the wall middle."""
    sign = 1.0 if v > 0 else -1.0
    for at, terms in ((half, {size: 0.5}), (half - WALL0, {size: 0.5, WALL: -1.0})):
        if abs(abs(v) - at) <= TOL:
            return Affine(0.0, {k: sign * a for k, a in terms.items()}, sketch)
    middle = half - WALL0 / 2
    return Affine(v - sign * middle, {size: sign * 0.5, WALL: -sign * 0.5}, sketch)


def _on_wall(v):
    return any(abs(abs(v) - w) <= TOL for w in WALLS)


def _crosses_support(x, y, centres):
    return any(abs(math.hypot(x - c[0], y - c[1]) - SUPPORT_R) <= TOL for c in centres)


def _support(x, y, centres=()):
    """(x, y) of a BoxSidesSupports point: the coordinate near a wall follows that wall, the other the support. Where
    a support crosses a wall the coordinate along the wall is stuck."""
    near_x = abs(abs(x) - HALF_W) <= 2.0
    near_y = abs(abs(y) - HALF_D) <= 2.0
    if _crosses_support(x, y, centres) and (_on_wall(x) or _on_wall(y)):
        stuck = Stuck([D if _on_wall(x) else W, WALL], "curve", "BoxSidesSupports")
        if _on_wall(x):
            return _side(x, HALF_W, W, "BoxSidesSupports"), stuck
        return stuck, _side(y, HALF_D, D, "BoxSidesSupports")
    if near_x and near_y:
        return _side(x, HALF_W, W, "BoxSidesSupports"), _side(y, HALF_D, D, "BoxSidesSupports")
    if near_x:
        return _side(x, HALF_W, W, "BoxSidesSupports"), _along(y, HALF_D, D)
    return _along(x, HALF_W, W), _side(y, HALF_D, D, "BoxSidesSupports")


def _along(v, half, size):
    sign = 1.0 if v > 0 else -1.0
    support = half - WALL0 - SUPPORT_FROM_WALL
    return Affine(v - sign * (support + SUPPORT_FROM_WALL), {size: sign * 0.5, WALL: -sign}, "BoxSidesSupports")


def _pipe(x, y, radii):
    """(x, y) of a PipeInsertTop point: on both circles of one radius it is a crossing (x stuck); on the moved circle
    only it moves with the offset; on the circle at the origin only it stays."""
    moved = any(abs(math.hypot(x, y - PIPE0) - r) <= TOL for r in radii)
    still = any(abs(math.hypot(x, y) - r) <= TOL for r in radii)
    if moved and still:
        return Stuck([PIPE], "curve", "PipeInsertTop"), Affine(y - PIPE0 / 2, {PIPE: 0.5}, "PipeInsertTop")
    if moved:
        return Affine(x, sketch="PipeInsertTop"), Affine(y - PIPE0, {PIPE: 1.0}, "PipeInsertTop")
    return None


def _curve_values(sketch, prefix, profile, values):
    """The measured sketch curves of one profile: a wall line's offset, an arc's centre."""
    for k, loop in enumerate(profile["loops"]):
        for j, curve in enumerate(loop["curves"]):
            key = "%s/c%d.%d/" % (prefix, k, j)
            if curve["kind"] == "line" and sketch == "BoxSidesSupports":
                d = [curve["end"][i] - curve["start"][i] for i in range(2)]
                size = math.hypot(*d)
                n = [-d[1] / size, d[0] / size]
                across = 0 if abs(n[0]) > 0.5 else 1
                half, size_name = (HALF_W, W) if across == 0 else (HALF_D, D)
                values[key + "offset"] = _side(curve["start"][across], half, size_name, sketch).scaled(n[across])
            elif curve["kind"] == "arc" and sketch == "BoxSidesSupports":
                cx, cy = _support(*curve["center"])
                values[key + "center.0"], values[key + "center.1"] = cx, cy
            elif curve["kind"] == "arc" and abs(curve["center"][1] - PIPE0) <= TOL:
                values[key + "center.1"] = Affine(0.0, {PIPE: 1.0}, sketch)


def _points(node, path, out):
    if isinstance(node, dict):
        for k, v in node.items():
            _points(v, path + [k], out)
    elif isinstance(node, list):
        if len(node) == 2 and all(isinstance(c, (int, float)) for c in node):
            out[".".join(path)] = node
        else:
            for at, v in enumerate(node):
                _points(v, path + [str(at)], out)


def filter_box_motion(capture):
    """The `Motion` of the FilterBox items that draw BoxBase, BoxSidesSupports and PipeInsertTop."""
    values, curves = {}, []
    for item in capture["items"]:
        for n, profile in enumerate((item.get("data") or {}).get("profiles") or []):
            sketch = profile.get("sketch")
            if sketch not in ("BoxBase", "BoxSidesSupports", "PipeInsertTop") or profile.get("foreign"):
                continue
            built = profile_loops(profile)
            arcs = [c for loop in profile["loops"] for c in loop["curves"] if c["kind"] in ("arc", "circle")]
            centres = [c["center"] for c in arcs]
            radii = sorted({round(c["radius"], 6) for c in arcs})
            curves.append("%s/p%d" % (item["index"], n))
            _curve_values(sketch, curves[-1], profile, values)
            for k, loop in enumerate([built[0]] + list(built[1])):
                prefix = "%s/p%d/l%d/" % (item["index"], n, k)
                if sketch == "BoxBase":
                    values[prefix + "width"] = Affine(0.0, {W: 1.0}, sketch)
                    values[prefix + "height"] = Affine(0.0, {D: 1.0}, sketch)
                    continue
                points = {}
                _points(loop, [], points)
                for path, (x, y) in points.items():
                    moved = _support(x, y, centres) if sketch == "BoxSidesSupports" else _pipe(x, y, radii)
                    if moved is None:
                        continue
                    for c, value in enumerate(moved):
                        if isinstance(value, Stuck) or value.terms:
                            values["%s%s.%d" % (prefix, path, c)] = value
    return Motion(values, curves=curves)
