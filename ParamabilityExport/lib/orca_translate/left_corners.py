"""Rounds and chamfers that are left out of the Orca copy, measured so that a later round of side edges can tell
whether they came near its edge.

A step left out between an extrude and a round may have changed the edge in Fusion, where the copy cannot see it.
`outline_rounds.note_left_out` measures such a step on the copy and keeps its regions in `ctx.left_corners`;
`clear_of_gaps` answers whether every step left out since an extrude is measured and apart from the corners of a new
round. Pure geometry on the copy's shapes, no Fusion access.
"""
from ..geometry import vec
from . import finish_body

POINT_TOL = finish_body.POINT_TOL

# Margin (mm) added to the reaches when two edges are compared.
_PAST = 0.05

# A left out round or chamfer of side edges changes the part only near its edges: within its reach of each edge,
# along the edge, when the edge is one straight edge of a copied extrude with flat ends square to it.

# A left out round and a later round count as apart when their edges are farther apart than this many times the sum of
# their reaches, plus `_PAST` (mm).
_APART = 2.0


def region(corner, shape, low, high):
    """(two ends of the edge, reach, the planes of the faces next to it as (point, normal)) of a corner, the edge
    running from `low` to `high` along the extrude. All in the capture's coordinates."""
    prism = corner.prism
    at = vec.add(prism.origin, vec.add(vec.scale(prism.x, corner.point[0]), vec.scale(prism.y, corner.point[1])))
    ends = [vec.add(at, vec.scale(prism.z, w)) for w in (low, high)]
    planes = []
    for d in (shape.d1, shape.d2):
        normal = vec.add(vec.scale(prism.x, -d[1]), vec.scale(prism.y, d[0]))
        planes.append((ends[0], normal))
    return ends, shape.reach, planes


def segment_gap(a0, a1, b0, b1):
    """The shortest distance between the segments a0-a1 and b0-b1."""
    da, db, r = vec.sub(a1, a0), vec.sub(b1, b0), vec.sub(a0, b0)
    aa, bb, ab, ar, br = vec.dot(da, da), vec.dot(db, db), vec.dot(da, db), vec.dot(da, r), vec.dot(db, r)

    def clamp(v):
        return max(0.0, min(1.0, v))
    candidates = []
    for s in (0.0, 1.0):
        candidates.append((s, clamp((ab * s + br) / bb) if bb > 0 else 0.0))
    for t in (0.0, 1.0):
        candidates.append((clamp((ab * t - ar) / aa) if aa > 0 else 0.0, t))
    den = aa * bb - ab * ab
    if den > 1e-12:
        s = clamp((ab * br - bb * ar) / den)
        candidates.append((s, clamp((ab * s + br) / bb)))
    return min(vec.length(vec.sub(vec.add(a0, vec.scale(da, s)), vec.add(b0, vec.scale(db, t))))
               for s, t in candidates)


def _on_plane(ends, planes):
    """True when both ends lie on one of the planes."""
    return any(all(abs(vec.dot(vec.sub(p, point), normal)) <= POINT_TOL for p in ends) for point, normal in planes)


def _apart(one, two):
    """True when the edges of two regions are far apart and neither lies on a face next to the other."""
    (a, ra, pa), (b, rb, pb) = one, two
    if _on_plane(a, pb) or _on_plane(b, pa):
        return False
    return segment_gap(a[0], a[1], b[0], b[1]) > _APART * (ra + rb) + _PAST


def clear_of_gaps(ctx, index, maker, regions):
    """True when every step left out between the extrude made by step `maker` and step `index` is a round or chamfer
    measured when it was left out whose edges are apart from the corners `regions`."""
    for gap in ctx.left_out:
        if not maker < gap.get("index", -1) < index:
            continue
        known = ctx.left_corners.get(gap.get("index"))
        if known is None or not all(_apart(one, two) for one in known for two in regions):
            return False
    return True
