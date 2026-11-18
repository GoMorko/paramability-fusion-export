"""The timing summary of the size tries for `report.json` (`timing.probe`), from the timer of the try runner
(`ProbeRun.timer`). Pure: no Fusion."""
from ...design_edit import metered
from ...timing.timer import rounded

# The parts of a probe read the Fusion reader times (`fusion_reader.probe_state.read_state`).
READ_PARTS = ("sketches", "points", "params", "refs", "box", "pieces", "faces")


def summary(timer, tries, time_limit, timed_out, left_out):
    """How the time of the tries went: `tries` rows run, `rebuild` (the rows without the reads made inside them:
    setting the sizes, rebuilding the design, putting them back), the state `read`s with the time of their parts
    (`read_parts`: sketches, points and lines, params, refs, box, the pieces of the part, faces), the `put_back` of
    sketches, the `calls` made to Fusion (`calls`) and the `time_limit` record (`time_limit_record`). `left_out()` gives the sizes the time limit left
    without a try (`Probe.time_left_out`). Never raises."""
    try:
        return {
            "tries": tries,
            "tries_seconds": rounded(timer.seconds("rows")),
            "rebuild": rounded(max(0.0, timer.seconds("rows") - timer.seconds("read_in_rows"))),
            "read": timer.entry("read"),
            "read_parts": {name: timer.entry("read_" + name) for name in READ_PARTS if timer.count("read_" + name)},
            "put_back": timer.entry("put_back"),
            "calls": calls(timer),
            "time_limit": time_limit_record(time_limit, timed_out, left_out),
        }
    except Exception:
        return None


def calls(timer):
    """What the tries asked of Fusion through the counting store (`metered.MeteredStore`), each as `{ count, seconds }`:
    `computes` (full rebuilds, by the part of the export that asked), `param_sets` (values set for a try or a walk),
    `param_put_backs`, `health_passes` (passes over the timeline items for errors and warnings) and `timeline_reads`
    (reads of the whole timeline); and one outcome as a count: `check_cleared` (a rebuild of a check after which a step
    that read worse was fine). These are the calls of the tries. The calls of the put back
    after the tries are in `calls.after_tries` (`note_after_tries`)."""
    return {
        "computes": {name[len(metered.COMPUTE):]: timer.entry(name) for name in timer.names(metered.COMPUTE)},
        "param_sets": timer.entry(metered.SETS),
        "param_put_backs": timer.entry(metered.PUT_BACKS),
        "health_passes": timer.entry(metered.HEALTH),
        "timeline_reads": timer.entry(metered.TIMELINE),
        "check_cleared": timer.count(metered.OUTCOME + metered.CHECK_CLEARED),
    }


def note_after_tries(found, timer):
    """The probe's timing summary `found` with `after_tries`: the calls the put back asked of the store once the tries
    were done (`calls` of `timer`: the values put back, and the end check under the label `metered.END_CHECK`). It is
    set again each time it is called, so it always holds all calls so far. Changes `found` in place and returns it.
    Never raises."""
    try:
        if isinstance(found, dict) and "calls" in found:
            found["calls"]["after_tries"] = calls(timer)
    except Exception:
        pass
    return found


def time_limit_record(time_limit, timed_out, left_out):
    """`{ limit_seconds, hit, left_out }`: the limit (None for no limit), whether it stopped the tries (`timed_out` is
    its record, else None), and, when it did, the sizes it left without a try (`left_out()`)."""
    record = {"limit_seconds": time_limit, "hit": timed_out is not None}
    if timed_out is not None:
        record["left_out"] = list(left_out())
    return record


def with_try_seconds(found, roll):
    """The probe's timing summary `found` with the time the tries took as `TryTimeline` counted it (`probe.timeline`)."""
    try:
        return dict(found, try_seconds=roll.seconds) if found is not None and roll is not None else found
    except Exception:
        return found
