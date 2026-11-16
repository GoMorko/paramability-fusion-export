"""The item loop: runs one handler per timeline item and writes the steps on the context.

The same loop copies the exported body and each tool body of a Combine. The context says what it builds
(`Context.target`, `Context.capture`, `Context.handlers`), so a handler always sees the body it works on as its target.

What each item is for the body (a sketch, an assembly item, a step of another component, a step of the body or of
another body) and the body before and after it come from the shared layer (`design_model/roles.py`); the walk decides
from them. An item the copy cannot hold either stops the copy or, when its effect stays on the body and the rest of
the timeline still reads right, is left out as a gap (gaps/stops.py). A gap is a step type with no handler, a
handler's Refusal, a step that reaches into another component, and a step that picks faces a gap made. What a left
out item would have recorded (doubts, notes) is dropped with it. Anything that leaves the body unknown still stops
the copy.
"""
from ..capture_model import gap_hints, gap_picks, step_kinds
from ..design_model import borrowed, refs, roles
from . import notes as wording
from .bodies import split_rules
from .faces import floating
from .gaps import stops
from .result import Refusal, StepResult, make_verdict
from .sizes import construction_fixes
from .words import type_words


def _refusal(item, reason, note=None, cause=None):
    """The refusal record of the result. `note` is the package note when it differs from the usual wording; `cause`
    (`gap_hints`) adds the `hint` that tells the person what to change in Fusion, when it has one."""
    out = {"index": item.get("index"), "name": item.get("name", ""), "type": item.get("type", ""), "reason": reason}
    if note:
        out["note"] = note
    found = gap_hints.hint(cause)
    if found:
        out["hint"] = found
    return out


def _label(item):
    return wording.step_label(item.get("name"), item.get("type")) or "A step"


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


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
        outcome.follows |= recorded.follows
    return outcome


def _type_cause(item):
    """The `gap_hints` cause of an item whose type the copy has no handler for."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec and spec.gap_cause) or gap_hints.UNSUPPORTED


def _unsupported_reason(item):
    """Why a step of a type with no handler is left out: the step kind table's reason, else the generic one."""
    spec = step_kinds.step_type(item.get("type"))
    return (spec and spec.unsupported) or "Steps of type %s are not copied yet." % type_words(item["type"])


def _gap_ids(ctx, item):
    """Ids of the gaps whose faces `item` picks, or may pick."""
    return [gap.id for gap in gap_picks.picked_gaps(ctx, item)[0]]


def walk_items(ctx, result):
    """Walk the items of `ctx.capture`: True when every item was dealt with, False when one stops the copy (then
    `result.refusal` says why). Verdicts and notes go to `result`, steps and doubts to `ctx`."""

    def refuse(item, reason, note=None, cause=None):
        """Stop the copy at `item`: False. A diagnosing walk (`Context.diagnose`) records the stop as a gap and goes
        on instead: True, unless there is no body to add the gap to yet. `cause` is the `gap_hints` cause, when the
        reason has one."""
        if ctx.diagnose and not stops.first_body_stop(ctx):
            gap = ctx.leave_out(item, reason, (), cause=cause)
            verdict = make_verdict(item, "leftOut", note=gap.reason)
            verdict.update(gap=gap.id, cause="stop")
            result.items.append(verdict)
            return True
        result.items.append(make_verdict(item, "unsupported", note=reason))
        result.refusal = _refusal(item, reason, note, cause)
        result.refusal_cause = cause
        return False

    def leave_out(item, reason, depends_on=(), note=None, picks=False, cause=None):
        """Leave the item out as a gap: True, or False when the copy stops here instead. `picks` says the item is a
        gap only because it picks, or may pick, faces of earlier gaps. `cause` is the `gap_hints` cause."""
        stop = stops.stop_reason(ctx, reason)
        if stop is not None:
            result.over_gap_cap = stops.at_cap(ctx)
            if stop != reason:
                return refuse(item, stop)
            return refuse(item, stop, note, cause)
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
        item = ctx.current = roles.seen_before_split(item, ctx.target, ctx.lineage)
        role = roles.role_of(item, ctx.target, ctx.lineage)
        if role.kind in (roles.SUPPRESSED, roles.NOT_A_STEP):
            note = "Suppressed in Fusion." if role.kind == roles.SUPPRESSED else ""
            result.items.append(make_verdict(item, "skipped", note=note))
            return None

        if role.kind == roles.ASSEMBLY:
            # Components, joints and the like: in component coordinates they never change the part's shape.
            if role.changed is True:
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note(),
                                  gap_hints.MADE_IN_OTHER_COMPONENT)
                return refuse(item, "This step changes the part, which is not copied yet.")
            result.items.append(make_verdict(item, "skipped", note=""))
            return None

        if role.kind == roles.TOOL_ELSEWHERE:
            # A step of a tool body from another component: the Combine that takes the tool walks it.
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            return None

        if role.kind == roles.OTHER_COMPONENT:
            # A step made in another component: harmless unless it changes the target.
            if role.changed is True or role.touches:
                if not made_in_component:
                    return refuse(item, "This body was made in another component and moved here later. "
                                  "Steps across components are not copied yet.", wording.made_elsewhere_note(),
                                  gap_hints.MADE_IN_OTHER_COMPONENT)
                return refuse(item, "This step changes the part from another component. "
                              "Steps across components are not copied yet.",
                              wording.from_other_component_note(_label(item)), gap_hints.CHANGED_FROM_OTHER_COMPONENT)
            result.items.append(make_verdict(item, "skipped", note="In another component."))
            return None

        if role.lost:
            return refuse(item, "The body could not be followed through the timeline.")
        if item.get("bodies_after") is None:
            return refuse(item, "The bodies this step changes could not be read.")

        touches = role.touches
        if item.get("health") == "error" and (touches or not item.get("bodies_after")):
            return refuse(item, "This step does not build in Fusion.")

        handler = ctx.handlers.get(item.get("type"))
        if not touches and not item["bodies_after"] and (handler is None or roles.changes_named_bodies(item)):
            if role.changed is False:
                result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
                return None
            if handler is not None or role.changed is not True:
                # Only a step the reader saw change the body is a gap: one that may have done anything stops.
                return refuse(item, "The bodies this %s changes could not be read." % type_words(item["type"]))
            if not leave_out(item, _unsupported_reason(item), _gap_ids(ctx, item), cause=_type_cause(item)):
                return False
            made_in_component = True
            return None
        if not touches:
            result.items.append(make_verdict(item, "skipped", note="Helper geometry, not part of the exported body."))
            return None

        if role.makes_other and role.changed is False:
            # Another body made next to the part (a surface offset, for one): a later Combine that takes it walks it
            # as a tool.
            result.items.append(make_verdict(item, "skipped", note="Does not change the exported body."))
            return None
        if role.makes_other or split_rules.is_split(item):
            # Later steps may belong to the other body, so no single missing step can stand for this one. A split
            # that keeps the body as one piece apart from the others is copied (bodies/split_rules.py), whichever piece
            # keeps the name of the body it split.
            stop = split_rules.stop_reason(item, ctx)
            if stop is not None:
                return refuse(item, stop)
        if handler is None and roles.only_splits_faces(item, role.bodies):
            note = wording.split_face_note(_label(item))
            result.items.append(make_verdict(item, "skipped", note=note))
            result.notes.append(note)
            return None
        if _data(item).get("read_error"):
            return refuse(item, "This step could not be read from Fusion.")
        if handler is None:
            if not leave_out(item, _unsupported_reason(item), _gap_ids(ctx, item), cause=_type_cause(item)):
                return False
            made_in_component = True
            return None
        picked, sure = gap_picks.picked_gaps(ctx, item)
        with ctx.recording() as brought:
            item = ctx.current = refs.bring_in(borrowed.bring_in(item, ctx))
        if refs.is_foreign(_data(item)):
            if refs.from_old_export(item):
                reason, note, cause = (
                    "This step reaches into another component, or was read by an older version of the add-in "
                    "that could not tell its own geometry apart. Export again with this version.",
                    wording.old_export_note(_label(item)), gap_hints.OLD_EXPORT)
            else:
                reason = (refs.why_foreign(item)
                          or "This step reaches into another component, which is not copied yet.")
                note, cause = wording.reaches_component_note(_label(item)), gap_hints.OTHER_COMPONENT
            if not leave_out(item, reason, [gap.id for gap in picked], note, cause=cause):
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
                return refuse(item, outcome.reason, cause=outcome.cause)
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
            if not leave_out(item, wording.floats_reason(), floating.sat_on(ctx, outcome), cause=gap_hints.AFTER_GAP):
                return False
            return None
        ctx.doubts.extend(brought.doubts + construction.doubts)
        ctx.follows |= brought.follows
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
