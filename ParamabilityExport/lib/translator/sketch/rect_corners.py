"""The corners of a rectangle loop as numbers and as raw size values (`curved.combine` over its centre, width and
height)."""
import math

from .curved import combine


def rect_axes(loop):
    angle = math.radians(loop.get("angleDeg", 0.0))
    c, s = math.cos(angle), math.sin(angle)
    if abs(s) < 1e-15:
        c, s = math.copysign(1.0, c), 0.0
    return (c, s), (-s, c)


def rect_corners(loop, raw_loop, sketch=""):
    """[(uv, (x, y))] of a rect's corners, numbers and raw values."""
    u, v = rect_axes(loop)
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        uv = [loop["center"][i] + sx * loop["width"] / 2 * u[i] + sy * loop["height"] / 2 * v[i] for i in range(2)]
        xy = tuple(combine([(1.0, raw_loop["center"][i]), (sx * u[i] / 2, raw_loop["width"]),
                            (sy * v[i] / 2, raw_loop["height"])], sketch) for i in range(2))
        out.append((uv, xy))
    return out
