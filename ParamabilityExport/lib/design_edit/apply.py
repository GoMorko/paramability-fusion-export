"""Apply one size row to the design and read back the resulting numbers."""
from ..package.units import to_manifest_value
from ..params.expressions.text import format_expression
from . import metered
from .store import timeline_control


class RowBuildError(Exception):
    """A size row cannot be built. The message is a plain sentence for the person.

    detail is a dict for report.json: "reason" (expression_refused, recompute_raised, recompute_failed or
    new_errors) plus the facts of that reason; "items" lists the names of the timeline items that went into error and
    "at" their timeline positions in the same order (None where the store gives no position).
    """

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = dict(detail or {})
        self.items = list(self.detail.get("items") or [])


def position(key):
    """The timeline position of an item keyed `key` in `error_entries` or `warning_entries`, or None when the key is
    no position (a store that keys its items by name)."""
    return key if isinstance(key, int) and not isinstance(key, bool) else None


def as_step(step):
    """`(position, name)` of a step given as that pair or as a name alone (position None)."""
    if isinstance(step, (list, tuple)) and len(step) == 2:
        return position(step[0]), step[1]
    return None, step


def detail_steps(detail):
    """`[(position, name)]` of the timeline items a `RowBuildError.detail` lists, in its order; position None where
    the detail gives none (a detail written before positions were kept)."""
    names = list((detail or {}).get("items") or ())
    at = list((detail or {}).get("at") or ())
    return [(position(at[i]) if i < len(at) else None, name) for i, name in enumerate(names)]


def _broken(health, baseline):
    """`[(position, name)]` of the timeline items in error in `health` that were not in error in `baseline`. Raises
    what the read of the errors raised."""
    return [(position(key), name) for key, name in health.errors.items() if key not in baseline.errors]


def _new_errors(broken, ok):
    """The `RowBuildError` of a row that left the steps `broken` (`[(position, name)]`) in error."""
    return RowBuildError(f"This size does not build in Fusion: {broken[0][1]}",
                         {"reason": "new_errors", "items": [name for _, name in broken],
                          "at": [at for at, _ in broken], "recompute_ok": ok})


class Baseline:
    """How the design recomputes with the parameters untouched: whether Fusion reported success, and the timeline
    items already in error and in warning, as {key: name}. Rows are judged against it, so a design with trouble
    elsewhere still gets its sizes checked."""

    def __init__(self, recompute_ok=True, errors=None, warnings=None):
        self.recompute_ok = recompute_ok
        self.errors = dict(errors or {})
        self.warnings = dict(warnings or {})


class Health:
    """The timeline items in error and in warning, read together in one pass over the timeline (`read`), as
    {key: name}. `errors` raises what the read of the errors raised, so a row whose errors cannot be read fails as
    before; `warnings` is None when the warnings could not be read, which gives no warning. A store with the
    `health_entries` control gives both in one pass; any other store gives them in one read each. Without
    `with_warnings` only the errors are read, and `warnings` stays None."""

    def __init__(self, store, with_warnings=True):
        self.store, self.with_warnings = store, with_warnings
        self._errors, self._failure, self.warnings = {}, None, None
        self.read()

    @property
    def errors(self):
        if self._failure is not None:
            raise self._failure
        return self._errors

    def read(self):
        """Read the items again, after a recompute. Never raises."""
        self._failure = None
        both = timeline_control(self.store, "health_entries") if self.with_warnings else None
        if both is not None:
            try:
                errors, warnings = both()
                self._errors, self.warnings = dict(errors), dict(warnings)
            except Exception as exc:
                self._errors, self._failure, self.warnings = {}, exc, None
            return
        try:
            self._errors = error_entries(self.store)
        except Exception as exc:
            self._errors, self._failure = {}, exc
        if not self.with_warnings:
            return
        try:
            self.warnings = warning_entries(self.store)
        except Exception:
            self.warnings = None


def error_entries(store):
    """{key: name} of the timeline items in error. The key tells apart items that share a name."""
    return dict(store.error_entries())


def warning_entries(store):
    """{key: name} of the timeline items in warning; empty for a store that does not read warnings."""
    read = timeline_control(store, "warning_entries")
    return dict(read()) if read is not None else {}


def new_warnings(store, baseline, counts=None, others=None, health=None):
    """`[(position, name)]` of the timeline items in warning now that were neither in warning nor in error in
    `baseline` (a `Baseline`): a step that a row made unsure. The position is the item's place in the timeline (None
    when the store gives none), so two items that share a name stay apart. `counts((position, name))` keeps only the
    steps that matter to the caller (all when None); the new warnings that do not count are added to the list `others`,
    when given, from the same read. `health` is the `Health` the row's own read gave; without it the items are read
    now. A step that reads in warning after a rebuild of only the changed steps is read again after one full
    recompute (`health` is read again, in place); a step that is in error after that recompute fails the row
    (RowBuildError, as `apply_row_values` raises it). Only a warning that counts leads to the recompute. An unreadable
    timeline gives no warning."""
    def read(note=None):
        try:
            if health.warnings is None:
                return []
            found = [(position(key), name) for key, name in health.warnings.items()
                     if key not in baseline.warnings and key not in baseline.errors]
            if note is not None and counts is not None:
                note.extend(step for step in found if not counts(step))
            return [step for step in found if counts is None or counts(step)]
        except Exception:
            return []

    health = health or Health(store)
    found = read(others)
    if found:
        with metered.caller(store, metered.COUNTING_WARNING):
            _recompute(store)
        health.read()
        broken = _broken(health, baseline)
        if broken:
            raise _new_errors(broken, True)
        found = read()
    return found


def cleared_errors(store, baseline, health=None):
    """`[(position, name)]` of the timeline items in error in `baseline` that are not in error now: steps that build
    with the values of a row although they did not at the start. A step the copy leaves out because Fusion shows it in
    error may then make a shape the copy does not have. `health` is the `Health` the row's own read gave; without it
    the items are read now. An unreadable timeline gives none. Never raises."""
    if not baseline.errors:
        return []
    try:
        now = (health or Health(store)).errors
    except Exception:
        return []
    return [(position(key), name) for key, name in baseline.errors.items() if key not in now]


def _set_each(store, expressions):
    """Set the expressions one at a time, then recompute; whether Fusion reported the recompute done. Raises
    RowBuildError when Fusion refuses an expression or the recompute raises."""
    for name, expression in expressions.items():
        try:
            store.set_expression(name, expression)
        except Exception as exc:
            raise RowBuildError(
                f"Fusion did not accept \"{expression}\" for {name}.",
                {"reason": "expression_refused", "parameter": name, "expression": expression}) from exc
    return _recompute(store)


def _recompute(store):
    """Recompute the whole design; whether Fusion reported it done. Raises RowBuildError when the recompute raises."""
    try:
        return store.recompute() is not False
    except Exception as exc:
        raise RowBuildError(
            "Fusion could not rebuild the design for this size.",
            {"reason": "recompute_raised", "error": f"{type(exc).__name__}: {exc}"[:200]}) from exc


def measure_baseline(store):
    """Recompute once with the parameters as they are and note the result and the items in error and in warning.
    Never raises."""
    with metered.caller(store, metered.BASELINE):
        try:
            ok = store.recompute() is not False
        except Exception:
            ok = False
    health = Health(store)
    try:
        errors = health.errors
    except Exception:
        errors = {}
    return Baseline(ok, errors, health.warnings or {})


def set_all(store, expressions):
    """Set every expression of `expressions` ({name: text}) in one change with one rebuild, when the store can
    (`set_expressions`, Fusion's `Design.modifyParameters`). True when it did; False, with nothing changed, when the
    store cannot or refused one of them: the caller then sets them one at a time. Never raises."""
    if not expressions:
        return False
    try:
        return store.set_expressions(dict(expressions)) is True
    except Exception:
        return False


def apply_row_values(store, units, values, baseline=None, full=False):
    """`apply_row`'s numbers: {name: number in mm or deg}."""
    return apply_row(store, units, values, baseline, full, with_warnings=False)[0]


def apply_row(store, units, values, baseline=None, full=False, with_warnings=True):
    """Set the row's values, rebuild, and return `({name: number in mm or deg}, health)`: the numbers, and the `Health`
    read after the last rebuild, for the checks that follow (`new_warnings`, `cleared_errors`). Without
    `with_warnings` the health holds only the errors.

    store is a `store.ParameterStore` (values in internal cm or rad). units maps parameter name to the Fusion unit
    string. baseline is `measure_baseline`'s result from before the first row; None
    means a clean design.

    The values go in as one change when the store can: Fusion rebuilds the steps they change once, as when the person
    edits the parameters, and no full recompute follows; that rebuild gives no answer of its own, so `recompute_ok`
    is None and only the steps in error judge the row. A step that reads in error then is judged after one full
    recompute: a rebuild of only the changed steps can leave an error that a full one clears.
    With `full` (a row whose STEP is written next) the design is recomputed in full after the change and judged by
    that recompute, as when each value is set in turn and the design is recomputed.
    The row fails when Fusion refuses an expression, the recompute raises, the recompute reports failure while
    the baseline did not, or timeline items went into error that were not in error in the baseline.
    """
    baseline = baseline or Baseline()
    expressions = {name: format_expression(value, units[name]) for name, value in values.items()}
    # After one change Fusion gives no answer for the rebuild as a whole (None): the steps in error decide alone.
    with metered.caller(store, metered.ROW):
        if set_all(store, expressions):
            ok = _recompute(store) if full else None
        else:
            ok = _set_each(store, expressions)
    health = Health(store, with_warnings)
    broken = _broken(health, baseline)
    if broken and ok is None:
        with metered.caller(store, metered.CONFIRM_NEW_ERRORS):
            _recompute(store)
        health.read()
        broken = _broken(health, baseline)
        if not broken:
            metered.note(store, metered.RESCUED)
    if broken:
        raise _new_errors(broken, ok)
    if ok is False and baseline.recompute_ok:
        raise RowBuildError("Fusion could not rebuild the design for this size.", {"reason": "recompute_failed"})
    return {name: to_manifest_value(store.read_value(name), units[name]) for name in values}, health
