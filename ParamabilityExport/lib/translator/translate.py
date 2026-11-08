"""The driver: walks a capture's items, calls one handler per feature type, builds the recipe."""
from . import combine, extrude, finish, hole, repeat, revolve
from .capture import validate_capture
from .context import Context
from .result import Refusal, TranslateResult, make_verdict
from .zup import turn_z_up

RECIPE_VERSION = 10
MAX_FEATURES = 400
MAX_NEAR_POINTS = 32
MAX_PATTERN_COPIES = 64

SKIP_TYPES = ("Sketch", "ConstructionPlane", "ConstructionAxis", "ConstructionPoint", "none")

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


def _touches_target(item, ctx):
    return any(ctx.is_target(b) for b in item.get("bodies_after") or [])


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
            copies = step.get("linear", {}).get("count", 1) * step.get("linear2", {}).get("count", 1)
            copies = max(copies, step.get("polar", {}).get("count", 1))
            if copies > MAX_PATTERN_COPIES:
                return "A pattern makes more than %d copies." % MAX_PATTERN_COPIES
    return None


def translate(capture, handlers=None):
    """Capture dict to TranslateResult. `handlers` maps a feature type to a handler and overrides the table.

    A handler is `handle(item, ctx) -> list[step] | Refusal`. Items after the first refusal are not walked, so
    `items` holds the verdicts up to and including it.
    """
    validate_capture(capture)
    table = dict(HANDLERS)
    if handlers:
        table.update(handlers)
    ctx = Context(capture)
    result = TranslateResult()

    def refuse(item, reason):
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason)
        return result

    for item in capture["items"]:
        ctx.current = item
        reason = _skip_reason(item)
        if reason is not None:
            result.items.append(make_verdict(item, "skipped", note=reason))
            continue

        touches = _touches_target(item, ctx)
        if item.get("health") == "error" and (touches or not item.get("bodies_after")):
            return refuse(item, "This step does not build in Fusion.")

        handler = table.get(item.get("type"))
        if not touches:
            _collect_helper(item, handler, ctx)
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            continue

        if handler is None:
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        outcome = handler(item, ctx)
        if isinstance(outcome, Refusal):
            ctx.take_notes()
            return refuse(item, outcome.reason)
        if not ctx.steps and outcome and outcome[0].get("combine") != "new":
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
        return result

    recipe = {"schema": "paramability.recipe", "version": RECIPE_VERSION, "features": ctx.steps}
    over = _over_caps(recipe)
    if over:
        result.refusal = {"index": None, "name": "", "type": "", "reason": over}
        return result
    if capture.get("up_axis") == "y":
        recipe = turn_z_up(recipe)
    result.recipe = recipe
    return result


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
