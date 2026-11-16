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
from ..capture_model import gap_hints, lineage, step_kinds
from ..capture_model.capture import CaptureError, outside_component, same_body, validate_capture
from ..orca_recipe.recipe import Recipe
from ..params.size_table import FREE
from ..translator.words import type_words
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
    items: a verdict per timeline item, `{index, name, type, verdict, note}` with `verdict` "copied", "leftOut" or
    "skipped". left_out: `{index, name, type, reason, cause}` per step left out. parameters: per ticked parameter
    `{name, variable, outcome, follows, reasons}`. variables: the recipe's variables. bound: `{feature, field,
    formula, reads}` per field that follows variables. notes: plain sentences about the copy.
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


def _verdict(item, verdict, note=""):
    return {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""),
            "verdict": verdict, "note": note}


def _touches(item, target):
    if any(same_body(b, target) for b in item.get("bodies_after") or []):
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    if same_body(data.get("target"), target) or any(same_body(b, target) for b in data.get("bodies") or []):
        return True
    return data.get("operation") != "newBody" and any(same_body(b, target) for b in data.get("participants") or [])


def _unsupported(item):
    spec = step_kinds.step_type(item.get("type"))
    words = type_words(item.get("type") or "")
    reason = spec.unsupported if spec is not None and spec.unsupported else \
        "Steps of type %s are not copied to Orca yet." % words
    return reason, (spec.gap_cause if spec is not None and spec.gap_cause else gap_hints.UNSUPPORTED)


def _item_sizes(ctx, item):
    """Fusion names of the free sizes a step reads: its own values and the dimensions of the sketches it uses."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    names = [p.get("name") for p in (data.get("params") or {}).values() if isinstance(p, dict)]
    profiles = [p for p in data.get("profiles") or [] if isinstance(p, dict)]
    # An outline of another component's sketch names that sketch, which may share its name with one of the part's
    # own: its sizes are the ones its dimensions read.
    sketches = {p.get("sketch") for p in profiles if not _other_sketch(p)} | {data.get("sketch")}
    for p in profiles:
        if _other_sketch(p):
            for param in p.get("sketch_params") or []:
                if isinstance(param, dict):
                    names += [param.get("name")] + list(param.get("reads") or [])
    for m in (ctx.table.model_params.values() if ctx.table is not None else ()):
        made = m.get("created_by") or {}
        if made.get("kind") == "sketchDimension" and made.get("sketch") in sketches:
            names.append(m["name"])
    for record in ctx.capture.get("sketch_graphs") or []:
        if isinstance(record, dict) and record.get("sketch") in sketches:
            names += [d.get("param") for d in record.get("dimensions") or [] if isinstance(d, dict)]
    return ctx.depends([n for n in names if n])


def _other_sketch(profile):
    return profile.get("foreign") is True or bool(profile.get("borrowed"))


def _walk(ctx):
    target = ctx.capture["target"]
    chain = lineage.of(ctx.capture)

    def leave_out(item, reason, cause, error=None):
        ctx.items.append(_verdict(item, "leftOut", reason))
        gap = {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""),
               "reason": reason, "cause": cause}
        if error is not None:
            gap["error"] = "%s: %s" % (type(error).__name__, error)
        ctx.left_out.append(gap)
        finishes.note_left_out(ctx, item)
        ctx.doubt(_item_sizes(ctx, item), "%s uses it, and %s is left out of the Orca copy" % (
            item.get("name") or "a step", item.get("name") or "that step"))

    for item in ctx.capture["items"]:
        kind = item.get("type")
        if item.get("suppressed"):
            ctx.items.append(_verdict(item, "skipped", "Suppressed in Fusion."))
            continue
        if step_kinds.skipped(kind):
            ctx.items.append(_verdict(item, "skipped"))
            continue
        changed = item.get("target_changed") is True
        if step_kinds.is_assembly(kind) or outside_component(item):
            if changed:
                leave_out(item, "This step changes the part from another component, which is not copied yet.",
                          gap_hints.CHANGED_FROM_OTHER_COMPONENT)
            else:
                ctx.items.append(_verdict(item, "skipped", "In another component."))
            continue
        if item.get("bodies_after") is None and not changed:
            leave_out(item, "The bodies this step changes could not be read.", gap_hints.REFUSED)
            continue
        # A body made by a split is built like the body it was split from, up to that split.
        before, after = lineage.at(chain, target, item.get("index"))
        ctx.part.target = before
        if not (_touches(item, before) or _touches(item, after)) and not changed:
            ctx.items.append(_verdict(item, "skipped", "Helper geometry, not part of the exported body."))
            continue
        if item.get("health") == "error":
            leave_out(item, "This step does not build in Fusion.", gap_hints.REFUSED)
            continue
        if (item.get("data") or {}).get("read_error"):
            leave_out(item, "This step could not be read from Fusion.", gap_hints.REFUSED)
            continue
        handler = HANDLERS.get(kind)
        if handler is None:
            reason, cause = _unsupported(item)
            leave_out(item, reason, cause)
            continue
        start = len(ctx.solid.pieces)
        # A handler may write features, notes, bound fields and doubts before it finds that its step cannot be
        # copied: a step left out, or one that does not change the part, keeps none of them. Bringing in the
        # geometry of other components records doubts and notes too, so it runs inside the checkpoint.
        mark = ctx.checkpoint()
        earlier = {id(f) for f in ctx.features}
        try:
            brought = other_components.bring_in(ctx, item)
            made = handler(ctx, brought)
            if made and not isinstance(made, (Skip, Pass)):
                other_components.mark_refs(ctx, brought)
        except Exception as error:  # an error in one step's copy leaves that step out, never the whole output
            ctx.rollback(mark)
            leave_out(item, _INTERNAL, causes.INTERNAL_ERROR, error)
            continue
        if isinstance(made, Skip):
            ctx.rollback(mark)
            leave_out(item, made.reason, made.cause)
            continue
        if isinstance(made, Pass):
            ctx.rollback(mark)
            ctx.items.append(_verdict(item, "skipped", made.note))
            continue
        note = _copied_note(ctx, made, earlier)
        ctx.written[item.get("index")] = list(made)
        ctx.shapes[item.get("index")] = ctx.solid.pieces[start:]
        if not made:
            ctx.items.append(_verdict(item, "skipped", "This step changes no shape."))
            continue
        ctx.items.append(_verdict(item, "copied", note))


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
