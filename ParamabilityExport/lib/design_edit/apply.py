"""Apply one size row to the design and read back the resulting numbers."""
from ..package.units import to_manifest_value
from ..params.expressions import format_expression


class RowBuildError(Exception):
    """A size row cannot be built. The message is a plain sentence for the person.

    detail is a dict for report.json: "reason" (expression_refused, recompute_raised, recompute_failed or
    new_errors) plus the facts of that reason; "items" lists the timeline items that went into error.
    """

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = dict(detail or {})
        self.items = list(self.detail.get("items") or [])


class Baseline:
    """How the design recomputes with the parameters untouched: whether Fusion reported success, and the timeline
    items already in error, as {key: name}. Rows are judged against it, so a design with trouble elsewhere still
    gets its sizes checked."""

    def __init__(self, recompute_ok=True, errors=None):
        self.recompute_ok = recompute_ok
        self.errors = dict(errors or {})


def error_entries(store):
    """{key: name} of the timeline items in error. The key tells apart items that share a name."""
    entries = getattr(store, "error_entries", None)
    if callable(entries):
        return dict(entries())
    return {name: name for name in store.error_items()}


def new_errors(store, before):
    """Names of the timeline items in error now that were not in error in `before` ({key: name}, as `error_entries`).
    A rebuild after one change (`set_all`) rebuilds only the steps it changed, so when some step reads in error the
    design is recomputed in full once and read again: only what stays in error counts. Never raises: an unreadable
    timeline gives none."""
    def read():
        try:
            return [name for key, name in error_entries(store).items() if key not in before]
        except Exception:
            return []

    found = read()
    if found:
        try:
            store.recompute()
        except Exception:
            pass
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
    """Recompute once with the parameters as they are and note the result and the items in error. Never raises."""
    try:
        ok = store.recompute() is not False
    except Exception:
        ok = False
    try:
        errors = error_entries(store)
    except Exception:
        errors = {}
    return Baseline(ok, errors)


def set_all(store, expressions):
    """Set every expression of `expressions` ({name: text}) in one change with one rebuild, when the store can
    (`set_expressions`, Fusion's `Design.modifyParameters`). True when it did; False, with nothing changed, when the
    store cannot or refused one of them: the caller then sets them one at a time. Never raises."""
    batch = getattr(store, "set_expressions", None)
    if not callable(batch) or not expressions:
        return False
    try:
        return batch(dict(expressions)) is True
    except Exception:
        return False


def apply_row_values(store, units, values, baseline=None, full=False):
    """Set the row's values, rebuild, and return {name: number in mm or deg}.

    store needs set_expression, recompute, error_items and read_value (internal cm or rad); error_entries
    (pairs of item key and name) is used when it has one, and set_expressions (`set_all`) when it has one. units maps
    parameter name to the Fusion unit string. baseline is `measure_baseline`'s result from before the first row; None
    means a clean design.

    The values go in as one change when the store can: Fusion rebuilds the steps they change once, as when the person
    edits the parameters, and no full recompute follows; that rebuild gives no answer of its own, so `recompute_ok`
    is None and only the steps in error judge the row. A step that reads in error then is judged after one full
    recompute, as `new_errors` does: a rebuild of only the changed steps can leave an error that a full one clears.
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
    broken = [n for key, n in error_entries(store).items() if key not in baseline.errors]
    if broken and ok is None:
        _recompute(store)
        broken = [n for key, n in error_entries(store).items() if key not in baseline.errors]
    if broken:
        raise RowBuildError(
            f"This size does not build in Fusion: {broken[0]}",
            {"reason": "new_errors", "items": broken, "recompute_ok": ok})
    if ok is False and baseline.recompute_ok:
        raise RowBuildError("Fusion could not rebuild the design for this size.", {"reason": "recompute_failed"})
    return {name: to_manifest_value(store.read_value(name), units[name]) for name in values}
