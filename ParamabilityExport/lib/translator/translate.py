"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
from . import combine, extrude, finish, hole, repeat, revolve
from .sizes import sketch_fixes, used_sizes
from .capture import renamed_target, same_body, validate_capture
from .context import Context
from .result import Refusal, TranslateResult, make_verdict
from ..params.expressions import MAX_FORMULA_LENGTH
from .values import Sized, number
from .zup import turn_z_up

RECIPE_VERSION = 12
MAX_FEATURES = 400
MAX_NEAR_POINTS = 32
MAX_PATTERN_COPIES = 64
MAX_PASSES = 70

SKIP_TYPES = ("Sketch", "ConstructionPlane", "ConstructionAxis", "ConstructionPoint", "none")

# Timeline items that hold no solid geometry: with no readable bodies they cannot change the part.
NON_GEOMETRY_TYPES = ("Joint", "JointOrigin", "AsBuiltJoint", "RigidGroup", "Canvas", "Decal")

_MODULES = (extrude, revolve, hole, finish, repeat, combine)
HANDLERS = {t: m.handle for m in _MODULES for t in m.TYPES}


def type_words(type_name):
    """'EmbossFeature' to 'emboss', 'RectangularPatternFeature' to 'rectangular pattern'."""
    base = type_name[: -len("Feature")] if type_name.endswith("Feature") and type_name != "Feature" else type_name
    words = []
    for ch in base:
        if ch.isupper() and words and not words[-1][-1].isupper():
            words.append(ch)
        elif words:
            words[-1] += ch
        else:
            words.append(ch)
    return " ".join(w.lower() for w in words) or type_name


def _refusal(item, reason):
    return {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""), "reason": reason}


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


def translate(capture, handlers=None, size_table=None):
    """Capture dict to TranslateResult. `handlers` maps a feature type to a handler and overrides the table.

    A handler is `handle(item, ctx) -> list[step] | Refusal`. An empty list means the item makes no step on purpose
    (verdict `skipped`, with the handler's notes). Items after the first refusal are not walked, so `items` holds the
    verdicts up to and including it.

    `size_table` (lib/params) makes the recipe follow Fusion parameters: feature values whose parameters read a size
    are written as formulas, the recipe gets `sizes` and the `sizesAsWritten` marker. A size that some value cannot
    follow is made a fixed number and the walk runs again; `result.fixed` lists those sizes as `{ name, reason }`.
    """
    validate_capture(capture)
    table = dict(HANDLERS)
    if handlers:
        table.update(handlers)
    if size_table is None:
        return _walk(capture, table, None)[0]
    fixed = sketch_fixes(size_table)
    current = size_table.with_fixed(fixed) if fixed else size_table
    for _ in range(MAX_PASSES):
        result, ctx = _walk(capture, table, current)
        more = {name: why for name, why in ctx.depends.items() if name not in fixed}
        if result.recipe is None or not more:
            break
        fixed.update(more)
        current = current.with_fixed(more)
    result.fixed = [{"name": name, "reason": why} for name, why in fixed.items()]
    if result.recipe is not None:
        _add_sizes(result, current)
    return result


def _add_sizes(result, table):
    """The recipe's `sizes` (those a formula reads) and the marker that says they are the whole list."""
    recipe = result.recipe
    sizes = used_sizes(recipe["features"], table.sizes)
    recipe["sizesAsWritten"] = True
    if sizes:
        recipe["sizes"] = sizes
    for name in table.ticked:
        if table.size_name(name) not in sizes:
            result.notes.append("%s is not used by any copied step, so it is not a size." % name)


def _walk(capture, table, size_table):
    """One walk over the items: (TranslateResult, Context)."""
    ctx = Context(capture, size_table)
    result = TranslateResult()

    def refuse(item, reason):
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason)
        return result, ctx

    for item in capture["items"]:
        ctx.current = item
        reason = _skip_reason(item)
        if reason is not None:
            result.items.append(make_verdict(item, "skipped", note=reason))
            continue

        if _lost_target(item, ctx):
            return refuse(item, "The body could not be followed through the timeline.")
        if item.get("bodies_after") is None:
            return refuse(item, "The bodies this step changes could not be read.")

        touches = _touches_target(item, ctx)
        if item.get("health") == "error" and (touches or not item.get("bodies_after")):
            return refuse(item, "This step does not build in Fusion.")

        handler = table.get(item.get("type"))
        if not touches and handler is None and not item["bodies_after"] and item.get("type") not in NON_GEOMETRY_TYPES:
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        if not touches:
            _collect_helper(item, handler, ctx)
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            continue

        if handler is None:
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        if _data(item).get("read_error"):
            return refuse(item, "This step could not be read from Fusion.")
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

    recipe = {"schema": "paramability.recipe", "version": RECIPE_VERSION, "features": ctx.steps}
    over = _over_caps(recipe)
    if over:
        result.refusal = {"index": None, "name": "", "type": "", "reason": over}
        return result, ctx
    if capture.get("up_axis") == "y":
        recipe = turn_z_up(recipe)
    _fix_long_formulas(recipe, ctx)
    result.recipe = recipe
    return result, ctx


def _fix_long_formulas(recipe, ctx):
    """Formulas a step builds from several values can pass the app's length cap: their sizes become fixed numbers."""
    def walk(node, label):
        if isinstance(node, Sized) and len(node["expr"]) > MAX_FORMULA_LENGTH:
            ctx.fix(node.reads, "a value in %s needs a formula too long to copy" % (label or "a step"))
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
