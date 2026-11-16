"""Fillet, chamfer and shell handlers (FilletFeature, ChamferFeature, ShellFeature).

Edges and faces are picked by `near` points taken from the captured edge and face positions (see faces/picks.py). When the
picked faces move with sizes, the pick names the extrude that made them or its points follow the sizes (faces/follow.py).
A step that holds whole Fusion sets picked by faces picks the edges around those faces (`faceEdges`), and one of
whole tangent chain sets picks one point per chain (`chain: tangent`), so edges that a size adds or splits are
still picked.
A chamfer with two distances, or a distance and an angle, says which face takes the first distance (`sizeOn`); the
reader measures it per edge (`sides`, `cut_normals`). What the recipe has no words for is refused: changing radii,
outside or rounded shells.
"""
import math

from ...capture_model import gap_hints, step_kinds
from ...design_model.values import Sized, number, reads_in
from ...geometry import vec
from ...package.numbers import is_number

from .. import values
from ..faces import follow, picks
from ..faces.placer_makers import ShellMaker
from ..ranges import range_check
from ..result import Entry, Refusal, StepResult

SIZE_TOL = 1e-9
ANGLE_TOL = 1e-6
EQUAL_ANGLE_DEG = 45.0
# The chamfer face normal is a mix of the two face normals, weighted by the two distances. It must be that mix within
# SPAN_TOL, and its weights must be within RATIO_SHARE of the distance ratio (in log scale) to name the face.
SPAN_TOL = 0.05
RATIO_SHARE = 0.5
# Of the two faces at each edge, the one that takes the first distance must lean this much more towards sizeOn.
SIZE_ON_MARGIN = 0.1

_FILLET_SET_REFUSALS = {
    "variable": "Rounds with a changing radius are not copied yet.",
    "chordLength": "Rounds set by chord length are not copied yet.",
    "asymmetric": "Rounds with two different radii are not copied yet.",
}


def _close(a, b, tol=SIZE_TOL):
    return abs(a - b) <= tol


def _split_note(ctx, entries):
    if len(entries) > 1:
        ctx.note("The edges are picked in %d steps, since one pick holds at most %d points."
                 % (len(entries), picks.MAX_NEAR_POINTS))


def _flat_edges(sets):
    """Every edge of `sets` with its set index, in order."""
    return [(edge, n) for n, entry in enumerate(sets) for edge in entry.get("edges") or []]


def _unlocated(edges):
    return any(not edge.get("points") for edge in edges)


def _edge_steps(ctx, item, kind, edges, sizes, extra=None, sets=()):
    """`round` or `bevel` steps over `edges` as result Entries, one per group of edges that fits a pick. `sizes` is one
    size Quantity per point of the edges, in order; steps with mixed sizes carry `edgeSizes`. `extra` holds more fields
    of every step (the second measure of a chamfer). `sets` are the capture sets the edges come from."""
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
    found = [entry for entry in sets if any(id(edge) in wanted for edge in entry.get("edges") or [])]
    held = {id(edge) for entry in found for edge in entry.get("edges") or []}
    return found if found and held == wanted else None


def _input_pick(ctx, item, edges, sets):
    """The edge selector that picks `edges` the way Fusion picked them, or None when one point per edge is needed:
    the edges around the faces of sets picked by faces, or the tangent chains of the picked edges of tangent chain
    sets."""
    found = _whole_sets(edges, sets)
    if found is None:
        return None
    if all(entry.get("input_kinds") == ["face"] and entry.get("faces") for entry in found):
        faces = [face for entry in found for face in entry["faces"]]
        if len(faces) <= picks.MAX_NEAR_POINTS:
            return {"faceEdges": follow.faces(ctx, item, faces)}
        return None
    if all(entry.get("input_kinds") == ["edge"] and entry.get("tangent_chain") for entry in found):
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
        sources = (other.get("data") or {}).get("sources") or []
        spec = step_kinds.step_type(other.get("type"))
        repeats = spec is not None and spec.repeats_sources
        if later and repeats and source_index in sources and item.get("index") not in sources:
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


def fillet(item, ctx):
    data = item.get("data") or {}
    sets = data.get("sets") or []
    if not sets:
        return Refusal("This round has no edges to copy.")
    for entry in sets:
        kind = entry.get("kind")
        if kind != "constant":
            return Refusal(_FILLET_SET_REFUSALS.get(kind, "This kind of round is not copied yet."),
                           cause=gap_hints.ROUND_KIND if kind in _FILLET_SET_REFUSALS else None)
        if "feature" in (entry.get("input_kinds") or []):
            return Refusal("A round that follows another step's edges is not copied yet.")
        if entry.get("continuity") == "curvature":
            return Refusal("Rounds with curvature continuity are not copied yet.")
        radius = entry.get("radius")
        if not isinstance(radius, (int, float)) or not radius > 0:
            return Refusal("This round has no readable radius.")
    sizes = {n: values.quantity(ctx, item, "sets.%d.radius" % n, entry["radius"], absolute=True)
             for n, entry in enumerate(sets)}
    pairs = [(edge, sizes[n]) for edge, n in _flat_edges(sets)]
    if not pairs or _unlocated([edge for edge, _ in pairs]):
        return Refusal("The edges of this round could not be located.")
    if any(entry.get("continuity") == "other" for entry in sets):
        ctx.note("The smoothness of this round could not be read; a tangent round was used.")
    if data.get("rolling_ball") is False:
        ctx.note("Fusion used setback corners for this round. The copy uses rolling ball corners, so corners where "
                 "three or more rounded edges meet can look different.")
    sizes = [size for edge, size in pairs for _ in edge["points"]]
    if len(sets) == 1:
        folded = _slot_outline(ctx, item, [edge for edge, _ in pairs], sizes[0])
        if folded is not None:
            return _fold_into_slot(ctx, item, folded)
    entries = _edge_steps(ctx, item, "round", [edge for edge, _ in pairs], sizes, sets=sets)
    _split_note(ctx, entries)
    return StepResult(entries)


def _chamfer_measures(entry):
    """(size, second) of a chamfer set: `second` is None for an even chamfer, else ("otherSize", distance) or
    ("cutAngleDeg", angle). A Refusal when a value cannot be read."""
    kind = entry.get("kind")
    distance = entry.get("distance")
    second = None
    if kind == "twoDistances":
        other = entry.get("distance_two")
        if not is_number(other) or not other > 0:
            return Refusal("This chamfer has no readable size.")
        if not _close(distance, other):
            second = ("otherSize", other)
    elif kind == "distanceAngle":
        angle = entry.get("angle_deg")
        if not is_number(angle) or not 0 < angle < 90:
            return Refusal("This chamfer has no readable angle.")
        if not _close(angle, EQUAL_ANGLE_DEG, ANGLE_TOL):
            second = ("cutAngleDeg", angle)
    elif kind != "equal":
        return Refusal("This kind of chamfer is not copied yet.")
    if not is_number(distance) or not distance > 0:
        return Refusal("This chamfer has no readable size.")
    return distance, second


def _first_face(sides, cut, ratio):
    """The outward normals (first, other) at one edge point: `first` is the face that takes the first distance.
    None when the chamfer face does not tell.

    `sides` are the normals of the edge's two faces, `cut` the normal of the chamfer face there, `ratio` the first
    distance over the second. The chamfer face normal is a * A + b * B with a / b the ratio of the distances on A and B.
    """
    a_n, b_n = [vec.unit(v) for v in sides]
    g = vec.dot(a_n, b_n)
    if abs(1.0 - g * g) < 1e-9:
        return None
    c = vec.unit(cut)
    ca, cb = vec.dot(c, a_n), vec.dot(c, b_n)
    a, b = (ca - g * cb) / (1 - g * g), (cb - g * ca) / (1 - g * g)
    if a <= 0 or b <= 0 or vec.length(vec.sub(c, vec.add(vec.scale(a_n, a), vec.scale(b_n, b)))) > SPAN_TOL:
        return None
    measured, wanted = math.log(a / b), math.log(ratio)
    if abs(measured - wanted) <= RATIO_SHARE * abs(wanted):
        return a_n, b_n
    if abs(measured + wanted) <= RATIO_SHARE * abs(wanted):
        return b_n, a_n
    return None


def _edge_leans(edge, ratio):
    """One (first - other) normal difference per point of an uneven chamfer edge, or None when not measured."""
    sides, cuts = edge.get("sides"), edge.get("cut_normals")
    points = edge.get("points") or []
    if not isinstance(sides, list) or not isinstance(cuts, list) or len(sides) != len(points) or len(cuts) != len(points):
        return None
    leans = []
    for pair, cut in zip(sides, cuts):
        if not isinstance(pair, list) or len(pair) != 2 or cut is None:
            return None
        found = _first_face(pair, cut, ratio)
        if found is None:
            return None
        leans.append(vec.sub(found[0], found[1]))
    return leans


def _size_on(leans):
    """The direction that picks the first face at every point, or None when one direction cannot do it."""
    total = [0.0, 0.0, 0.0]
    for lean in leans:
        total = vec.add(total, lean)
    if vec.length(total) < 1e-9:
        return None
    direction = vec.unit(total)
    if any(vec.dot(lean, direction) < SIZE_ON_MARGIN for lean in leans):
        return None
    return [round(c, 9) + 0.0 for c in direction]


def _uneven_groups(edges, ratio):
    """Edges of an uneven chamfer split into [(sizeOn, edges)], or a Refusal when a side cannot be told."""
    groups = []
    for edge in edges:
        leans = _edge_leans(edge, ratio)
        if leans is None:
            return Refusal("The chamfer has two different sizes, and the face each size is on could not be read.")
        for group in groups:
            size_on = _size_on(group["leans"] + leans)
            if size_on is not None:
                group.update(size_on=size_on, leans=group["leans"] + leans)
                group["edges"].append(edge)
                break
        else:
            size_on = _size_on(leans)
            if size_on is None:
                return Refusal("The chamfer has two different sizes, and the face each size is on could not be read.")
            groups.append({"size_on": size_on, "leans": leans, "edges": [edge]})
    return [(g["size_on"], g["edges"]) for g in groups]


def _second_ratio(size, second):
    """The first distance over the second on a square edge."""
    key, value = second
    if key == "otherSize":
        return size / value
    return 1.0 / math.tan(math.radians(value))


def chamfer(item, ctx):
    data = item.get("data") or {}
    sets = data.get("sets") or []
    if not sets:
        return Refusal("This chamfer has no edges to copy.")
    groups = []
    for n, entry in enumerate(sets):
        measures = _chamfer_measures(entry)
        if isinstance(measures, Refusal):
            return measures
        raw, second = measures
        size = values.quantity(ctx, item, "sets.%d.distance" % n, raw, absolute=True)
        if "feature" in (entry.get("input_kinds") or []):
            return Refusal("A chamfer that follows another step's edges is not copied yet.")
        edges = list(entry.get("edges") or [])
        if _unlocated(edges):
            return Refusal("The edges of this chamfer could not be located.")
        if second is None:
            if entry.get("kind") != "equal":
                for path in ("distance_two", "angle_deg"):
                    values.pin(ctx, item, "sets.%d.%s" % (n, path), "the chamfer in %s is even only while it stays"
                               % item.get("name", "a step"))
            parts = [(None, edges)]
            extra = {}
        else:
            parts = _uneven_groups(edges, _second_ratio(raw, second))
            if isinstance(parts, Refusal):
                return parts
            path, dim = ("distance_two", "length") if second[0] == "otherSize" else ("angle_deg", "angle")
            measure = values.quantity(ctx, item, "sets.%d.%s" % (n, path), second[1], dim=dim, absolute=True)
            if dim == "angle":
                measure = values.stays_below(ctx, item, measure, 90.0, "the chamfer angle in %s would reach 90 degrees"
                                             % item.get("name", "a step"))
            extra = {second[0]: measure}
        for size_on, part in parts:
            for group in groups:
                if group["size"].same_as(size) and group["size_on"] == size_on and _same_extra(group["extra"], extra):
                    group["edges"] += part
                    break
            else:
                groups.append({"size": size, "size_on": size_on, "extra": extra, "edges": list(part)})
    groups = [g for g in groups if g["edges"]]
    if not groups:
        return Refusal("This chamfer has no edges to copy.")
    if data.get("corner_type", "chamfer") != "chamfer":
        ctx.note("Fusion used another corner type for this chamfer; the copy uses the default one.")
    if len(groups) > 1:
        ctx.note("Chamfers of different sizes are applied one after the other.")
    entries = []
    for group in groups:
        sizes = [group["size"]] * sum(len(edge["points"]) for edge in group["edges"])
        extra = {key: q.json() for key, q in group["extra"].items()}
        if group["size_on"] is not None:
            extra["sizeOn"] = group["size_on"]
        entries += _edge_steps(ctx, item, "bevel", group["edges"], sizes, extra, sets)
    _split_note(ctx, entries)
    return StepResult(entries)


def _same_extra(a, b):
    return a.keys() == b.keys() and all(a[k].same_as(b[k]) for k in a)


def shell(item, ctx):
    data = item.get("data") or {}
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
