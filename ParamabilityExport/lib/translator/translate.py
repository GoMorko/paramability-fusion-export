"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
import importlib

from . import borrowed, range_check, step_kinds
from .audit import audit
from .sizes import construction_fixes, joint_reasons, untried_reasons, used_sizes
from . import notes as wording, place
from .notes import dropped_reason, fixed_reason, loose_reason, unmoved_reason, unused_reason
from .capture import outside_component, renamed_target, same_body, validate_capture
from .context import Context
from .result import Refusal, StepResult, TranslateResult, make_verdict
from ..params.expressions import MAX_FORMULA_LENGTH
from .values import Sized, number
from ..probe.motion import Motion, Stuck
from .words import type_words

RECIPE_VERSION = 12
# Edge selector keys newer than RECIPE_VERSION, the same way.
SELECTOR_VERSIONS = {"chain": 14, "faceEdges": 14}
MAX_FEATURES = 400
MAX_NEAR_POINTS = 32
MAX_PATTERN_COPIES = 64
MAX_PASSES = 70



def _resolve(handler):
    """The function a step kind table entry names as "module:function" in this package."""
    module, function = handler.split(":")
    return getattr(importlib.import_module("." + module, __package__), function)


# Capture type -> handler, from the step kind table.
HANDLERS = {t.name: _resolve(t.handler) for t in step_kinds.STEP_TYPES if t.handler}


def _refusal(item, reason, note=None):
    """The refusal record of the result. `note` is the package note when it differs from the usual wording."""
    out = {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""), "reason": reason}
    if note:
        out["note"] = note
    return out


def _label(item):
    return wording.step_label(item.get("name"), item.get("type")) or "A step"


def _foreign(node):
    """A record of the step's data marked `foreign` by the reader: it belongs to another component. Other bodies a
    step lists (participants) and the tool bodies a combine lists are left to their own rules."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            return True
        return any(_foreign(v) for k, v in node.items() if k not in ("participants", "tools"))
    if isinstance(node, list):
        return any(_foreign(v) for v in node)
    return False


def _placement_refusal(capture):
    """A refusal when the part's place in the assembly cannot be used, else None."""
    placement = capture["target"].get("placement")
    if not isinstance(placement, dict):
        return None
    if placement.get("linked"):
        return {"index": None, "name": "", "type": "", "reason": "This part comes from a linked design.",
                "note": wording.linked_part_note()}
    problem = placement.get("error") or (place.frame_problem(placement["frame"]) if "frame" in placement else None)
    if problem:
        return {"index": None, "name": "", "type": "", "reason": "The place of this part in the assembly cannot be used. %s" % problem,
                "note": wording.place_unreadable_note()}
    return None


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _touches_target(item, ctx):
    """The item lists the target among its bodies, or its own data names the target as the body it works on."""
    if any(ctx.is_target(b) for b in item.get("bodies_after") or []):
        return True
    data = _data(item)
    if ctx.is_target(data.get("target")):
        return True
    if data.get("operation") != "newBody":
        return any(ctx.is_target(b) for b in data.get("participants") or [])
    return False


def _existing_bodies(item):
    """Bodies that existed before the item: the reader's `bodies_before`, else the bodies the item's data names."""
    before = item.get("bodies_before")
    if isinstance(before, list):
        return before
    data = _data(item)
    named = list(data.get("participants") or []) + list(data.get("tools") or [])
    if data.get("target"):
        named.append(data["target"])
    return named


def _new_bodies(item, ctx):
    """Bodies the item lists that are not the target and did not exist before it (a split, or a second new body)."""
    existing = _existing_bodies(item)
    return [
        b for b in item.get("bodies_after") or []
        if not ctx.is_target(b) and not any(same_body(b, e) for e in existing)
    ]


def _lost_target(item, ctx):
    bodies = list(item.get("bodies_after") or []) + list(item.get("bodies_before") or [])
    return any(renamed_target(b, ctx.target) for b in bodies)


def _only_splits_faces(item, ctx):
    """A split of faces that the capture shows left the exported body as it was: its solid is the same, only its faces
    are cut up, so nothing is copied."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec is not None and spec.splits_faces and item.get("target_changed") is False
            and not _new_bodies(item, ctx))


def _skip_reason(item):
    if item.get("suppressed"):
        return "Suppressed in Fusion."
    if step_kinds.skipped(item.get("type")):
        return ""
    return None


def _count_part(value):
    """(formula text, Fusion names it reads) of a written count."""
    if isinstance(value, dict):
        return "(%s)" % value["expr"], tuple(getattr(value, "reads", ()))
    return str(value), ()


def _copy_counts(step):
    """(formula, reads) for each count of copies a pattern step makes: the grid (both directions) and the turn."""
    first = _count_part(step.get("linear", {}).get("count", 1))
    second = _count_part(step.get("linear2", {}).get("count", 1))
    return [("%s * %s" % (first[0], second[0]), first[1] + second[1]),
            _count_part(step.get("polar", {}).get("count", 1))]


def _over_caps(recipe, ctx):
    """Return a plain reason when the recipe breaks a reader cap at its current values, else None. A count of copies
    that can pass its cap inside the size ranges marks the sizes it reads (`Context.doubt`)."""
    features = recipe["features"]
    if len(features) > MAX_FEATURES:
        return "The part has more than %d steps." % MAX_FEATURES

    def walk(node):
        if isinstance(node, dict):
            near = node.get("near")
            if isinstance(near, list) and len(near) > MAX_NEAR_POINTS:
                return "A selection has more than %d points." % MAX_NEAR_POINTS
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None

    for step in features:
        found = walk(step)
        if found:
            return found
        if step.get("kind") == "pattern":
            copies = number(step.get("linear", {}).get("count", 1)) * number(step.get("linear2", {}).get("count", 1))
            copies = max(copies, number(step.get("polar", {}).get("count", 1)))
            if copies > MAX_PATTERN_COPIES:
                return "A pattern makes more than %d copies." % MAX_PATTERN_COPIES
            if ctx.table is None:
                continue
            for formula, reads in _copy_counts(step):
                if reads and not range_check.sweep(ctx.table, formula, reads).at_most(MAX_PATTERN_COPIES):
                    ctx.doubt(reads, "%s could make more than %d copies at some sizes"
                              % (step.get("label") or "a pattern", MAX_PATTERN_COPIES))
    return None


def translate(capture, handlers=None, size_table=None, motion=None):
    """Capture dict to TranslateResult. `handlers` maps a feature type to a handler and overrides the table.

    A handler is `handle(item, ctx) -> StepResult | Refusal` (result.py). An empty result means the item makes no step
    on purpose (verdict `skipped`, with the handler's notes). Items after the first refusal are not walked, so `items`
    holds the verdicts up to and including it.

    `size_table` makes the recipe follow Fusion parameters: feature values whose parameters read a size
    are written as formulas, the recipe gets `sizes` and the `sizesAsWritten` marker. A value that cannot follow its
    sizes is written as its number, and the sizes it reads stay free: the shape at the current values is the same and
    the other values still follow them. `result.loose` lists those sizes with the reason; one that no formula reads is
    not a size and is listed in `result.dropped` with the reason (as is every ticked size no step reads). After the walk
    an audit (`audit.py`) marks the sizes a copied step reads that no handler named. The ranges are the table's. A formula too long to copy fixes its sizes (`result.fixed`, as
    `{ name, reason }`).

    The walk runs twice when some value cannot follow. The first walk fixes every size such a value reads, to learn
    which sizes and reasons there are. The second keeps them free.

    `motion` is what the size probe measured about sketch values (`probe.motion.Motion`): sketch points, planes, hole
    points and revolve axes are then written as formulas where they follow sizes. `probe.motion.OPTIMISTIC` writes
    them as numbers without fixing anything for them (the first translation of an export). Without it, no size that
    moves a sketch or construction geometry can be followed.
    """
    validate_capture(capture)
    unplaced = _placement_refusal(capture)
    if unplaced is not None:
        return TranslateResult(refusal=unplaced)
    table = dict(HANDLERS)
    if handlers:
        table.update(handlers)
    cache = {}
    if size_table is None:
        return _walk(capture, table, None, cache=cache)[0]
    upfront = joint_reasons(size_table) if motion is not None else untried_reasons(size_table)
    first = _settle(capture, table, size_table, motion, upfront, False, cache)
    if first.result.recipe is None or not first.whys:
        return _finish(first, {}, capture, motion)
    pinned = _Pinned(motion) if isinstance(motion, Motion) and not motion.optimistic else motion
    found = _settle(capture, table, size_table, pinned, {}, True, cache)
    doubts = dict(upfront)
    for name, why in list(first.whys.items()) + list(found.depends.items()):
        doubts.setdefault(name, why)
    return _finish(found, {name: why for name, why in doubts.items() if name not in found.whys}, capture, motion)


class _Pinned:
    """A motion file where a stuck value follows only the sizes that still move it (`Stuck.rest`, or nothing), as it
    does once its own sizes are fixed. The second walk keeps those sizes free, so the other values still follow them."""
    optimistic = False

    def __init__(self, motion):
        self._motion = motion

    def get(self, key):
        found = self._motion.get(key)
        return found.rest if isinstance(found, Stuck) else found

    def __getattr__(self, name):
        return getattr(self._motion, name)


class _Settled:
    """Where the passes of one walk mode ended: the last walk, its context, the table it used, the fixed sizes with
    why, and what the last walk could not follow (`Context.depends`)."""

    def __init__(self, result, ctx, table, whys, depends):
        self.result, self.ctx, self.table, self.whys, self.depends = result, ctx, table, whys, depends


def _settle(capture, handlers, size_table, motion, fixed, follow, cache):
    """Walk until nothing changes. `fixed` (Fusion name to why) are fixed up front. Without `follow` every size a
    value cannot follow is fixed and the walk runs again; with it only the sizes that must be fixed
    (`Context.must_fix`) are."""
    whys = dict(fixed)
    current = size_table.with_fixed(_reasons(whys)) if whys else size_table
    for _ in range(MAX_PASSES):
        result, ctx = _walk(capture, handlers, current, motion, cache)
        cannot = ctx.must_fix if follow else {**ctx.depends, **ctx.must_fix}
        more = {name: why for name, why in cannot.items() if name not in whys}
        if result.recipe is None or not more:
            break
        whys.update(more)
        current = current.with_fixed(_reasons(more))
    return _Settled(result, ctx, current, whys, ctx.depends)


def _reasons(whys):
    return {name: fixed_reason(name, why) for name, why in whys.items()}


def _finish(settled, doubts, capture, motion):
    """The result of the last walk with its fixed and loose sizes, the ones left out, and the recipe `sizes`.

    `doubts` (Fusion name to why) are sizes kept free that some value cannot follow. The audit adds the sizes a copied
    step reads that no handler named. A doubted size that no formula reads is not a size: it is listed in
    `result.dropped` with its reason, like every other ticked size that the recipe does not hold."""
    result, table, whys = settled.result, settled.table, dict(settled.whys)
    result.fixed = [{"name": name, "reason": fixed_reason(name, why)} for name, why in whys.items()]
    if result.recipe is None:
        result.loose = [{"name": name, "reason": loose_reason(name, why)} for name, why in doubts.items()]
        return result
    checked = audit(capture, settled.ctx, table, set(whys) | set(doubts), motion)
    for name, why in checked.forgotten.items():
        doubts.setdefault(name, why)
    sizes = used_sizes(result.recipe["features"], table.sizes)
    result.loose = [{"name": name, "reason": loose_reason(name, why)} for name, why in doubts.items()
                    if table.size_name(name) in sizes]
    result.dropped = _dropped(table, sizes, doubts, checked.unmoved)
    result.notes.extend(d["reason"] for d in result.dropped)
    result.recipe["sizesAsWritten"] = True
    if sizes:
        result.recipe["sizes"] = sizes
    return result


def _dropped(table, sizes, doubts, unmoved):
    """`{ name, reason, used }` for each ticked size that no written formula reads. `used` is True when a step reads
    it and the copy could not follow it, False when nothing copied depends on it."""
    out = []
    for name in table.ticked:
        if table.size_name(name) in sizes:
            continue
        if name in doubts:
            out.append({"name": name, "reason": dropped_reason(name, doubts[name]), "used": True})
        else:
            reason = unmoved_reason(name) if name in unmoved else unused_reason(name)
            out.append({"name": name, "reason": reason, "used": False})
    return out


def _walk(capture, table, size_table, motion=None, cache=None):
    """One walk over the items: (TranslateResult, Context). `cache` is shared by the walks of one translation."""
    ctx = Context(capture, size_table, motion, cache)
    result = TranslateResult()

    def refuse(item, reason, note=None):
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason, note)
        return result, ctx

    made_in_component = False
    for item in capture["items"]:
        ctx.current = item
        reason = _skip_reason(item)
        if reason is not None:
            result.items.append(make_verdict(item, "skipped", note=reason))
            continue

        if step_kinds.is_assembly(item.get("type")):
            # Components, joints and the like: in component coordinates they never change the part's shape.
            if item.get("target_changed") is True:
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note())
                return refuse(item, "This step changes the part, which is not copied yet.")
            result.items.append(make_verdict(item, "skipped", note=""))
            continue

        if outside_component(item):
            # A step made in another component: harmless unless it changes the target.
            if item.get("target_changed") is True or _touches_target(item, ctx):
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note())
                return refuse(item, "This step changes the part from another component. "
                              "Steps across components are not copied yet.",
                              wording.from_other_component_note(_label(item)))
            result.items.append(make_verdict(item, "skipped", note="In another component."))
            continue

        if _lost_target(item, ctx):
            return refuse(item, "The body could not be followed through the timeline.")
        if item.get("bodies_after") is None:
            return refuse(item, "The bodies this step changes could not be read.")

        touches = _touches_target(item, ctx)
        if item.get("health") == "error" and (touches or not item.get("bodies_after")):
            return refuse(item, "This step does not build in Fusion.")

        handler = table.get(item.get("type"))
        if not touches and handler is None and not item["bodies_after"]:
            if item.get("target_changed") is False:
                result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
                continue
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        if not touches:
            if not _foreign(_data(item)):
                _collect_helper(item, handler, ctx, motion is not None and size_table is not None)
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            continue

        if handler is None and _only_splits_faces(item, ctx):
            note = wording.split_face_note(_label(item))
            result.items.append(make_verdict(item, "skipped", note=note))
            result.notes.append(note)
            continue
        if handler is None:
            spec = step_kinds.step_type(item["type"])
            return refuse(item, (spec and spec.unsupported)
                          or "Steps of type %s are not copied yet." % type_words(item["type"]))
        if _data(item).get("read_error"):
            return refuse(item, "This step could not be read from Fusion.")
        with ctx.recording() as brought:
            item = ctx.current = borrowed.bring_in(item, ctx)
        ctx.doubts.extend(brought.doubts)
        if _foreign(_data(item)):
            return refuse(item, "This step reaches into another component, which is not copied yet.",
                          wording.reaches_component_note(_label(item)))
        made_in_component = True
        if motion is not None and size_table is not None:
            for names, why in construction_fixes(size_table, item):
                ctx.doubt(names, why)
        if _new_bodies(item, ctx):
            return refuse(item, "This step splits the part or makes another body, which is not copied yet.")
        outcome = _handle(handler, item, ctx)
        if isinstance(outcome, Refusal):
            ctx.doubts.extend(outcome.doubts)
            return refuse(item, outcome.reason)
        ctx.commit(outcome)
        notes = brought.notes + outcome.notes
        if not outcome.entries:
            result.items.append(make_verdict(item, "skipped", note=" ".join(notes)))
            result.notes.extend(notes)
            continue
        if not ctx.steps and outcome.steps[0].get("combine") != "new":
            return refuse(item, "The body starts in a way that cannot be copied.")
        ids = ctx.add_steps(item, outcome)
        ctx.copied_items.append(item)
        if item.get("health") == "warning":
            notes.append(wording.health_warning_note(_label(item), item.get("message")))
        if notes:
            result.items.append(make_verdict(item, "translatedWithNote", ids, " ".join(notes)))
            result.notes.extend(notes)
        else:
            result.items.append(make_verdict(item, "translated", ids))

    ctx.current = None
    if not ctx.steps:
        result.refusal = {"index": None, "name": "", "type": "", "reason": "Nothing in the timeline makes this body."}
        return result, ctx

    version = max([RECIPE_VERSION] + [step_kinds.recipe_kind(step["kind"]).version for step in ctx.steps]
                  + [SELECTOR_VERSIONS.get(key, 0) for step in ctx.steps for key in (step.get("edges") or {})])
    recipe = {"schema": "paramability.recipe", "version": version, "features": ctx.steps}
    over = _over_caps(recipe, ctx)
    if over:
        result.refusal = {"index": None, "name": "", "type": "", "reason": over}
        return result, ctx
    recipe = place.place(recipe, place.move_for(capture))
    _fix_long_formulas(recipe, ctx)
    result.recipe = recipe
    return result, ctx


def _fix_long_formulas(recipe, ctx):
    """Formulas a step builds from several values can pass the app's length cap: their sizes become fixed numbers."""
    def walk(node, label):
        if isinstance(node, Sized) and len(node["expr"]) > MAX_FORMULA_LENGTH:
            ctx.doubt(node.reads, "a value in %s needs a formula too long to copy" % (label or "a step"), fixed=True)
        if isinstance(node, dict):
            for value in node.values():
                walk(value, label)
        elif isinstance(node, list):
            for value in node:
                walk(value, label)

    for step in recipe["features"]:
        walk(step, step.get("label"))


def _handle(handler, item, ctx):
    """Run a handler. The doubts and notes it records on the context go into its StepResult, ahead of any it joined
    itself; a Refusal gets the doubts as `doubts`."""
    with ctx.recording() as recorded:
        outcome = handler(item, ctx)
    if not isinstance(outcome, (StepResult, Refusal)):
        raise TypeError("The handler for %s returned %r, not a StepResult or a Refusal." % (item.get("type"), outcome))
    if isinstance(outcome, Refusal):
        outcome.doubts = recorded.doubts
    else:
        outcome.doubts[:0] = recorded.doubts
        outcome.notes[:0] = recorded.notes
    return outcome


def _collect_helper(item, handler, ctx, with_construction):
    """Keep steps of a body other than the target for a later Combine. A refusal or a missing handler drops it.

    The doubts of the handler stay with its steps in `ctx.pending_tools`: they count only when a Combine takes the body
    (`StepResult.join`), because until then nothing it wrote reaches the exported body. Its notes are dropped."""
    if handler is None:
        return
    with ctx.recording() as construction:
        if with_construction:
            for names, why in construction_fixes(ctx.table, item):
                ctx.doubt(names, why)
    outcome = _handle(handler, item, ctx)
    bodies = item.get("bodies_after") or []
    if isinstance(outcome, Refusal) or not outcome.entries or not bodies:
        return
    key = bodies[0].get("token") or bodies[0].get("name")
    if key in ctx.pending_tools or outcome.steps[0].get("combine") == "new":
        held = ctx.pending_tools.setdefault(key, StepResult())
        held.extend(outcome.entries)
        held.doubts.extend(construction.doubts + outcome.doubts)
        held.items.append(item)
