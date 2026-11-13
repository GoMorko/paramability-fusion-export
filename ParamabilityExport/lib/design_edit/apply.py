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


def new_errors(store, baseline):
    """Names of the timeline items in error now that were not in error in `baseline`. Never raises: an unreadable
    timeline gives none."""
    try:
        return [name for key, name in error_entries(store).items() if key not in baseline.errors]
    except Exception:
        return []


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


def apply_row_values(store, units, values, baseline=None):
    """Set the row's values, recompute, and return {name: number in mm or deg}.

    store needs set_expression, recompute, error_items and read_value (internal cm or rad); error_entries
    (pairs of item key and name) is used when it has one. units maps parameter name to the Fusion unit string.
    baseline is `measure_baseline`'s result from before the first row; None means a clean design.

    The row fails when Fusion refuses an expression, the recompute raises, the recompute reports failure while
    the baseline did not, or timeline items went into error that were not in error in the baseline.
    """
    baseline = baseline or Baseline()
    for name, value in values.items():
        expression = format_expression(value, units[name])
        try:
            store.set_expression(name, expression)
        except Exception as exc:
            raise RowBuildError(
                f"Fusion did not accept \"{expression}\" for {name}.",
                {"reason": "expression_refused", "parameter": name, "expression": expression}) from exc
    try:
        ok = store.recompute() is not False
    except Exception as exc:
        raise RowBuildError(
            "Fusion could not rebuild the design for this size.",
            {"reason": "recompute_raised", "error": f"{type(exc).__name__}: {exc}"[:200]}) from exc
    new_errors = [n for key, n in error_entries(store).items() if key not in baseline.errors]
    if new_errors:
        raise RowBuildError(
            f"This size does not build in Fusion: {new_errors[0]}",
            {"reason": "new_errors", "items": new_errors, "recompute_ok": ok})
    if not ok and baseline.recompute_ok:
        raise RowBuildError("Fusion could not rebuild the design for this size.", {"reason": "recompute_failed"})
    return {name: to_manifest_value(store.read_value(name), units[name]) for name in values}
