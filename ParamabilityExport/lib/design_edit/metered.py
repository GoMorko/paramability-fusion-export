"""A parameter store that counts what the export asks of Fusion through it, for the timing record (`timing.probe.calls`):
each full recompute by the part of the export that asked for it, the parameter sets and put backs, the passes over the
timeline items for health and the reads of the whole timeline. Pure: the store it wraps is passed in.

The wrapper gives every other member of the store as it is, so a store without a timeline control still has none
(`store.timeline_control`). A count that cannot be made is dropped; the call itself always goes through."""
import contextlib

# What the counts are named in the timer. A recompute is `COMPUTE + label`.
COMPUTE = "call_compute_"
SETS = "call_sets"
PUT_BACKS = "call_put_backs"
HEALTH = "call_health"
TIMELINE = "call_timeline"
OUTCOME = "outcome_"

# The labels of recomputes, by the part of the export that asks for them (`MeteredStore.caller`).
ROW = "row"  # the rebuild that gives a row its numbers
COUNTING_WARNING = "counting_warning"  # one more rebuild because a row showed a warning that counts
CHECK_AFTER_ROW = "check_after_row"  # the rebuild of the check after a row that read worse
SKETCH_PUT_BACK = "sketch_put_back"
BASELINE = "baseline"
REBASE = "rebase"  # the baseline measured again after items were turned back on
END_CHECK = "end_check"
WALK_STEP = "walk_step"  # every rebuild made while a walk back runs
PUT_BACK_VALUES = "put_back_values"  # the rebuild after the parameters were set back
OTHER = "other"

# The outcomes `note` counts.
CHECK_CLEARED = "check_cleared"  # the rebuild of a check after which a step that read worse was fine


class MeteredStore:
    """`store` with the calls below counted on `timer` (`timing.timer.Timer`): `recompute` by the label set with
    `caller`, `set_expression` and `set_expressions`, `timeline_health`, `health_entries`, `error_entries` and
    `warning_entries`."""

    def __init__(self, store, timer):
        self._inner = store
        self._timer = timer
        self._labels = []

    @contextlib.contextmanager
    def caller(self, label):
        """The recomputes made inside the block count under `label`. A block inside another one counts under the outer
        label: a walk back that meets a row error counts all its rebuilds as the walk's."""
        self._labels.append(label)
        try:
            yield
        finally:
            self._labels.pop()

    def note(self, name):
        """Count one outcome (`CHECK_CLEARED`)."""
        try:
            self._timer.add(OUTCOME + name, 0.0)
        except Exception:
            pass

    def _call(self, name, function, args, kwargs):
        try:
            began = self._timer.clock()
        except Exception:
            return function(*args, **kwargs)
        try:
            return function(*args, **kwargs)
        finally:
            try:
                self._timer.add(name, self._timer.clock() - began)
            except Exception:
                pass

    def _sets_name(self):
        return PUT_BACKS if self._labels and self._labels[0] == PUT_BACK_VALUES else SETS

    def recompute(self, *args, **kwargs):
        return self._call(COMPUTE + (self._labels[0] if self._labels else OTHER), self._inner.recompute, args, kwargs)

    def set_expression(self, *args, **kwargs):
        return self._call(self._sets_name(), self._inner.set_expression, args, kwargs)

    def set_expressions(self, *args, **kwargs):
        return self._call(self._sets_name(), self._inner.set_expressions, args, kwargs)

    def __getattr__(self, name):
        member = getattr(self._inner, name)  # raises AttributeError for a member the store lacks
        counted = _COUNTED.get(name)
        if counted is None or not callable(member):
            return member
        return lambda *args, **kwargs: self._call(counted, member, args, kwargs)


_COUNTED = {"timeline_health": TIMELINE, "health_entries": HEALTH, "error_entries": HEALTH,
            "warning_entries": HEALTH}


def caller(owner, label):
    """`owner.caller(label)` when `owner` is a `MeteredStore`, else a block that does nothing."""
    return owner.caller(label) if isinstance(owner, MeteredStore) else contextlib.nullcontext()


def note(owner, name):
    """Count the outcome `name` when `owner` is a `MeteredStore`."""
    if isinstance(owner, MeteredStore):
        owner.note(name)
