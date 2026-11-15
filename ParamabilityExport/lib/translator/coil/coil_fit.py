"""The helix of a measured coil: its axis, its hand, and a check that it is the helix Fusion built.

Fusion's API gives no axis, hand or place of a coil, so they are worked out from what the reader measured:
- the two flat end faces (`coil_section.cap_of`): each is the wire's section on a plane through the axis;
- points along the helical edges of the curved faces.
The axis points from the first end face to the second. For a coil of whole turns the two faces lie in one plane and the
axis runs along the line between their centres, and where it sits across that direction comes from a circle fitted to
the points of a helical edge seen along the axis. Otherwise the axis is where the two planes cross. The hand follows from
which way the first end face looks: the wire leaves it into the body.

`verify` then walks every measured point back to the first turn and tests that it lies on the section's outline, which
rejects a tapered coil, a section that is not on a plane through the axis, and any wrong pitch, turns, hand or axis.
"""
import math

from ...geometry import vec
from ...geometry.plane2d import to_ring
from ..result import Refusal
from . import coil_limits as limits
from .coil_section import outline, outline_3d

PARALLEL_TOL = 1e-3
LEAN_TOL = 0.98
FIT_SHARE = 0.004       # of the section's size: how far a measured point may lie from the model
MIN_SPREAD = 0.2        # minor over major spread of a fitted edge seen along the axis (a half turn or more)
MARGIN = 0.2            # rad: how far past the ends of the helix a measured point may turn


def _basis(direction):
    """Two unit vectors square to `direction` and to each other."""
    other = [0.0, 1.0, 0.0] if abs(direction[0]) > 0.9 else [1.0, 0.0, 0.0]
    first = vec.unit(vec.cross(direction, other))
    return first, vec.cross(direction, first)


def _solve3(m, b):
    """The solution of a 3 x 3 linear system, or None when it is singular."""
    rows = [list(m[i]) + [b[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(3):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [x - factor * y for x, y in zip(rows[r], rows[col])]
    return [rows[i][3] / rows[i][i] for i in range(3)]


def _spread(points):
    """Minor over major standard deviation of 2D points: near 0 for a line, near 1 for a round cloud."""
    n = len(points)
    mx, my = sum(p[0] for p in points) / n, sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points) / n
    syy = sum((p[1] - my) ** 2 for p in points) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
    mid, gap = (sxx + syy) / 2.0, math.hypot((sxx - syy) / 2.0, sxy)
    major, minor = mid + gap, max(mid - gap, 0.0)
    return math.sqrt(minor / major) if major > 0 else 0.0


def _circle_centre(points):
    """The centre of the circle that fits 2D points best (algebraic fit), or None for points on a line."""
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points)
    syy = sum(p[1] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    sz = sum(p[0] ** 2 + p[1] ** 2 for p in points)
    sxz = sum(p[0] * (p[0] ** 2 + p[1] ** 2) for p in points)
    syz = sum(p[1] * (p[0] ** 2 + p[1] ** 2) for p in points)
    found = _solve3([[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]], [sxz, syz, sz])
    return None if found is None else [found[0] / 2.0, found[1] / 2.0]


def _axis_point(direction, start, edges):
    """A point of the axis at the level of `start` (the centre of the first end face), from the helical edges, or None.
    An edge seen along the axis is a round arc around it; the edge with the roundest spread is used."""
    first, second = _basis(direction)
    best = None
    for points in edges:
        flat = [[vec.dot(vec.sub(p, start), first), vec.dot(vec.sub(p, start), second)] for p in points]
        spread = _spread(flat)
        if spread >= MIN_SPREAD and (best is None or spread > best[0]):
            centre = _circle_centre(flat)
            if centre is not None:
                best = (spread, centre)
    if best is None:
        return None
    return vec.add(start, vec.add(vec.scale(first, best[1][0]), vec.scale(second, best[1][1])))


def _planes_meet(direction, start, end):
    """The point of the axis at the level of the first end face: where the two end planes and the plane square to the
    axis through the first face's centre meet."""
    rows = [start["frame"]["z"], end["frame"]["z"], direction]
    found = _solve3(rows, [vec.dot(start["frame"]["z"], start["centre"]), vec.dot(end["frame"]["z"], end["centre"]),
                           vec.dot(direction, start["centre"])])
    return found


def find_axis(start, end, edges):
    """`{ point, dir, radial, rho, hand, rise }` of the coil from its two end faces (`coil_section.cap_of`) and the
    sampled edges, or a Refusal. `point` is on the axis at the level of the first end face, `radial` points from it to
    the section's centre, `rho` is that distance and `rise` the distance between the faces along the axis."""
    chord = vec.sub(end["centre"], start["centre"])
    if vec.length(chord) < limits.LEN_TOL:
        return Refusal(limits.PLACE, cause=limits.CAUSE_PLACE)
    crossing = vec.cross(start["frame"]["z"], end["frame"]["z"])
    if vec.length(crossing) > PARALLEL_TOL:
        direction = vec.unit(crossing)
    elif abs(vec.dot(chord, start["frame"]["z"])) <= limits.LEN_TOL:
        direction = vec.unit(chord)
    else:
        return Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER)
    if vec.dot(direction, chord) < 0:
        direction = vec.scale(direction, -1.0)
    rise = vec.dot(direction, chord)
    if rise < limits.LEN_TOL:
        return Refusal(limits.SPIRAL, cause=limits.CAUSE_SPIRAL)
    if vec.length(crossing) > PARALLEL_TOL:
        point = _planes_meet(direction, start, end)
    else:
        point = _axis_point(direction, start["centre"], edges)
    if point is None:
        return Refusal(limits.PLACE, cause=limits.CAUSE_PLACE)
    out = vec.sub(start["centre"], point)
    rho = vec.length(out)
    if rho < limits.LEN_TOL:
        return Refusal(limits.PLACE, cause=limits.CAUSE_PLACE)
    radial = vec.scale(out, 1.0 / rho)
    # The wire leaves the first face into the body, against the face's outward normal.
    lean = vec.dot(vec.cross(direction, radial), vec.scale(start["frame"]["z"], -1.0))
    if abs(lean) < LEAN_TOL:
        return Refusal(limits.NOT_FITTING, cause=limits.CAUSE_OTHER)
    return {"point": point, "dir": direction, "radial": radial, "rho": rho, "rise": rise,
            "hand": "right" if lean > 0 else "left"}


def _section(axis, start):
    """The outline of the first end face as (r, h) points: outward from the axis and along it."""
    return [[vec.dot(vec.sub(p, axis["point"]), axis["radial"]), vec.dot(vec.sub(p, axis["point"]), axis["dir"])]
            for p in outline_3d(start)]


def _ends_forward(axis, end, turns):
    """True when the second end face looks along the way the wire travels there."""
    sign = 1.0 if axis["hand"] == "right" else -1.0
    radial = vec.rotate(axis["radial"], axis["dir"], math.degrees(sign * 2.0 * math.pi * turns))
    travel = vec.scale(vec.cross(axis["dir"], radial), sign)
    return vec.dot(travel, end["frame"]["z"]) >= LEAN_TOL


def verify(axis, start, end, edges, pitch, turns):
    """True when the helix of `axis`, `pitch` and `turns` carrying the first end face's section passes through every
    measured point: the sampled edges and the outline of the second end face."""
    if not _ends_forward(axis, end, turns):
        return False
    section = _section(axis, start)
    size = max(max(p[0] for p in section) - min(p[0] for p in section),
               max(p[1] for p in section) - min(p[1] for p in section))
    tolerance = limits.LEN_TOL * 10.0 + FIT_SHARE * size
    sign = 1.0 if axis["hand"] == "right" else -1.0
    third = vec.cross(axis["dir"], axis["radial"])
    total = 2.0 * math.pi * turns
    points = [p for edge in edges for p in edge] + outline_3d(end)
    for p in points:
        rel = vec.sub(p, axis["point"])
        h = vec.dot(rel, axis["dir"])
        across = vec.sub(rel, vec.scale(axis["dir"], h))
        r = vec.length(across)
        theta = sign * math.atan2(vec.dot(across, third), vec.dot(across, axis["radial"]))
        first = math.ceil((-MARGIN - theta) / (2.0 * math.pi))
        last = math.floor((total + MARGIN - theta) / (2.0 * math.pi))
        if not any(to_ring((r, h - pitch * (theta + 2.0 * math.pi * k) / (2.0 * math.pi)), section) <= tolerance
                   for k in range(first, last + 1)):
            return False
    return True


def section_in_axis(axis, start):
    """The first end face's outline as (r, h) points, for the checks and the written section."""
    return _section(axis, start)
