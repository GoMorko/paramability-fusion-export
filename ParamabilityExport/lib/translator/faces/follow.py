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

A plane, axis or face of another component (`assembly` records, with their `ref`) moves with the sizes the probe
measured (`ref_motion`): its place is a formula of them, or the sizes that act on its component are marked.

A step inside a tool can reach to a face that is not on the tool. The walk that holds the tool places that face as it
stood at that step (`_beyond_tool`), so the step follows the part although the tool is built on its own.

A point on the inner wall of a shell is placed through the outer wall it was moved from (faces/shells.py), and a point on
a face that an offsetFaces step moved through the face before the move (faces/offset_faces.py). An edge where the walls of
two steps cross is placed on both walls (faces/crossings.py).
"""
from ...geometry import vec
from . import crossings, picks, shells
from .. import notes, ref_motion, values
from ..sketch import sketch_motion
from .copy_counts import stays_at_least
from ..sizes import offset_param, on_part
from .placer import ADD
from .slabs import (
    AXIAL_TOL, CONSTANT_TOL, FACTOR_DIGITS, IDENTITY_ROWS, LATERAL_TOL, Motion, Place, Slab, as_quantity,
    cleaned_all,
)
from ..values import Quantity

__all__ = ["AXIAL_TOL", "CONSTANT_TOL", "FACTOR_DIGITS", "IDENTITY_ROWS", "LATERAL_TOL", "Motion", "Place", "Slab",
           "as_quantity", "cleaned_all"]


def _latest_first(ctx, below=None):
    """The placers written so far (before the placer `below` when given), the latest first."""
    end = len(ctx.placers) if below is None else below.order
    for n in range(end - 1, -1, -1):
        yield ctx.placers[n]


def _on_one_face(found):
    """True for a Place inside one face (not on an outline): an edge there comes from another step's wall."""
    if isinstance(found, shells.InnerPlace):
        return found.single is not None
    return found.which in ("start", "end") and found.curve is None


def _walls(ctx, p, below=None):
    """The flat walls through `p`, the latest first: at most one per slab or shell."""
    out = []
    for placer in _latest_first(ctx, below):
        wall = crossings.wall_of(placer.place(p, False), p)
        if wall is not None:
            out.append(wall)
    return out


def locate(ctx, p, edge=False, below=None):
    """The Place of a measured point on the latest slab or shell that has it (written before `below`), or None.

    An edge that lies inside a face of the latest step that has the point, or on no step's edge at all, is placed
    where the walls of two steps cross when it can be, else inside the one flat side wall it lies on.
    """
    found = None
    for placer in _latest_first(ctx, below):
        found = placer.place(p, edge)
        if found is not None:
            break
    if edge and (found is None or _on_one_face(found)):
        crossed = crossings.cross(_walls(ctx, p, below), p)
        if crossed is not None:
            return crossed
    if edge and found is None:
        found = _on_a_wall(ctx, p, below)
    return found


def _on_a_wall(ctx, p, below=None):
    """The Place of an edge point inside one flat side wall of the latest slab that has it, where no second flat wall
    crosses it (the other face is a round or a curved face): the point follows that wall. None when no slab has it."""
    for placer in _latest_first(ctx, below):
        on_wall = getattr(placer, "place_on_wall", None)
        found = on_wall(p) if on_wall is not None else None
        if found is not None:
            return found
    return None


def inside(ctx, p):
    """True when `p` lies in or on the part built so far: in or on an added slab or the material an offset added, and
    not in or on a later cut, hollow or the material an offset removed."""
    held = False
    for placer in list(ctx.placers):
        material = placer.material_at(p)
        if material is not None:
            held = material == ADD
    return held


def _name(item):
    return item.get("name", "a step")


def _keep_copies(ctx, item, found):
    """A pick on a copy of a pattern needs that copy: a turned copy keeps the sizes that count or turn the copies,
    and a copy in a grid needs its count to stay high enough. A point the moving outline of its sketch cannot carry
    needs that outline to stay."""
    for slab in found.slabs:
        motion = slab.motion
        if motion.needs:
            ctx.doubt(motion.needs, "%s picks a copy made by %s, so its copies must stay as they are"
                      % (_name(item), motion.by or "a pattern"))
        for count, least, by in motion.requires:
            if ctx.table is not None and not stays_at_least(ctx.table, count, least):
                ctx.doubt(count.reads, "%s picks copy %d of %s, and a smaller value would leave that copy out"
                          % (_name(item), least, by or "a pattern"))
    for names, what in getattr(found, "keeps", ()):
        ctx.doubt(names, "%s picks %s, which moves with these sizes, and the copy cannot follow that"
                  % (_name(item), what))
    for stuck in found.blocked:
        why = (notes.bends_reason(_name(item), stuck.sketch) if stuck.cause == sketch_motion.BENDS
               else notes.stuck_reason(stuck.cause, stuck.sketch))
        ctx.doubt(sketch_motion.movers(ctx.table, stuck), why)


def _reads_behind(ctx, p):
    """The sizes that may move a point no step could place: every size read so far, less those that cannot reach it
    when it lies on one tool and on nothing else."""
    for tool in ctx.placers:
        unrelated = tool.not_moved_by(p)
        if unrelated and not any(other is not tool and (other.opaque or other.not_moved_by(p)
                                                        or other.place(p, False) is not None) for other in ctx.placers):
            return tuple(name for name in ctx.written_reads if name not in unrelated)
    return ctx.written_reads


def follow_points(ctx, item, points, edge=True, what="edges"):
    """Points as positions that follow sizes; None when a point cannot be placed (its sizes are then fixed)."""
    out = []
    for p in points:
        found = locate(ctx, p, edge)
        if found is None:
            ctx.doubt(_reads_behind(ctx, p), "the %s that %s picks may move with it, and the copy cannot follow them"
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
    wanted = slab.edge_count(first.which)
    if wanted is None or not first.moves or len(set(keys)) != len(keys) or len(keys) != wanted:
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


# `_beyond_tool` answers this for a reference that lies on the body being walked.
_ON_THIS_BODY = object()


def _held_by_a_walk(ctx, body):
    while ctx is not None:
        if ctx.is_target(body):
            return True
        ctx = ctx.outer
    return False


def reads_with_outer(ctx, item):
    """The sizes read before `item` by this walk and the walks that hold it."""
    if ctx.outer is None:
        return ctx.written_reads
    with ctx.outer.as_of(item):
        return tuple(dict.fromkeys(ctx.written_reads + reads_with_outer(ctx.outer, item)))


def _beyond_tool(ctx, item, ref, points, what, ask, edge=False):
    """How a reference a tool step uses moves, when it is not on the tool; `_ON_THIS_BODY` when it is, or outside a
    tool. `ask(outer)` works it out in the walk that holds the tool, as that walk stood at `item`.

    The body on record says where the reference lies. Without one, a point the tool cannot place is taken to lie
    outside it. A body no walk builds, or a tool in another frame, cannot be followed: every size may move it."""
    outer = ctx.outer
    if outer is None:
        return _ON_THIS_BODY
    body = ref.get("body")
    placed = bool(points) and all(locate(ctx, p, edge) is not None for p in points)
    why = "%s %s a face outside its tool body that may move with it, and the copy cannot follow that" % (_name(item), what)
    same_frame = ctx.component == outer.component
    if not ctx.is_target(body) if body else not placed:
        if not same_frame or (body and not _held_by_a_walk(outer, body)):
            ctx.doubt(ctx.table.ticked if ctx.table is not None else (), why)
            return None
        with outer.as_of(item), outer.recording() as seen:
            found = ask(outer)
        for record in seen.doubts:
            ctx.doubt(record.names, record.why, record.fixed)
        if not body and (found is None or not points):
            ctx.doubt(ctx.written_reads, why)
        return found
    if not body and same_frame:
        # The tool has this point, and the part may have a face there too: either could be the one meant.
        with outer.as_of(item):
            shared = outer.written_reads if any(locate(outer, p, edge) is not None for p in points) else ()
        if shared:
            ctx.doubt(shared, why)
    return _ON_THIS_BODY


def target_shift(ctx, item, target, direction, what="reaches to"):
    """How a face an extrude starts from or reaches to moves along unit `direction`: a Quantity whose formula gives
    the face's offset and whose number is that offset at the measured sizes (plain zero when it does not move); None
    when it cannot follow (its sizes are then fixed). `what` words the reason.

    A construction plane follows what it is built on (`_plane_shift`). A face is placed by its `face_point`.
    """
    zero = Quantity(0.0)
    if target.get("assembly"):
        return ref_motion.plane_shift(ctx, item, target, direction, what)
    if target.get("entity_type") == "ConstructionPlane":
        return _plane_shift(ctx, item, target, direction, what)
    point = target.get("face_point")
    beyond = _beyond_tool(ctx, item, target, [point] if point else [], what,
                          lambda outer: target_shift(outer, item, target, direction, what))
    if beyond is not _ON_THIS_BODY:
        return beyond
    if not ctx.written_reads:
        return zero
    found = locate(ctx, point) if point else None
    if isinstance(found, shells.InnerPlace) and (found.single is None or abs(vec.dot(found.single, direction)) < 1 - 1e-9):
        found = None
    if found is None or found.which == "side":
        names = _reads_behind(ctx, point) if point else ctx.written_reads
        ctx.doubt(names, "%s %s a face that may move with it, and the copy cannot follow that" % (_name(item), what))
        return None
    if not found.moves:
        return zero
    _keep_copies(ctx, item, found)
    slab = found.slab
    if (isinstance(slab, Slab) and found.which in ("start", "end") and not slab.is_copy
            and not any(q.sized for q in slab.origin)):
        return slab.length.scaled(found.factor * vec.dot(slab.axis, direction))
    shift = zero
    for q, p, d in zip(found.quantities(point), point, direction):
        if abs(d) > 1e-9:
            shift = shift.plus(q.plus(-p).scaled(d))
    return shift


def _plane_shift(ctx, item, target, direction, what):
    """How a construction plane an extrude starts from or reaches to moves along unit `direction`. An origin plane,
    or one made from parameters alone, stays: a size behind its own parameters is marked (`sizes.construction_fixes`).
    One built on the part follows what it is built on (`_built_shift`), through a chain of planes. A record that does
    not say what the plane is built on (an older capture) marks the sizes read before the step."""
    if target.get("origin"):
        return Quantity(0.0)
    if "definition" in target or "built_on" in target:
        if on_part(target) or offset_param(ctx.table, target) is not None:
            return _built_shift(ctx, item, target, direction, what)
        return Quantity(0.0)
    reads = reads_with_outer(ctx, item)
    if not reads:
        return Quantity(0.0)
    ctx.doubt(reads, "%s %s a construction plane that may move with it, and this export does not say what the plane "
              "is built on" % (_name(item), what))
    return None


def _is_plane(ref):
    return bool(ref.get("origin")) or ref.get("entity_type") == "ConstructionPlane" or (
        ref.get("entity_type") == "BRepFace" and ref.get("surface") in (None, "Plane"))


def _round_face_axis(ctx, item, ref, what):
    """Zero when the axis of a round face (a cylinder wall of one extrude) stays where it is: the face does not move,
    or only slides along its own axis as the length changes. None (sizes fixed) otherwise."""
    found = locate(ctx, ref["face_point"]) if ref.get("face_point") else None
    if found is not None and not found.moves:
        return Quantity(0.0)
    slab = getattr(found, "slab", None)
    axis = ref.get("dir")
    if (isinstance(found, Place) and found.which == "side" and not slab.is_copy and found.lateral is None
            and not found.blocked and slab.taper is None and not slab.motion.moves
            and not any(q.sized for q in slab.origin) and axis is not None
            and abs(abs(vec.dot(slab.axis, axis)) - 1) < 1e-9):
        return Quantity(0.0)
    ctx.doubt(ctx.written_reads, "%s %s a round face that may move with it, and the copy cannot follow that"
              % (_name(item), what))
    return None


def _edge_shift(ctx, item, points, direction, what):
    found = locate(ctx, points[0], True)
    if found is None:
        ctx.doubt(ctx.written_reads, "%s %s an edge that may move with it, and the copy cannot follow that"
                  % (_name(item), what))
        return None
    if not found.moves:
        return Quantity(0.0)
    _keep_copies(ctx, item, found)
    shift = Quantity(0.0)
    for q, p, d in zip(found.quantities(points[0]), points[0], direction):
        if abs(d) > 1e-9:
            shift = shift.plus(q.plus(-p).scaled(d))
    return shift


def _built_shift(ctx, item, ref, direction, what):
    """The shift of construction geometry built on part geometry: an offset plane moves with its base, a midplane
    with the mean of its two bases, an axis on an edge or round face with that edge or face. Anything else cannot be
    followed."""
    parts, definition = ref.get("built_on") or [], (ref.get("definition") or "").lower()
    if ref.get("entity_type") == "ConstructionPlane":
        if "offset" in definition and len(parts) == 1 and _is_plane(parts[0]):
            base = place_plane(ctx, item, parts[0], direction, what)
            return base if base is None else _own_offset(ctx, item, ref, base, direction, what)
        if "midplane" in definition and len(parts) == 2 and all(_is_plane(p) for p in parts):
            shifts = [place_plane(ctx, item, p, direction, what) for p in parts]
            return None if None in shifts else shifts[0].plus(shifts[1]).scaled(0.5)
    elif len(parts) == 1 and parts[0].get("entity_type") in ("BRepEdge", "BRepFace"):
        return place_plane(ctx, item, dict(parts[0], dir=ref.get("dir")), direction, what)
    ctx.doubt(reads_with_outer(ctx, item), "%s %s a %s built on part geometry that may move with it, and the copy "
              "cannot follow that" % (_name(item), what, "plane" if ref.get("entity_type") == "ConstructionPlane" else "axis"))
    return None


def _base_point(ref):
    """A point of the plane or face an offset plane is built on: the origin for an origin plane."""
    if ref.get("origin"):
        return [0.0, 0.0, 0.0]
    return ref.get("point") or ref.get("face_point")


def _own_offset(ctx, item, ref, shift, direction, what):
    """`shift` (the move of the plane an offset plane is built on) plus the change of the plane's own distance when
    a size sets it (`sizes.offset_param`). The measured distance from the base tells which way a positive distance
    goes; when it does not, the sizes behind the distance are marked and only the base move is followed."""
    param = offset_param(ctx.table, ref)
    if param is None:
        return shift
    plane = ref.get("plane") if isinstance(ref.get("plane"), dict) else ref
    point, normal, base = plane.get("point"), plane.get("normal"), _base_point(ref["built_on"][0])
    distance = param["value"] * 10.0
    measured = vec.dot(vec.sub(point, base), normal) if point and normal and base else None
    sign = None
    if measured is not None and abs(distance) > 1e-9:
        sign = 1.0 if abs(measured - distance) <= 1e-6 else -1.0 if abs(measured + distance) <= 1e-6 else None
    names = [n for n in ctx.table.depends(param["name"]) if n in ctx.table.ticked]
    if sign is None:
        ctx.doubt(names, "%s %s a plane whose distance from its base cannot be read, and the copy cannot follow it"
                  % (_name(item), what))
        return shift
    own = {"index": item.get("index"), "name": item.get("name"),
           "data": {"params": {"plane.offset": {"name": param["name"], "expression": param["expression"],
                                                "value": distance}}}}
    q = values.quantity(ctx, own, "plane.offset", distance)
    if not q.sized:
        return shift
    k = sign * vec.dot(vec.unit(normal), direction)
    # The numbers of both moves go last, so they fold into one.
    core = Quantity(shift.n - shift.const, shift.core, shift.reads) if shift.sized else Quantity(shift.n)
    return core.plus(q.scaled(k)).plus(shift.const - distance * k)


def shifted_origin(origin, normal, shift):
    """A plane origin as the recipe writes it, moved along `normal` by `shift` (`place_plane`): formulas in the
    coordinates the normal has a part in when the shift follows sizes, else `origin` as it is."""
    if shift is None or not shift.sized:
        return origin
    return [shift.scaled(c).plus(o).json() if abs(c) > 1e-9 else o for o, c in zip(origin, normal)]


def place_plane(ctx, item, ref, direction, what="mirrors across"):
    """How a plane or axis moves along unit `direction` as sizes change: a Quantity (plain zero when it stays), or
    None when it may move and cannot be followed (its sizes are then fixed). The Quantity is the move from the
    measured place (its number is zero), not the distance from some base. `ref` is the capture's plane or axis record.
    An axis moves by its offset in each coordinate direction; the part of it along the axis is harmless.

    An origin plane or axis, or a record that says nothing about what it is (an older capture), stays. A face is
    placed like the face an extrude reaches to (`target_shift`). `what` words the reason.
    """
    zero = Quantity(0.0)
    if ref.get("assembly"):
        return ref_motion.shift_along(ctx, item, ref, direction, what)
    if ref.get("origin") or ref.get("foreign"):
        return zero
    kind = ref.get("entity_type")
    on_face = ref.get("face_point") is not None or kind == "BRepFace"
    if on_face or ref.get("edge_points") or kind == "BRepEdge":
        points = [ref["face_point"]] if ref.get("face_point") is not None else ref.get("edge_points") or []
        beyond = _beyond_tool(ctx, item, ref, points, what,
                              lambda outer: place_plane(outer, item, ref, direction, what), not on_face)
        if beyond is not _ON_THIS_BODY:
            return beyond
    if ctx.outer is not None and kind in ("ConstructionPlane", "ConstructionAxis") and on_part(ref):
        return _built_shift(ctx, item, ref, direction, what)
    if offset_param(ctx.table, ref) is not None:
        return _built_shift(ctx, item, ref, direction, what)
    if not ctx.written_reads:
        return zero
    if on_face:
        if ref.get("surface") not in (None, "Plane"):
            return _round_face_axis(ctx, item, ref, what)
        found = locate(ctx, ref["face_point"]) if ref.get("face_point") else None
        if found is not None and getattr(found, "which", None) == "side" and not found.moves:
            return zero
        offset = target_shift(ctx, item, {"face_point": ref.get("face_point"), "body": ref.get("body")}, direction, what)
        return offset.plus(-offset.n) if offset is not None and offset.sized and abs(offset.n) > 1e-9 else offset
    if ref.get("edge_points") or kind == "BRepEdge":
        if not ref.get("edge_points"):
            ctx.doubt(ctx.written_reads, "%s %s an edge that may move with it, and the copy cannot follow that"
                      % (_name(item), what))
            return None
        return _edge_shift(ctx, item, ref["edge_points"], direction, what)
    if kind in ("ConstructionPlane", "ConstructionAxis") and on_part(ref):
        return _built_shift(ctx, item, ref, direction, what)
    return zero
