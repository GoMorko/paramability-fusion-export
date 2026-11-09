"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
from . import borrowed, combine, extrude, finish, hole, offset, repeat, revolve
from .sizes import construction_fixes, joint_reasons, untried_reasons, used_sizes
from . import notes as wording, place
from .notes import fixed_reason, loose_reason
from .capture import ASSEMBLY_TYPES, SKETCH_TYPES, outside_component, renamed_target, same_body, validate_capture
from .context import Context
from .result import Refusal, TranslateResult, make_verdict
from ..params.expressions import MAX_FORMULA_LENGTH
from .values import Sized, number
from ..probe.motion import Motion, Stuck
from .words import type_words

RECIPE_VERSION = 12
# Step kinds newer than RECIPE_VERSION: a recipe that holds one states the version that introduced it.
KIND_VERSIONS = {"offsetFaces": 13}
MAX_FEATURES = 400
MAX_NEAR_POINTS = 32
MAX_PATTERN_COPIES = 64
MAX_PASSES = 70

SKIP_TYPES = SKETCH_TYPES + ("none",)

_MODULES = (extrude, revolve, hole, finish, repeat, combine, offset)

# Plain reasons for feature types the recipe has no step for.
UNSUPPORTED_REASONS = {
    "EmbossFeature": "Emboss steps raise or sink a sketch on a face, which Paramability cannot do yet.",
}
HANDLERS = {t: m.handle for m in _MODULES for t in m.TYPES}


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


def _skip_reason(item):
    if item.get("suppressed"):
        return "Suppressed in Fusion."
    if item.get("type") in SKIP_TYPES:
        return ""
    if item.get("component_root") is False:
        return "Not in the root component."
    return None


def _over_caps(recipe):
    """Return a plain reason when the recipe breaks a reader cap, else None."""
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
    return None


def translate(capture, handlers=None, size_table=None, motion=None, loose=False, plain=False):
    """Capture dict to TranslateResult. `handlers` maps a feature type to a handler and overrides the table.

    A handler is `handle(item, ctx) -> list[step] | Refusal`. An empty list means the item makes no step on purpose
    (verdict `skipped`, with the handler's notes). Items after the first refusal are not walked, so `items` holds the
    verdicts up to and including it.

    `size_table` makes the recipe follow Fusion parameters: feature values whose parameters read a size
    are written as formulas, the recipe gets `sizes` and the `sizesAsWritten` marker. A value that cannot follow its
    sizes is written as its number. Its sizes are then made fixed numbers and the walk runs again; `result.fixed`
    lists them as `{ name, reason }`. With `loose` they stay free sizes instead, so the shape at the current values is
    the same and the other values still follow; `result.loose` lists them with the reason. A formula too long to copy
    fixes its sizes in both modes.

    `plain` keeps every range as the table gives it: no minimum is raised and no range is shortened. A size whose
    range would have needed that stays free and goes to `loose` with the reason instead. Use it with `loose`.

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
    if size_table is None:
        return _walk(capture, table, None)[0]
    upfront = joint_reasons(size_table) if motion is not None else untried_reasons(size_table)
    strict = _settle(capture, table, size_table, motion, upfront, follow=False, plain=plain)
    if not loose or strict.result.recipe is None or not (strict.whys or strict.narrowed):
        return _finish(strict, {}, plain)
    pinned = _Pinned(motion) if isinstance(motion, Motion) and not motion.optimistic else motion
    found = _settle(capture, table, size_table, pinned, {}, follow=True, plain=plain)
    doubts = dict(upfront)
    for name, why in list(strict.whys.items()) + list(found.depends.items()):
        doubts.setdefault(name, why)
    return _finish(found, {name: why for name, why in doubts.items() if name not in found.whys}, plain)


class _Pinned:
    """A motion file where a stuck value follows only the sizes that still move it (`Stuck.rest`, or nothing), as it
    does once its own sizes are fixed. The loose walk keeps those sizes free, so the other values still follow them."""
    optimistic = False

    def __init__(self, motion):
        self._motion = motion

    def get(self, key):
        found = self._motion.get(key)
        return found.rest if isinstance(found, Stuck) else found

    def __getattr__(self, name):
        return getattr(self._motion, name)


class _Settled:
    """Where the passes of one mode ended: the last walk, the table it used, the fixed sizes with why, the raised
    minimums and shortened ranges, and what the last walk could not follow (`Context.depends`)."""

    def __init__(self, result, table, whys, raised, narrowed, depends):
        self.result, self.table, self.whys = result, table, whys
        self.raised, self.narrowed, self.depends = raised, narrowed, depends


def _settle(capture, handlers, size_table, motion, fixed, follow, plain=False):
    """Walk until nothing changes. `fixed` (Fusion name to why) are fixed up front. Without `follow` every size a
    value cannot follow is fixed and the walk runs again; with it only the sizes of `Context.fix_always` are."""
    whys = dict(fixed)
    current = size_table.with_fixed(_reasons(whys)) if whys else size_table
    raised, narrowed = {}, {}
    for _ in range(MAX_PASSES):
        result, ctx = _walk(capture, handlers, current, motion, follow, plain)
        cannot = ctx.must_fix if follow else {**ctx.depends, **ctx.must_fix}
        more = {name: why for name, why in cannot.items() if name not in whys}
        lifted = {name: low for name, low in ctx.minimums.items()
                  if name not in whys and name not in more and low[0] > raised.get(name, (float("-inf"),))[0]}
        shortened = {name: bounds for name, bounds in ctx.narrowings.items()
                     if name not in whys and name not in more and _shorter(bounds[0], narrowed.get(name))}
        if result.recipe is None or not (more or lifted or shortened):
            break
        whys.update(more)
        raised.update(lifted)
        narrowed.update(shortened)
        current = current.with_fixed(_reasons(more)) if more else current
        current = current.with_minimums({name: low[0] for name, low in lifted.items()}) if lifted else current
        current = current.with_narrowed({name: b[0] for name, b in shortened.items()}) if shortened else current
    return _Settled(result, current, whys, raised, narrowed, ctx.depends)


def _reasons(whys):
    return {name: fixed_reason(name, why) for name, why in whys.items()}


def _finish(settled, doubts, plain=False):
    """The result of the last walk with its fixed, loose, raised and shortened sizes, and the recipe `sizes`.

    `doubts` (Fusion name to why) are sizes kept free that some value cannot follow; one that no formula reads is
    listed as fixed, since it is a fixed number in all but name. With `plain` it is simply not a size."""
    result, table, whys = settled.result, settled.table, dict(settled.whys)
    if result.recipe is not None:
        written = used_sizes(result.recipe["features"], table.sizes)
        for name in [n for n in doubts if table.size_name(n) not in written]:
            why = doubts.pop(name)
            if not plain:
                whys[name] = why
    result.fixed = [{"name": name, "reason": fixed_reason(name, why)} for name, why in whys.items()]
    result.loose = [{"name": name, "reason": loose_reason(name, why)} for name, why in doubts.items()]
    result.raised = [{"name": name, "min": low, "reason": why} for name, (low, why) in settled.raised.items()
                     if name not in whys]
    result.narrowed = [{"name": name, "min": b[0], "max": b[1], "reason": why}
                       for name, (b, why) in settled.narrowed.items() if name not in whys]
    result.notes.extend(r["reason"] for r in result.raised + result.narrowed)
    if result.recipe is not None:
        _add_sizes(result, table, whys)
    return result


def _shorter(bounds, before):
    """True when the range `bounds` is shorter than the one recorded before (or there was none)."""
    if before is None:
        return True
    (lo, hi), (old_lo, old_hi) = bounds, before[0]
    return lo > old_lo + 1e-12 or hi < old_hi - 1e-12


def _add_sizes(result, table, fixed=()):
    """The recipe's `sizes` (those a formula reads) and the marker that says they are the whole list. A ticked size
    that no formula reads gets a note, unless it is among the `fixed` names."""
    recipe = result.recipe
    sizes = used_sizes(recipe["features"], table.sizes)
    recipe["sizesAsWritten"] = True
    if sizes:
        recipe["sizes"] = sizes
    for name in table.ticked:
        if table.size_name(name) not in sizes and name not in fixed:
            result.notes.append("%s is not used by any copied step, so it is not a size." % name)


def _walk(capture, table, size_table, motion=None, follow=False, plain=False):
    """One walk over the items: (TranslateResult, Context). `follow` keeps sizes free that a value cannot follow;
    `plain` leaves ranges alone (`translate`)."""
    ctx = Context(capture, size_table, motion, follow, plain)
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

        if item.get("type") in ASSEMBLY_TYPES:
            # Components, joints and the like: in component coordinates they never change the part's shape.
            if item.get("target_changed") is True:
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note())
                return refuse(item, "This step changes the part, which is not copied yet.")
            result.items.append(make_verdict(item, "skipped", note=""))
            continue

        if outside_component(item) and "component_root" not in item:
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
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        if not touches:
            if not _foreign(_data(item)):
                _collect_helper(item, handler, ctx)
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            continue

        if handler is None:
            return refuse(item, UNSUPPORTED_REASONS.get(item["type"])
                          or "Steps of type %s are not copied yet." % type_words(item["type"]))
        if _data(item).get("read_error"):
            return refuse(item, "This step could not be read from Fusion.")
        item = ctx.current = borrowed.bring_in(item, ctx)
        if _foreign(_data(item)):
            return refuse(item, "This step reaches into another component, which is not copied yet.",
                          wording.reaches_component_note(_label(item)))
        made_in_component = True
        if motion is not None and size_table is not None:
            for names, why in construction_fixes(size_table, item):
                ctx.fix(names, why)
        if _new_bodies(item, ctx):
            return refuse(item, "This step splits the part or makes another body, which is not copied yet.")
        outcome = handler(item, ctx)
        if isinstance(outcome, Refusal):
            ctx.take_notes()
            return refuse(item, outcome.reason)
        if not outcome:
            notes = ctx.take_notes()
            result.items.append(make_verdict(item, "skipped", note=" ".join(notes)))
            result.notes.extend(notes)
            continue
        if not ctx.steps and outcome[0].get("combine") != "new":
            return refuse(item, "The body starts in a way that cannot be copied.")
        ids = ctx.add_steps(item, outcome)
        notes = ctx.take_notes()
        if notes:
            result.items.append(make_verdict(item, "translatedWithNote", ids, " ".join(notes)))
            result.notes.extend(notes)
        else:
            result.items.append(make_verdict(item, "translated", ids))

    if not ctx.steps:
        result.refusal = {"index": None, "name": "", "type": "", "reason": "Nothing in the timeline makes this body."}
        return result, ctx

    version = max([RECIPE_VERSION] + [KIND_VERSIONS.get(step["kind"], 0) for step in ctx.steps])
    recipe = {"schema": "paramability.recipe", "version": version, "features": ctx.steps}
    over = _over_caps(recipe)
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
            ctx.fix_always(node.reads, "a value in %s needs a formula too long to copy" % (label or "a step"))
        if isinstance(node, dict):
            for value in node.values():
                walk(value, label)
        elif isinstance(node, list):
            for value in node:
                walk(value, label)

    for step in recipe["features"]:
        walk(step, step.get("label"))


def _collect_helper(item, handler, ctx):
    """Keep steps of a body other than the target for a later Combine. A refusal or a missing handler drops it."""
    if handler is None:
        return
    outcome = handler(item, ctx)
    ctx.take_notes()
    bodies = item.get("bodies_after") or []
    if isinstance(outcome, Refusal) or not outcome or not bodies:
        return
    key = bodies[0].get("token") or bodies[0].get("name")
    if key in ctx.pending_tools or outcome[0].get("combine") == "new":
        ctx.pending_tools.setdefault(key, []).extend(outcome)
