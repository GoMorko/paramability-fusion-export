"""The outline that several touching outlines of one sketch make together, drawn through their corners.

An outline joined from the outlines of one sketch (`geometry.outlines.merge_touching`) has no values of its own in
the probe's motion file: each of its corners is a corner of one or more of the outlines, and takes the raw values they
give it (`sketch_motion.Outline.anchors`). Two outlines that share a corner must move it alike, else the joined
outline cannot be told. Nothing here cuts a range or marks a size: the caller checks the joined outline over the size
ranges before it uses it (faces/revolve_joined.py).
"""
import math

from ...sketch_values.motion import Affine, Stuck
from .curved import combine
from .sketch_motion import MATCH_TOL, Anchors, Outline, from_anchors, same


def _agree(a, b):
    """True when two raw values of one sketch corner move alike: the same sum of sizes, or products that cancel. A
    stuck value agrees with nothing: the corner cannot be told."""
    if isinstance(a, Stuck) or isinstance(b, Stuck):
        return False
    if isinstance(a, Affine) and isinstance(b, Affine):
        return same(a, b)
    found = combine([(1.0, a), (-1.0, b)])
    return not isinstance(found, Stuck) and found.is_constant


class _SharedAnchors(Anchors):
    """The anchors of several outlines of one sketch. `split` turns true when a looked up corner is in no outline, or
    two outlines that have it move it apart."""

    def __init__(self, parts, sketch):
        Anchors.__init__(self, sketch)
        self.split = False
        for part in parts:
            self.points += part.anchors.points
            self.rounds += part.anchors.rounds

    def point(self, uv, tol=MATCH_TOL):
        found = [xy for p, xy in self.points if math.hypot(p[0] - uv[0], p[1] - uv[1]) <= tol]
        if not found or any(not _agree(xy[i], found[0][i]) for xy in found[1:] for i in range(2)):
            self.split = True
        return Anchors.point(self, uv, tol)

    def round_at(self, center, size, tol=MATCH_TOL):
        found = Anchors.round_at(self, center, size, tol)
        if found is None:
            self.split = True
        return found


def joined_outline(ctx, profile, loops, parts):
    """The `Outline` of `loops` (the written loops of `profile`, outer first), drawn through the corners of the
    outlines `parts` (their `Outline`s, of one sketch) that it was joined from: each corner takes the raw values the
    parts give it, and the size ranges cut for the parts hold for it too. None when a corner of `loops` is a corner of
    no part, when two parts that share a corner move it apart, or when the parts do not share their sketch plane.
    Nothing is cut or marked here: the caller checks the joined outline over the size ranges."""
    first = parts[0]
    if any(not _agree(part.plane, first.plane) for part in parts[1:]):
        return None
    anchors = _SharedAnchors(parts, first.sketch)
    raw_loops = [from_anchors(loop, anchors, first.sketch) for loop in loops]
    if anchors.split:
        return None
    bounds = {}
    for part in parts:
        for name, (low, high) in (part.bounds or {}).items():
            was = bounds.get(name, (low, high))
            bounds[name] = (max(low, was[0]), min(high, was[1]))
    return Outline(ctx, profile["frame"], loops, raw_loops, first.plane, first.sketch, bounds or None)
