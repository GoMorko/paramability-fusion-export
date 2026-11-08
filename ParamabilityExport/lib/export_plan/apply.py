"""Apply one size row to the design and read back the resulting numbers."""
from ..package.units import to_manifest_value
from .expressions import format_expression


class RowBuildError(Exception):
    """A size row cannot be built. The message is a plain sentence for the person."""


def apply_row_values(store, units, values, baseline_errors=()):
    """Set the row's values, recompute, and return {name: number in mm or deg}.

    store needs set_expression, recompute, error_items and read_value (internal cm or rad).
    units maps parameter name to the Fusion unit string. baseline_errors are timeline items that were
    already in error before the export started.
    """
    for name, value in values.items():
        expression = format_expression(value, units[name])
        try:
            store.set_expression(name, expression)
        except Exception as exc:
            raise RowBuildError(f"Fusion did not accept \"{expression}\" for {name}.") from exc
    try:
        ok = store.recompute()
    except Exception as exc:
        raise RowBuildError("Fusion could not rebuild the design for this size.") from exc
    if ok is False:
        raise RowBuildError("Fusion could not rebuild the design for this size.")
    new_errors = [n for n in store.error_items() if n not in baseline_errors]
    if new_errors:
        raise RowBuildError(f"This size does not build in Fusion: {new_errors[0]}")
    return {name: to_manifest_value(store.read_value(name), units[name]) for name in values}
