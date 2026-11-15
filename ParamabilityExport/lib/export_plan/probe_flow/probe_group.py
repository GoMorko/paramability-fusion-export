"""The probes of several parts of one export, run over one set of rows."""
from ...package.manifest import MAX_FIXED_REASON
from ...package.text import clip
from ...probe import plan
from ..part_names import tagged
from .row_schedule import RowSchedule
from .shadow import shadow_of
from .states import marked_states


class ProbeGroup:
    """The probes of several parts of one export, run over one set of rows.

    Every part has its own `SizeProbe` (its sketches, references and motion), all over the same size table. The rows
    are the same for all of them (sizes that move a sketch of any part), so Fusion recomputes once per row and each
    probe reads its own part there. The row limit (`plan.MAX_PROBE_ROWS`) is for the whole export, not per part. It
    has every member of `interface.Probe`; a read is a list with one entry per probe. Each part's probe keeps its own
    row phase; the group keeps the nearer and check rows the parts share (`schedule`).
    """

    def __init__(self, probes, names):
        self.probes = list(probes)
        self.names = list(names)
        self.table = self.probes[0].table
        self.schedule = RowSchedule()

    def read_now(self, values=None, outline=False, park=False):
        """The probe state of each part as the design is now (`SizeProbe.read_now`). Only the last part's read may leave
        the marker before a face's step (`park`), since every part reads with the marker where the tries hold it."""
        last = len(self.probes) - 1
        return [probe.read_now(values, outline, park and number == last) for number, probe in enumerate(self.probes)]

    def probe_rows(self, sizes, extra=()):
        """The extra rows. Every probe plans them (that sets what it leaves untried); they are the same for all."""
        return [probe.probe_rows(sizes, extra) for probe in self.probes][0]

    def _marked(self):
        """The first probe's states with the outline changes of every part marked: the rows are shared."""
        changed = set().union(*(probe.outline_changes() for probe in self.probes))
        return marked_states(self.probes[0].states, changed)

    def pair_rows(self, sizes, room):
        """The near pair rows, the same for all parts."""
        states = self._marked()
        return [probe.pair_rows(sizes, room, states) for probe in self.probes][0]

    def far_rows(self, sizes, room):
        """The far rows: every probe plans them (that clears what it holds); they are the same for all."""
        states = self._marked()
        return [probe.far_rows(sizes, room, states) for probe in self.probes][0]

    def far_pair_rows(self, sizes, room):
        """The far pair rows: every probe plans them (that clears what it holds); they are the same for all."""
        states = self._marked()
        return [probe.far_pair_rows(sizes, room, states) for probe in self.probes][0]

    def add_states(self, entries):
        """Give each probe its own state per `(values, result, reads)`, `(values, result, reads, starts)` or
        `(values, result, reads, starts, more)`; `reads`, `starts` and the `put_back` of `more` have one read per
        probe."""
        def mine(more, number):
            backs = (more or {}).get("put_back")
            return dict(more or {}, put_back=backs[number] if backs else None)

        for number, probe in enumerate(self.probes):
            probe.add_states([(values, result, reads[number] if reads else None,
                               rest[0][number] if rest and rest[0] else None,
                               mine(rest[1] if len(rest) > 1 else None, number))
                              for values, result, reads, *rest in entries])

    def followed_sketches(self):
        """Tokens of the sketches any part reads at every row."""
        return list(dict.fromkeys(t for probe in self.probes for t in probe.followed_sketches()))

    def left_start(self, reads):
        """True when a part's followed sketch reads otherwise than at its E0 (`SizeProbe.left_start`)."""
        return any(probe.left_start(read) for probe, read in zip(self.probes, reads or []))

    def note_recovery(self, record):
        for probe in self.probes:
            probe.note_recovery(record)

    def note_stop(self, record, unrun=()):
        for probe in self.probes:
            probe.note_stop(record, unrun)

    def note_time_limit(self, record, unrun=()):
        for probe in self.probes:
            probe.note_time_limit(record, unrun)

    def time_left_out(self):
        """The sizes the time limit left without a try, over the parts."""
        return list(dict.fromkeys(name for probe in self.probes for name in probe.time_left_out()))

    def matches_start(self, reads):
        """True when every part's read equals its first read (`SizeProbe.matches_start`)."""
        return all(probe.matches_start(read) for probe, read in zip(self.probes, reads or []))

    def off_outline(self, reads):
        """True when a part's followed sketch reads as another outline in its read of `reads`."""
        return any(probe.off_outline(read) for probe, read in zip(self.probes, reads or []))

    def nearer_rows(self, sizes, room):
        """The nearer rows for all parts (`SizeProbe.nearer_rows`): the rows and their failures are shared, and a size
        that moved a part counts as moving for all."""
        moving = list(dict.fromkeys(n for probe in self.probes for n in probe.moving_sizes()))
        first = self.probes[0]
        changed = set().union(*(probe.outline_changes() for probe in self.probes))
        rows = plan.nearer_rows(sizes, marked_states(first.states, changed), moving, self.schedule.nearer_room(room))
        self.schedule.count_nearer(rows)
        return rows

    def check_rows(self, sizes, room):
        """The check rows for all parts: a size curved in any part counts as curved for all."""
        if not self.schedule.check_once():
            return []
        first = self.probes[0]
        found = [probe.curved_sizes() for probe in self.probes]
        curved = list(dict.fromkeys(n for c, _ in found for n in c))
        partners = [n for n in dict.fromkeys(n for _, p in found for n in p) if n not in curved]
        return plan.check_rows(sizes, curved, first.spans_now(), room, partners) if curved else []

    def discovery_rows(self, candidates, room):
        return self.probes[0].discovery_rows(candidates, room)

    def set_discovery_base(self, reads, put_backs=None):
        """Give each probe its own read of the design before the discovery rows (`SizeProbe.set_discovery_base`)."""
        for number, (probe, read) in enumerate(zip(self.probes, reads)):
            probe.set_discovery_base(read, put_backs[number] if put_backs else None)

    def discover(self, entries):
        """Give each probe its own reads of the discovery rows `(row, result, reads)`."""
        for number, probe in enumerate(self.probes):
            probe.discover([(row, result, reads[number] if reads else None) for row, result, reads in entries])

    @property
    def also_changes(self):
        return list(dict.fromkeys(name for probe in self.probes for name in probe.also_changes))

    def finish(self, afters, labels):
        """Build each part's motion. Returns the sizes the probes cannot follow, one entry per size. Its reason starts
        with the parts that have that reason (the rows are shared, so a size left untried is untried for all). When
        parts give different reasons for one size, the entry holds each reason led by its parts."""
        found = {}
        for name, probe, after in zip(self.names, self.probes, afters):
            for entry in probe.finish(after, labels):
                kept = found.setdefault(entry["param"], (entry, {}))
                kept[1].setdefault(entry["reason"], []).append(name)
        out = []
        for entry, reasons in found.values():
            parts = [tagged(names, reason) for reason, names in reasons.items()]
            text = parts[0] if len(parts) == 1 else clip("; ".join(p.rstrip(".") for p in parts) + ".",
                                                         MAX_FIXED_REASON)
            out.append(dict(entry, reason=text))
        return out

    def measure_restore(self, afters):
        """The largest gap over the parts, or None when one part cannot be compared."""
        gaps = [probe.measure_restore(after) for probe, after in zip(self.probes, afters)]
        return None if any(gap is None for gap in gaps) else max(gaps)

    @property
    def restore_unchecked(self):
        """What the restore check could not compare, led by the part."""
        return [tagged([name], why) for name, probe in zip(self.names, self.probes) for why in probe.restore_unchecked]

    @property
    def motions(self):
        return [probe.motion for probe in self.probes]

    def reports(self):
        """The `SizeProbe.report` of each part."""
        return [probe.report() for probe in self.probes]

    def derived_records(self, log=None):
        """The `shadow_of` block of each part; `log(text)` gets one line per part."""
        return [shadow_of(probe, log, name) for probe, name in zip(self.probes, self.names)]
