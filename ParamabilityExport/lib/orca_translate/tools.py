"""Tool bodies: bodies the copy builds in Orca only to add them to the part, cut them from it or keep what they share.

Orca's body steps (Boolean, Pattern, Mirror) work on whole bodies. So a Combine's tool is written as its own body
from the steps that made it (`build`), and a pattern or mirror of features repeats a body made of the copied steps
of its sources (`of_steps`): the same outlines and ends, the first one starting a new body. A Boolean then adds the
tool to the part, cuts it away or keeps what both share, and Orca drops the tool (`boolean`).

Each tool is a `context.Body`: its features are written while it is the innermost body of the context, so every
handler works on it as it does on the part, and its shape (`solid.Solid`) goes into the part's shape with the
Boolean, so later cuts are still checked against what the copy builds.

Which steps build a tool, and where a tool of another component sits, are facts of the shared layer
(`design_model.tool_chains`). A tool of another component is written in that component's coordinates, as the reader
read its steps, and an Orca Transform then carries it to its place at the Combine.
"""
import copy

from ..capture_model import gap_hints, lineage, tool_items
from ..capture_model.capture import outside_component, same_body
from ..design_model import design, refs, roles, tool_chains
from ..geometry import rigid
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from ..orca_recipe.feature import CadFeature
from ..results.verdicts import COPIED, SKIPPED
from ..design_model.words import type_words
from ..design_model import words as shared
from . import causes, corner_hosts, other_components, outline_cuts
from .context import Body
from .solid import ADD, CUT, INTERSECT
from .steps import Skip

# Tool bodies inside tool bodies, at most.
MAX_DEPTH = 3
SOLID_MODES = {BooleanMode.ADD: ADD, BooleanMode.CUT: CUT, BooleanMode.INTERSECT: INTERSECT}
OPERATIONS = {"join": BooleanMode.ADD, "cut": BooleanMode.CUT, "intersect": BooleanMode.INTERSECT}
# Features that only finish the surfaces of a step: a repeat cannot give them to its copies (`step_mode`).
FINISHES = frozenset((FeatureType.FILLET, FeatureType.CHAMFER))
# The fields of a hole that place it on its plane.
PLACE_FIELDS = ("hole_x", "hole_y")


class Pass:
    """A step that does not change the part (it makes or changes another body): `note` says why, in plain words."""

    def __init__(self, note):
        self.note = note


def label(item):
    return item.get("name") or "the step"


def data_of(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def feature(kind, name, **values):
    """A new feature with the fields Orca sets on every feature it makes."""
    return CadFeature(type=kind, name=name, thread_major_nominal=True, pattern_inclusive=True, **values)


def _handlers():
    from .translate import HANDLERS  # the handler map imports this module
    return HANDLERS


def _why(step, owner):
    """The reason the resolved step `step` (`design.ResolvedStep`) that builds a tool cannot be copied, or None.
    `owner` is the token of the other component whose tool body the step builds ("" for the part's component): such a
    step must have been read in that component's coordinates (`helper_of`)."""
    item = step.item
    if owner and not item.get("helper_of"):
        return "it could not be read from Fusion", gap_hints.REFUSED
    if owner and tool_chains.sketch_by_name_only(item):
        return "its sketch is named only by its name, which a sketch of the part may share", gap_hints.REFUSED
    if owner and lineage.is_split(item):
        # The split rules look for later steps that use its other pieces in the part's component only.
        return "a split in a tool body of another component is not copied to Orca yet", gap_hints.OTHER_COMPONENT
    if not owner and (item.get("helper_of") or outside_component(item)):
        return "it is in another component", gap_hints.OTHER_COMPONENT
    if step.has(design.FAILS):
        return "it does not build in Fusion", gap_hints.REFUSED
    if step.has(design.UNREAD) or item.get("helper_unread"):
        return "it could not be read from Fusion", gap_hints.REFUSED
    if _handlers().get(item.get("type")) is None:
        return "steps of type %s are not copied to Orca yet" % type_words(item.get("type") or ""), \
            gap_hints.UNSUPPORTED
    return None


def _foreign_scope(ctx):
    """The record of the innermost tool body of another component that the walk is inside, else None."""
    return next((b.target for b in reversed(ctx.scopes) if tool_items.is_foreign_tool(b.target)), None)


def _unusable(ctx, record, name):
    """A Skip when the tool `record` cannot be built where it is taken, else its `tool_chains.Place` (None for a
    tool of the part's component)."""
    if not tool_items.is_foreign_tool(record):
        if record.get("foreign"):
            return Skip("The tool body %s is in another component that the export could not name, which is not "
                        "copied to Orca." % name, gap_hints.OTHER_COMPONENT)
        return None
    if _foreign_scope(ctx) is not None:
        return Skip(shared.TOOL_NESTED_ELSEWHERE % name, gap_hints.OTHER_COMPONENT)
    place = tool_chains.place_of(record)
    if place.problem:
        return Skip.of(place.problem)
    return place


# Why a step that the chain of a tool cannot see stops its copy (`tool_chains.unseen_change`).
_UNSEEN_CAUSES = {tool_chains.CHANGED_ELSEWHERE: gap_hints.CHANGED_FROM_OTHER_COMPONENT,
                  tool_chains.NOT_FOLLOWED: causes.BODY_LOST}


def build(ctx, record, anchor):
    """Write the steps that made the body `record` before the item `anchor` as a new Orca body. Returns the
    `context.Body`, or a Skip that names the tool and the step that stops it. The steps are those of the tool's
    chain (`tool_chains.read`); a Combine among them builds its own tools the same way.

    A tool of another component is written in its component's coordinates, as its steps were read, then carried to
    its place at the Combine by an Orca Transform (`tool_chains.place_of`). The sizes that may move that component
    are marked: the copy keeps the tool where it is now."""
    name = tool_chains.name_of(record)
    place = _unusable(ctx, record, name)
    if isinstance(place, Skip):
        return place
    if len(ctx.scopes) > MAX_DEPTH:
        return Skip("The tool body %s is built from tool bodies nested too deep for the Orca copy." % name)
    # The steps read what the reader measured on the tool itself, not on the exported part (`roles.seen_on`).
    exported = any(same_body(record, b) for b in roles.held(ctx.capture["target"], lineage.of(ctx.capture),
                                                               anchor.get("index", 0)))
    holder = record if tool_items.is_foreign_tool(record) else _foreign_scope(ctx)
    found = tool_chains.read(ctx.capture["items"], record, anchor["index"], tool_items.component_token(holder),
                             exported)
    if found.unseen is not None:
        item, why = found.unseen
        return Skip("The tool body %s cannot be copied: %s (%s)." % (name, label(item), _lower(why.rstrip("."))),
                    _UNSEEN_CAUSES.get(why))
    if found.links:
        return Skip("The tool body %s is a piece of a split body, which is not copied to Orca yet." % name,
                    gap_hints.UNSUPPORTED)
    if not found.items:
        return Skip("The steps that build the tool body %s were not found." % name)
    body = ctx.push(Body(record, name, anchor))
    try:
        for item in found.items:
            # Steps of another component are named with it: their names may repeat the part's own.
            seen = dict(item, name="%s of %s" % (label(item), tool_items.component_name(holder))) \
                if found.owner else item
            step = design.resolve(seen, ctx)
            why = _why(step, found.owner)
            made = None
            start = len(body.solid.pieces)
            if why is None:
                design.replay(step, ctx)
                brought = step.brought
                made = _handlers()[item["type"]](ctx, brought)
                if isinstance(made, Skip):
                    why = (made.reason.rstrip("."), made.cause)
                elif made and not isinstance(made, Pass):
                    other_components.mark_refs(ctx, brought)
            if why is not None:
                return Skip("The tool body %s cannot be copied: %s (%s)." % (name, label(item), _lower(why[0])),
                            why[1])
            if not isinstance(made, Pass):
                ctx.written[item["index"]] = list(made)
                ctx.shapes[item["index"]] = body.solid.pieces[start:]
        if place is not None and body.index is not None:
            _carry(ctx, body, place.move, "%s place" % name)
    finally:
        ctx.pop()
    if body.index is None:
        return Skip("No step that builds the tool body %s could be copied." % name)
    if place is not None and place.moves_with is not None:
        refs.mark_all(ctx, anchor, place.moves_with, tool_chains.PLACE_VERB)
    mark_copied(ctx, [item["index"] for item in found.items], "Copied into the tool body %s." % name)
    return body


def _carry(ctx, body, move, name):
    """An Orca Transform that carries the innermost body by the rigid `move` (component coordinates), and its shape
    with it. Orca turns about the pivot, then shifts; the pivot is the component origin."""
    if move.is_identity:
        return
    made = feature(FeatureType.TRANSFORM, name, target_body=body.index)
    made.xf_pivot, made.xf_translate = ctx.place.point([0.0, 0.0, 0.0]), ctx.place.direction(list(move.offset))
    turn = rigid.axis_angle(move.rows)
    if turn is not None:
        made.xf_axis, made.xf_angle_deg = ctx.place.direction(turn[0]), turn[1]
    ctx.add(made)
    body.solid.moved([list(row) for row in move.rows], list(move.offset))


def _lower(text):
    """A reason that goes on inside a sentence: its first word in lower case, unless it is a name (Orca)."""
    return text[:1].lower() + text[1:] if text[1:2].islower() and not text.startswith("Orca") else text


def mark_copied(ctx, indexes, note):
    """Steps that were passed by as building another body, now copied as part of a tool."""
    wanted = set(indexes)
    for verdict in ctx.items:
        if verdict.get("index") in wanted and verdict.get("verdict") == SKIPPED:
            verdict["verdict"], verdict["note"] = COPIED, note


def boolean(ctx, tool, mode, name):
    """Add the tool body to the innermost body, cut it away or keep what both share (`mode`). Orca drops the tool.
    Returns the Boolean feature."""
    part = ctx.scope
    made = feature(FeatureType.BOOLEAN, name, mode=mode, target_body=part.index, bool_tool_body=tool.index,
                   bool_keep_tool=False)
    ctx.add(made)
    ctx.consume(tool)
    part.solid.add(SOLID_MODES[mode], tool.solid.copy())
    return made


# ---- a body made of copied steps -------------------------------------------------------------------------------

def step_mode(ctx, index):
    """The Orca mode a copied step works with (ADD or CUT), or `(reason, cause)` when it cannot be repeated."""
    if index in ctx.reshaped:
        return ctx.reshaped[index], causes.REPEATS_FINISH
    if index in ctx.corner_steps:
        # Corner tools are written with their outline (`of_steps`), so the step goes the way the outline goes.
        modes = {host.mode for host in ctx.corner_steps[index]}
        return modes.pop() if len(modes) == 1 else ("a step that both adds and removes material cannot be repeated",
                                                    causes.NOT_REPEATABLE)
    built = ctx.cut_built.get(index) or []
    modes = {b.mode for b in built}
    owned = {id(f) for b in built for f in b.features}
    for f in ctx.written.get(index) or ():
        if id(f) in owned:
            continue
        if f.type in FINISHES:
            return "a step that rounds or chamfers edges cannot be repeated in Orca yet", causes.REPEATS_FINISH
        if f.type in (FeatureType.EXTRUDE, FeatureType.REVOLVE, FeatureType.SWEEP, FeatureType.LOFT):
            modes.add(f.mode)
        elif f.type in (FeatureType.HOLE, FeatureType.THREAD):
            modes.add(BooleanMode.CUT)
        elif f.type == FeatureType.BOOLEAN:
            modes.add(f.mode)
    if BooleanMode.NEW in modes:
        return "a step that makes a separate body cannot be repeated", causes.NOT_REPEATABLE
    if BooleanMode.INTERSECT in modes:
        return "a step that trims the part to an outline cannot be repeated", causes.NOT_REPEATABLE
    if len(modes) != 1:
        return "a step that both adds and removes material cannot be repeated", causes.NOT_REPEATABLE
    return modes.pop()


def of_steps(ctx, indexes, name):
    """A new Orca body made of the copied steps at `indexes` (timeline order): their extrudes, revolves and holes
    written again on the same sketches (an outline built from plane cuts is built again, `outline_cuts.again`, with
    the corner tools of the repeated rounds, `corner_hosts.for_again`), the first one starting the body, every one
    adding. Returns the Body and the holes among the steps whose place follows variables (the copies keep the place
    they have now, so the caller holds those holes there too, `hold_place`), or a Skip."""
    body = ctx.push(Body(None, name))
    placed = []
    steps = set(indexes)
    try:
        for index in indexes:
            if index in ctx.corner_steps:
                # Its corner tools were written again with the outline they are cut from.
                if not all(host.maker in steps for host in ctx.corner_steps[index]):
                    return Skip("It repeats a round of an outline without the outline.", causes.REPEATS_FINISH)
                continue
            if not corner_hosts.repeats(ctx, index, steps):
                return Skip("It repeats an outline without the rounds or chamfers cut from it, and Orca would put "
                            "back the sharp corners of the original.", causes.REPEATS_FINISH)
            built = ctx.cut_built.get(index) or []
            owned = {id(f): b for b in built for f in b.features}
            for f in ctx.written.get(index) or ():
                if id(f) in owned:
                    if f is owned[id(f)].features[0]:
                        outline_cuts.again(ctx, owned[id(f)], name,
                                           corner_hosts.for_again(ctx, index, owned[id(f)], steps))
                        ctx.has_body = True
                    continue
                if f.type == FeatureType.SKETCH:
                    continue
                if f.type in (FeatureType.EXTRUDE, FeatureType.REVOLVE):
                    _again(ctx, f, name)
                elif f.type == FeatureType.HOLE:
                    if f.hole_style == 2:
                        return Skip("A countersunk hole cannot be repeated in Orca yet.", causes.NOT_REPEATABLE)
                    if any(field in f.expr for field in PLACE_FIELDS):
                        placed.append(f)
                    _bore_again(ctx, f, name)
                else:
                    return Skip("A step it repeats (%s) cannot be repeated in Orca yet." % f.name,
                                causes.NOT_REPEATABLE)
            for _, shape in ctx.shapes.get(index) or ():
                body.solid.add(ADD, shape)
    finally:
        ctx.pop()
    if body.index is None:
        return Skip("It repeats no step the Orca copy holds.")
    return body, placed


def hold_place(ctx, hole, why):
    """Unbind the place of a hole already written (`hole_x`, `hole_y`): it keeps its numbers, and the sizes that
    moved it get `why`. The hole code names that place "<hole> place" where it binds it."""
    held = [e for e in ctx.bound if e["feature"] == hole.name and e["field"] in PLACE_FIELDS]
    for field in PLACE_FIELDS:
        hole.expr.pop(field, None)
    ctx.bound[:] = [e for e in ctx.bound if not any(e is h for h in held)]
    reads = list(dict.fromkeys(n for e in held for n in e["reads"]))
    where = "%s place" % hole.name
    for name in reads:
        found = ctx.follows.get(name)
        if found is not None and where in found:
            found.remove(where)
            if not found:
                del ctx.follows[name]
    ctx.doubt(reads, why)


def _first(ctx):
    return BooleanMode.ADD if ctx.has_body else BooleanMode.NEW


def _bound_like(ctx, source, target):
    """Record the bound fields `target` took over from `source` (same formulas)."""
    for entry in list(ctx.bound):
        if entry["feature"] == source.name:
            ctx.bound.append(dict(entry, feature=target.name))


def _again(ctx, source, name):
    """An extrude or revolve written again on its own sketch, adding to the body being built."""
    made = copy.deepcopy(source)
    made.name = "%s: %s" % (name, source.name)
    made.mode, made.target_body = _first(ctx), -1
    ctx.add(made)
    ctx.has_body = True
    _bound_like(ctx, source, made)


def _bore_again(ctx, hole, name):
    """The material a hole removes, as a cylinder on its plane at its place now (and a wider one for a
    counterbore)."""
    plane = copy.deepcopy(hole.plane)
    plane.origin = tuple(plane.origin[i] + plane.x_axis[i] * hole.hole_x + plane.y_axis[i] * hole.hole_y
                         for i in range(3))
    tools = [("hole_diameter", "hole_depth", not hole.hole_through)]
    if hole.hole_style == 1:
        tools.append(("hole_cbore_diameter", "hole_cbore_depth", True))
    for n, (diameter, depth, blind) in enumerate(tools):
        sketch = feature(FeatureType.SKETCH, "%s: %s sketch%s" % (name, hole.name, " %d" % (n + 1) if n else ""),
                         shape=SketchShape.CIRCLE, plane=plane, radius=getattr(hole, diameter) / 2.0)
        if diameter in hole.expr:
            sketch.expr["radius"] = "(%s) / 2" % hole.expr[diameter]
            _bound_copy(ctx, hole, sketch, diameter, "radius", sketch.expr["radius"])
        at = ctx.add(sketch)
        made = feature(FeatureType.EXTRUDE, "%s: %s%s" % (name, hole.name, " %d" % (n + 1) if n else ""),
                       sketch_ref=at, mode=_first(ctx))
        if blind:
            made.extrude_end, made.distance = ExtrudeEnd.BLIND, getattr(hole, depth)
            if depth in hole.expr:
                made.expr["distance"] = hole.expr[depth]
                _bound_copy(ctx, hole, made, depth, "distance", made.expr["distance"])
        else:
            made.extrude_end = ExtrudeEnd.THROUGH_ALL
        ctx.add(made)
        ctx.has_body = True


def _bound_copy(ctx, source, target, field, to_field, formula):
    for entry in list(ctx.bound):
        if entry["feature"] == source.name and entry["field"] == field:
            ctx.bound.append(dict(entry, feature=target.name, field=to_field, formula=formula))
            return
