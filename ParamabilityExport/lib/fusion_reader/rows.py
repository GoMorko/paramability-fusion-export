"""Apply size rows to a design and put the parameters back. Works on the design object it is given."""
from ..export_plan.apply import apply_row_values
from ..export_plan.restore import restore_parameters


def _error_state():
    """Fusion's error health value; 2 when adsk.fusion cannot be imported (tests)."""
    try:
        import adsk.fusion
        return adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    except ImportError:
        return 2


class DesignParameterStore:
    """User parameters and timeline health of one design, shaped for export_plan."""

    def __init__(self, design):
        self.design = design

    def saved_expressions(self):
        params = self.design.userParameters
        return {params.item(i).name: params.item(i).expression for i in range(params.count)}

    current_expressions = saved_expressions

    def set_expression(self, name, expression):
        self.design.userParameters.itemByName(name).expression = expression

    def read_value(self, name):
        return self.design.userParameters.itemByName(name).value

    def recompute(self):
        return self.design.computeAll()

    def error_items(self):
        """Names of timeline items whose health is error. Empty for a design without a timeline."""
        try:
            timeline = self.design.timeline
            names = []
            error = _error_state()
            for i in range(timeline.count):
                item = timeline.item(i)
                if not item.isSuppressed and item.healthState == error:
                    names.append(item.name)
            return names
        except Exception:
            return []


def saved_expressions(design):
    return DesignParameterStore(design).saved_expressions()


def apply_row(design, values, units, baseline_errors=()):
    """Set values (display units), recompute, return manifest numbers. Raises RowBuildError."""
    return apply_row_values(DesignParameterStore(design), units, values, baseline_errors)


def restore(design, saved):
    """Put parameters back to the saved expressions. Returns the names that could not be restored."""
    return restore_parameters(DesignParameterStore(design), saved)
