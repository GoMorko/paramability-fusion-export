"""Faces an offsetFaces step moved, for picks that follow sizes (see follow.py).

An offsetFaces step moves each face it picks along the face's normal by its distance. A later point on a moved face
(or on its edge) is the point of the face before the move, shifted by the distance. So the point is moved back,
placed on what made the face before, and its coordinates follow that and the distance.
"""
from . import vec
from .footprint import Footprint
from .shells import InnerPlace
from .slabs import AXIAL_TOL, LATERAL_TOL, as_quantity


class MovedFaces:
    """One offsetFaces step: the capture faces it moved (each with `frame` and `loops`), its distance (a written
    number or formula) and `earlier(p, edge)`, which places a point on the steps written before it. `at` and `seq`
    order it among the other placers (follow.py)."""

    combine = "offset"

    def __init__(self, faces, distance, earlier, at, seq):
        self.faces = [(f["frame"], Footprint(f)) for f in faces
                      if isinstance(f, dict) and isinstance(f.get("frame"), dict) and "loops" in f]
        self.distance = as_quantity(distance)
        self.earlier = earlier
        self.at, self.seq = at, seq

    def place(self, p, edge):
        """The Place of point `p` on a moved face, or None."""
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
