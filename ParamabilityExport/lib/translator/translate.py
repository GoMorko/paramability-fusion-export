"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
from ..capture_model import lineage, step_kinds
from ..capture_model.capture import validate_capture
from ..geometry import rigid
from ..params import geometry_links
from ..params.expressions.formula import tokenize_formula
from ..params.expressions.simplify import collected_sum
from ..params.expressions.text import MAX_FORMULA_LENGTH
from ..sketch_values import coverage, keys
from ..sketch_values.motion import Motion, Stuck, Terms
from ..timing.timer import span_on
from . import repeat
from . import notes as wording, place
from .audit import audit
from .combine.tool_walk import MAX_DEPTH as MAX_TOOL_DEPTH
from .context import Context
from .faces.picks import MAX_NEAR_POINTS
from .handlers import HANDLERS
from .gaps import gap_file, gap_measures, gap_place, stops
from .notes import (
    BODY_MOVED_WHY, dropped_reason, fixed_reason, loose_reason, tried_unmoved_reason, unmoved_link_reason,
    unmoved_reason, unused_reason)
from .ranges import kept_ranges, range_check
from .result import TranslateResult
from .sizes import joint_reasons, probed_sizes, text_reasons, untried_reasons, used_sizes
from .step_walk import all_steps, nesting
from .values import Sized, number
from .walk import walk_items

RECIPE_VERSION = 12
# Edge selector keys newer than RECIPE_VERSION, the same way.
SELECTOR_VERSIONS = {"chain": 14, "faceEdges": 14}
# Sweep step fields (and the flat path's `closed`) newer than RECIPE_VERSION, the same way.
SWEEP_VERSIONS = {"twistDeg": 16, "taperDeg": 16, "orientation": 16}
SWEEP_PATH_VERSIONS = {"closed": 16}
MAX_FEATURES = 400
MAX_PATTERN_COPIES = 256
# Recipes before version 15 take at most 64 copies per pattern count (both linear counts together for a grid).
OLD_PATTERN_COPIES = 64
WIDE_PATTERN_VERSION = 15
MAX_PASSES = 70


def _placement_refusal(capture):
    """A refusal when the part's place in the assembly cannot be used, else None."""
    placement = capture["target"].get("placement")
    if not isinstance(placement, dict):
        return None
    if placement.get("linked"):
        return {"index": None, "name": "", "type": "", "reason": "This part comes from a linked design.",
                "note": wording.linked_part_note()}
    problem = placement.get("error") or (rigid.frame_problem(placement["frame"]) if "frame" in placement else None)
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


def _counts_version(step, table):
    """WIDE_PATTERN_VERSION for a pattern step whose copy counts pass OLD_PATTERN_COPIES, at the current values or
    anywhere in the size ranges (a count that cannot be worked out counts as passing), else 0."""
    if step.get("kind") != "pattern":
        return 0
    now = [number(step.get("linear", {}).get("count", 1)) * number(step.get("linear2", {}).get("count", 1)),
           number(step.get("polar", {}).get("count", 1))]
    for (formula, reads), copies in zip(_copy_counts(step), now):
        if copies > OLD_PATTERN_COPIES:
            return WIDE_PATTERN_VERSION
        if reads and table is not None and not range_check.sweep(table, formula, reads).at_most(OLD_PATTERN_COPIES):
            return WIDE_PATTERN_VERSION
    return 0


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


def translate(capture, handlers=None, size_table=None, motion=None, timer=None):
    """`_translate`, and when the copy stops in the walk, `result.after_stop` from a walk that goes on past the stop
    (`_diagnosis`): the export still lands as a fixed shape, and the report names every step that cannot be copied.
    `timer` (`timing.timer.Timer`) gets the time of that second walk as `after_stop`."""
    result = _translate(capture, handlers, size_table, motion)
    if result.recipe is None and result.refusal is not None and result.items:
        with span_on(timer, "after_stop"):
            result.after_stop = _diagnosis(capture, handlers, result.refusal)
    return result


def _diagnosis(capture, handlers, refusal):
    """What a walk with every stop turned into a gap and no gap cap (`Context.diagnose`) finds, without sizes:
    `{ stopped_at, items, steps }`. `stopped_at` is the timeline index of the step the copy stopped at (null for a
    check after the walk), `items` the verdicts of the steps after it, `steps` every step that walk could not copy
    (`{ index, name, type, reason }`, in timeline order; the last one `stops: true` when even that walk had to stop).
    None when that walk fails: it only explains, so it never changes the export."""
    try:
        table = dict(HANDLERS)
        table.update(handlers or {})
        ctx = Context(capture, None, None, {}, table)
        ctx.lineage = lineage.of(capture)
        ctx.diagnose = True
        found = TranslateResult()
        walk_items(ctx, found)
    except Exception:
        return None
    stop = refusal.get("index")
    steps = [{"index": gap.index, "name": gap.name, "type": gap.item.get("type", ""), "reason": gap.reason}
             for gap in ctx.gaps]
    if found.refusal is not None:
        steps.append(dict(found.refusal, stops=True))
    later = [v for v in found.items if stop is not None and isinstance(v.get("index"), int) and v["index"] > stop]
    return {"stopped_at": stop, "items": later, "steps": steps}


def _translate(capture, handlers=None, size_table=None, motion=None):
    """Capture dict to TranslateResult. `handlers` maps a feature type to a handler and overrides the table.

    A handler is `handle(item, ctx) -> StepResult | Refusal` (result.py). An empty result means the item makes no step
    on purpose (verdict `skipped`, with the handler's notes). Items after the first refusal are not walked, so `items`
    holds the verdicts up to and including it.

    `size_table` makes the recipe follow Fusion parameters: feature values whose parameters read a size
    are written as formulas, the recipe gets `sizes` and the `sizesAsWritten` marker. A value that cannot follow its
    sizes is written as its number, and the sizes it reads stay free: the shape at the current values is the same and
    the other values still follow them. `result.loose` lists those sizes with the reason; one that no formula reads is
    not a size and is listed in `result.dropped` with the reason (as is every ticked size no step reads). After the walk
    an audit (`audit.py`) marks the sizes a copied step reads that no handler named. The ranges are the table's, cut
    where the size probe saw Fusion fail to rebuild or a followed sketch make a different outline
    (`kept_ranges.built_ranges`) and where a written value would be refused (`Context.cut`). A formula too long to
    copy fixes its sizes (`result.fixed`, as `{ name, reason }`).

    The walk runs twice when some value cannot follow. The first walk fixes every size such a value reads, to learn
    which sizes and reasons there are. The second keeps them free.

    A step the copy cannot hold but whose effect stays on the body is left out as a gap (gaps/stops.py, walk.py): the recipe
    is written without it and `result.gaps` describes it, with where it belongs. A size that only such steps read stays
    a size, loose, with a reason that holds once the steps are added.

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
    size_table = size_table.with_narrowed(kept_ranges.built_ranges(size_table, motion, capture))
    upfront = joint_reasons(size_table) if motion is not None else untried_reasons(size_table)
    for name, why in text_reasons(size_table, capture).items():
        upfront.setdefault(name, why)
    for name in getattr(motion, "body_moved", None) or ():
        upfront.setdefault(name, BODY_MOVED_WHY)
    for name in probed_sizes(size_table):
        if coverage.not_built(motion, name):
            upfront.setdefault(name, wording.not_built_why(coverage.span(motion, name)))
        elif coverage.kept_only_now(motion, name):
            upfront.setdefault(name, wording.only_now_why(coverage.span(motion, name)))
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
    """A motion file whose `Terms` values hold, at their value now, the sizes a stuck point or plane of the same step
    names: those sizes cannot be followed there, so the values of the step's outlines all follow the same other
    sizes. The other steps still follow them. A stuck sketch curve does not hold sizes: a line's direction turns along a
    curve even when both its ends follow, and a corner found through such a curve is stuck on its own."""
    optimistic = False

    def __init__(self, motion, table):
        self._motion = motion
        now = {e.name: e.value for e in table.entries}
        self._held = {}
        for key, value in motion.values.items():
            if isinstance(value, Stuck) and not keys.is_curve(key):
                held = self._held.setdefault(keys.item_of(key), {})
                held.update((name, now[name]) for name in value.movers if name in now)

    def get(self, key):
        found = self._motion.get(key)
        held = self._held.get(keys.item_of(key)) if isinstance(found, Terms) else None
        return found.held(held) if held else found

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
    if result.gaps:
        sizes = _gap_sizes(settled.ctx, result, table, sizes, doubts, checked.gap_reads)
    sizes = _with_cuts(table, sizes, settled.ctx.cuts)
    result.cuts = _cut_notes(table, sizes, settled.ctx)
    spans = _narrow_spans(table, motion)
    for name, (span, _, _) in spans.items():
        size = sizes.get(table.size_name(name))
        if size and wording.narrow_span(span, size["min"], size["max"]):
            doubts[name] = wording.with_span(doubts.get(name), span, size["min"], size["max"])
    result.loose = [{"name": name, "reason": loose_reason(name, why)} for name, why in doubts.items()
                    if table.size_name(name) in sizes]
    result.dropped = _dropped(table, sizes, doubts, checked.unmoved, checked.unmoved_links, _tried(motion),
                              {name: found[0] for name, found in spans.items()})
    result.notes.extend(d["reason"] for d in result.dropped)
    result.follows_components = _followed_components(settled.ctx, checked)
    result.recipe["sizesAsWritten"] = True
    if sizes:
        result.recipe["sizes"] = sizes
    return result


def _followed_components(ctx, checked):
    """`[{ token, name }]` of the other components whose sizes the copy follows: those a written reference or borrowed
    outline follows (`Context.follows`) and those a sketch tied to them follows (`Audit.follows`, names only)."""
    found = {(token, name) for token, name in ctx.follows}
    found |= {("", name) for name in checked.follows if not any(name == known for _, known in found)}
    return [{"token": token, "name": name} for token, name in sorted(found)]


def _gap_sizes(ctx, result, table, sizes, doubts, reads):
    """The recipe sizes with those that only left out steps read added, and each gap record's `sizes` and
    `looseSizes`. Such a size is loose with a reason in `doubts`, unless it has a state already: a fixed size has no
    recipe name, and a doubted one keeps its reason."""
    readers, kept, loose = {}, set(), {}
    for gap in ctx.gaps:
        for name in reads.get(gap.id, ()):
            readers.setdefault(name, []).append(gap)
    for name, found in readers.items():
        size = table.size_name(name)
        if size is None or size not in table.sizes or size in sizes:
            continue
        kept.add(size)
        if name not in doubts:
            doubts[name] = wording.gap_only_why([gap.name for gap in found])
            for gap in found:
                loose.setdefault(gap.id, set()).add(size)
    out = {name: spec for name, spec in table.sizes.items() if name in sizes or name in kept}
    for gap, written in zip(ctx.gaps, result.gaps):
        names = {table.size_name(name) for name in reads.get(gap.id, ())}
        written["sizes"] = [name for name in out if name in names][:gap_file.MAX_SIZES]
        written["looseSizes"] = [name for name in written["sizes"] if name in loose.get(gap.id, ())]
    return out


def _with_cuts(table, sizes, cuts):
    """`sizes` with the ranges cut where a written value stops working (`Context.cut`)."""
    out = dict(sizes)
    for name, (low, high) in cuts.items():
        size = out.get(table.size_name(name))
        if size and "min" in size:
            out[table.size_name(name)] = dict(size, min=max(size["min"], low), max=min(size["max"], high))
    return out


def _cut_notes(table, sizes, ctx):
    """`[{ name, reason, words, why, min, max }]` for each recipe size whose range is shorter than the one typed or default
    (`SizeTable.uncut_range`): where it stops and what was seen there (`notes.cut_reason`)."""
    out = []
    made = ctx.cut_causes
    for e in table.entries:
        size, uncut = sizes.get(e.size_name) if e.size_name else None, table.uncut_range(e.name)
        if not size or not uncut or "min" not in size:
            continue
        low, high = size["min"], size["max"]
        cut_low, cut_high = low > uncut[0] + 1e-9, high < uncut[1] - 1e-9
        if not (cut_low or cut_high):
            continue
        causes = []
        seen = table.cut_of(e.name)
        failures = [seen.failed[side] for side, at, hit in (("low", low, cut_low), ("high", high, cut_high))
                    if seen and hit and side in seen.failed and abs(seen[0 if side == "low" else 1] - at) < 1e-9]
        if failures:
            causes.append(wording.not_rebuilt_why(failures))
        changes = [seen.changed[side] for side, at, hit in (("low", low, cut_low), ("high", high, cut_high))
                   if seen and hit and side in seen.changed and abs(seen[0 if side == "low" else 1] - at) < 1e-9]
        if changes:
            causes.append(wording.outline_changed_why(changes))
        causes += [why for ends, why in made.get(e.name, {}).items()
                   if (cut_low and abs(ends[0] - low) < 1e-9) or (cut_high and abs(ends[1] - high) < 1e-9)]
        if not causes:
            continue
        words, why = wording.cut_words(cut_low, cut_high, low, high), "; ".join(dict.fromkeys(causes))
        out.append({"name": e.name, "reason": wording.cut_reason(e.name, words, why), "words": words, "why": why,
                    "min": low, "max": high})
    return out


def _narrow_spans(table, motion):
    """`{ Fusion name: (span, min, max) }` of the probed sizes that the probe measured over less than their range
    before it was cut (`Motion.spans`, `SizeTable.uncut_range`): the copy follows them only between the values
    measured."""
    out = {}
    for name in probed_sizes(table):
        span = _followed_span(coverage.span(motion, name))
        uncut = table.uncut_range(name)
        if span and uncut and wording.narrow_span(span, *uncut):
            out[name] = (span,) + uncut
    return out


def _followed_span(span):
    """The span without the values past the ends where a followed sketch made a different outline (`kept`): the
    copy follows the size only up to there."""
    kept = (span or {}).get("kept")
    if not kept or (None not in kept and kept[1] - kept[0] <= 1e-9):
        return span
    low = span["low"] if kept[0] is None else max(span["low"], kept[0])
    high = span["high"] if kept[1] is None else min(span["high"], kept[1])
    return dict(span, low=low, high=high)


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


def _sweep_version(step):
    """The recipe version a sweep step's newer fields need, 0 for any other step or a sweep without them."""
    if step.get("kind") != "sweep":
        return 0
    fields = [SWEEP_VERSIONS[key] for key in step if key in SWEEP_VERSIONS]
    fields += [SWEEP_PATH_VERSIONS[key] for key in step.get("path") or {} if key in SWEEP_PATH_VERSIONS]
    return max(fields, default=0)


def _walk(capture, table, size_table, motion=None, cache=None):
    """One walk over the items: (TranslateResult, Context). `cache` is shared by the walks of one translation."""
    ctx = Context(capture, size_table, motion, cache, table)
    ctx.lineage = lineage.of(capture)
    result = TranslateResult()
    if not walk_items(ctx, result):
        return result, ctx
    if not ctx.steps:
        result.refusal = {"index": None, "name": "", "type": "", "reason": "Nothing in the timeline makes this body."}
        return result, ctx

    written = all_steps(ctx.steps)
    version = max([RECIPE_VERSION] + [step_kinds.recipe_kind(step["kind"]).version for step in written]
                  + [SELECTOR_VERSIONS.get(key, 0) for step in written for key in (step.get("edges") or {})]
                  + [_counts_version(step, ctx.table) for step in written]
                  + [_sweep_version(step) for step in written])
    recipe = {"schema": "paramability.recipe", "version": version, "features": ctx.steps}
    over = _over_caps(recipe, ctx)
    if over:
        result.refusal = {"index": None, "name": "", "type": "", "reason": over}
        return result, ctx
    move = rigid.move_for(capture)
    recipe = place.place(recipe, move)
    _fix_long_formulas(recipe, ctx)
    if ctx.gaps:
        result.over_gap_cap = len(ctx.gaps) > stops.MAX_GAPS
        problem = (wording.too_many_gaps_reason(stops.MAX_GAPS) if result.over_gap_cap
                   else gap_place.place_all(ctx.gaps, recipe["features"]))
        if problem:
            result.refusal = {"index": None, "name": "", "type": "", "reason": problem}
            return result, ctx
        result.gaps = [gap_file.record(gap, size_table, move) for gap in ctx.gaps]
        result.to_recipe = gap_measures.to_recipe(move)
        result.notes.append(wording.left_out_note([gap.name for gap in ctx.gaps]))
    result.recipe = recipe
    return result, ctx


def _still_read(table, reads, formula):
    """The Fusion names among `reads` that the recipe sizes named in `formula` still depend on: a size whose terms
    cancelled is no longer read."""
    if table is None:
        return reads
    named = {token[1] for token in tokenize_formula(formula) if token[0] == "id"}
    kept = set()
    for e in table.entries:
        if table.size_name(e.name) in named:
            kept.update(table.depends(e.name))
    return tuple(name for name in reads if name in kept)


def _fix_long_formulas(recipe, ctx):
    """Formulas a step builds from several values can pass the app's length cap. Their equal terms are added up first
    (a plane's move less the same move of another plane cancels); a formula still too long fixes its sizes."""
    def walk(node, label):
        if isinstance(node, Sized) and len(node["expr"]) > MAX_FORMULA_LENGTH:
            shorter = collected_sum(node["expr"])
            if len(shorter) <= MAX_FORMULA_LENGTH:
                node["expr"] = shorter
                node.reads = _still_read(ctx.table, node.reads, shorter)
            else:
                ctx.doubt(node.reads, "a value in %s needs a formula too long to copy" % (label or "a step"),
                          fixed=True)
        if isinstance(node, dict):
            for value in node.values():
                walk(value, label)
        elif isinstance(node, list):
            for value in node:
                walk(value, label)

    for step in recipe["features"]:
        walk(step, step.get("label"))
