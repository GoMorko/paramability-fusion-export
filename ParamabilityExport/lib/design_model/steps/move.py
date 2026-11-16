"""The rigid move that carried a body, read from the places of its corners before and after a Move step.

`fit` finds the turn and shift that put the points `before` on the points `after`, or None when too few points tell
or no rigid move does it (a mirror or a scale). The result is a `geometry.rigid.Move` of plain numbers. Which size a
move follows, and how it is written, stay with the destination.
"""
from ...geometry import vec
from ...geometry.rigid import IDENTITY_ROWS, Move

FIT_TOL_MM = 1e-3
ROTATION_TOL = 1e-6


def _apply(move, point):
    return [sum(move.rows[i][k] * point[k] for k in range(3)) + move.offset[i] for i in range(3)]


def carries(move, before, after):
    """True when `move` puts each of the points `before` on the point of `after` at its place in the list."""
    return len(before) == len(after) and all(vec.close(_apply(move, p), q, FIT_TOL_MM) for p, q in zip(before, after))


def spread(points):
    """Places of three points of the list that are far apart and not on one line, or None."""
    far = max(range(len(points)), key=lambda n: vec.length(vec.sub(points[n], points[0])))
    along = vec.sub(points[far], points[0])
    if vec.length(along) <= FIT_TOL_MM:
        return None

    def off_line(n):
        return vec.length(vec.cross(along, vec.sub(points[n], points[0]))) / vec.length(along)

    third = max(range(len(points)), key=off_line)
    return None if off_line(third) <= FIT_TOL_MM else (0, far, third)


def _axes(a, b, c):
    """Three right angled unit axes made from three points, or None when they lie on one line."""
    normal = vec.cross(vec.sub(b, a), vec.sub(c, a))
    if vec.length(normal) <= FIT_TOL_MM ** 2:
        return None
    x, z = vec.unit(vec.sub(b, a)), vec.unit(normal)
    return x, vec.cross(z, x), z


def fit(before, after):
    """The rigid `Move` that carries the points `before` onto `after`, or None when there are too few points to tell
    or no turn and shift does it (a mirror or a scale)."""
    if len(before) != len(after) or not before:
        return None
    places = spread(before)
    if places is None:
        return None
    source = _axes(*[before[n] for n in places])
    image = _axes(*[after[n] for n in places])
    if image is None:
        return None
    rows = [[sum(image[k][i] * source[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    if vec.close(rows, [list(row) for row in IDENTITY_ROWS], ROTATION_TOL):
        rows = IDENTITY_ROWS
    shift = vec.sub(after[places[0]], _apply(Move(rows), before[places[0]]))
    found = Move(rows, shift)
    return found if carries(found, before, after) else None
