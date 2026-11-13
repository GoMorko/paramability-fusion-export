"""Settling the design after the tries: the end check of the timeline steps, the sketch gap and what stays off."""
from ...design_edit.timeline_health import FULL_COMPUTE, VALUES_AGAIN, read_timeline, settle_timeline


def settle_after_tries(owner, run):
    """Put every parameter back, turn the suppressed items back on (`owner._restore`, `owner._end_trim`) and put a
    sketch left on another solution back (`ProbeRun.settle`). Never raises, so it also runs when the tries ended with
    an error or a cancel. The run's sketch keeper is kept as `owner.keeper` for the health record."""
    owner.keeper = run.keeper
    try:
        owner._restore()
        owner._end_trim()
    except Exception as exc:
        owner.port.log(f"putting the design back after the tries failed: {exc!r}")
    run.settle()


def start_steps(owner):
    """The timeline steps at the start of the export: the read the request carries, taken before the dialog read the
    design, else one read now."""
    start = getattr(owner.request, "timeline_start", None)
    return start if start is not None else read_timeline(owner.port.store)


def settle_steps(owner):
    """Compare the timeline steps with the start and bring back what differs (`timeline_health.settle_timeline`), once
    per export, after the parameters, the suppressed items, the sketches and the marker are back. Items of the tries
    that would not turn back on and that this turned on leave `TryTimeline.left_off`."""
    if owner.settled is None:
        owner.settled = settle_timeline(owner.port.store, owner.steps_start, owner.saved, owner.port.log)
        roll = getattr(owner, "roll", None)
        if roll is not None and owner.settled.recovered:
            roll.back_on(owner.settled.recovered)
    return owner.settled


def gap_after_settle(owner, gap, measure):
    """`(gap, gap after)`: the sketch gap of the export once `settle_steps` is done. When it rebuilt the design, the
    outlines are read again (`measure()` reads and compares, None when it cannot tell) and the larger of the two gaps
    is kept, so a sketch that the rebuild moved counts as drift; `gap after` is that second gap, else None."""
    settled = owner.settled
    if settled is None or not any(a in (FULL_COMPUTE, VALUES_AGAIN) for a in settled.actions):
        return gap, None
    try:
        after = measure()
    except Exception as exc:
        owner.port.log(f"reading the sketches after the end rebuild failed: {exc!r}")
        return gap, None
    if after is None:
        return gap, None
    return (after if gap is None else max(gap, after)), after


def undo_dropped(owner):
    """True when Fusion forgot Undo data during the export (Lighter on memory, `undo_steps.UndoSteps`)."""
    steps = getattr(owner.port, "undo_steps", None)
    return bool(steps is not None and steps.record.get("applied"))


def left_off(owner):
    """The items of the tries still turned off (`TryTimeline.left_off`)."""
    return list(owner.roll.left_off) if getattr(owner, "roll", None) is not None else []


def deferred_left(owner):
    """Sketches whose compute flag the keeper could not put back (`SketchKeeper.deferred_left`)."""
    return list(getattr(getattr(owner, "keeper", None), "deferred_left", None) or [])
