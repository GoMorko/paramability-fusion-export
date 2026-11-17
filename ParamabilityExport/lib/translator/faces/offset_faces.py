"""Faces an offsetFaces step moved, for picks that follow sizes (see faces/follow.py).

An offsetFaces step moves each face it picks along the face's normal by its distance. A later point on a moved face
(or on its edge) is the point of the face before the move, shifted by the distance. So the point is moved back,
placed on what made the face before, and its coordinates follow that and the distance.

The side walls around a moved face grow or shrink with it. A point on such a wall sits at a share of the distance
above the outline of the face before the move, so it is placed on that outline and follows the same share of the
distance.

A whole round face (a pin or a bore, `Ring`) moves along its outward normal too: its radius changes by the distance,
up for a pin and down for a bore. Its ends lie on flat faces square to its axis that do not move.
"""
import math

from ...geometry import vec
from ...geometry.footprint import Footprint
from .placer import ADD, CUT, Placer
from .shells import InnerPlace
from .slabs import AXIAL_TOL, FACTOR_DIGITS, LATERAL_TOL, as_quantity


class _WallPlace(InnerPlace):
    """A point on a side wall that the move grew or shrank: it is not on one face of the moved side."""

    @property
    def single(self):
        return None


class _RingPlace(InnerPlace):
    """A point on a moved round face: the face is curved, so it has no single flat normal."""

    @property
    def single(self):
        return None


def is_ring(face):
    """True for a round face record with an axis, a radius, a known side and two circle ends."""
    ends = face.get("ends") if isinstance(face, dict) and face.get("kind") == "round" else None
    return (isinstance(ends, list) and len(ends) == 2
            and all(isinstance(e, dict) and e.get("kind") == "circle" for e in ends)
            and all(face.get(k) is not None for k in ("axis", "radius", "outward")))


class Ring:
    """A whole round face (`is_ring`): the axis through the centre of its first end circle, its radius before the move,
    `sign` 1 when it faces away from the axis (a pin or a boss) and -1 when it faces the axis (a bore), and `span`, the
    places of its two end circles along the axis."""

    def __init__(self, face):
        self.axis = vec.unit(face["axis"])
        self.base = list(face["ends"][0]["center"])
        self.span = sorted(vec.dot(vec.sub(end["center"], self.base), self.axis) for end in face["ends"])
        self.radius = face["radius"]
        self.sign = 1.0 if face["outward"] else -1.0

    def moved_radius(self, distance):
        """The radius after a move of `distance` along the outward normal."""
        return self.radius + self.sign * distance

    def local(self, p):
        """(place along the axis, the vector from the axis out to `p`) of a point."""
        rel = vec.sub(p, self.base)
        along = vec.dot(rel, self.axis)
        return along, vec.sub(rel, vec.scale(self.axis, along))

    def middle(self):
        """The point of the axis halfway between the two ends."""
        return vec.add(self.base, vec.scale(self.axis, (self.span[0] + self.span[1]) / 2.0))

    def box(self, radius):
        """The box (low corner, high corner) of the cylinder of `radius` between the two ends."""
        ends = [vec.add(self.base, vec.scale(self.axis, h)) for h in self.span]
        reach = [radius * math.sqrt(max(0.0, 1.0 - a * a)) for a in self.axis]
        return ([min(e[i] for e in ends) - reach[i] for i in range(3)],
                [max(e[i] for e in ends) + reach[i] for i in range(3)])

    def crossings(self, q, n, radii):
        """Parameters t where q + t * n crosses the cylinder of one of `radii` or the plane of an end."""
        out = []
        dz = vec.dot(n, self.axis)
        along, w = self.local(q)
        if abs(dz) > 1e-9:
            out += [(h - along) / dz for h in self.span]
        m = vec.sub(n, vec.scale(self.axis, dz))
        a, b = vec.dot(m, m), 2.0 * vec.dot(w, m)
        if a <= 1e-12:
            return out
        for radius in radii:
            root = b * b - 4.0 * a * (vec.dot(w, w) - radius * radius)
            if root >= 0:
                out += [(-b - math.sqrt(root)) / (2.0 * a), (-b + math.sqrt(root)) / (2.0 * a)]
        return out


class MovedFaces(Placer):
    """One offsetFaces step: the capture faces it moved (each with `frame` and `loops`), its distance (a written
    number or formula) and `earlier(p, edge)`, which places a point on the steps written before it."""

    def __init__(self, faces, distance, earlier=None):
        usable = [f for f in faces if isinstance(f, dict) and isinstance(f.get("frame"), dict) and "loops" in f]
        self.faces = [(f["frame"], Footprint(f)) for f in usable]
        self.square = [f.get("sides") != "other" for f in usable]
        self.rings = [Ring(f) for f in faces if is_ring(f)]
        self.distance = as_quantity(distance)
        self.earlier = earlier

    def material_at(self, p):
        """The material the move added (moved out) or removed (moved in), where `p` lies in it."""
        if not self.swept(p):
            return None
        return ADD if self.distance.n > 0 else CUT

    def crossings(self, q, n, offsets):
        """Parameters t where q + t * n crosses a moved face, before or after the move."""
        out = []
        for frame, _ in self.faces:
            dz = vec.dot(n, frame["z"])
            if abs(dz) > 1e-9:
                for k in (0.0, self.distance.n):
                    out.append((vec.dot(vec.sub(frame["origin"], q), frame["z"]) + k) / dz)
        for ring in self.rings:
            out += ring.crossings(q, n, (ring.radius, ring.moved_radius(self.distance.n)))
        return out

    def swept(self, p):
        """True when `p` lies in or on the material the move added or removed: the prism between the face before and
        after the move."""
        d = self.distance.n
        low, high = min(0.0, d), max(0.0, d)
        for frame, footprint in self.faces:
            local = vec.frame_to_local(frame, p)
            uv = local[:2]
            if low - AXIAL_TOL <= local[2] <= high + AXIAL_TOL and (
                    footprint.covers(uv) or min(footprint.gaps(uv) or [LATERAL_TOL + 1]) <= LATERAL_TOL):
                return True
        for ring in self.rings:
            along, out = ring.local(p)
            radii = sorted((ring.radius, ring.moved_radius(d)))
            if (ring.span[0] - AXIAL_TOL <= along <= ring.span[1] + AXIAL_TOL
                    and radii[0] - LATERAL_TOL <= vec.length(out) <= radii[1] + LATERAL_TOL):
                return True
        return False

    def place(self, p, edge):
        """The Place of point `p` on a moved face or on a side wall it grew or shrank, or None."""
        found = self._place_on_face(p, edge)
        if found is None:
            found = self._place_on_ring(p, edge)
        return found if found is not None else self._place_on_wall(p, edge)

    def _place_on_ring(self, p, edge):
        """A point on a moved round face: moved back along the radius onto the face before the move."""
        d = self.distance.n
        for ring in self.rings:
            along, out = ring.local(p)
            size = vec.length(out)
            if (not ring.span[0] - AXIAL_TOL <= along <= ring.span[1] + AXIAL_TOL or size <= LATERAL_TOL
                    or abs(size - ring.moved_radius(d)) > LATERAL_TOL):
                continue
            normal = vec.scale(out, ring.sign / size)
            back = vec.sub(p, vec.scale(normal, d))
            outer = self.earlier(back, edge)
            if outer is None:
                return None
            return _RingPlace(outer, back, vec.scale(normal, -1.0), self.distance)
        return None

    def _place_on_wall(self, p, edge):
        d = self.distance.n
        for (frame, footprint), square in zip(self.faces, self.square):
            z = vec.unit(frame["z"])
            local = vec.frame_to_local(frame, p)
            height, uv = local[2], local[:2]
            low, high = min(0.0, d), max(0.0, d)
            if not square or abs(height) <= AXIAL_TOL or not low - AXIAL_TOL <= height <= high + AXIAL_TOL:
                continue
            if min(footprint.gaps(uv) or [LATERAL_TOL + 1]) > LATERAL_TOL:
                continue
            if edge and footprint.corner_at(uv, LATERAL_TOL) is None:
                continue
            base = vec.sub(p, vec.scale(z, height))
            outer = self.earlier(base, edge)
            if outer is None:
                return None
            share = round(min(1.0, height / d), FACTOR_DIGITS)
            return _WallPlace(outer, base, vec.scale(z, -1.0), self.distance.scaled(share))
        return None

    def _place_on_face(self, p, edge):
        d = self.distance.n
        for frame, footprint in self.faces:
            z = vec.unit(frame["z"])
            back = vec.sub(p, vec.scale(z, d))
            local = vec.frame_to_local(frame, back)
            if abs(local[2]) > AXIAL_TOL:
                continue
            uv = local[:2]
            if not footprint.covers(uv) and min(footprint.gaps(uv) or [LATERAL_TOL + 1]) > LATERAL_TOL:
                continue
            outer = self.earlier(back, edge)
            if outer is None:
                return None
            return InnerPlace(outer, back, vec.scale(z, -1.0), self.distance)
        return None
