"""Edges where the walls of two steps cross, for picks that follow sizes (see follow.py).

An edge that no single step explains, for example where a cut's flat floor runs into the round side of a rib, lies on
one wall of each step. When both walls are flat there, the edge is where their two planes meet: the point is moved so
it stays on both planes as they follow their sizes. Along the edge it follows the shorter of the two walls, since that
wall bounds the edge.
"""
import math

from . import vec
from .footprint import curve_length
from .shells import InnerPlace
from .slabs import cleaned
from .values import Quantity
from .vec import POINT_TOL

# Walls closer to parallel than this (sine of the angle between them) do not make an edge.
PARALLEL_SINE = 0.05
COEF_DIGITS = 9


def _coef(value):
    value = round(value, COEF_DIGITS) + 0.0
    return 0.0 if abs(value) < 1e-9 else value


def _sum(terms):
    """The sum of `coef * Quantity` terms, leaving out zero terms."""
    total = Quantity(0.0)
    for coef, q in terms:
        coef = _coef(coef)
        if coef:
            total = total.plus(q.scaled(coef))
    return total


class Wall:
    """One flat wall through the point: the Place on it, its unit normal and how far it runs along a direction."""

    def __init__(self, place, normal, reach):
        self.place, self.normal, self.reach = place, normal, reach


def _wall(place, p):
    """The Wall of a Place that sits on one face, or None."""
    if isinstance(place, InnerPlace):
        normal = place.single
        if normal is None:
            return None
        outer = place.outer
        reach = _reach_of(outer, place.outer_point)
        return Wall(place, normal, reach)
    slab = place.slab
    if place.which in ("start", "end") and place.curve is None:
        return Wall(place, slab.motion.turn_vector(slab.axis), lambda e: math.inf)
    if place.which == "side" and place.corner is None and slab.taper is None:
        _, uv = slab.local(p)
        normal = slab.lateral(uv, slab.footprint.nearest_curve(uv)[0])
        return None if normal is None else Wall(place, normal, _reach_of(place, p))
    return None


def _reach_of(place, p):
    """How far the face of `place` runs along a unit direction: its length along the axis, the length of its outline
    curve across it, and no limit on an end face."""
    slab = place.slab
    if place.which in ("start", "end"):
        return lambda e: math.inf
    _, uv = slab.local(p)
    curve, _ = slab.footprint.nearest_curve(uv)
    length = curve_length(slab.footprint.curves[curve])
    axis = slab.motion.turn_vector(slab.axis)
    return lambda e: slab.length.n if abs(vec.dot(e, axis)) > 0.9 else length


class CrossPlace:
    """A point on the edge where walls `a` and `b` cross."""

    which = "cross"
    curve = corner = None
    factor = None

    def __init__(self, a, b, quantities):
        self.a, self.b = a, b
        self.slab = a.place.slab
        self.slabs = a.place.slabs + b.place.slabs
        self.blocked = a.place.blocked + b.place.blocked
        self._quantities = quantities

    @property
    def moves(self):
        return any(q.sized for q in self._quantities)

    def quantities(self, p):
        return self._quantities

    def coordinates(self, p):
        return [cleaned(q) for q in self._quantities]


def _plane(wall, p):
    """n . x for the wall's plane as it follows its sizes."""
    return _sum(zip(wall.normal, wall.place.quantities(p)))


def cross(walls, p):
    """The CrossPlace of `p` on the latest two walls (latest first in `walls`) that are not parallel, or None."""
    if len(walls) < 2:
        return None
    a = walls[0]
    for b in walls[1:]:
        if any(s is t for s in a.place.slabs for t in b.place.slabs):
            continue
        edge = vec.cross(a.normal, b.normal)
        sine = vec.length(edge)
        if sine < PARALLEL_SINE:
            continue
        e = vec.scale(edge, 1.0 / sine)
        g = vec.dot(a.normal, b.normal)
        da, db = _plane(a, p), _plane(b, p)
        along = a if a.reach(e) <= b.reach(e) else b
        de = _sum(zip(e, along.place.quantities(p)))
        k = 1.0 / (1.0 - g * g)
        alpha = _sum([(k, da), (-g * k, db)])
        beta = _sum([(k, db), (-g * k, da)])
        out = [_sum([(a.normal[i], alpha), (b.normal[i], beta), (e[i], de)]) for i in range(3)]
        if any(abs(q.n - v) > POINT_TOL for q, v in zip(out, p)):
            continue
        return CrossPlace(a, b, out)
    return None


def wall_of(place, p):
    """The Wall a Place sits on, or None when it is not on exactly one flat face."""
    return None if place is None else _wall(place, p)
