"""Keep where the points of some sketches are, and move them back there later.

A sketch whose dimensions allow two solutions (a distance from a point to a projected point has no side) keeps the
solution it was last solved to: putting the parameter values back does not bring it back once a size try made Fusion
pick the other one. Fusion solves a sketch starting from where its points are, so moving the points back to where they
were, with the values back, lets it solve to the first solution again. The points are moved while the sketch defers
its compute, so it is solved once, from the kept places; the design must then be rebuilt (the caller recomputes).

Only points the sketch owns move: projected or fixed points stay. Nothing here raises; Fusion is reached only through
the design and the native objects. No adsk import at module level.
"""
from . import read_geometry as geo

MOVE_TOL_CM = 1e-7


def _vector(dx, dy, dz):
    import adsk.core
    return adsk.core.Vector3D.create(dx, dy, dz)


def _free_points(sketch):
    """The sketch's own points that may move: not projected, not fixed."""
    return [point for point in geo.collection_items(geo.safe(lambda: sketch.sketchPoints, None))
            if not (geo.safe(lambda: point.isReference, True) or geo.safe(lambda: point.isFixed, True))]


def _token(entity):
    return geo.safe(lambda: entity.entityToken, None)


def _place(point):
    """[x, y, z] of a sketch point in sketch space (cm), or None."""
    at = geo.safe(lambda: point.geometry, None)
    return geo.safe(lambda: [float(at.x), float(at.y), float(at.z)], None)


class SketchKeeper:
    """The points of the sketches `tokens`, as they are when it is made. `put_back` moves them back there."""

    def __init__(self, design, tokens, vector=_vector):
        self.design = design
        self._vector = vector
        self.kept = {}  # sketch token: [(point token, [x, y, z])]
        for token in tokens or ():
            sketch = geo.find_native(design, token)
            if sketch is None:
                continue
            places = [(_token(point), _place(point)) for point in _free_points(sketch)]
            self.kept[token] = [(point, at) for point, at in places if point and at is not None]

    def _point(self, by_token, token):
        """The sketch point kept as `token`: by the token it reads now, else the one Fusion finds for it (a token can
        change while its entity stays), else None when the point is gone."""
        found = by_token.get(token)
        return found if found is not None else geo.find_native(self.design, token)

    def put_back(self):
        """Move every kept point that left its place back to it. Returns how many points moved. Points are matched by
        their entity token, so a point that is gone is skipped and the others still go back. A sketch whose points
        are all in place is not touched: its compute is deferred only while points move."""
        moved = 0
        for token, places in self.kept.items():
            sketch = geo.find_native(self.design, token)
            if sketch is None:
                continue
            by_token = {_token(point): point for point in _free_points(sketch)}
            moves = []
            for point_token, kept in places:
                point = self._point(by_token, point_token)
                now = _place(point) if point is not None else None
                if now is None:
                    continue
                delta = [k - n for k, n in zip(kept, now)]
                if max(abs(d) for d in delta) > MOVE_TOL_CM:
                    moves.append((point, delta))
            if not moves:
                continue
            geo.safe(lambda: setattr(sketch, "isComputeDeferred", True), None)
            try:
                for point, delta in moves:
                    if geo.safe(lambda: point.move(self._vector(*delta)), False) is not False:
                        moved += 1
            finally:
                geo.safe(lambda: setattr(sketch, "isComputeDeferred", False), None)
        return moved
