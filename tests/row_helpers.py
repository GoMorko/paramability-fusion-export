"""Design-level wrappers around the row writer, for tests that work on a fake design."""
from tests import context  # noqa: F401
from lib.export_plan.apply import apply_row_values
from lib.export_plan.restore import restore_parameters
from lib.fusion_reader.rows import DesignParameterStore


def saved_expressions(design):
    return DesignParameterStore(design).saved_expressions()


def apply_row(design, values, units, baseline=None):
    """Set values (display units), recompute, return manifest numbers. Raises RowBuildError."""
    return apply_row_values(DesignParameterStore(design), units, values, baseline)


def restore(design, saved):
    """Put parameters back to the saved expressions. Returns the names that could not be restored."""
    return restore_parameters(DesignParameterStore(design), saved)
