"""The item loop: runs one handler per timeline item and writes the steps on the context.

The same loop copies the exported body and each tool body of a Combine. The context says what it builds
(`Context.target`, `Context.capture`, `Context.handlers`), so a handler always sees the body it works on as its target.
"""
from . import borrowed, notes as wording, ref_motion, step_kinds
from .capture import outside_component, renamed_target, same_body
from .result import Refusal, StepResult, make_verdict
from .sizes import construction_fixes
from .words import type_words


def _refusal(item, reason, note=None):
    """The refusal record of the result. `note` is the package note when it differs from the usual wording."""
    out = {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""), "reason": reason}
    if note:
        out["note"] = note
    return out


def _label(item):
    return wording.step_label(item.get("name"), item.get("type")) or "A step"


def is_foreign(node):
    """A record of the step's data marked `foreign` by the reader: it belongs to another component. Other bodies a
    step lists (participants) and the tool bodies a combine lists are left to their own rules."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            return True
        return any(is_foreign(v) for k, v in node.items() if k not in ("participants", "tools"))
    if isinstance(node, list):
        return any(is_foreign(v) for v in node)
    return False


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
    """A split of faces that the capture shows left the body as it was: its solid is the same, only its faces are cut
    up, so nothing is copied."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec is not None and spec.splits_faces and item.get("target_changed") is False
            and not _new_bodies(item, ctx))


def _skip_reason(item):
    if item.get("suppressed"):
        return "Suppressed in Fusion."
    if step_kinds.skipped(item.get("type")):
        return ""
    return None


def fix_construction(ctx, item):
    """Mark the sizes that move construction geometry the step uses, when the sketches can follow sizes at all."""
    if ctx.motion is not None and ctx.table is not None:
        for names, why in construction_fixes(ctx.table, item):
            ctx.doubt(names, why)


def run_handler(handler, item, ctx):
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
        outcome.asked |= recorded.asked
    return outcome


def walk_items(ctx, result):
    """Walk the items of `ctx.capture`: True when every item was dealt with, False when one stops the copy (then
    `result.refusal` says why). Verdicts and notes go to `result`, steps and doubts to `ctx`."""

    def refuse(item, reason, note=None):
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason, note)
        return False

    made_in_component = False
    for item in ctx.capture["items"]:
        ctx.enter(item)
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

        if outside_component(item) and item.get("helper_of"):
            # A step of a tool body from another component: the Combine that takes the tool walks it.
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
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

        handler = ctx.handlers.get(item.get("type"))
        if not touches and handler is None and not item["bodies_after"]:
            if item.get("target_changed") is False:
                result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
                continue
            return refuse(item, "Steps of type %s are not copied yet." % type_words(item["type"]))
        if not touches:
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
            item = ctx.current = ref_motion.bring_in(borrowed.bring_in(item, ctx))
        ctx.doubts.extend(brought.doubts)
        if is_foreign(_data(item)):
            return refuse(item, ref_motion.why_foreign(item)
                          or "This step reaches into another component, which is not copied yet.",
                          wording.reaches_component_note(_label(item)))
        made_in_component = True
        fix_construction(ctx, item)
        if _new_bodies(item, ctx):
            return refuse(item, "This step splits the part or makes another body, which is not copied yet.")
        outcome = run_handler(handler, item, ctx)
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
    return True
