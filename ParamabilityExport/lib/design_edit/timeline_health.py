"""The health of every timeline step at the start of an export, compared with the end, and what is done when they
differ. Pure: the store (`store.ParameterStore`) is passed in.

An export sets other values, rebuilds, moves the timeline marker and puts all of it back. A step that only just
builds (a fillet that barely fits, a sketch with two solutions) can come out of that in another state than before,
also with every value back: Fusion rebuilt it from another starting point, or only the steps a change touched were
rebuilt. `settle_timeline` reads the steps again once everything else is back, and when one differs from the start it
rebuilds the whole design once; when a step is still worse, it sets the start values once more and rebuilds again.
What is left is recorded for `report.json` (`health`) and told to the person.

A store gives the steps through its `timeline_health()` control (`DesignParameterStore`): a list of
`{ index, name, type, health, message, suppressed }` for the steps before the marker. A store without it gives only
the steps in error (`apply.error_entries`); the other steps then count as fine.
"""
from .apply import error_entries, set_all
from .restore import restore_parameters
from .store import timeline_control

OK, WARNING, ERROR = "ok", "warning", "error"
NEW, GONE = "new", "gone"  # a step that was not there at the start, or is not there at the end
_RANK = {OK: 0, WARNING: 1, ERROR: 2}

MAX_STEPS = 8  # steps listed in `report.json`
MAX_MESSAGE = 160

# What `settle_timeline` did, in `health.end_actions`.
FULL_COMPUTE = "full_compute"  # the whole design was rebuilt once because a step differed from the start
VALUES_AGAIN = "values_again"  # the start values were set once more, then the design was rebuilt
TURNED_ON = "turned_back_on"  # steps turned off during the export were turned back on
MARKER_BACK = "marker_back"  # the timeline marker read elsewhere and was put back
MARKER_LOST = "marker_lost"  # the timeline marker read elsewhere and would not go back


class TimelineRead:
    """The steps of the design at one moment: `steps` maps `(index, name)` to the step's record. `complete` is False
    when only the steps in error could be read: a step missing from `steps` then counts as fine."""

    def __init__(self, steps, complete=True):
        self.steps = dict(steps)
        self.complete = complete


def _step(entry):
    return {
        "index": entry.get("index"),
        "name": str(entry.get("name") or ""),
        "type": str(entry.get("type") or ""),
        "health": entry.get("health") if entry.get("health") in _RANK else OK,
        "message": str(entry.get("message") or "")[:MAX_MESSAGE],
        "suppressed": bool(entry.get("suppressed")),
    }


def read_timeline(store):
    """The steps as they are now (`TimelineRead`), or None when they cannot be read. Never raises."""
    full = timeline_control(store, "timeline_health")
    try:
        if full is not None:
            found = [_step(entry) for entry in full() or []]
            return TimelineRead({(s["index"], s["name"]): s for s in found})
        steps = {}
        for key, name in error_entries(store).items():
            steps[key] = _step({"index": key[0] if isinstance(key, tuple) else None, "name": name, "health": ERROR})
        return TimelineRead(steps, complete=False)
    except Exception:
        return None


def _missing(key, complete):
    """The record of a step a read does not hold: None (not there) for a complete read, fine for a read of only the
    steps in error."""
    if complete:
        return None
    index, name = key if isinstance(key, tuple) else (None, key)
    return _step({"index": index, "name": name})


def _order(key):
    index = key[0] if isinstance(key, tuple) else None
    return (index if isinstance(index, int) else -1, str(key))


def _state(step):
    if step is None:
        return None
    return (step["health"], step["message"], step["suppressed"])


def changes(before, after):
    """`[{ index, name, type, before, after, message, was_message?, suppressed? }]`, one per step whose health, message
    or suppression differs between two reads (`TimelineRead`), in timeline order. `before` is `NEW` for a step that
    was not there at the start, `after` is `GONE` for one that is not there now."""
    out = []
    for key in sorted(set(before.steps) | set(after.steps), key=_order):
        old = before.steps.get(key) or _missing(key, before.complete)
        new = after.steps.get(key) or _missing(key, after.complete)
        if _state(old) == _state(new):
            continue
        shown = new or old
        change = {"index": shown["index"], "name": shown["name"], "type": shown["type"],
                  "before": old["health"] if old else NEW, "after": new["health"] if new else GONE,
                  "message": new["message"] if new else ""}
        if old and new and old["message"] != new["message"] and old["message"]:
            change["was_message"] = old["message"]
        if old and new and old["suppressed"] != new["suppressed"]:
            change["suppressed"] = new["suppressed"]
        out.append(change)
    return out


def is_worse(change):
    """True when a step is in a worse state than at the start: a higher health level, turned off, gone, or new and
    not fine."""
    before, after = change["before"], change["after"]
    if after == GONE or change.get("suppressed") is True:
        return True
    if before == NEW:
        return after != OK
    return _RANK.get(after, 0) > _RANK.get(before, 0)


def _recompute(store, log):
    try:
        store.recompute()
    except Exception as exc:
        log(f"rebuilding the design after the export failed: {exc!r}")


def _values_again(store, saved, log):
    """Set every parameter to its start expression once more, in one change when the store can, then rebuild the whole
    design. Never raises."""
    try:
        if not set_all(store, dict(saved)):
            restore_parameters(store, saved)
    except Exception as exc:
        log(f"setting the start values again failed: {exc!r}")
    _recompute(store, log)


def _turn_on(store, found, log):
    """Turn back on the steps that were on at the start and read turned off now (`store.turn_on`). True when there
    were any."""
    off = [(c["index"], c["name"]) for c in found if c.get("suppressed") is True and isinstance(c["index"], int)]
    turn_on = timeline_control(store, "turn_on")
    if not off or turn_on is None:
        return False
    try:
        turn_on(off)
    except Exception as exc:
        log(f"turning steps back on after the export failed: {exc!r}")
    return True


def _marker_home(store, log):
    """`MARKER_BACK` or `MARKER_LOST` when the marker read away from where the store keeps it, else None."""
    try:
        moved = store.return_marker()
    except Exception as exc:
        log(f"checking the timeline marker failed: {exc!r}")
        return None
    return {"moved": MARKER_BACK, "lost": MARKER_LOST}.get(moved)


class TimelineSettle:
    """What `settle_timeline` found: `changed` lists the steps still not as at the start (`changes`), `recovered` the
    names of the steps that differed and came back, `actions` what was done, `unread` True when the steps could not be
    compared."""

    def __init__(self, changed=(), recovered=(), actions=(), unread=False):
        self.changed = list(changed)
        self.recovered = list(recovered)
        self.actions = list(actions)
        self.unread = unread

    @property
    def broken(self):
        """Names of the steps in error now that were not at the start."""
        return [c["name"] for c in self.changed if c["after"] == ERROR and c["before"] != ERROR]


def settle_timeline(store, start, saved, log=lambda text: None):
    """Compare the steps now with `start` (`read_timeline` at the start of the export) once everything else is put
    back, and bring back what can be brought back. Never raises.

    The marker goes back first when it reads elsewhere. When a step differs from the start, steps turned off since the
    start are turned back on (`TURNED_ON`) and the whole design is rebuilt once (`FULL_COMPUTE`): the last rebuild of
    an export may have been one of only the steps a change touched. When a
    step is then still worse than at the start (`is_worse`), the start values are set once more and the design rebuilt
    again (`VALUES_AGAIN`). A step that is only better than at the start (a warning gone) asks for no more rebuilds."""
    actions = []
    marker = _marker_home(store, log)
    if marker:
        actions.append(marker)
    if start is None:
        return TimelineSettle(actions=actions, unread=True)
    now = read_timeline(store)
    if now is None:
        return TimelineSettle(actions=actions, unread=True)
    first = changes(start, now)
    if first:
        if _turn_on(store, first, log):
            actions.append(TURNED_ON)
        _recompute(store, log)
        actions.append(FULL_COMPUTE)
        now = read_timeline(store) or now
        if any(is_worse(c) for c in changes(start, now)):
            _values_again(store, saved, log)
            actions.append(VALUES_AGAIN)
            now = read_timeline(store) or now
        marker = _marker_home(store, log)
        if marker and marker not in actions:
            actions.append(marker)
    left = changes(start, now)
    still = {c["name"] for c in left}
    recovered = list(dict.fromkeys(c["name"] for c in first if c["name"] not in still))
    return TimelineSettle(left, recovered, actions)


def record(settled):
    """The `health` keys of a `TimelineSettle` for `report.json`: `steps_changed` (at most `MAX_STEPS`, the rest
    counted in `steps_more`), `steps_worse` (true when any changed step is worse, listed or not), `steps_recovered`,
    `end_actions` and `steps_unread`. Only keys with something to say."""
    out = {}
    if settled is None:
        return out
    if settled.changed:
        out["steps_changed"] = [{k: v for k, v in c.items() if k != "index"} for c in settled.changed[:MAX_STEPS]]
        if len(settled.changed) > MAX_STEPS:
            out["steps_more"] = len(settled.changed) - MAX_STEPS
        if any(is_worse(c) for c in settled.changed):
            out["steps_worse"] = True
    if settled.recovered:
        out["steps_recovered"] = settled.recovered[:MAX_STEPS]
    if settled.actions:
        out["end_actions"] = list(settled.actions)
    if settled.unread:
        out["steps_unread"] = True
    return out
