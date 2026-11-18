"""Apply size rows to a design and put the parameters back. Works on the design object it is given."""
from ..design_edit.marker import at_end, put_back, read_marker
from ..timing import trail
from . import read_geometry as geo


def _error_state():
    """Fusion's error health value; 2 when adsk.fusion cannot be imported (tests)."""
    try:
        import adsk.fusion
        return adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState
    except ImportError:
        return 2


def _warning_state():
    """Fusion's warning health value; 1 when adsk.fusion cannot be imported (tests)."""
    try:
        import adsk.fusion
        return adsk.fusion.FeatureHealthStates.WarningFeatureHealthState
    except ImportError:
        return 1


def _index_of(obj):
    """`TimelineObject.index` of `obj`, or None when it cannot be read."""
    try:
        index = obj.index
    except Exception:
        return None
    return index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else None


class DesignParameterStore:
    """User parameters and timeline health of one design, shaped for export_plan.

    The design is worked on as it is at the timeline marker: the marker found when the store is made stays there
    after every recompute, and only the items before it count for health. `roll_marker` holds it earlier for a while
    (Fusion then rebuilds fewer items per recompute) and `unroll_marker` puts it back. `suppress_items` turns off
    timeline items for a while for the same reason, and `unsuppress_items` turns them back on. A read may leave the
    marker earlier for a while (an outline face read before its step); the next change, recompute or `keep_marker`
    brings it back."""

    def __init__(self, design, value_input=None):
        self.design = design
        self._value_input = value_input  # text to a Fusion ValueInput; `adsk.core.ValueInput.createByString` if None
        self.marker = read_marker(getattr(design, "timeline", None))
        self._home = None  # the marker the store was made with, while it is rolled
        self._rolled_with = None  # the parameter expressions when the marker was rolled
        self._suppressed = []  # (name, timeline object) of the items `suppress_items` turned off

    def _rebuild(self):
        try:
            self.recompute()
        except Exception:
            pass

    def suppress_items(self, items):
        """Suppress the timeline items until `unsuppress_items`, in a trail stage (`_suppress_items`)."""
        with trail.stage("turn off %d timeline items" % len(items)):
            return self._suppress_items(items)

    def _suppress_items(self, items):
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
        """Turn the suppressed items back on, in a trail stage (`_unsuppress_items`)."""
        with trail.stage("turn on %d timeline items" % len(self._suppressed)):
            return self._unsuppress_items()

    def _unsuppress_items(self):
        """Turn the items `suppress_items` suppressed back on, last first, then rebuild once. Items that were
        suppressed before are never touched. Returns the names that still read suppressed."""
        pending = []
        for name, obj in reversed(self._suppressed):
            if self._set_on(obj):
                pending.append((name, obj, _index_of(obj)))
        left = self._on_with_marker_rolled(pending)
        had = bool(self._suppressed)
        self._suppressed = []
        if had:
            self._rebuild()
        return left

    @staticmethod
    def _set_on(obj):
        """Set `obj` to not suppressed. True when it still reads suppressed or cannot be read."""
        try:
            obj.isSuppressed = False
        except Exception:
            pass
        try:
            return bool(obj.isSuppressed)
        except Exception:
            return True

    def _on_with_marker_rolled(self, pending):
        """Turn on the `(name, object, index)` items of `pending` that a plain set could not turn on. Turning an item
        on makes Fusion rebuild the steps after it, and a later step that was already in error makes the set fail.
        With the marker held at the first of the items, Fusion does not rebuild past them. The marker goes back to
        where it was in every case; when it does not, the later marker check says so (`return_marker`). Returns the
        names that still read suppressed."""
        if not pending:
            return []
        start = read_marker(getattr(self.design, "timeline", None))
        indexes = [index for _, _, index in pending if index is not None]
        if start is None or not indexes or min(indexes) >= start["position"]:
            return [name for name, _, _ in pending]
        lowest = min(indexes)
        left = []
        try:
            self.design.timeline.markerPosition = lowest
        except Exception:
            pass
        try:
            left = [name for name, obj, _ in pending if self._set_on(obj)]
        finally:
            back = self._put_marker(start, "turn on")
        trail.line("turned on %d of %d timeline items with the marker held at step %d%s" % (
            len(pending) - len(left), len(pending), lowest, "" if back else "; the marker did not go back"))
        return left

    def turn_on(self, steps):
        """Turn the listed items on, in a trail stage (`_turn_on`)."""
        with trail.stage("turn on %d timeline items (end check)" % len(steps)):
            return self._turn_on(steps)

    def _turn_on(self, steps):
        """Unsuppress the timeline items `steps` ((index, name) pairs) that read suppressed, skipping an index that now
        holds another name. Returns the names that still read suppressed. The caller rebuilds."""
        left, pending = [], []
        for index, name in steps:
            try:
                obj = self.design.timeline.item(index)
                if obj.name != name or not obj.isSuppressed:
                    continue
            except Exception:
                left.append(name)
                continue
            if self._set_on(obj):
                pending.append((name, obj, index))
        return left + self._on_with_marker_rolled(pending)

    def _keep_marker(self):
        if self.marker is not None:
            self._put_marker(self.marker, "keep")

    def _put_marker(self, marker, what):
        """`put_back` of the marker to `marker` (`marker.put_back`), in a trail stage when the marker reads elsewhere."""
        timeline = self.design.timeline
        try:
            now = timeline.markerPosition
            there = timeline.count if at_end(marker) else marker["position"]
        except Exception:
            return put_back(timeline, marker)
        if now == there:
            return put_back(timeline, marker)
        with trail.stage("marker %s to %s (%s)" % (now, there, what)):
            return put_back(timeline, marker)

    def return_marker(self):
        """Put the marker back where the store keeps it when it reads elsewhere: "" when it was there or cannot be
        read, "moved" when it was put back, "lost" when it would not go back."""
        if self.marker is None:
            return ""
        timeline = self.design.timeline
        try:
            there = timeline.count if at_end(self.marker) else self.marker["position"]
            if timeline.markerPosition == there:
                return ""
        except Exception:
            return ""
        return "moved" if self._put_marker(self.marker, "return") else "lost"

    def keep_marker(self):
        """Move the marker back to where the store holds it, when a read left it earlier. True when it reads there (or
        there is no timeline)."""
        if self.marker is None:
            return True
        try:
            return self._put_marker(self.marker, "keep")
        except Exception:
            return False

    def _expressions(self):
        try:
            return self.saved_expressions()
        except Exception:
            return None

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
        self._rolled_with = self._expressions()
        if self._put_marker(self.marker, "roll"):
            return True
        self.unroll_marker()
        return False

    def unroll_marker(self):
        """Put the marker back where the store found it. Fusion builds the items after the rolled position as the
        marker passes them. When a parameter expression differs from the roll, or cannot be read, the design is also
        rebuilt once, so every item is built with the values set now. True when the marker reads there."""
        if self._home is None:
            return True
        self.marker, self._home = self._home, None
        moved = self._put_marker(self.marker, "unroll")
        before, self._rolled_with = self._rolled_with, None
        if before is None or self._expressions() != before:
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
        trail.line("set %s = %s" % (name, expression))
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
        trail.line("set %s" % ", ".join("%s = %s" % pair for pair in expressions.items()))
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
            with trail.stage("recompute"):
                return self.design.computeAll()
        finally:
            self._keep_marker()

    def error_entries(self):
        """(timeline position, name) of each item before the marker whose health is error. Empty for a design
        without a timeline."""
        return self._entries_in(_error_state())

    def warning_entries(self):
        """(timeline position, name) of each item before the marker whose health is warning. Empty for a design
        without a timeline."""
        return self._entries_in(_warning_state())

    def health_entries(self):
        """`(errors, warnings)`: the items `error_entries` and `warning_entries` give, read in one pass over the
        timeline. Both empty when the timeline cannot be read."""
        try:
            timeline = self.design.timeline
            error, warning = _error_state(), _warning_state()
            errors, warnings = [], []
            end = timeline.count if self.marker is None else min(self.marker["position"], timeline.count)
            for i in range(end):
                item = timeline.item(i)
                if item.isSuppressed:
                    continue
                state = item.healthState
                if state == error:
                    errors.append((i, item.name))
                elif state == warning:
                    warnings.append((i, item.name))
            return errors, warnings
        except Exception:
            return [], []

    def _entries_in(self, state):
        """(timeline position, name) of each item before the marker that is not suppressed and whose health
        (`TimelineObject.healthState`) is `state`. Empty when the timeline cannot be read."""
        try:
            timeline = self.design.timeline
            entries = []
            end = timeline.count if self.marker is None else min(self.marker["position"], timeline.count)
            for i in range(end):
                item = timeline.item(i)
                if not item.isSuppressed and item.healthState == state:
                    entries.append((i, item.name))
            return entries
        except Exception:
            return []

    def timeline_health(self, known=None):
        """`{ index, name, type, health, message, suppressed }` of each item before the marker where the store found
        it (groups left out), for `design_edit.timeline_health`. Raises when the timeline cannot be read. `known` is
        `{(index, name): (health, suppressed)}` of an earlier read: an item that is fine and has that health and
        suppression is given with `type` and `message` None, and its entity and message are not read."""
        timeline = self.design.timeline
        home = self._home or self.marker
        end = timeline.count if home is None else min(home["position"], timeline.count)
        steps = []
        for i in range(end):
            item = timeline.item(i)
            if geo.safe(lambda: item.isGroup, False):
                continue
            name = geo.safe(lambda: item.name, "")
            health = geo.safe(lambda: geo.health_name(item.healthState), "ok")
            suppressed = bool(geo.safe(lambda: item.isSuppressed, False))
            if known is not None and health == "ok" and known.get((i, name)) == (health, suppressed):
                steps.append({"index": i, "name": name, "type": None, "health": health, "message": None,
                              "suppressed": suppressed})
                continue
            steps.append({
                "index": i,
                "name": name,
                "type": geo.type_name(geo.safe(lambda: item.entity, None)),
                "health": health,
                "message": geo.safe(lambda: item.errorOrWarningMessage or "", ""),
                "suppressed": suppressed,
            })
        return steps

    def error_items(self):
        """Names of the timeline items whose health is error."""
        return [name for _, name in self.error_entries()]

