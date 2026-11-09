"""Apply size rows to a design and put the parameters back. Works on the design object it is given."""
from ..design_edit.marker import put_back, read_marker


def _error_state():
    """Fusion's error health value; 2 when adsk.fusion cannot be imported (tests)."""
    try:
        import adsk.fusion
        return adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    except ImportError:
        return 2


class DesignParameterStore:
    """User parameters and timeline health of one design, shaped for export_plan.

    The design is worked on as it is at the timeline marker: the marker found when the store is made stays there
    after every recompute, and only the items before it count for health."""

    def __init__(self, design):
        self.design = design
        self.marker = read_marker(getattr(design, "timeline", None))

    def _keep_marker(self):
        if self.marker is not None:
            put_back(self.design.timeline, self.marker)

    def saved_expressions(self):
        params = self.design.userParameters
        return {params.item(i).name: params.item(i).expression for i in range(params.count)}

    current_expressions = saved_expressions

    def set_expression(self, name, expression):
        self.design.userParameters.itemByName(name).expression = expression

    def read_value(self, name):
        return self.design.userParameters.itemByName(name).value

    def recompute(self):
        try:
            return self.design.computeAll()
        finally:
            self._keep_marker()

    def error_entries(self):
        """(timeline position, name) of each item before the marker whose health is error. Empty for a design
        without a timeline."""
        try:
            timeline = self.design.timeline
            entries = []
            error = _error_state()
            end = timeline.count if self.marker is None else min(self.marker["position"], timeline.count)
            for i in range(end):
                item = timeline.item(i)
                if not item.isSuppressed and item.healthState == error:
                    entries.append((i, item.name))
            return entries
        except Exception:
            return []

    def error_items(self):
        """Names of the timeline items whose health is error."""
        return [name for _, name in self.error_entries()]

