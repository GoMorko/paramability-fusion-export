"""The item loop: runs one handler per timeline item and writes the steps on the context.

The same loop copies the exported body and each tool body of a Combine. The context says what it builds
(`Context.target`, `Context.capture`, `Context.handlers`), so a handler always sees the body it works on as its target.

An item the copy cannot hold either stops the copy or, when its effect stays on the body and the rest of the timeline
still reads right, is left out as a gap (gaps.py). A gap is a step type with no handler, a handler's Refusal, a step
that reaches into another component, and a step that picks faces a gap made. What a left out item would have recorded
(doubts, notes) is dropped with it. Anything that leaves the body unknown still stops the copy.
"""
from . import (body_states, borrowed, floating, gap_hints, gap_picks, gaps, notes as wording, ref_motion, split_rules,
               step_kinds)
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


# Lists of the bodies a step takes or makes. A body of another component in one of them has its own rules.
_BODY_LISTS = ("participants", "tools", "sources", "source_bodies", "result_bodies", "bodies", "pieces")


def is_foreign(node):
    """A record of the step's data marked `foreign` by the reader: it belongs to another component. The bodies a step
    lists are left to their own rules."""
    if isinstance(node, dict):
        if node.get("foreign") is True:
            return True
        return any(is_foreign(v) for k, v in node.items() if k not in _BODY_LISTS)
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
    if ctx.is_target(data.get("target")) or any(ctx.is_target(b) for b in data.get("bodies") or []):
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
    named = list(data.get("participants") or []) + list(data.get("tools") or []) + list(data.get("bodies") or [])
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


def copies_bodies(item):
    """The item makes bodies that copy others: a Paste, or a pattern or mirror of bodies."""
    spec = step_kinds.step_type(item.get("type"))
    return spec is not None and spec.makes_bodies and _data(item).get("entity_type", "bodies") == "bodies"


def _changes_named_bodies(item):
    """The item copies or moves bodies, so one that lists no body may still have changed the part."""
    spec = step_kinds.step_type(item.get("type"))
    return copies_bodies(item) or (spec is not None and spec.moves_bodies)


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


def _type_cause(item):
    """The `gap_hints` cause of an item whose type the copy has no handler for."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec and spec.gap_cause) or gap_hints.UNSUPPORTED


def _gap_ids(ctx, item):
    """Ids of the gaps whose faces `item` picks, or may pick."""
    return [gap.id for gap in gap_picks.picked_gaps(ctx, item)[0]]


def _seen_before_split(item, ctx):
    """Before the split that made the body this walk builds, an item of the body it was split from is read with what
    the reader measured on that body (`body_states`), like a step of the target."""
    if not ctx.lineage or split_rules.is_split(item) or outside_component(item):
        return item
    held = ctx.lineage_at(item.get("index", 0))[0]
    if same_body(held, ctx.target) or not body_states.measured(item, held):
        return item
    return body_states.seen_on(item, held)


def walk_items(ctx, result):
    """Walk the items of `ctx.capture`: True when every item was dealt with, False when one stops the copy (then
    `result.refusal` says why). Verdicts and notes go to `result`, steps and doubts to `ctx`."""

    def refuse(item, reason, note=None):
        """Stop the copy at `item`: False. A diagnosing walk (`Context.diagnose`) records the stop as a gap and goes
        on instead: True, unless there is no body to add the gap to yet."""
        if ctx.diagnose and not gaps.first_body_stop(ctx):
            gap = ctx.leave_out(item, reason, ())
            verdict = make_verdict(item, "leftOut", note=gap.reason)
            verdict.update(gap=gap.id, cause="stop")
            result.items.append(verdict)
            return True
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason, note)
        return False

    def leave_out(item, reason, depends_on=(), note=None, picks=False, cause=None):
        """Leave the item out as a gap: True, or False when the copy stops here instead. `picks` says the item is a
        gap only because it picks, or may pick, faces of earlier gaps. `cause` is the `gap_hints` cause."""
        stop = gaps.stop_reason(ctx, reason)
        if stop is not None:
            result.over_gap_cap = gaps.at_cap(ctx)
            return refuse(item, stop, note if stop == reason else None)
        gap = ctx.leave_out(item, reason, depends_on, picks, cause)
        verdict = make_verdict(item, "leftOut", note=gap.reason)
        verdict["gap"] = gap.id
        verdict["cause"] = "picks" if picks else "own"
        result.items.append(verdict)
        return True

    made_in_component = False

    def visit(item):
        """One item: False when it stops the copy, else None (a step forced to a gap while diagnosing too)."""
        nonlocal made_in_component
        ctx.enter(item)
        item = ctx.current = _seen_before_split(item, ctx)
        reason = _skip_reason(item)
        if reason is not None:
            result.items.append(make_verdict(item, "skipped", note=reason))
            return None

        if step_kinds.is_assembly(item.get("type")):
            # Components, joints and the like: in component coordinates they never change the part's shape.
            if item.get("target_changed") is True:
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note())
                return refuse(item, "This step changes the part, which is not copied yet.")
            result.items.append(make_verdict(item, "skipped", note=""))
            return None

        if outside_component(item) and item.get("helper_of"):
            # A step of a tool body from another component: the Combine that takes the tool walks it.
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            return None

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
            return None

        if _lost_target(item, ctx):
            return refuse(item, "The body could not be followed through the timeline.")
        if item.get("bodies_after") is None:
            return refuse(item, "The bodies this step changes could not be read.")

        touches = _touches_target(item, ctx)
        if item.get("health") == "error" and (touches or not item.get("bodies_after")):
            return refuse(item, "This step does not build in Fusion.")

        handler = ctx.handlers.get(item.get("type"))
        if not touches and not item["bodies_after"] and (handler is None or _changes_named_bodies(item)):
            if item.get("target_changed") is False:
                result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
                return None
            if handler is not None or item.get("target_changed") is not True:
                # Only a step the reader saw change the body is a gap: one that may have done anything stops.
                return refuse(item, "The bodies this %s changes could not be read." % type_words(item["type"]))
            if not leave_out(item, "Steps of type %s are not copied yet." % type_words(item["type"]),
                             _gap_ids(ctx, item), cause=_type_cause(item)):
                return False
            made_in_component = True
            return None
        if not touches:
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            return None

        makes_other = bool(_new_bodies(item, ctx)) and not copies_bodies(item)
        if makes_other and item.get("target_changed") is False:
            # Another body made next to the part (a surface offset, for one): a later Combine that takes it walks it
            # as a tool.
            result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
            return None
        if makes_other or split_rules.is_split(item):
            # Later steps may belong to the other body, so no single missing step can stand for this one. A split
            # that keeps the body as one piece apart from the others is copied (split_rules.py), whichever piece
            # keeps the name of the body it split.
            stop = split_rules.stop_reason(item, ctx)
            if stop is not None:
                return refuse(item, stop)
        if handler is None and _only_splits_faces(item, ctx):
            note = wording.split_face_note(_label(item))
            result.items.append(make_verdict(item, "skipped", note=note))
            result.notes.append(note)
            return None
        if _data(item).get("read_error"):
            return refuse(item, "This step could not be read from Fusion.")
        if handler is None:
            spec = step_kinds.step_type(item["type"])
            if not leave_out(item, (spec and spec.unsupported)
                             or "Steps of type %s are not copied yet." % type_words(item["type"]),
                             _gap_ids(ctx, item), cause=_type_cause(item)):
                return False
            made_in_component = True
            return None
        picked, sure = gap_picks.picked_gaps(ctx, item)
        with ctx.recording() as brought:
            item = ctx.current = ref_motion.bring_in(borrowed.bring_in(item, ctx))
        if is_foreign(_data(item)):
            if not leave_out(item, ref_motion.why_foreign(item)
                             or "This step reaches into another component, which is not copied yet.",
                             [gap.id for gap in picked], wording.reaches_component_note(_label(item)),
                             cause=gap_hints.OTHER_COMPONENT):
                return False
            made_in_component = True
            return None
        made_in_component = True
        with ctx.recording() as construction:
            fix_construction(ctx, item)
        if picked:
            if not leave_out(item, wording.picks_gap_reason([gap.name for gap in picked], sure),
                             [gap.id for gap in picked], picks=True, cause=gap_hints.AFTER_GAP):
                return False
            return None
        outcome = run_handler(handler, item, ctx)
        if isinstance(outcome, Refusal):
            if outcome.stops:
                return refuse(item, outcome.reason)
            if outcome.over_gap_cap:
                result.over_gap_cap = True
                refuse(item, outcome.reason)
                if outcome.tool_steps:
                    result.items[-1]["tool_steps"] = outcome.tool_steps
                return False
            if not leave_out(item, outcome.reason, outcome.depends_on, cause=gap_hints.refusal_cause(outcome)):
                return False
            return None
        if floating.floats(ctx, outcome):
            if not leave_out(item, wording.floats_reason(), cause=gap_hints.AFTER_GAP):
                return False
            return None
        ctx.doubts.extend(brought.doubts + construction.doubts)
        ctx.commit(outcome)
        notes = brought.notes + outcome.notes
        if not outcome.entries:
            result.items.append(make_verdict(item, "skipped", note=" ".join(notes)))
            result.notes.extend(notes)
            return None
        if not ctx.steps and outcome.steps[0].get("combine") != "new":
            return refuse(item, "The body starts in a way that cannot be copied.")
        ids = ctx.add_steps(item, outcome)
        ctx.copied_items.append(item)
        if item.get("health") == "warning":
            notes.append(wording.health_warning_note(_label(item), item.get("message")))
        verdict = make_verdict(item, "translatedWithNote" if notes else "translated", ids, " ".join(notes))
        if outcome.tool_steps:
            verdict["tool_steps"] = outcome.tool_steps
        result.items.append(verdict)
        result.notes.extend(notes)
        return None

    for item in ctx.capture["items"]:
        if visit(item) is False:
            return False
    ctx.current = None
    return True
