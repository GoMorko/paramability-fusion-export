"""Fillet, chamfer and shell handlers (FilletFeature, ChamferFeature, ShellFeature).

Edges and faces are picked by `near` points taken from the captured edge and face positions (see faces/picks.py). When the
picked faces move with sizes, the pick names the extrude that made them or its points follow the sizes (faces/follow.py).
A step that holds whole Fusion sets picked by faces picks the edges around those faces (`faceEdges`), and one of
whole tangent chain sets picks one point per chain (`chain: tangent`), so edges that a size adds or splits are
still picked.
A chamfer with two distances, or a distance and an angle, says which face takes the first distance (`sizeOn`); the
reader measures it per edge (`sides`, `cut_normals`). Rounds set by chord length and rounds whose radius changes
along the edge are worked out from what the reader measured along the edges (finishes/measured_rounds.py). What the
recipe has no words for is refused: two radii, curvature continuity, outside or rounded shells.
"""
from ...capture_model import gap_hints
from ...design_model.steps import finish as sets_of
from ...design_model.steps.repeat import repeated_items
from ...design_model.values import Sized, number, reads_in
from ...design_model import words as shared

from .. import values
from ..faces import follow, picks
from ..faces.placer_makers import ShellMaker
from ..ranges import range_check
from ..result import Entry, Refusal, StepResult
from . import measured_rounds

_FILLET_SET_REFUSALS = {
    "asymmetric": "Rounds with two different radii are not copied yet.",
}
# The fillet set kinds the copy writes.
_ROUND_KINDS = (sets_of.CONSTANT, sets_of.CHORD_LENGTH, sets_of.VARIABLE)


def _split_note(ctx, entries):
    if len(entries) > 1:
        ctx.note("The edges are picked in %d steps, since one pick holds at most %d points."
                 % (len(entries), picks.MAX_NEAR_POINTS))


def _edge_steps(ctx, item, kind, edges, sizes, extra=None, sets=()):
    """`round` or `bevel` steps over `edges` as result Entries, one per group of edges that fits a pick. `sizes` is one
    size Quantity per point of the edges, in order; steps with mixed sizes carry `edgeSizes`. `extra` holds more fields
    of every step (the second measure of a chamfer). `sets` are the sets (`design_model.steps.finish`) the edges come from."""
    extra = extra or {}
    even = all(s.same_as(sizes[0]) for s in sizes)
    whole = follow.whole_edges(ctx, edges) if even else None
    if whole is not None:
        reads = next(p.followed_reads for p in ctx.placers if getattr(p, "id", None) == whole["featureEdges"])
        return [_with_plain(dict({"kind": kind, "edges": whole, "size": sizes[0].json()}, **extra), edges, reads)]
    picked = _input_pick(ctx, item, edges, sets) if even else None
    if picked is not None:
        step = dict({"kind": kind, "edges": picked, "size": sizes[0].json()}, **extra)
        return [_with_plain(step, edges, reads_in(picked), always=True)]
    steps, at = [], 0
    for group in picks.edge_groups(edges):
        count = sum(len(edge["points"]) for edge in group)
        own = sizes[at:at + count]
        at += count
        step = dict({"kind": kind, "edges": follow.edges_near(ctx, item, group), "size": own[0].json()}, **extra)
        if any(not s.same_as(own[0]) for s in own):
            step["edgeSizes"] = [s.json() for s in own]
        steps.append(_with_plain(step, group))
    return steps


def _with_plain(step, edges, reads=None, always=False):
    """The Entry of the step: with a pick that follows sizes it hands the measured points over, for patterns and
    mirrors that copy it. `reads` are the sizes the pick follows (default: those its points read). `always` hands them
    over for a pick with no point per edge, whose copies need one."""
    reads = reads_in(step["edges"]) if reads is None else reads
    if reads or always:
        written = None if always else step["edges"].get("near")
        return Entry(step, picks={"near": picks.near_points(edges), "reads": reads, "written": written})
    return Entry(step)


def _whole_sets(edges, sets):
    """The sets whose edges are exactly `edges`, or None when the edges hold part of a set or edges of no set."""
    wanted = {id(edge) for edge in edges}
    found = [one for one in sets if any(id(edge) in wanted for edge in one.edges)]
    held = {id(edge) for one in found for edge in one.edges}
    return found if found and held == wanted else None


def _input_pick(ctx, item, edges, sets):
    """The edge selector that picks `edges` the way Fusion picked them, or None when one point per edge is needed:
    the edges around the faces of sets picked by faces, or the tangent chains of the picked edges of tangent chain
    sets."""
    found = _whole_sets(edges, sets)
    if found is None:
        return None
    if all(one.entry.get("input_kinds") == ["face"] and one.entry.get("faces") for one in found):
        faces = [face for one in found for face in one.entry["faces"]]
        if len(faces) <= picks.MAX_NEAR_POINTS:
            return {"faceEdges": follow.faces(ctx, item, faces)}
        return None
    if all(one.entry.get("input_kinds") == ["edge"] and one.entry.get("tangent_chain") for one in found):
        seeds = [edge for edge in edges if edge.get("seed")]
        if seeds and len(picks.near_points(seeds)) <= picks.MAX_NEAR_POINTS:
            return dict(follow.edges_near(ctx, item, seeds), chain="tangent")
    return None


# How far the round may be from half the short side, and how far the sides may cross, at any size setting (mm).
SLOT_TOL = 1e-6


def _formula(value):
    """(formula text, Fusion names it reads) of a written value: a number or a formula."""
    if isinstance(value, Sized):
        return "(%s)" % value["expr"], tuple(value.reads)
    if isinstance(value, dict) and "expr" in value:
        return None, ()
    return "(%r)" % float(value), ()


def _always_equal(ctx, a, b):
    """True when the written values `a` and `b` (numbers or formulas) are equal at every size setting."""
    (ta, ra), (tb, rb) = _formula(a), _formula(b)
    if ta is None or tb is None:
        return False
    reads = tuple(dict.fromkeys(ra + rb))
    if not reads or ctx.table is None:
        return abs(number(a) - number(b)) <= SLOT_TOL
    span = range_check.sweep(ctx.table, "%s - %s" % (ta, tb), reads)
    return not span.failed and span.low is not None and max(abs(span.low), abs(span.high)) <= SLOT_TOL


def _repeated_without(ctx, item, source_index):
    """True when a later pattern or mirror repeats the item at `source_index` but not `item`."""
    later = False
    for other in ctx.capture.get("items") or []:
        if other is item or other.get("index") == item.get("index"):
            later = True
            continue
        sources = repeated_items(other)
        if later and source_index in sources and item.get("index") not in sources:
            return True
    return False


def _slot_outline(ctx, item, edges, size):
    """`(step position, slot loop)` when the round is the round ends of a slot: `edges` are exactly the four side
    edges of an earlier extrude whose outline is a plain rectangle, and the radius is half its short side at every
    size setting (the short sides become half circles). The extrude drawn with that slot outline is the same part
    with no round step, which the CAD kernel builds more reliably than a round that uses up a whole face. Where the
    other side gets shorter than the short one, Fusion cannot make the round either, and the app refuses the slot.
    None when any of this does not hold."""
    found = [follow.locate(ctx, p, True) for edge in edges for p in edge.get("points") or []]
    if not found or any(f is None for f in found):
        return None
    slab = found[0].slab
    corners = {f.corner for f in found}
    if (not isinstance(slab, follow.Slab) or slab.is_copy or any(f.slab is not slab or f.which != "side" for f in found)
            or None in corners
            or len(corners) != 4 or len(edges) != 4 or len(slab.footprint.corners) != 4):
        return None
    at = next((n for n, step in enumerate(ctx.steps) if step.get("id") == slab.id), None)
    step = ctx.steps[at] if at is not None else None
    if step is None or step.get("kind") != "extrude" or "taperDeg" in step or "twistDeg" in step:
        return None
    sketch = step.get("sketch") or {}
    outer = sketch.get("outer") or {}
    if outer.get("kind") != "rect" or sketch.get("inner"):
        return None
    width, height = outer["width"], outer["height"]
    long_, short, turn = (width, height, 0.0) if number(width) >= number(height) else (height, width, 90.0)
    diameter = Sized(expr="2 * %s" % _formula(size.json())[0]) if size.sized else 2.0 * size.n
    if size.sized:
        diameter.n, diameter.reads = 2.0 * size.n, size.reads
    if not _always_equal(ctx, short, diameter):
        return None
    index = next((i for i, ids in ctx._ids_by_index.items() if slab.id in ids), None)
    if index is None or _repeated_without(ctx, item, index):
        return None
    angle = outer.get("angleDeg", 0.0)
    if not isinstance(angle, (int, float)):
        return None
    slot = {"kind": "slot", "center": outer["center"], "length": long_, "width": short}
    if angle + turn:
        slot["angleDeg"] = angle + turn
    return at, slot


def _fold_into_slot(ctx, item, folded):
    """Draw the extrude of `_slot_outline` as that slot and record that this round's item lives in it."""
    at, slot = folded
    step = ctx.steps[at]
    ctx.steps[at] = dict(step, sketch=dict(step["sketch"], outer=slot))
    ctx.folded[item.get("index")] = step["id"]
    ctx.note("The rounded ends of the slot are drawn into the outline of %s." % (step.get("label") or "the cut"))
    return StepResult()


def fillet(ctx, step):
    item, data, sets = step.brought, step.brought_data, step.facts
    if not sets:
        return Refusal(shared.ROUND_NO_EDGES)
    for one in sets:
        if one.kind not in _ROUND_KINDS:
            return Refusal(_FILLET_SET_REFUSALS.get(one.kind, "This kind of round is not copied yet."),
                           cause=gap_hints.ROUND_KIND if one.kind in _FILLET_SET_REFUSALS else None)
        if one.follows_step:
            return Refusal("A round that follows another step's edges is not copied yet.")
        if one.continuity == "curvature":
            return Refusal("Rounds with curvature continuity are not copied yet.")
        if one.kind == sets_of.CONSTANT and one.radius is None:
            return Refusal(shared.ROUND_NO_RADIUS)
    edges = sets_of.edges_of(sets)
    if not edges or any(one.unlocated for one in sets):
        return Refusal("The edges of this round could not be located.")
    quantity = _quantity(ctx, item)
    extra = {}
    if any(one.kind == sets_of.VARIABLE for one in sets):
        found = measured_rounds.changing(ctx, item, sets, quantity)
        if isinstance(found, Refusal):
            return found
        size, size_end = found
        point_sizes = [size] * sets_of.point_count(edges)
        if size_end is not None:
            extra["sizeEnd"] = size_end.json()
    else:
        point_sizes = []
        for one in sets:
            found = (measured_rounds.chord_sizes(ctx, item, one, quantity) if one.kind == sets_of.CHORD_LENGTH
                     else [one.size(quantity)] * sets_of.point_count(one.edges))
            if isinstance(found, Refusal):
                return found
            point_sizes += found
    if any(one.continuity == "other" for one in sets):
        ctx.note("The smoothness of this round could not be read; a tangent round was used.")
    if data.get("rolling_ball") is False:
        ctx.note("Fusion used setback corners for this round. The copy uses rolling ball corners, so corners where "
                 "three or more rounded edges meet can look different.")
    if len(sets) == 1 and sets[0].kind == sets_of.CONSTANT:
        folded = _slot_outline(ctx, item, edges, point_sizes[0])
        if folded is not None:
            return _fold_into_slot(ctx, item, folded)
    # Fusion's own picks (faces, tangent chains) can take in edges at other sizes; only a round of one radius gives
    # them the same size as Fusion does.
    plain = all(one.kind == sets_of.CONSTANT for one in sets)
    entries = _edge_steps(ctx, item, "round", edges, point_sizes, extra, sets=sets if plain else ())
    _split_note(ctx, entries)
    return StepResult(entries)


def _quantity(ctx, item):
    """The `quantity(path, value, dim)` the set readers call: a value that may follow the sizes, kept above zero."""
    def quantity(path, value, dim):
        return values.quantity(ctx, item, path, value, dim=dim, absolute=True)
    return quantity


_CHAMFER_PROBLEMS = {
    sets_of.NO_SIZE: shared.CHAMFER_NO_SIZE,
    sets_of.NO_ANGLE: "This chamfer has no readable angle.",
    sets_of.UNKNOWN_KIND: "This kind of chamfer is not copied yet.",
}
# The recipe key of the second measure of an uneven chamfer.
_SECOND_KEYS = {sets_of.DISTANCE: "otherSize", sets_of.ANGLE: "cutAngleDeg"}


def _chamfer_parts(ctx, item, sets, sides):
    """The edges of the chamfer sets as `sets_of.Part`s, each with its size and second measure as Quantities. `sides`
    is the split of each set by the face of the first distance. A chamfer that is even only while its second value
    stays so pins that value; an angle must stay below 90 degrees."""
    quantity = _quantity(ctx, item)
    name = item.get("name", "a step")
    parts = []
    for one, split in zip(sets, sides):
        size = one.size(quantity)
        extra = {}
        if one.held:
            for field in ("distance_two", "angle_deg"):
                values.pin(ctx, item, one.path(field), "the chamfer in %s is even only while it stays" % name)
        elif one.second:
            measure = one.second.size(quantity)
            if one.second.kind == sets_of.ANGLE:
                measure = values.stays_below(ctx, item, measure, 90.0,
                                             "the chamfer angle in %s would reach 90 degrees" % name)
            extra = {one.second.kind: measure}
        parts += [sets_of.Part(size, direction, extra, edges, [one]) for direction, edges in split]
    return sets_of.merge(parts)


def chamfer(ctx, step):
    item, data, sets = step.brought, step.brought_data, step.facts
    if not sets:
        return Refusal(shared.CHAMFER_NO_EDGES)
    sides = []
    for one in sets:
        if one.problem:
            return Refusal(_CHAMFER_PROBLEMS[one.problem])
        if one.follows_step:
            return Refusal("A chamfer that follows another step's edges is not copied yet.")
        if one.unlocated:
            return Refusal("The edges of this chamfer could not be located.")
        split = one.sides()
        if split is None:
            return Refusal("The chamfer has two different sizes, and the face each size is on could not be read.")
        sides.append(split)
    groups = _chamfer_parts(ctx, item, sets, sides)
    if not groups:
        return Refusal(shared.CHAMFER_NO_EDGES)
    if data.get("corner_type", "chamfer") != "chamfer":
        ctx.note("Fusion used another corner type for this chamfer; the copy uses the default one.")
    if len(groups) > 1:
        ctx.note("Chamfers of different sizes are applied one after the other.")
    entries = []
    for group in groups:
        sizes = [group.size] * sets_of.point_count(group.edges)
        extra = {_SECOND_KEYS[kind]: q.json() for kind, q in group.extra.items()}
        if group.direction is not None:
            extra["sizeOn"] = group.direction
        entries += _edge_steps(ctx, item, "bevel", group.edges, sizes, extra, sets)
    _split_note(ctx, entries)
    return StepResult(entries)


def shell(ctx, step):
    item, data = step.brought, step.brought_data
    if (data.get("outside") or 0) > 0:
        return Refusal("Shells that grow outward are not copied yet.", cause=gap_hints.SHELL_KIND)
    if data.get("bodies_input"):
        return Refusal("Closed hollow shells are not copied yet.", cause=gap_hints.SHELL_KIND)
    if data.get("shell_type", "sharp") != "sharp":
        return Refusal("Shells with rounded corners are not copied yet.")
    thickness = data.get("inside")
    if not isinstance(thickness, (int, float)) or not thickness > 0:
        return Refusal("This shell has no readable wall thickness.")
    faces = data.get("faces") or []
    points = picks.face_points(faces)
    if not points:
        return Refusal("This shell has no open faces to copy.")
    if len(points) > picks.MAX_NEAR_POINTS:
        return Refusal("This shell opens more than %d faces." % picks.MAX_NEAR_POINTS)
    wall = values.quantity(ctx, item, "inside", thickness, absolute=True)
    out = StepResult()
    out.add({"kind": "shell", "thickness": wall.json(), "openFaces": follow.faces(ctx, item, faces)},
            [ShellMaker(wall, faces)])
    return out
