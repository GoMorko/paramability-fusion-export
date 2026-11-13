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
    (Fusion then rebuilds fewer items per recompute) and `unroll_marker` puts it back. `suppress_items` turns off
    timeline items for a while for the same reason, and `unsuppress_items` turns them back on."""

    def __init__(self, design, value_input=None):
        self.design = design
        self._value_input = value_input  # text to a Fusion ValueInput; `adsk.core.ValueInput.createByString` if None
        self.marker = read_marker(getattr(design, "timeline", None))
        self._home = None  # the marker the store was made with, while it is rolled
        self._suppressed = []  # (name, timeline object) of the items `suppress_items` turned off

    def _rebuild(self):
        try:
            self.recompute()
        except Exception:
            pass

    def suppress_items(self, items):
        """Suppress the timeline items `items` ((index, name) pairs) until `unsuppress_items`, then rebuild once.
        Returns how many read suppressed after. Nothing is touched, and 0 is returned, when one of them is not as the
        capture saw it: another name at that index, suppressed already, a group, or unreadable."""
        if self._suppressed:
            return 0
        try:
            timeline = self.design.timeline
            found = [timeline.item(index) for index, _ in items]
            if any(obj.name != name or obj.isSuppressed or getattr(obj, "isGroup", False)
                   for obj, (_, name) in zip(found, items)):
                return 0
        except Exception:
            return 0
        count = 0
        for obj, (_, name) in zip(found, items):
            try:
                obj.isSuppressed = True
            except Exception:
                pass
            try:
                off = obj.isSuppressed
            except Exception:
                off = None  # unreadable: not counted, but turned back on at the end
            if off is not False:
                self._suppressed.append((name, obj))
                count += off is True
        self._rebuild()
        return count

    def unsuppress_items(self):
        """Turn the items `suppress_items` suppressed back on, last first, then rebuild once. Items that were
        suppressed before are never touched. Returns the names that still read suppressed."""
        left = []
        for name, obj in reversed(self._suppressed):
            try:
                obj.isSuppressed = False
            except Exception:
                pass
            try:
                off = obj.isSuppressed
            except Exception:
                off = True
            if off:
                left.append(name)
        had = bool(self._suppressed)
        self._suppressed = []
        if had:
            self._rebuild()
        return left

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
        self._rebuild()
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

    def _make_value(self):
        if self._value_input is None:
            import adsk.core
            self._value_input = adsk.core.ValueInput.createByString
        return self._value_input

    def set_expressions(self, expressions):
        """Set the user parameters `expressions` ({name: text}) in one change (`Design.modifyParameters`): Fusion sets
        all or none and rebuilds once, as for the person's own edit. True when it took them all; False, with nothing
        changed, when this Fusion has no such call, a parameter is missing or Fusion refused one. The marker stays
        where the store keeps it."""
        modify = getattr(self.design, "modifyParameters", None)
        if modify is None or not expressions:
            return False
        try:
            params = self.design.userParameters
            found = [params.itemByName(name) for name in expressions]
            if any(p is None for p in found):
                return False
            make = self._make_value()
            done = bool(modify(found, [make(text) for text in expressions.values()]))
        except Exception:
            return False
        self._keep_marker()
        return done

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

