"""Unused timeline items turned off while the sketch tries run. Pure: no Fusion imports.

Every try rebuilds each item before the timeline marker, also the items of other components the picked body does not
use. `unused_items` lists the items that can be suppressed for the tries; `TimelineTrim` suppresses them through the
parameter store (`DesignParameterStore.suppress_items`) and turns them back on when the tries end. It runs on every
export unless the person unticks "Faster tries" in the dialog. The discovery tries, which look for links to other
components that the capture cannot show, run with every item back on (`pipeline.ProbeRun.discover`).

The capture does not say which item is built from which, so a component is the unit of trust: an item of another
component is suppressed only when no item of that component is needed by the tries (`marker_roll.needed_items`, the
evidence the marker roll uses). An item is suppressed when all of these hold:
- it comes before the stop point (the items each try rebuilds) and is not suppressed already;
- it belongs to a named component other than the ones of the picked bodies;
- no item of its component is needed by the tries;
- it is not an assembly item (an occurrence, a joint and the like) and it has a name to check it by.
Nothing is suppressed when the evidence cannot be matched (as in `needed_position`), when a link or reference leaves
the component it depends on unnamed and its step cannot be found, when a needed item has no component, when an item
before the stop point has a type the step kind table does not know and that does not read as a body feature
(`marker_roll.is_feature`), or when an assembly item other than an occurrence comes before the stop point
(a joint or a rigid group can hang on geometry of any component).

`TryTimeline` holds the marker roll and the suppression together for one export, with the time the tries took. Its
record goes to `report.json` under `probe.timeline`.
"""
import time

from ..capture_model import step_kinds
from ..design_edit.store import timeline_control
from .marker_roll import NO_ROLL_WHY, MarkerRoll, marker_end, is_feature, needed_items, unbounded_link

NO_TRIM_WHY = dict(NO_ROLL_WHY, **{
    "unlinked": "a link or reference does not name the component it depends on",
    "no_component": "a step the tries need could not be matched to a component",
    "unknown_type": "a step of a type the add-in does not know comes before the stop point",
    "assembly": "a joint or another assembly step can depend on any component",
    "nothing_unused": "every step before the stop point may be needed",
})


def _token(value):
    return value if isinstance(value, str) and value else None


def _capture_unused(capture, stop):
    """`({index: name}, reason)`: the items of one capture that may be suppressed, or `(None, key of NO_TRIM_WHY)`."""
    needed, why = needed_items(capture)
    if needed is None:
        return None, why
    if unbounded_link(capture):
        return None, "unlinked"
    own = _token(((capture.get("target") or {}).get("component") or {}).get("token"))
    if own is None:
        return None, "no_component"
    kept = {own}
    for item in needed:
        if item.get("type") == "Occurrence":
            continue  # never suppressed, and it makes no item of its component needed
        token = _token(item.get("component"))
        if token is None:
            return None, "no_component"
        kept.add(token)
    active = [i for i in capture.get("items") or []
              if isinstance(i, dict) and isinstance(i.get("index"), int) and i["index"] < stop
              and not i.get("suppressed")]
    found = {}
    for item in active:
        spec = step_kinds.step_type(item.get("type"))
        if (spec is None and not is_feature(item)) or (spec is not None and spec.role == step_kinds.UNREAD):
            return None, "unknown_type"
        if spec is not None and spec.role == step_kinds.ASSEMBLY:
            if item.get("type") != "Occurrence":
                return None, "assembly"
            continue
        token = _token(item.get("component"))
        if item.get("in_target_component") is False and token and token not in kept and item.get("name"):
            found[item["index"]] = item["name"]
    return found, ""


def unused_items(captures, stop):
    """`(items, reason)`: the `(index, name)` of the timeline items the tries of these captures do not need, before
    `stop` (the items each try rebuilds), or `([], key of NO_TRIM_WHY)`. Several captures share one timeline: an item
    is listed only when every capture can do without it. Captures that are not dicts have no tries."""
    found = [c for c in captures if isinstance(c, dict)]
    end = marker_end(found)
    if not found or end is None or not isinstance(stop, int):
        return [], "no_marker"
    common = None
    for capture in found:
        picked, why = _capture_unused(capture, min(stop, end))
        if picked is None:
            return [], why
        common = picked if common is None else {i: n for i, n in common.items() if picked.get(i) == n}
    if not common:
        return [], "nothing_unused"
    return sorted(common.items()), ""


class TimelineTrim:
    """The unused items suppressed for the tries of one export. `record` is `{ asked, on, items, reason?, left_off? }`:
    whether the dialog box was ticked (it is by default), whether the tries ran with items suppressed, how many, why
    not, and the items that would not turn back on. `left_off` lists those names too.

    store: the parameter store; one without `suppress_items` never suppresses. log(text): a line for the log."""

    def __init__(self, store, log, asked):
        self.store, self.log = store, log
        self.record = {"asked": bool(asked), "on": False, "items": 0}
        self.left_off = []
        self._off = False

    def _errors(self):
        try:
            return set(self.store.error_items())
        except Exception:
            return set()

    def begin(self, captures, stop, unchanged):
        """Suppress the unused items unless the person turned it off. `unchanged()` is called with them suppressed and
        says whether the design still reads as it did at the start (`SizeProbe.matches_start`); when it says no or
        raises, or a step shows a new error, every item is turned back on and the tries run as without the option."""
        if not self.record["asked"]:
            return
        picked, why = unused_items(captures, stop)
        if not picked:
            self.record["reason"] = NO_TRIM_WHY[why]
            return
        suppress = timeline_control(self.store, "suppress_items")
        if suppress is None:
            self.record["reason"] = "the design has no timeline steps to turn off"
            return
        before = self._errors()
        count = 0
        # The store turns back on whatever it tried to turn off, also an item it could not count as off.
        self._off = True
        try:
            count = suppress(picked)
            if count != len(picked):
                self.record["reason"] = "the unused steps could not all be turned off"
            elif not unchanged():
                self.record["reason"] = "the body reads differently with the unused steps off"
            elif self._errors() - before:
                self.record["reason"] = "a step shows an error with the unused steps off"
        except Exception as exc:
            self.log(f"turning off unused steps failed: {exc!r}")
            self.record["reason"] = "the body could not be read with the unused steps off"
        if "reason" in self.record:
            self.end()
        else:
            self.record.update(on=True, items=count)

    def end(self):
        """Turn the suppressed items back on. Safe to call at any time and more than once. True when there were
        items to turn on (turned off for the tries and not yet back on), else False."""
        if not self._off:
            return False
        self._off = False
        try:
            self.left_off = list(self.store.unsuppress_items())
        except Exception as exc:
            self.log(f"turning steps back on failed: {exc!r}")
            self.left_off = ["(unknown)"]
        if self.left_off:
            self.log("steps still turned off: " + ", ".join(self.left_off))
            self.record["left_off"] = list(self.left_off)
        return True

    def back_on(self, names):
        """Drop from `left_off` the items a later step turned back on (`names`, the end check's recovered steps)."""
        names = set(names)
        self.left_off = [name for name in self.left_off if name not in names]
        if self.left_off:
            self.record["left_off"] = list(self.left_off)
        else:
            self.record.pop("left_off", None)


class TryTimeline:
    """The timeline as the tries of one export keep it: the marker held early (`MarkerRoll`), the unused items
    suppressed unless `faster` is off (`TimelineTrim`), and how long the tries took.

    `record` is `MarkerRoll.record` plus `suppressed` (`TimelineTrim.record`) and `try_seconds`."""

    def __init__(self, store, log, faster=True):
        self.roll = MarkerRoll(store, log)
        self.trim = TimelineTrim(store, log, faster)
        self._started = None
        self.seconds = None

    def begin(self, captures, unchanged):
        self.roll.begin(captures, unchanged)
        self.trim.begin(captures, self.roll.record["items"], unchanged)
        self._started = time.monotonic()

    def tries_done(self):
        """Note the time the tries took; only the first call counts."""
        if self._started is not None and self.seconds is None:
            self.seconds = round(time.monotonic() - self._started, 1)

    def end_trim(self):
        """Turn the suppressed items back on, before any read that checks the design. True when items were turned on."""
        return self.trim.end()

    def end(self):
        """Turn the items back on, then put the marker back. Safe to call at any time and more than once."""
        self.trim.end()
        self.roll.end()

    def back_on(self, names):
        self.trim.back_on(names)

    @property
    def left_off(self):
        return self.trim.left_off

    @property
    def record(self):
        if self.roll.record is None:
            return None
        return dict(self.roll.record, suppressed=dict(self.trim.record), try_seconds=self.seconds)
