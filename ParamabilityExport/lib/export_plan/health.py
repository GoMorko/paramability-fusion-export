"""How the design came out of an export, and what to tell the person about it. Pure: no Fusion imports.

An export changes parameters many times and puts them back. After that the design must be as it was, and the sketch
measuring must have worked. `make_health` records what is known, `health_lines` says in plain words what is wrong and
what to do, and `measuring_doubtful` tells when the recipe rests on measurements that cannot be trusted.
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from ..design_edit import timeline_health as steps_module
from ..geometry.tolerances import RESTORE_TOLERANCE_MM
from ..package.text import clip
from ..probe.plan import RETRY_NOTE

MEASURED, NOT_NEEDED, FAILED = "measured", "not needed", "failed"
MAX_LISTED = 5
MAX_NOTE = 200
MAX_LINE = 400

UNDO_ADVICE = (
    "Use Undo in Fusion until the design looks as it did before the export, or reopen the design from its last "
    "save. Then export again.")
# With Lighter on memory on, Fusion forgot the Undo data of the tries (`undo_steps`), so Undo is not offered.
NO_UNDO_ADVICE = (
    "Undo may not step back through this export, since Lighter on memory was on. If the design looks wrong, close "
    "it without saving and open the version you saved before the export.")


@dataclass
class HealthInputs:
    """What an export knows at its end about how the design came out (`pipeline.put_back.PutBack.health_inputs`).

    unrestored: Fusion names of the parameters that could not be put back.
    gap_mm: how far the sketches are from their start after the restore, None when that was not measured.
    probe: MEASURED, NOT_NEEDED (no sketch to follow) or FAILED (sketches exist but could not be measured).
    probe_error: why the probe failed, else empty.
    unchecked: why the restore could not be checked, one text per sketch ("Sketch3 reads another outline").
    flipped: names of the sketches that stayed on another outline for a while after the values were put back
      (`Motion.flipped`); the tries made then blamed no size.
    stopped: `{ after, items }` when a try left the design broken with the values back and the tries stopped there
      (`RowExport.not_back`).
    broken: names of the timeline steps in error after the export that were not in error before it; taken from
      `steps` when that could compare the steps.
    steps: the `design_edit.timeline_health.TimelineSettle` of the export: the steps whose health differs from the
      start, and what was done to bring them back (`timeline_health.record` gives its keys).
    deferred_left: sketches whose compute flag would not go back after their points were moved
      (`SketchKeeper.deferred_left`).
    gap_after_mm: the gap read again after the end check rebuilt the design, already counted in `gap_mm`; None when
      there was no such rebuild or read.
    left_off: timeline items turned off for the tries that are still off (`TryTimeline.left_off`).
    undo_dropped: True when Fusion forgot Undo data during the export (Lighter on memory, `undo_steps`).
    outlines_changed: the followed sketches the restore check found on another outline or a turned plane, compared
      by their curves (`SizeProbe.restore_changed`), one text per sketch.
    body_changed: what of the part's body clearly differs from its start once the design is back
      (`SizeProbe.measure_body`, `states.BodyCheck.clear`).
    body_small: small differences of the body (`states.BodyCheck.small`): a change when the end check also finds an
      outline, a step or a value changed, or the tries stopped on a damaged design; else not confirmed.
    body_unconfirmed: differences of the body that appeared only after the end check rebuilt the whole design.
    body_unchecked: True when the body could not be compared at the end.
    """

    unrestored: Sequence = ()
    gap_mm: Optional[float] = None
    probe: str = NOT_NEEDED
    probe_error: str = ""
    unchecked: Sequence = ()
    flipped: Sequence = ()
    stopped: Optional[dict] = None
    broken: Sequence = ()
    steps: Optional[object] = None
    deferred_left: Sequence = ()
    gap_after_mm: Optional[float] = None
    left_off: Sequence = ()
    undo_dropped: bool = False
    outlines_changed: Sequence = ()
    body_changed: Sequence = ()
    body_small: Sequence = ()
    body_unconfirmed: Sequence = ()
    body_unchecked: bool = False


def make_health(inputs):
    """The record kept in `report.json` under `health`, from the `HealthInputs` of the export."""
    gap_mm, steps = inputs.gap_mm, inputs.steps
    measured = inputs.probe == MEASURED
    out = {
        "unrestored": list(inputs.unrestored),
        "sketch_gap_mm": gap_mm,
        "sketch_drift": gap_mm is not None and gap_mm > RESTORE_TOLERANCE_MM,
        "restore_unverified": measured and gap_mm is None,
        "probe": inputs.probe,
        "probe_error": inputs.probe_error[:200],
    }
    if measured and gap_mm is None and inputs.unchecked:
        out["unchecked"] = list(inputs.unchecked)[:MAX_LISTED]
    if measured and inputs.flipped:
        out["flipped"] = list(dict.fromkeys(inputs.flipped))[:MAX_LISTED]
    if inputs.stopped:
        stopped = inputs.stopped
        out["tries_stopped"] = {"after": stopped.get("after") or "", "items": list(stopped.get("items") or [])[:MAX_LISTED]}
        if stopped.get("steps"):
            out["tries_stopped"]["steps"] = [dict(step) for step in stopped["steps"][:MAX_LISTED]]
    broken = steps.broken if steps is not None and not steps.unread else inputs.broken
    if broken:
        out["broken"] = list(dict.fromkeys(broken))[:MAX_LISTED]
    out.update(steps_module.record(steps))
    if inputs.deferred_left:
        out["deferred_left"] = list(dict.fromkeys(inputs.deferred_left))[:MAX_LISTED]
    if inputs.gap_after_mm is not None:
        out["sketch_gap_after_rebuild_mm"] = inputs.gap_after_mm
    if inputs.left_off:
        out["left_off"] = list(dict.fromkeys(inputs.left_off))[:MAX_LISTED]
    if inputs.undo_dropped:
        out["undo_dropped"] = True
    if measured and inputs.outlines_changed:
        out["outlines_changed"] = list(dict.fromkeys(inputs.outlines_changed))[:MAX_LISTED]
    # A small difference of the body is a change only when something else shows the design changed.
    small = list(inputs.body_small)
    backed = design_changed(out) or bool(out.get("tries_stopped"))
    changed = list(inputs.body_changed) + (small if backed else [])
    unconfirmed = list(inputs.body_unconfirmed) + ([] if backed else small)
    if changed:
        out["body_changed"] = list(dict.fromkeys(changed))[:MAX_LISTED]
    if unconfirmed:
        out["body_unconfirmed"] = list(dict.fromkeys(unconfirmed))[:MAX_LISTED]
    if inputs.body_unchecked:
        out["body_unchecked"] = True
    return out


def any_worse(health):
    """True when a step is in a worse state than at the start (`timeline_health.is_worse`), also one past the steps
    `steps_changed` lists (`steps_worse`)."""
    health = health or {}
    return bool(health.get("steps_worse")) or any(
        steps_module.is_worse(c) for c in health.get("steps_changed") or [])


def design_changed(health):
    """True when the design may differ from before the export: a parameter not put back, sketches that moved or read
    another outline, a body that differs, steps in a worse state than before, or a sketch left with its compute
    deferred."""
    return bool(health and (health.get("unrestored") or health.get("sketch_drift") or health.get("broken")
                            or health.get("outlines_changed") or health.get("body_changed")
                            or any_worse(health) or health.get("deferred_left")))


def back_as_it_was(health):
    """True only when the end check confirms the design is as it was before the export: every value back, no sketch
    drift, no step worse or left turned off, nothing left deferred, no difference of the body, and every check that
    tells this could be made (the steps read, the sketches compared, the marker back). After tries that stopped on a
    damaged design, the sketches and the body must also have been compared; the stop alone does not count."""
    if not health or design_changed(health) or health.get("left_off"):
        return False
    if health.get("steps_unread") or health.get("restore_unverified") or health.get("body_unconfirmed"):
        return False
    # Tries that stopped on a damaged design are back only when the end check also compared the sketches and the body.
    if health.get("tries_stopped") and (health.get("probe") != MEASURED or health.get("sketch_gap_mm") is None
                                        or health.get("body_unchecked")):
        return False
    if steps_module.MARKER_LOST in (health.get("end_actions") or []):
        return False
    return not (health.get("probe") == FAILED and health.get("sketch_gap_mm") is None)


def _undo(health):
    """What to do about a changed design: Undo, unless the export made Fusion forget Undo data."""
    return NO_UNDO_ADVICE if (health or {}).get("undo_dropped") else UNDO_ADVICE


def measuring_doubtful(health):
    """True when sketch sizes were measured on a design that did not come back to its start."""
    return design_changed(health)


def _names(names):
    shown = ", ".join(names[:MAX_LISTED])
    return shown + (" and %d more" % (len(names) - MAX_LISTED) if len(names) > MAX_LISTED else "")


def _step_text(change):
    """One changed step for a line: "Fillet3 (now a warning)", "Sketch2 (warning gone)"."""
    before, after, name = change.get("before"), change.get("after"), change.get("name") or "a step"
    level = {"warning": "a warning", "error": "an error"}
    if after == steps_module.GONE:
        what = "gone"
    elif change.get("suppressed") is True:
        what = "turned off"
    elif change.get("suppressed") is False:
        what = "turned back on"
    elif before == steps_module.NEW:
        what = "new" if after == steps_module.OK else "new, with %s" % level.get(after, after)
    elif after == steps_module.OK:
        what = "%s gone" % before
    elif after == before:
        what = "another %s" % after
    else:
        what = "now %s" % level.get(after, after)
    return "%s (%s)" % (name, what)


def steps_line(health):
    """The line about steps whose health differs from the start of the export, or None."""
    changed = (health or {}).get("steps_changed") or []
    if not changed:
        return None
    shown = ", ".join(_step_text(c) for c in changed[:MAX_LISTED])
    more = len(changed) - MAX_LISTED + (health.get("steps_more") or 0)
    if more > 0:
        shown += " and %d more" % more
    if any_worse(health):
        tail = ("Fusion rebuilt the design with your values and they stayed so, so your design may be changed. "
                + _undo(health))
    elif health.get("undo_dropped"):
        tail = "Check them in the timeline. " + NO_UNDO_ADVICE
    else:
        tail = "Check them in the timeline, and use Undo in Fusion if they look wrong."
    text = "After the export these steps differ from before: %s. " + tail
    # The list is cut, not the advice after it.
    return text % clip(shown, max(40, MAX_LINE - len(text) + 2))


def _stopped_line(stopped):
    """The line about tries that stopped because a try left steps worse than before even with the values back: which
    try, and which steps in what state."""
    # The try label of a retried row ends with a note for the progress window, which does not fit inside this line.
    after = (stopped.get("after") or "").replace(RETRY_NOTE, "") or "a value"
    steps = stopped.get("steps") or []
    if steps and any(step.get("after") != steps_module.ERROR for step in steps):
        shown = ", ".join(_step_text(step) for step in steps[:MAX_LISTED])
        text = ("The tries stopped early: after trying %s, these steps stayed changed even with your values back: %s. "
                "Only the tries before it were used." % (after, shown))
    else:
        text = ("The tries stopped early: after trying %s, Fusion could not rebuild %s even with your values back. Only "
                "the tries before it were used." % (after, _names(stopped.get("items") or []) or "the design"))
    return clip(text, MAX_LINE)


def _changed_line(text, found, health):
    """`text` with the things found that changed, then that the design is changed and what to do. The list is cut,
    not the advice after it."""
    tail = " Your design is changed. " + _undo(health)
    return clip(text % "; ".join(found), max(60, MAX_LINE - len(tail))) + tail


def health_lines(health):
    """Plain sentences for the result window, most important first. Empty when all is well: the lines about the
    design (`design_lines`), then those about the copy (`copy_lines`)."""
    return design_lines(health) + copy_lines(health)


def design_lines(health):
    """The lines about the state of the design after the export: what did not come back, what could not be checked."""
    if not health:
        return []
    lines = []
    if health.get("unrestored"):
        lines.append(
            "These parameters could not be set back to their values: %s. Your design is changed. %s"
            % (_names(health["unrestored"]), _undo(health)))
    line = steps_line(health)
    if line:
        lines.append(line)
    elif health.get("broken"):
        lines.append(clip(
            "After the export these steps of your design show an error they did not have before: %s. Your design is "
            "changed. %s" % (_names(health["broken"]), _undo(health)), MAX_LINE))
    if health.get("outlines_changed"):
        lines.append(_changed_line("These sketches did not come back to their first shape after the tries: %s.",
                                   health["outlines_changed"], health))
    if health.get("body_changed"):
        lines.append(_changed_line("The part did not come back as it was after the tries: %s.",
                                   health["body_changed"], health))
    if health.get("body_unconfirmed"):
        lines.append(clip("Could not confirm that the part came back as it was after the tries: %s differed slightly "
                          "at the end. Please look at it in Fusion." % "; ".join(health["body_unconfirmed"]), MAX_LINE))
    if health.get("sketch_drift"):
        lines.append(
            "The sketches did not come back to their first shape after the tries (largest gap %.4g mm). "
            "Your design may be changed, and sizes that move a sketch may be off. %s"
            % (health["sketch_gap_mm"], _undo(health)))
    elif health.get("restore_unverified") and health.get("unchecked"):
        lines.append(clip("Could not check that the sketches came back to their first shape: %s. Please look at %s "
                          "in Fusion." % ("; ".join(health["unchecked"]),
                                          "it" if len(health["unchecked"]) == 1 else "them"), MAX_LINE))
    elif health.get("restore_unverified"):
        lines.append("Could not check that the sketches came back to their first shape. Please look at them.")
    if health.get("deferred_left"):
        fix = (" " + NO_UNDO_ADVICE) if health.get("undo_dropped") else ", or use Undo in Fusion."
        lines.append(clip("These sketches may not update until you edit them: %s. Open each one and finish it%s"
                          % (_names(health["deferred_left"]), "." + fix if fix.startswith(" ") else fix), MAX_LINE))
    return lines


def copy_lines(health):
    """The lines about the copy the export made: sketches that stayed on another solution during the tries, tries that
    stopped early, sketches that could not be measured. They still hold after Fusion undid the export."""
    if not health:
        return []
    lines = []
    if health.get("flipped"):
        lines.append(clip("During the tries Fusion left %s on its other solution after a value was put back. The "
                          "tries made while it stayed there were not used to judge any size." % _names(health["flipped"]),
                          MAX_LINE))
    stopped = health.get("tries_stopped")
    if stopped:
        lines.append(_stopped_line(stopped))
    if health.get("probe") == FAILED:
        lines.append(
            "The sketches could not be measured, so sizes that move a sketch may give unexpected results.")
    return lines


def left_off_line(names, undo_dropped=False):
    """The message about timeline items of the faster tries that would not turn back on (`TryTimeline.left_off`)."""
    fix = NO_UNDO_ADVICE if undo_dropped else "Or use Undo in Fusion."
    return ("These timeline steps could not be turned back on after the tries: %s.\nIn the timeline, right click each "
            "one and pick Unsuppress. %s" % (", ".join(names), fix))


def steps_lines(settled, deferred_left=(), undo_dropped=False):
    """The lines about the timeline steps (`timeline_health.TimelineSettle`) and the sketches left deferred alone, for
    an export that stopped or keeps no other health record."""
    return health_lines(make_health(HealthInputs(steps=settled, deferred_left=deferred_left,
                                                 undo_dropped=undo_dropped)))


def measuring_note(health):
    """The package note for a recipe built on doubtful sketch measurements, else ''."""
    if not measuring_doubtful(health):
        return ""
    return clip("Sketch sizes may be off: the design did not come back to its start while they were measured.",
                MAX_NOTE)


def with_lines(text, health):
    """`text` with the health sentences added below it, for a message box."""
    lines = health_lines(health)
    return text + "".join("\n\n" + line for line in lines)
