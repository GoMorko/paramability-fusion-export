"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
import importlib

from . import range_check, repeat, step_kinds
from .audit import audit
from .sizes import joint_reasons, probed_sizes, text_reasons, untried_reasons, used_sizes
from . import notes as wording, place
from .picks import MAX_NEAR_POINTS
from .notes import (
    BODY_MOVED_WHY, dropped_reason, fixed_reason, loose_reason, tried_unmoved_reason, unmoved_link_reason,
    unmoved_reason, unused_reason)
from .capture import validate_capture
from .context import Context
from .result import TranslateResult
from .step_walk import all_steps, nesting
from .tool_walk import MAX_DEPTH as MAX_TOOL_DEPTH
from ..params import geometry_links
from ..params.expressions import MAX_FORMULA_LENGTH
from .values import Sized, number
from ..sketch_values import coverage
from ..sketch_values.motion import Motion, Stuck, Terms
from .walk import walk_items

RECIPE_VERSION = 12
# Edge selector keys newer than RECIPE_VERSION, the same way.
SELECTOR_VERSIONS = {"chain": 14, "faceEdges": 14}
MAX_FEATURES = 400
MAX_PATTERN_COPIES = 256
MAX_PASSES = 70


def _resolve(handler):
    """The function a step kind table entry names as "module:function" in this package."""
    module, function = handler.split(":")
    return getattr(importlib.import_module("." + module, __package__), function)


# Capture type -> handler, from the step kind table.
HANDLERS = {t.name: _resolve(t.handler) for t in step_kinds.STEP_TYPES if t.handler}


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
    features = all_steps(recipe["features"])
    if len(features) > MAX_FEATURES:
        return "The part has more than %d steps." % MAX_FEATURES
    if nesting(recipe["features"]) > MAX_TOOL_DEPTH:
        return "The part is built from tools nested too deep to copy."
    if repeat.copied_bodies(features) > repeat.MAX_COPIED_BODIES:
        return "The patterns of this part make more than %d copies in all." % repeat.MAX_COPIED_BODIES

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

    `motion` is what the size probe measured about sketch values (`sketch_values.motion.Motion`): sketch points, planes, hole
    points and revolve axes are then written as formulas where they follow sizes. `sketch_values.motion.OPTIMISTIC` writes
    them as numbers without fixing anything for them (the first translation of an export). Without it, no size that
    moves a sketch or construction geometry can be followed.

    A size table without geometry links gets the capture's (`params.geometry_links.reach`): a ticked size that may
    reach a sketch through another component counts as a size that sketch reads.
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
    if not size_table.links:
        size_table = size_table.with_links(geometry_links.reach(capture))
    upfront = joint_reasons(size_table) if motion is not None else untried_reasons(size_table)
    for name, why in text_reasons(size_table, capture).items():
        upfront.setdefault(name, why)
    for name in getattr(motion, "body_moved", None) or ():
        upfront.setdefault(name, BODY_MOVED_WHY)
    for name in probed_sizes(size_table):
        if coverage.not_built(motion, name):
            upfront.setdefault(name, wording.not_built_why(coverage.span(motion, name)))
    held = _Held(motion, size_table) if isinstance(motion, Motion) and not motion.optimistic else motion
    first = _settle(capture, table, size_table, held, upfront, False, cache)
    if first.result.recipe is None or not first.whys:
        return _finish(first, {}, capture, motion)
    pinned = _Pinned(motion, size_table) if isinstance(motion, Motion) and not motion.optimistic else motion
    found = _settle(capture, table, size_table, pinned, {}, True, cache)
    doubts = dict(upfront)
    for name, why in list(first.whys.items()) + list(found.depends.items()):
        doubts.setdefault(name, why)
    return _finish(found, {name: why for name, why in doubts.items() if name not in found.whys}, capture, motion)


class _Held:
    """A motion file whose `Terms` values hold the sizes some stuck value names at their value now: those sizes cannot
    be followed, so the values of one outline all follow the same other sizes."""
    optimistic = False

    def __init__(self, motion, table):
        self._motion = motion
        held = {n for v in motion.values.values() if isinstance(v, Stuck) for n in v.movers}
        self._held = {e.name: e.value for e in table.entries if e.name in held}

    def get(self, key):
        found = self._motion.get(key)
        if isinstance(found, Terms) and self._held:
            return found.held(self._held)
        return found

    def __getattr__(self, name):
        return getattr(self._motion, name)


class _Pinned(_Held):
    """A held motion file where a stuck value follows only the sizes that still move it (`Stuck.rest`, or nothing),
    as it does once its own sizes are fixed. The second walk keeps those sizes free, so the other values still follow
    them."""

    def get(self, key):
        found = super().get(key)
        return found.rest if isinstance(found, Stuck) else found


class _Settled:
    """Where the passes of one walk ended: the last walk, its context, the table it used, the fixed sizes with
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
    spans = _narrow_spans(table, motion)
    for name, (span, low, high) in spans.items():
        if table.size_name(name) in sizes:
            doubts[name] = wording.with_span(doubts.get(name), span, low, high)
    result.loose = [{"name": name, "reason": loose_reason(name, why)} for name, why in doubts.items()
                    if table.size_name(name) in sizes]
    result.dropped = _dropped(table, sizes, doubts, checked.unmoved, checked.unmoved_links, _tried(motion),
                              {name: found[0] for name, found in spans.items()})
    result.notes.extend(d["reason"] for d in result.dropped)
    result.recipe["sizesAsWritten"] = True
    if sizes:
        result.recipe["sizes"] = sizes
    return result


def _narrow_spans(table, motion):
    """`{ Fusion name: (span, min, max) }` of the probed sizes that the probe measured over less than their range
    (`Motion.spans`): the copy follows them only between the values measured."""
    out = {}
    for name in probed_sizes(table):
        span = coverage.span(motion, name)
        size = table.sizes.get(table.size_name(name)) or {}
        if span and "min" in size and wording.narrow_span(span, size["min"], size["max"]):
            out[name] = (span, size["min"], size["max"])
    return out


def _tried(motion):
    """Fusion names of the sizes the size probe set to other values in a state that built."""
    if not isinstance(motion, Motion) or motion.optimistic:
        return set()
    return {name for state in motion.states or () if state.get("built", True) for name in state.get("values") or {}}


def _dropped(table, sizes, doubts, unmoved, unmoved_links=None, tried=(), spans=None):
    """`{ name, reason, used }` for each ticked size that no written formula reads. `used` is True when a step reads
    it and the copy could not follow it, False when nothing copied depends on it. `unmoved_links` names, per size
    tied to a sketch only through another component that did not move with it, that component. A size in `tried`
    (set to other values by the size probe) that nothing reads was measured to change nothing: it gets
    `"tried": True` and says so; with a span in `spans` (measured over less than its range) it says between which
    values."""
    out = []
    for name in table.ticked:
        if table.size_name(name) in sizes:
            continue
        if name in doubts:
            out.append({"name": name, "reason": dropped_reason(name, doubts[name]), "used": True})
        else:
            span = (spans or {}).get(name)
            if name in (unmoved_links or {}):
                reason = unmoved_link_reason(name, unmoved_links[name], span)
            elif name in unmoved:
                reason = unmoved_reason(name)
            elif name in tried:
                reason = tried_unmoved_reason(name, span)
            else:
                reason = unused_reason(name)
            entry = {"name": name, "reason": reason, "used": False}
            if name in tried or name in unmoved or name in (unmoved_links or {}):
                entry["tried"] = True
            out.append(entry)
    return out


def _walk(capture, table, size_table, motion=None, cache=None):
    """One walk over the items: (TranslateResult, Context). `cache` is shared by the walks of one translation."""
    ctx = Context(capture, size_table, motion, cache, table)
    result = TranslateResult()
    if not walk_items(ctx, result):
        return result, ctx
    if not ctx.steps:
        result.refusal = {"index": None, "name": "", "type": "", "reason": "Nothing in the timeline makes this body."}
        return result, ctx

    written = all_steps(ctx.steps)
    version = max([RECIPE_VERSION] + [step_kinds.recipe_kind(step["kind"]).version for step in written]
                  + [SELECTOR_VERSIONS.get(key, 0) for step in written for key in (step.get("edges") or {})])
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
