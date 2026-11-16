"""A capture to an OrcaSlicer Design tab recipe for one body, with a verdict per timeline item.

The walk keeps the steps that build the exported body: sketches, construction geometry and steps of other bodies are
passed by, and every other step of the body is copied by its handler (`HANDLERS`, gathered from `steps`, `holes` and
the other step modules) or left out with a reason. A left out step changes the shape Orca builds, so the result lists
it; later steps are still copied.

The variables are the sizes of the size table (the parameters ticked in the dialog, and the formulas over them) that
a bound field reads. Each ticked parameter ends in one of: it follows a variable everywhere it is used ("variable"),
in some places only ("partly"), nowhere because Orca cannot follow what it moves ("fixed"), or it is not used by any
copied step ("unused").
"""
from ..capture_model import gap_hints, step_kinds
from ..capture_model.capture import CaptureError, validate_capture
from ..design_model import design, reach, roles
from ..design_model.verdicts import COPIED, LEFT_OUT, SKIPPED, left_out, verdict
from ..design_model import words as shared
from ..orca_recipe.recipe import Recipe
from ..params.size_table import FREE
from .context import Context
from .place import BED_CENTRE, Placement
from .steps import HANDLERS, Skip
from . import causes, finishes, other_components
from .finishes import HANDLERS as FINISH_HANDLERS
from .threads import HANDLERS as THREAD_HANDLERS
from .bodies import HANDLERS as BODY_HANDLERS
from .combine import HANDLERS as COMBINE_HANDLERS
from .place import copy_box
from .repeat import HANDLERS as REPEAT_HANDLERS
from .revolve import HANDLERS as REVOLVE_HANDLERS
from .sweeps import HANDLERS as SWEEP_HANDLERS
from .lofts import HANDLERS as LOFT_HANDLERS
from .holes import HANDLERS as HOLE_HANDLERS
from .tools import Pass

HANDLERS = dict(HANDLERS, **HOLE_HANDLERS, **FINISH_HANDLERS, **THREAD_HANDLERS)
HANDLERS.update(REPEAT_HANDLERS, **COMBINE_HANDLERS, **BODY_HANDLERS, **REVOLVE_HANDLERS,
                **SWEEP_HANDLERS, **LOFT_HANDLERS)

VARIABLE, PARTLY, FIXED, UNUSED = "variable", "partly", "fixed", "unused"
_INTERNAL = ("The Orca copy stopped on an error it did not expect in this step, so the step is left out. The report "
             "holds the error.")
UNUSED_REASON = "No copied step uses it."


class OrcaResult:
    """What a translation made.

    recipe: the `orca_recipe.Recipe`. place: the `place.Placement` (the mesh takes `place.root_to_orca`).
    items: a verdict per timeline item (`design_model.verdicts.verdict`) with `verdict` "copied", "leftOut" or
    "skipped". left_out: a record (`design_model.verdicts.left_out`) per step left out, with its `index` and `cause`.
    parameters: per ticked parameter `{name, variable, outcome, follows, reasons}`. variables: the recipe's variables.
    bound: `{feature, field, formula, reads}` per field that follows variables. notes: plain sentences about the
    copy.
    """

    def __init__(self, recipe, place, items, left_out, parameters, bound, notes):
        self.recipe, self.place = recipe, place
        self.items, self.left_out, self.parameters = items, left_out, parameters
        self.variables = dict(recipe.variables)
        self.bound, self.notes = bound, notes

    @property
    def feature_count(self):
        return len(self.recipe.features)

    def summary(self):
        """The `orca` block of `report.json`."""
        return {
            "features": [{"name": f.name, "type": int(f.type), "expr": dict(f.expr)} for f in self.recipe.features],
            "variables": dict(self.variables),
            "bound": [dict(b) for b in self.bound],
            "parameters": [dict(p) for p in self.parameters],
            "left_out": [dict(g) for g in self.left_out],
            "notes": list(self.notes),
            "modeling_origin": list(self.recipe.modeling_origin),
            "shift": list(self.place.shift),
        }


def _unsupported(item):
    spec = step_kinds.step_type(item.get("type"))
    reason = spec.unsupported if spec is not None and spec.unsupported else shared.unsupported_type(item.get("type"))
    return reason, (spec.gap_cause if spec is not None and spec.gap_cause else gap_hints.UNSUPPORTED)


def _item_sizes(ctx, item):
    """Fusion names of the free sizes a step reads: its own values and the dimensions of the sketches it uses."""
    return reach.step_sizes(ctx.table, ctx.capture, item)


def _walk(ctx):
    def leave_out(step, reason, cause, error=None):
        item = step.item
        ctx.items.append(verdict(item, LEFT_OUT, reason))
        gap = {"index": item.get("index"), **left_out(item, reason, causes.tip(cause)), "cause": cause}
        if error is not None:
            gap["error"] = "%s: %s" % (type(error).__name__, error)
        ctx.left_out.append(gap)
        finishes.note_left_out(ctx, step)
        ctx.doubt(_item_sizes(ctx, item), "%s uses it, and %s is left out of the Orca copy" % (
            item.get("name") or "a step", item.get("name") or "that step"))

    # Before the split that made the part, a step of the body it was split from reads that body's measures
    # (`design.read`).
    for step in design.read(ctx.capture, ctx.table, ctx.motion, cache=ctx.cache):
        item, role, kind = step.item, step.role, step.type
        if role.kind == roles.SUPPRESSED:
            ctx.items.append(verdict(item, SKIPPED, shared.SUPPRESSED))
            continue
        if role.kind == roles.NOT_A_STEP:
            ctx.items.append(verdict(item, SKIPPED))
            continue
        changed = role.changed is True
        if role.kind in (roles.ASSEMBLY, roles.TOOL_ELSEWHERE, roles.OTHER_COMPONENT):
            if changed:
                leave_out(step, "This step changes the part from another component, which is not copied.",
                          gap_hints.CHANGED_FROM_OTHER_COMPONENT)
            else:
                ctx.items.append(verdict(item, SKIPPED, shared.IN_OTHER_COMPONENT))
            continue
        if role.lost:
            leave_out(step, "This step lists another body with the part's name, so the copy cannot tell whether it "
                      "changes the part.", causes.BODY_LOST)
            continue
        if step.has(design.BODIES_UNREAD) and not changed:
            leave_out(step, step.problem(design.BODIES_UNREAD).words, gap_hints.REFUSED)
            continue
        # A body made by a split is built like the body it was split from, up to that split.
        ctx.part.target = role.before
        if role.kind == roles.HELPER and not changed:
            ctx.items.append(verdict(item, SKIPPED, shared.HELPER))
            continue
        if step.has(design.FAILS):
            leave_out(step, step.problem(design.FAILS).words, gap_hints.REFUSED)
            continue
        if step.has(design.UNREAD):
            leave_out(step, step.problem(design.UNREAD).words, gap_hints.REFUSED)
            continue
        handler = HANDLERS.get(kind)
        if handler is None:
            reason, cause = _unsupported(item)
            leave_out(step, reason, cause)
            continue
        start = len(ctx.solid.pieces)
        # A handler may write features, notes, bound fields and doubts before it finds that its step cannot be
        # copied: a step left out, or one that does not change the part, keeps none of them. Bringing in the
        # geometry of other components records doubts and notes too, so it runs inside the checkpoint.
        mark = ctx.checkpoint()
        earlier = {id(f) for f in ctx.features}
        try:
            design.replay(step, ctx)
            brought = step.brought
            made = handler(ctx, brought)
            if made and not isinstance(made, (Skip, Pass)):
                other_components.mark_refs(ctx, brought)
        except Exception as error:  # an error in one step's copy leaves that step out, never the whole output
            ctx.rollback(mark)
            leave_out(step, _INTERNAL, causes.INTERNAL_ERROR, error)
            continue
        if isinstance(made, Skip):
            ctx.rollback(mark)
            leave_out(step, made.reason, made.cause)
            continue
        if isinstance(made, Pass):
            ctx.rollback(mark)
            ctx.items.append(verdict(item, SKIPPED, made.note))
            continue
        note = _copied_note(ctx, made, earlier)
        ctx.written[item.get("index")] = list(made)
        ctx.shapes[item.get("index")] = ctx.solid.pieces[start:]
        if not made:
            ctx.items.append(verdict(item, SKIPPED, "This step changes no shape."))
            continue
        ctx.items.append(verdict(item, COPIED, note))


def _copied_note(ctx, made, earlier):
    """The note of a copied step: how many features it wrote, and which features of earlier steps it changed (a
    round drawn into the outline of an extrude changes the extrude's sketch). `earlier` holds the ids of the
    features in the recipe before the step."""
    writers = {}
    for index in sorted(ctx.written):
        for f in ctx.written[index]:
            writers.setdefault(id(f), index)
    own = [f for f in made if id(f) not in earlier]
    changed = [f for f in made if id(f) in earlier]
    parts = []
    if own:
        parts.append("Copied as %d Orca %s." % (len(own), "feature" if len(own) == 1 else "features"))
    if changed:
        steps = {}
        for f in changed:
            steps.setdefault(writers.get(id(f)), []).append(f.name)
        names = {i.get("index"): i.get("name") or "a step" for i in ctx.capture["items"]}
        parts.append("%s by changing %s." % (
            "Also copied" if own else "Copied",
            "; ".join("%s (from %s)" % (", ".join(found), names.get(index, "an earlier step"))
                      for index, found in steps.items())))
    return " ".join(parts)


def _parameters(ctx, variables):
    """The outcome of each ticked parameter, in table order."""
    out = []
    if ctx.table is None:
        return out
    for e in ctx.table.entries:
        if e.state != FREE:
            continue
        follows = list(ctx.follows.get(e.name) or [])
        reasons = list(ctx.doubts.get(e.name) or [])
        name = ctx.names.get(e.size_name)
        if follows and reasons:
            outcome = PARTLY
        elif follows:
            outcome = VARIABLE
        elif reasons:
            outcome = FIXED
        else:
            outcome, reasons = UNUSED, [UNUSED_REASON]
        out.append({"name": e.name, "variable": name if name in variables else None, "outcome": outcome,
                    "follows": follows, "reasons": reasons})
    return out


def translate(capture, size_table=None, bed=BED_CENTRE):
    """`OrcaResult` for a capture. `size_table` is the export's size table (None: every value a number). Raises
    `CaptureError` for a capture the translator cannot read, and for a part whose place in the assembly is not
    known (the plate mesh and the recipe would not meet)."""
    validate_capture(capture)
    placement = capture["target"].get("placement")
    if isinstance(placement, dict) and not isinstance(placement.get("frame"), dict):
        raise CaptureError("The place of the part in the assembly could not be read.")
    place = Placement(capture, bed)
    ctx = Context(capture, size_table, place)
    _walk(ctx)
    # A copy that leaves steps out may be smaller or larger than the Fusion part: it is placed by its own box.
    own = copy_box(ctx)
    if own is not None:
        place = Placement(capture, bed, box=own)
        ctx = Context(capture, size_table, place)
        _walk(ctx)
    recipe = Recipe(features=ctx.features)
    recipe.modeling_origin = place.bed
    recipe.variables = ctx.variables()
    if not ctx.has_body:
        ctx.notes.append("No step that builds the part could be copied, so the Design tab starts empty.")
    result = OrcaResult(recipe, place, ctx.items, ctx.left_out, _parameters(ctx, recipe.variables), ctx.bound,
                        ctx.notes)
    result.copy_box = own  # the box the copy is placed by (capture coordinates); None: the Fusion part's box
    return result
