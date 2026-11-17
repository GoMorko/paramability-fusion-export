"""Apply one size row to the design and read back the resulting numbers."""
from ..package.units import to_manifest_value
from ..params.expressions.text import format_expression
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


def _broken(store, baseline):
    """`[(position, name)]` of the timeline items in error now that were not in error in `baseline`."""
    return [(position(key), name) for key, name in error_entries(store).items() if key not in baseline.errors]


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


def error_entries(store):
    """{key: name} of the timeline items in error. The key tells apart items that share a name."""
    return dict(store.error_entries())


def warning_entries(store):
    """{key: name} of the timeline items in warning; empty for a store that does not read warnings."""
    read = timeline_control(store, "warning_entries")
    return dict(read()) if read is not None else {}


def new_warnings(store, baseline, counts=None, others=None):
    """`[(position, name)]` of the timeline items in warning now that were neither in warning nor in error in
    `baseline` (a `Baseline`): a step that a row made unsure. The position is the item's place in the timeline (None
    when the store gives none), so two items that share a name stay apart. `counts((position, name))` keeps only the
    steps that matter to the caller (all when None); the new warnings that do not count are added to the list `others`,
    when given, from the same read. A step that reads in warning after a rebuild of only the changed steps is read
    again after one full recompute; a step that is in error after that recompute fails the row (RowBuildError, as
    `apply_row_values` raises it). Only a warning that counts leads to the recompute. An unreadable timeline gives
    no warning."""
    def read(note=None):
        try:
            found = [(position(key), name) for key, name in warning_entries(store).items()
                     if key not in baseline.warnings and key not in baseline.errors]
        except Exception:
            return []
        if note is not None and counts is not None:
            note.extend(step for step in found if not counts(step))
        return [step for step in found if counts is None or counts(step)]

    found = read(others)
    if found:
        _recompute(store)
        broken = _broken(store, baseline)
        if broken:
            raise _new_errors(broken, True)
        found = read()
    return found


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
    try:
        ok = store.recompute() is not False
    except Exception:
        ok = False
    try:
        errors = error_entries(store)
    except Exception:
        errors = {}
    try:
        warnings = warning_entries(store)
    except Exception:
        warnings = {}
    return Baseline(ok, errors, warnings)


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
    """Set the row's values, rebuild, and return {name: number in mm or deg}.

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
    if set_all(store, expressions):
        ok = _recompute(store) if full else None
    else:
        ok = _set_each(store, expressions)
    broken = _broken(store, baseline)
    if broken and ok is None:
        _recompute(store)
        broken = _broken(store, baseline)
    if broken:
        raise _new_errors(broken, ok)
    if ok is False and baseline.recompute_ok:
        raise RowBuildError("Fusion could not rebuild the design for this size.", {"reason": "recompute_failed"})
    return {name: to_manifest_value(store.read_value(name), units[name]) for name in values}
