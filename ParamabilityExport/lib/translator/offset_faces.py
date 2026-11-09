"""Faces an offsetFaces step moved, for picks that follow sizes (see follow.py).

An offsetFaces step moves each face it picks along the face's normal by its distance. A later point on a moved face
(or on its edge) is the point of the face before the move, shifted by the distance. So the point is moved back,
placed on what made the face before, and its coordinates follow that and the distance.

The side walls around a moved face grow or shrink with it. A point on such a wall sits at a share of the distance
above the outline of the face before the move, so it is placed on that outline and follows the same share of the
distance.
"""
from . import vec
from .footprint import Footprint
from .placer import ADD, CUT, Placer
from .shells import InnerPlace
from .slabs import AXIAL_TOL, FACTOR_DIGITS, LATERAL_TOL, as_quantity


class _WallPlace(InnerPlace):
    """A point on a side wall that the move grew or shrank: it is not on one face of the moved side."""

    @property
    def single(self):
        return None


class MovedFaces(Placer):
    """One offsetFaces step: the capture faces it moved (each with `frame` and `loops`), its distance (a written
    number or formula) and `earlier(p, edge)`, which places a point on the steps written before it."""

    def __init__(self, faces, distance, earlier=None):
        usable = [f for f in faces if isinstance(f, dict) and isinstance(f.get("frame"), dict) and "loops" in f]
        self.faces = [(f["frame"], Footprint(f)) for f in usable]
        self.square = [f.get("sides") != "other" for f in usable]
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
        return False

    def place(self, p, edge):
        """The Place of point `p` on a moved face or on a side wall it grew or shrank, or None."""
        found = self._place_on_face(p, edge)
        return found if found is not None else self._place_on_wall(p, edge)

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
