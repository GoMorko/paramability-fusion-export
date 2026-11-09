"""A motion file for the owner's FilterBox capture, written by hand from how its sketches are drawn.

The capture holds no probe states, so the motion is what the probe would fit if the support sketch stayed rigid:
- BoxBase: a rectangle centred on the origin, `FilterBox_width_mm` by `FilterBox_depth_mm`.
- BoxSidesSupports: the outer wall at half the box size, the inner wall one wall thickness in, round supports centred
  on the wall middle and placed 2.75 mm from the inner wall. Points on a support keep their place on it.
- PipeInsertTop: two circles, one at the origin and one moved by `FilterBox__PipeTop_offsetFromCenter_mm`, whose
  crossing points sit at half the offset.
"""
from tests import context  # noqa: F401

from lib.probe.motion import Affine, Motion
from lib.translator.loops import profile_loops

W, D = "FilterBox_width_mm", "FilterBox_depth_mm"
WALL = "_Filter__Wall_thickness_mm"
PIPE = "FilterBox__PipeTop_offsetFromCenter_mm"
HALF_W, HALF_D, WALL0, PIPE0 = 17.2, 17.2, 1.25, 0.05
SUPPORT_FROM_WALL = 2.75
TOL = 1e-4


def _side(v, half, size, sketch):
    """A coordinate across one pair of walls: on the outer or inner wall, else kept from the wall middle."""
    sign = 1.0 if v > 0 else -1.0
    for at, terms in ((half, {size: 0.5}), (half - WALL0, {size: 0.5, WALL: -1.0})):
        if abs(abs(v) - at) <= TOL:
            return Affine(0.0, {k: sign * a for k, a in terms.items()}, sketch)
    middle = half - WALL0 / 2
    return Affine(v - sign * middle, {size: sign * 0.5, WALL: -sign * 0.5}, sketch)


def _support(x, y):
    """(x, y) of a BoxSidesSupports point: the coordinate near a wall follows that wall, the other the support."""
    near_x = abs(abs(x) - HALF_W) <= 2.0
    near_y = abs(abs(y) - HALF_D) <= 2.0
    if near_x and near_y:
        return _side(x, HALF_W, W, "BoxSidesSupports"), _side(y, HALF_D, D, "BoxSidesSupports")
    if near_x:
        return _side(x, HALF_W, W, "BoxSidesSupports"), _along(y, HALF_D, D)
    return _along(x, HALF_W, W), _side(y, HALF_D, D, "BoxSidesSupports")


def _along(v, half, size):
    sign = 1.0 if v > 0 else -1.0
    support = half - WALL0 - SUPPORT_FROM_WALL
    return Affine(v - sign * (support + SUPPORT_FROM_WALL), {size: sign * 0.5, WALL: -sign}, "BoxSidesSupports")


def _pipe(x, y):
    if abs(abs(y) - PIPE0 / 2) <= TOL:
        return Affine(x, sketch="PipeInsertTop"), Affine(y - PIPE0 / 2 * (1 if y > 0 else -1),
                                                         {PIPE: 0.5 if y > 0 else -0.5}, "PipeInsertTop")
    if abs(x) <= TOL and abs(abs(y - PIPE0) - 8.125) <= TOL:
        return Affine(x, sketch="PipeInsertTop"), Affine(y - PIPE0, {PIPE: 1.0}, "PipeInsertTop")
    return None


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
    values = {}
    for item in capture["items"]:
        for n, profile in enumerate((item.get("data") or {}).get("profiles") or []):
            sketch = profile.get("sketch")
            if sketch not in ("BoxBase", "BoxSidesSupports", "PipeInsertTop") or profile.get("foreign"):
                continue
            built = profile_loops(profile)
            for k, loop in enumerate([built[0]] + list(built[1])):
                prefix = "%s/p%d/l%d/" % (item["index"], n, k)
                if sketch == "BoxBase":
                    values[prefix + "width"] = Affine(0.0, {W: 1.0}, sketch)
                    values[prefix + "height"] = Affine(0.0, {D: 1.0}, sketch)
                    continue
                points = {}
                _points(loop, [], points)
                for path, (x, y) in points.items():
                    moved = _support(x, y) if sketch == "BoxSidesSupports" else _pipe(x, y)
                    if moved is None:
                        continue
                    for c, value in enumerate(moved):
                        if value.terms:
                            values["%s%s.%d" % (prefix, path, c)] = value
    return Motion(values)
