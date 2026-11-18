"""The timing summary of the size tries for `report.json` (`timing.probe`), from the timer of the try runner
(`ProbeRun.timer`). Pure: no Fusion."""
from ...timing.timer import rounded

# The parts of a probe read the Fusion reader times (`fusion_reader.probe_state.read_state`).
READ_PARTS = ("sketches", "points", "params", "refs", "box", "pieces", "faces")


def summary(timer, tries, time_limit, timed_out, left_out):
    """How the time of the tries went: `tries` rows run, `rebuild` (the rows without the reads made inside them:
    setting the sizes, rebuilding the design, putting them back), the state `read`s with the time of their parts
    (`read_parts`: sketches, points and lines, params, refs, box, the pieces of the part, faces), the `put_back` of
    sketches and the `time_limit` record (`time_limit_record`). `left_out()` gives the sizes the time limit left
    without a try (`Probe.time_left_out`). Never raises."""
    try:
        return {
            "tries": tries,
            "tries_seconds": rounded(timer.seconds("rows")),
            "rebuild": rounded(max(0.0, timer.seconds("rows") - timer.seconds("read_in_rows"))),
            "read": timer.entry("read"),
            "read_parts": {name: timer.entry("read_" + name) for name in READ_PARTS if timer.count("read_" + name)},
            "put_back": timer.entry("put_back"),
            "time_limit": time_limit_record(time_limit, timed_out, left_out),
        }
    except Exception:
        return None


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
