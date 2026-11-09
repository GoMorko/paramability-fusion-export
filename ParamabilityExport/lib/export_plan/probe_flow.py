"""The size probe of one export: which sketch states to read, and how the answers become a motion. Pure: no Fusion.

The export reads the sketches of the part at its current settings (E0), at every size check (phase 1, with a STEP),
and at extra settings that only recompute (phase 2, no STEP). `SizeProbe` keeps that record and hands the states to
`probe.build`. Fusion is reached through the `read` callable given to `start`: `read(request)` returns one probe
state (`fusion_reader.probe_state.read_state`).
"""
from ..probe import build, match, plan
from ..probe import motion as motion_module
from .size_checks import fixed_entry

_STATE_KEYS = ("sketches", "points", "lines", "params", "box")


def kept_size_names(table, free_sizes):
    """Recipe names of the sizes to check: the free sizes of the first translation and every ticked size that
    reaches a sketch dimension or a construction plane."""
    names = plan.kept_sizes(table, free_sizes)
    return {table.size_name(n) for n in names if table.size_name(n)}


def covers_a_sketch(capture):
    """True when the probe can follow at least one sketch of the capture."""
    return bool(plan.scan(capture).covered)


def _state_values(row):
    state = row.get("state") or {}
    return {p: state[p] for p in row.get("varied") or [] if p in state}


def _untried_reason(label):
    return "%s stays fixed: it changes a sketch and could not be tried at other values." % label


def _unreadable_reason(label):
    return "%s stays fixed: a sketch it changes could not be read at other values." % label


class SizeProbe:
    """One export's sketch states and what they gave. Build it with `start`, which returns None when there is
    nothing to follow."""

    def __init__(self, capture, table, read, request, e0):
        self.capture = capture
        self.table = table
        self.read = read
        self.request = request
        self.e0 = e0
        self.states = [{"values": {}, "built": True, "read": e0, "e0": True}]
        self.skip = set()
        self.dropped = []
        self.untried = []
        self._tried = []
        self.restore_gap_mm = None
        self.motion = None
        self.moved = []

    @classmethod
    def start(cls, capture, table, read):
        """Read E0 and keep the sketches whose first read matches the capture. None when no sketch stays covered or
        Fusion gave no read."""
        wide = plan.request(capture, table)
        if wide is None:
            return None
        e0 = read(wide)
        if not isinstance(e0, dict) or not e0.get("sketches") and not e0.get("points") and not e0.get("lines"):
            return None
        found = plan.scan(capture)
        readable = match.readable(found, e0)
        request = plan.request(capture, table, covered=readable)
        if request is None:
            return None
        probe = cls(capture, table, read, request, e0)
        probe.skip = set(found.names(readable))
        return probe

    # ---- states -----------------------------------------------------------------------------------------------

    def read_now(self):
        """The probe state of the design as it is now."""
        return self.read(self.request)

    def _add(self, varied, results, reads):
        """Add one state per result. `reads` are the states read at the rows that built, in order."""
        pending = list(reads)
        for values, result in zip(varied, results):
            if result.get("error"):
                self.states.append({"values": values, "built": False})
                self.dropped.append({"name": result.get("name"), "error": result.get("error")})
            else:
                self.states.append({"values": values, "built": True, "read": pending.pop(0) if pending else None})

    def add_checks(self, checks, results, reads):
        """The states of the phase 1 checks (`results` in check order, `reads` for those that built)."""
        self._add([{c["param"]: c["value"]} for c in checks], results, reads)

    def probe_rows(self, sizes, checks, results, unchecked):
        """The phase 2 rows. `unchecked` lists the Fusion names of kept sizes that got no check."""
        current = {e.name: e.value for e in self.table.entries}
        self.moved = build.moved_sizes(self.capture, self.states, current)
        reach = set(plan.sketch_driven(self.table))
        moved = set(self.moved) | {p for p in unchecked if p in reach}
        check_values = {c["param"]: c["value"] for c, r in zip(checks, results) if not r.get("error")}
        rows, self.untried = plan.probe_rows(sizes, check_values, moved)
        self._tried = [_state_values(r) for r in rows]
        return rows

    def add_tried(self, results, reads):
        self._add(self._tried, results, reads)

    # ---- result -----------------------------------------------------------------------------------------------

    def finish(self, after, labels):
        """Build the motion and compare the design after the restore with E0.

        Returns the sizes this probe makes fixed, as fixed entries (`size_checks.fixed_entry` plus `param`, `size`):
        the ones left without rows, and the ones that moved a sketch when the motion could not be built.
        `labels` maps a recipe size name to the text for the person.
        """
        fixed = []
        for param in self.untried:
            fixed.append(self._fixed(param, _untried_reason, labels))
        try:
            self.motion = motion_module.build(self.capture, self.table, self.states)
        except Exception:
            self.motion = None
            fixed.extend(self._fixed(p, _unreadable_reason, labels) for p in self.moved if p not in self.untried)
        self.restore_gap_mm = self._gap(after)
        return fixed

    def _fixed(self, param, reason, labels):
        size = self.table.size_name(param) or param
        return {**fixed_entry(param, reason(labels.get(size, param))), "param": param, "size": size}

    def _gap(self, after):
        """Largest difference in mm between E0 and a read after the restore, over the covered values. None when the
        read does not give them."""
        if not isinstance(after, dict):
            return None
        found = plan.scan(self.capture)
        gap = 0.0
        for target in found.targets:
            if target["sketch_token"] not in self.request["sketches"]:
                continue
            before, _ = match.state_values(target, self.e0, self.e0)
            now, _ = match.state_values(target, after, self.e0)
            if before is None or now is None or before.keys() != now.keys():
                return None
            gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
        return gap

    def report(self):
        """The record kept in `report.json`: what was asked, what was read, and what was found."""
        return {
            "request": self.request,
            "states": [self._state_json(s) for s in self.states],
            "dropped": list(self.dropped),
            "untried": list(self.untried),
            "restore_gap_mm": self.restore_gap_mm,
            "motion": self.motion.json() if self.motion is not None else None,
        }

    @staticmethod
    def _state_json(state):
        out = {"values": state.get("values") or {}, "built": state.get("built") is not False}
        if state.get("e0"):
            out["e0"] = True
        if isinstance(state.get("read"), dict):
            out["read"] = {k: v for k, v in state["read"].items() if k in _STATE_KEYS}
        return out
