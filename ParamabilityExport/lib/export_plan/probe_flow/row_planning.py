"""The rows a probe plans: near, pair, far, nearer and check rows."""
from ...probe import build, plan, plane_sizes, series
from .states import marked_states


class RowPlanning:
    """The row planning calls of `SizeProbe`."""

    def probe_rows(self, sizes, extra=()):
        """The first extra rows, near the value of each size that moves a sketch: the sizes the states already show
        moving one, every size that reaches a sketch, and every size that may move the plane a sketch sits on
        (`plane_sizes`). Then the sizes in `extra` (Fusion names tried on a guess, `extra_size_params`) while rows are
        left. Any other size that only feeds step values has no row. The far range ends come later (`far_rows`)."""
        current = {e.name: e.value for e in self.table.entries}
        self.moved = build.moved_sizes(self.capture, self.states, current)
        reach = set(plan.sketch_driven(self.table)) | set(plane_sizes.plane_driven(self.capture, self.table))
        moved = set(self.moved) | {s["param"] for s in sizes if s["param"] in reach}
        rows, self.untried = plan.probe_rows(sizes, moved, extra=set(extra))
        self._moving = set(moved)
        self._far = (moved, set(extra))
        return rows

    def _marked(self):
        """The states after E0, those whose own size changed a followed outline marked (`marked_states`)."""
        return marked_states(self.states, self.outline_changes())

    def pair_rows(self, sizes, room, states=None):
        """The near pair rows of the sizes `probe_rows` tried, within `room` rows (`plan.pair_rows`). `states` are the
        marked states to judge by, this probe's own by default."""
        if self._far is None:
            return []
        moved, extra = self._far
        return plan.pair_rows(sizes, moved, self._marked() if states is None else states, room, extra=extra)

    def far_rows(self, sizes, room, states=None):
        """The rows at the far range ends of the sizes `probe_rows` tried, within `room` rows (`plan.far_rows`), and
        then the far pair rows (`far_pair_rows`) once."""
        if self._far is None:
            return []
        moved, extra = self._far
        self._pairs, self._far = self._far, None
        return plan.far_rows(sizes, moved, room, extra=extra, states=self._marked() if states is None else states)

    def far_pair_rows(self, sizes, room, states=None):
        """Once, after the far rows: all sizes at their minimum, then at their maximum (`plan.far_pair_rows`)."""
        if self._pairs is None:
            return []
        moved, extra = self._pairs
        self._pairs = None
        return plan.far_pair_rows(sizes, moved, self._marked() if states is None else states, room, extra=extra)

    def nearer_rows(self, sizes, room):
        """The next rows that try the sizes nearer to their value now where rows did not build or changed a followed
        outline (`plan.nearer_rows`), within `room` rows and the export's `plan.MAX_NEARER_ROWS`."""
        rows = plan.nearer_rows(sizes, marked_states(self.states, self.outline_changes()), self.moving_sizes(),
                                min(room, plan.MAX_NEARER_ROWS - self.nearer_count))
        self.nearer_count += len(rows)
        return rows

    def curved_sizes(self):
        """`(curved, partners)` from the states so far (`series.curve_sizes`)."""
        try:
            motion = build.build(self.capture, self.table, self.states)
        except Exception:
            return [], []
        return series.curve_sizes(motion.values)

    def spans_now(self):
        """`Motion.spans` of the states so far."""
        return build.spans(self.states[1:], {e.name: e.value for e in self.table.entries})

    def check_rows(self, sizes, room):
        """Once per export: the rows that fit and check the values some size moves along a curve
        (`plan.check_rows`)."""
        if self.checked:
            return []
        self.checked = True
        curved, partners = self.curved_sizes()
        return plan.check_rows(sizes, curved, self.spans_now(), room, partners) if curved else []
