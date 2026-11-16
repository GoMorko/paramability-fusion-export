"""Rounds set by chord length, and rounds whose radius changes along the edge (FilletFeature sets).

Both are written as `round` steps. The reader measures each edge at fixed places along it (`samples`), and after the
step the radius of the round there; `design_model.steps.finish` reads what the samples show.

A chord length set is a plain round. Its radius is chord / (2 sin(a / 2)), where `a` is the angle between the
outward normals of the edge's two faces. The angle must be the same along each edge, and the radius measured on the
round must match. Edges with different angles get their own size (`edgeSizes`). The radius follows the chord length
scaled by a constant only while no size can turn the faces (`design_model.edges.angle_sizes`). Otherwise the radius
is written as its number, and the chord length and the sizes that may turn the faces are marked.

A changing radius is written with `sizeEnd`: the radius changes evenly along the edge from `size` at the end lowest
along x (then y, then z) of the recipe to `sizeEnd` at the other end. The copy is made only for one edge in a step
of its own, with no radii set between the ends, and only when the radii measured at 0, 1/4, 1/2, 3/4 and 1 along the
edge show an even change. Fusion may blend the radius in a smooth curve, and the API does not say how. The measured
radii also tell which end has which radius; the direction of the edge in Fusion does not.
"""
from ...capture_model import gap_hints
from ...design_model import edges as part_edges
from ...design_model.steps import finish as sets_of
from ...design_model.values import Quantity
from ...geometry import rigid
from .. import values
from ..faces import follow
from ..ranges import range_check
from ..result import Refusal

# The app: ends of an edge nearer than this along an axis (mm) count as level there, and the next axis decides.
LEVEL_MM = 1e-6
# Ends further apart than LEVEL_MM but nearer than this along the axis that decides (mm) are too close to tell.
CLEAR_MM = 1e-3
# The curves of edges a changing radius is copied on: along these, the place on the edge and the length along it
# change in step.
EVEN_CURVES = ("Line3D", "Arc3D")
# Digits of the factor between the chord length and the radius.
FACTOR_DIGITS = 9


def _name(item):
    return item.get("name", "a step")


def _optimistic(ctx):
    return bool(getattr(ctx.motion, "optimistic", False))


def _measured(edge):
    return bool(sets_of.samples(edge))


def chord_sizes(ctx, item, one, quantity):
    """One radius `Quantity` per measured point of the edges of the chord length set `one`, or a Refusal."""
    if one.chord is None:
        return Refusal("This round has no readable chord length.")
    found = []
    for edge in one.edges:
        if not _measured(edge):
            return Refusal("The faces of this round could not be measured.")
        angle = sets_of.face_angle(edge)
        if angle is None:
            return Refusal("The faces of this round meet at an angle that changes along the edge, so its radius "
                           "changes too.", cause=gap_hints.ROUND_KIND)
        factor = sets_of.chord_radius(1.0, angle)
        if factor is None:
            return Refusal("The faces of this round run almost flat into each other.")
        factor = round(factor, FACTOR_DIGITS)
        if not sets_of.matches_radius(edge, lambda at: one.chord * factor, ends=False):
            return Refusal("The round Fusion made does not have the radius its chord length gives.")
        found.append((edge, factor))
    turners = set()
    for edge, _ in found:
        turners |= set(part_edges.angle_sizes(ctx.table, ctx.capture, item, edge.get("side_faces") or []))
    if turners:
        values.pin(ctx, item, one.path("chord_length"), "the round in %s is set by its chord length, and the copy "
                   "writes its radius" % _name(item))
        if not _optimistic(ctx):
            ctx.doubt([name for name in ctx.table.ticked if name in turners],
                      "the radius of the round in %s changes with the angle between its faces, which may turn "
                      "with these sizes" % _name(item))
        chord = Quantity(one.chord)
    else:
        chord = one.chord_size(quantity)
    return [chord.scaled(factor) for edge, factor in found for _ in edge.get("points") or []]


def changing(ctx, item, sets, quantity):
    """`(size, sizeEnd or None)` as Quantities of the round of a step with a changing radius set, or a Refusal."""
    if len(sets) != 1:
        return Refusal("A round with a changing radius is copied only when it is the only set of edges in its "
                       "fillet.", cause=gap_hints.ROUND_CHANGING)
    one = sets[0]
    if len(one.edges) != 1:
        return Refusal("A round with a changing radius is copied only on a single edge.",
                       cause=gap_hints.ROUND_CHANGING)
    if one.start is None or one.end is None or one.mid_count is None:
        return Refusal("The radii of this round could not be read.")
    if one.mid_count:
        return Refusal("A round with radii set between the ends of its edge is not copied yet.",
                       cause=gap_hints.ROUND_CHANGING)
    if ctx.outer is not None:
        return Refusal("A round with a changing radius is not copied inside a tool body yet.")
    (edge,) = one.edges
    if edge.get("closed") or edge.get("curve") not in EVEN_CURVES:
        return Refusal("A round with a changing radius is copied only on a straight edge or an arc.",
                       cause=gap_hints.ROUND_CHANGING)
    runs = sets_of.law(edge, one.start, one.end)
    if runs is None:
        if not all(isinstance(s.get("radius"), (int, float)) for s in sets_of.samples(edge)) \
                or len(sets_of.samples(edge)) != 5:
            return Refusal("The radius of this round could not be measured along its edge.")
        return Refusal("The radius of this round does not change evenly along its edge, and the copy can only make "
                       "an even change.", cause=gap_hints.ROUND_KIND)
    start, end = one.end_sizes(quantity)
    if runs == sets_of.LEVEL:
        if start.same_as(end):
            return start, None
        why = "the round in %s has the same radius at both ends now, and the copy cannot tell its ends apart" \
            % _name(item)
        values.pin(ctx, item, one.path("start_radius"), why)
        values.pin(ctx, item, one.path("end_radius"), why)
        return Quantity(one.start), None
    first, last = (start, end) if runs == sets_of.FROM_START else (end, start)
    lowest = _first_end_lowest(ctx, item, edge)
    if lowest is None:
        return Refusal("The two ends of this round are too close along an axis to tell which end has which radius.")
    return (first, last) if lowest else (last, first)


def _ends(ctx, item, edge):
    """The points at the first and last sample of the edge as Quantities that follow sizes where they move."""
    found = sets_of.samples(edge)
    ends = [found[0]["point"], found[-1]["point"]]
    if ctx.written_reads:
        followed = follow.follow_points(ctx, item, ends, True, "edges")
        if followed is not None:
            ends = followed
    return [[follow.as_quantity(v) for v in p] for p in ends]


def _gap(row, a, b):
    """How much further `b` lies than `a` along the recipe axis given by `row` of the move into the recipe."""
    gap = Quantity(0.0)
    for coef, qa, qb in zip(row, a, b):
        if coef:
            gap = gap.plus(qb.plus(qa.scaled(-1)).scaled(coef))
    return gap


def _first_end_lowest(ctx, item, edge):
    """True when the end at the first sample of the edge is the one the app starts the radius from, False for the
    other end, None when they are too close to tell (`end_order`). Sizes that may change the answer are marked."""
    a, b = _ends(ctx, item, edge)

    def span_of(gap):
        return range_check.sweep(ctx.table, gap.text, gap.reads) if gap.sized and ctx.table is not None else None
    lowest, unsure = end_order(rigid.move_for(ctx.capture).rows, a, b, span_of)
    if unsure:
        ctx.doubt(unsure, "the round in %s may swap which end has which radius" % _name(item))
    return lowest


def end_order(rows, a, b, span_of):
    """`(lowest, unsure)` for the ends `a` and `b` of an edge (three Quantities each, in the part's frame) and the
    turn `rows` into the recipe's frame. `lowest` is True when `a` lies lowest along x, then y, then z of the recipe
    (ends nearer than LEVEL_MM along an axis are level there), False when `b` does, None when the axis that decides
    has them nearer than CLEAR_MM. `unsure` are the sizes that may change the answer: those of a level gap that may
    open, and of the deciding gap when it may close. `span_of(gap)` gives the `Span` of a gap that follows sizes over
    the size ranges, or None."""
    unsure = []
    for row in rows:
        gap = _gap(row, a, b)
        span = span_of(gap)
        if abs(gap.n) <= LEVEL_MM:
            if span is not None and (span.failed or span.low is None
                                     or max(abs(span.low), abs(span.high)) > LEVEL_MM):
                unsure += gap.reads
            continue
        if abs(gap.n) < CLEAR_MM:
            return None, unsure
        if span is not None and (span.failed or span.low is None or (span.low < CLEAR_MM and span.high > -CLEAR_MM)):
            unsure += gap.reads
        return gap.n > 0, list(dict.fromkeys(unsure))
    return None, unsure
