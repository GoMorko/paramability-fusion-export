"""Small vector helpers on [x, y, z] lists. Angles in degrees; rotations follow the right hand rule."""
import math

# Points closer than this (mm) are the same point.
POINT_TOL = 1e-6


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def scale(a, k):
    return [x * k for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def length(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = length(a)
    if n == 0:
        raise ValueError("zero length vector")
    return [x / n for x in a]


def rotate(p, axis_dir, angle_deg, axis_point=(0.0, 0.0, 0.0)):
    """Rotate point or vector p about the line through axis_point along axis_dir (Rodrigues). For a vector pass the default point."""
    k = unit(axis_dir)
    v = sub(p, axis_point)
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    rotated = add(add(scale(v, c), scale(cross(k, v), s)), scale(k, dot(k, v) * (1 - c)))
    return add(rotated, axis_point)


def reflect(p, plane_point, plane_normal):
    """Mirror point p across the plane."""
    n = unit(plane_normal)
    d = dot(sub(p, plane_point), n)
    return sub(p, scale(n, 2 * d))


def reflect_vector(v, plane_normal):
    n = unit(plane_normal)
    return sub(v, scale(n, 2 * dot(v, n)))


def frame_apply(frame, local):
    """Point in a frame's own coordinates to model coordinates."""
    o, x, y, z = frame["origin"], frame["x"], frame["y"], frame["z"]
    return [o[i] + local[0] * x[i] + local[1] * y[i] + local[2] * z[i] for i in range(3)]


def frame_to_local(frame, p):
    """Model point to a frame's own coordinates."""
    d = sub(p, frame["origin"])
    return [dot(d, frame["x"]), dot(d, frame["y"]), dot(d, frame["z"])]


def box_side(box, point, normal, tol, flat=0):
    """+1 or -1 when the box ({min, max}) lies on that side of the plane through `point` with unit `normal` (`tol` mm
    allowed across it), else 0. A box that lies within `tol` of the plane on both sides gives `flat`."""
    lo, hi = box["min"], box["max"]
    dists = [dot(sub([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]], point), normal)
             for i in range(8)]
    if min(dists) >= -tol and max(dists) <= tol:
        return flat
    if min(dists) >= -tol:
        return 1
    if max(dists) <= tol:
        return -1
    return 0


def close(a, b, tol=1e-9):
    """Numbers or equal length sequences agree within tol."""
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol
