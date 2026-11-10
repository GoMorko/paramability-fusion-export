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

A plane, axis or face of another component (`assembly` records, with their `ref`) is not measured by the capture. Every
size that acts on its component (`foreign_place`) is marked, since the copy keeps it where it is now.

A point on the inner wall of a shell is placed through the outer wall it was moved from (shells.py), and a point on
a face that an offsetFaces step moved through the face before the move (offset_faces.py). An edge where the walls of
two steps cross is placed on both walls (crossings.py).
"""
from ..params import geometry_links
from . import crossings, notes, picks, shells, sketch_motion, vec
from .copy_counts import stays_at_least
from .placer import ADD
from .slabs import (AXIAL_TOL, CONSTANT_TOL, FACTOR_DIGITS, IDENTITY_ROWS, LATERAL_TOL, Motion, Place, Slab,
                    as_quantity, cleaned_all)
from .values import Quantity

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
    where the walls of two steps cross when it can be.
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
    return found


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
    for stuck in found.blocked:
        why = (notes.bends_reason(_name(item), stuck.sketch) if stuck.cause == sketch_motion.BENDS
               else notes.stuck_reason(stuck.cause, stuck.sketch))
        ctx.doubt(sketch_motion.movers(ctx.table, stuck), why)


def follow_points(ctx, item, points, edge=True, what="edges"):
    """Points as positions that follow sizes; None when a point cannot be placed (its sizes are then fixed)."""
    out = []
    for p in points:
        found = locate(ctx, p, edge)
        if found is None:
            ctx.doubt(ctx.written_reads, "the %s that %s picks may move with it, and the copy cannot follow them"
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


_NOUNS = {"ConstructionPlane": "a plane", "ConstructionAxis": "an axis", "BRepFace": "a face", "BRepEdge": "an edge",
          "SketchPoint": "a sketch point", "SketchLine": "a sketch line"}


def _acting(ctx):
    """{ component token: Fusion names of the user parameters that act on it } from the capture's parameter data
    (`geometry_links.acts`), or None when the capture does not say where parameters act (an older capture)."""
    cache = ctx.cache.setdefault("follow", {})
    if "acting" not in cache:
        users = (ctx.capture.get("parameters") or {}).get("user") or []
        found = None
        if any("dependents" in p for p in users):
            found = {}
            for p in users:
                for token, _ in geometry_links.acts(ctx.capture, p).components:
                    found.setdefault(token, []).append(p["name"])
        cache["acting"] = found
    return cache["acting"]


def foreign_ref(ctx, item, ref, what):
    """Marks the sizes that may move the plane, axis, face or point of another component that a step uses (`ref`, the
    measured reference of the capture, see `fusion_reader.placement.ref_record`). The copy keeps that place where it
    is now, so every size that acts on the owning component is doubted. Without data on where sizes act, or without
    the owning component, the step gets a note instead. An origin plane or axis only moves with the occurrence, which
    joints cover, so it marks nothing."""
    if ctx.table is None or ref.get("origin"):
        return
    owner = ref.get("component") or {}
    noun = _NOUNS.get(ref.get("type"), "geometry")
    where = owner.get("name") or "another component"
    acting = _acting(ctx)
    if acting is None or not owner.get("token"):
        ctx.note("%s %s %s of %s, and the sizes that may move it could not be found, so the copy keeps it where it "
                 "is now." % (_name(item), what, noun, where))
        return
    names = [n for n in acting.get(owner["token"], ()) if n in ctx.table.ticked]
    if names:
        ctx.doubt(names, "%s %s %s of %s that may move with it, and the copy cannot follow that"
                  % (_name(item), what, noun, where))


def foreign_place(ctx, item, record, what):
    """`foreign_ref` for a plane, axis or target record of another component (`assembly: true`), else nothing."""
    if record.get("assembly"):
        foreign_ref(ctx, item, record.get("ref") or {}, what)


def foreign_points(ctx, item, data, what="is placed on"):
    """`foreign_ref` once per component and kind of entity among the `position_refs` of a hole."""
    seen = set()
    for ref in data.get("position_refs") or ():
        key = ((ref.get("component") or {}).get("token"), ref.get("type"))
        if key not in seen:
            seen.add(key)
            foreign_ref(ctx, item, ref, what)


def target_shift(ctx, item, target, direction, what="reaches to"):
    """How a face an extrude starts from or reaches to moves along unit `direction`: a Quantity whose formula gives
    the face's offset and whose number is that offset at the measured sizes (plain zero when it does not move); None
    when it cannot follow (its sizes are then fixed). `what` words the reason.

    A construction plane stays where it is (a size that moves it is fixed with the sketches). A face is placed by
    its `face_point`.
    """
    zero = Quantity(0.0)
    if target.get("assembly"):
        foreign_place(ctx, item, target, what)
        return zero
    if not ctx.written_reads or target.get("entity_type") == "ConstructionPlane":
        return zero
    point = target.get("face_point")
    found = locate(ctx, point) if point else None
    if isinstance(found, shells.InnerPlace) and (found.single is None or abs(vec.dot(found.single, direction)) < 1 - 1e-9):
        found = None
    if found is None or found.which == "side":
        ctx.doubt(ctx.written_reads, "%s %s a face that may move with it, and the copy cannot follow that"
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


def _on_part(ref):
    """True when a plane or axis description sits on geometry of the part (a face, an edge, a sketch) or on
    construction geometry built on such. Origin planes and axes, and construction geometry made from parameters
    alone, do not."""
    if ref.get("origin") or ref.get("foreign"):
        return False
    if ref.get("entity_type") in ("ConstructionPlane", "ConstructionAxis"):
        return any(_on_part(entry) for entry in ref.get("built_on") or ())
    return True


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
    parts, definition = ref["built_on"], (ref.get("definition") or "").lower()
    if ref.get("entity_type") == "ConstructionPlane":
        if "offset" in definition and len(parts) == 1 and _is_plane(parts[0]):
            return place_plane(ctx, item, parts[0], direction, what)
        if "midplane" in definition and len(parts) == 2 and all(_is_plane(p) for p in parts):
            shifts = [place_plane(ctx, item, p, direction, what) for p in parts]
            return None if None in shifts else shifts[0].plus(shifts[1]).scaled(0.5)
    elif len(parts) == 1 and parts[0].get("entity_type") in ("BRepEdge", "BRepFace"):
        return place_plane(ctx, item, dict(parts[0], dir=ref.get("dir")), direction, what)
    ctx.doubt(ctx.written_reads, "%s %s a %s built on part geometry that may move with it, and the copy cannot follow "
              "that" % (_name(item), what, "plane" if ref.get("entity_type") == "ConstructionPlane" else "axis"))
    return None


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
        foreign_place(ctx, item, ref, what)
        return zero
    if not ctx.written_reads or ref.get("origin") or ref.get("foreign"):
        return zero
    kind = ref.get("entity_type")
    if ref.get("face_point") is not None or kind == "BRepFace":
        if ref.get("surface") not in (None, "Plane"):
            return _round_face_axis(ctx, item, ref, what)
        found = locate(ctx, ref["face_point"]) if ref.get("face_point") else None
        if found is not None and getattr(found, "which", None) == "side" and not found.moves:
            return zero
        offset = target_shift(ctx, item, {"face_point": ref.get("face_point")}, direction, what)
        return offset.plus(-offset.n) if offset is not None and offset.sized and abs(offset.n) > 1e-9 else offset
    if ref.get("edge_points") or kind == "BRepEdge":
        if not ref.get("edge_points"):
            ctx.doubt(ctx.written_reads, "%s %s an edge that may move with it, and the copy cannot follow that"
                      % (_name(item), what))
            return None
        return _edge_shift(ctx, item, ref["edge_points"], direction, what)
    if kind in ("ConstructionPlane", "ConstructionAxis") and _on_part(ref):
        return _built_shift(ctx, item, ref, direction, what)
    return zero
