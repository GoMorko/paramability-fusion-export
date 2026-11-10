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
    after every recompute, and only the items before it count for health. `roll_marker` holds it earlier for a while
    (Fusion then rebuilds fewer items per recompute) and `unroll_marker` puts it back."""

    def __init__(self, design):
        self.design = design
        self.marker = read_marker(getattr(design, "timeline", None))
        self._home = None  # the marker the store was made with, while it is rolled

    def _keep_marker(self):
        if self.marker is not None:
            put_back(self.design.timeline, self.marker)

    def roll_marker(self, position):
        """Hold the marker at `position` (that many items stay built) until `unroll_marker`. False, with the marker
        back where it was, when there is no timeline, it is rolled already, the position is not before the marker or
        Fusion does not move it there."""
        if self.marker is None or self._home is not None:
            return False
        end = min(self.marker["position"], self.marker["count"])
        if not 0 < position < end:
            return False
        self._home, self.marker = self.marker, {"position": position, "count": self.marker["count"]}
        if put_back(self.design.timeline, self.marker):
            return True
        self.unroll_marker()
        return False

    def unroll_marker(self):
        """Put the marker back where the store found it and rebuild once, so the items after the rolled position are
        built with the values set now. True when the marker reads there."""
        if self._home is None:
            return True
        self.marker, self._home = self._home, None
        moved = put_back(self.design.timeline, self.marker)
        try:
            self.recompute()
        except Exception:
            pass
        return moved

    def marker_holds(self):
        """False when the marker sits before the position the store keeps it at (a read would then miss items the
        tries need); a marker further on only costs time. True when the timeline cannot be read."""
        if self.marker is None:
            return True
        try:
            return self.design.timeline.markerPosition >= min(self.marker["position"], self.marker["count"])
        except Exception:
            return True

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

