"""Where a probe is in its row phases, and the limits of the rows it plans more than once. Pure: no Fusion."""
from ...probe import plan

# The row phases, in order. The near rows (`SizeProbe.probe_rows`) start the schedule; the near pair rows and the far
# rows come in the near phase, the far rows end it (planned one size at a time, the last call for all sizes left), and
# the far pair rows come once after them.
NOT_PLANNED = "not planned"
NEAR = "near"
FAR = "far"
DONE = "done"


class RowSchedule:
    """The row phase of one probe, the sizes its near rows tried, the sizes whose far rows it planned, how many nearer
    rows it planned and whether it planned its check rows. `ProbeGroup` keeps one for the nearer and check rows its
    parts share."""

    def __init__(self):
        self.phase = NOT_PLANNED
        self.moved = set()  # the sizes the near rows tried because they move a sketch or a measured place
        self.extra = set()  # the sizes the near rows tried on a guess
        self.far_done = set()  # the sizes whose far rows were planned (`far_sizes`)
        self.nearer_count = 0
        self.checked = False

    def planned(self, moved, extra):
        """The near rows were planned for `moved` and `extra`: the near pair rows and the far rows may follow."""
        self.phase, self.moved, self.extra = NEAR, set(moved), set(extra)

    def take(self, phase, then=None):
        """`(moved, extra)` when the schedule is at `phase`, moving it on to `then` when given; else None."""
        if self.phase != phase:
            return None
        if then is not None:
            self.phase = then
        return self.moved, self.extra

    def far_sizes(self, order, only=None):
        """The Fusion names in `order` (`plan.far_order`) whose far rows are planned now, noted as planned: those in
        `only` not planned yet, and the schedule stays at the near phase so the next size can have its far rows; or,
        without `only`, every one not planned yet, and the phase moves on to FAR. None when the schedule is not at the
        near phase."""
        if self.phase != NEAR:
            return None
        names = [name for name in order if name not in self.far_done and (only is None or name in only)]
        self.far_done.update(names)
        if only is None:
            self.phase = FAR
        return names

    def nearer_room(self, room):
        """How many nearer rows fit in `room` rows and what `plan.MAX_NEARER_ROWS` leaves."""
        return min(room, plan.MAX_NEARER_ROWS - self.nearer_count)

    def count_nearer(self, rows):
        self.nearer_count += len(rows)

    def check_once(self):
        """True the first time only: the check rows are planned once per export."""
        if self.checked:
            return False
        self.checked = True
        return True
