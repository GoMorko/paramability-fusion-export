"""Picks and reaches that follow sizes.

Rounds, chamfers and shells pick edges and faces by points measured in Fusion, and an extrude can reach to a face or
start from one. When an earlier extrude's length follows a size, the faces it made move with that size, so a fixed
point would pick another face once the size changes.

Every extrude step is kept as a `Slab`: its placement, its profile and its length. A point that lies on an end face
of a slab, or on a side edge at a profile corner, is placed against it. When that place moves with a size, the pick
names the extrude (`featureFace`, `featureEdges`) or its coordinates become formulas of the length. A point that no
slab places may sit on geometry that moves, so the sizes of the steps written before it become fixed numbers.

A pattern or mirror copy of an extrude is a slab too, with the `Motion` that carries the original to the copy. A
point on a copy is placed on the original and moved back: its coordinates follow the length and the spacing.

A point on the inner wall of a shell is placed through the outer wall it was moved from (shells.py). An edge where
the walls of two steps cross is placed on both walls (crossings.py).
"""
from . import crossings, notes, picks, shells, sketch_motion, vec
from .slabs import (AXIAL_TOL, CONSTANT_TOL, FACTOR_DIGITS, IDENTITY_ROWS, LATERAL_TOL, Motion, Place, Slab,
                    as_quantity, cleaned_all)
from .values import Quantity

__all__ = ["AXIAL_TOL", "CONSTANT_TOL", "FACTOR_DIGITS", "IDENTITY_ROWS", "LATERAL_TOL", "Motion", "Place", "Slab",
           "as_quantity", "cleaned_all"]


def _latest_first(ctx):
    """The slabs and shells written so far, the latest first."""
    shells_left = sorted(ctx.shells, key=lambda s: -s.at)
    for n in range(len(ctx.slabs) - 1, -1, -1):
        while shells_left and shells_left[0].at > n:
            yield shells_left.pop(0)
        yield ctx.slabs[n]
    yield from shells_left


def _on_one_face(found):
    """True for a Place inside one face (not on an outline): an edge there comes from another step's wall."""
    if isinstance(found, shells.InnerPlace):
        return found.single is not None
    return found.which in ("start", "end") and found.curve is None


def _walls(ctx, p):
    """The flat walls through `p`, the latest first: at most one per slab or shell."""
    out = []
    for placer in _latest_first(ctx):
        wall = crossings.wall_of(placer.place(p, False), p)
        if wall is not None:
            out.append(wall)
    return out


def locate(ctx, p, edge=False):
    """The Place of a measured point on the latest slab or shell that has it, or None.

    An edge that lies inside a face of the latest step that has the point, or on no step's edge at all, is placed
    where the walls of two steps cross when it can be.
    """
    found = None
    for placer in _latest_first(ctx):
        found = placer.place(p, edge)
        if found is not None:
            break
    if edge and (found is None or _on_one_face(found)):
        crossed = crossings.cross(_walls(ctx, p), p)
        if crossed is not None:
            return crossed
    return found


def inside(ctx, p):
    """True when `p` lies in or on the part built so far: in or on an added slab, and not in or on a later cut or
    hollow."""
    held = False
    for placer in reversed(list(_latest_first(ctx))):
        if isinstance(placer, shells.Shell):
            held = held and not placer.hollows(p)
        elif placer.combine in ("new", "add"):
            held = held or placer.holds(p)
        elif placer.combine == "cut" and placer.holds(p):
            held = False
    return held


def _name(item):
    return item.get("name", "a step")


def _keep_copies(ctx, item, found):
    """A pick on a copy of a pattern needs that copy: the sizes that count or turn the copies stay. A pick on a
    tapered outline needs the taper. A point the moving outline of its sketch cannot carry needs that outline to stay."""
    for slab in found.slabs:
        motion = slab.motion
        if motion.needs:
            ctx.fix(motion.needs, "%s picks a copy made by %s, so its copies must stay as they are"
                    % (_name(item), motion.by or "a pattern"))
    for names in found.fixes:
        ctx.fix(names, "%s picks an edge of a tapered wall, and a change of taper would move it" % _name(item))
    for stuck in found.blocked:
        why = (notes.bends_reason(_name(item), stuck.sketch) if stuck.cause == sketch_motion.BENDS
               else notes.stuck_reason(stuck.cause, stuck.sketch))
        ctx.fix(sketch_motion.movers(ctx.table, stuck), why)


def follow_points(ctx, item, points, edge=True, what="edges"):
    """Points as positions that follow sizes; None when a point cannot be placed (its sizes are then fixed)."""
    out = []
    for p in points:
        found = locate(ctx, p, edge)
        if found is None:
            ctx.fix(ctx.written_reads, "the %s that %s picks may move with it, and the copy cannot follow them"
                    % (what, _name(item)))
            return None
        _keep_copies(ctx, item, found)
        out.append(found.coordinates(p) if found.moves else p)
    return out


def edges_near(ctx, item, edge_list):
    """`{ near }` for a group of capture edges, with points that follow sizes where they move."""
    points = picks.near_points(edge_list)
    if not ctx.written_reads:
        return {"near": points}
    followed = follow_points(ctx, item, points, True, "edges")
    return {"near": followed if followed is not None else points}


def whole_edges(ctx, edge_list):
    """`{ featureEdges, which }` when the edges are exactly the side edges, or the edges of a moving end face, of one
    extrude step whose length follows a size; else None."""
    if not ctx.written_reads or not edge_list:
        return None
    keys, first = [], None
    for edge in edge_list:
        found = [locate(ctx, p, True) for p in edge.get("points") or []]
        if not found or any(f is None for f in found):
            return None
        first = first or found[0]
        if first.slab.is_copy or any(f.slab is not first.slab or f.which != first.which for f in found):
            return None
        edge_keys = {f.corner if f.which == "side" else f.curve for f in found}
        if len(edge_keys) != 1 or None in edge_keys:
            return None
        keys.append(edge_keys.pop())
    slab = first.slab
    wanted = len(slab.footprint.corners) if first.which == "side" else len(slab.footprint.curves)
    if not first.moves or len(set(keys)) != len(keys) or len(keys) != wanted:
        return None
    return {"featureEdges": slab.id, "which": "sides" if first.which == "side" else first.which}


def faces(ctx, item, face_list):
    """The selector for faces a shell opens: `featureFace` for one moving end face, else `{ near }`."""
    points = picks.face_points(face_list)
    if not ctx.written_reads:
        return {"near": points}
    if len(points) == 1:
        found = locate(ctx, points[0])
        if found is not None and found.moves and found.which in ("start", "end") and not found.slab.is_copy:
            return {"featureFace": found.slab.id, "which": found.which}
    followed = follow_points(ctx, item, points, False, "faces")
    return {"near": followed if followed is not None else points}


def target_shift(ctx, item, target, direction, what="reaches to"):
    """How a face an extrude starts from or reaches to moves along unit `direction`: a Quantity whose formula gives
    the face's offset and whose number is that offset at the measured sizes (plain zero when it does not move); None
    when it cannot follow (its sizes are then fixed). `what` words the reason.

    A construction plane stays where it is (a size that moves it is fixed with the sketches). A face is placed by
    its `face_point`.
    """
    zero = Quantity(0.0)
    if not ctx.written_reads or target.get("entity_type") == "ConstructionPlane":
        return zero
    point = target.get("face_point")
    found = locate(ctx, point) if point else None
    if isinstance(found, shells.InnerPlace) and (found.single is None or abs(vec.dot(found.single, direction)) < 1 - 1e-9):
        found = None
    if found is None or found.which == "side":
        ctx.fix(ctx.written_reads, "%s %s a face that may move with it, and the copy cannot follow that"
                % (_name(item), what))
        return None
    if not found.moves:
        return zero
    _keep_copies(ctx, item, found)
    slab = found.slab
    if found.which in ("start", "end") and not slab.is_copy and not any(q.sized for q in slab.origin):
        return slab.length.scaled(found.factor * vec.dot(slab.axis, direction))
    shift = zero
    for q, p, d in zip(found.quantities(point), point, direction):
        if abs(d) > 1e-9:
            shift = shift.plus(q.plus(-p).scaled(d))
    return shift
