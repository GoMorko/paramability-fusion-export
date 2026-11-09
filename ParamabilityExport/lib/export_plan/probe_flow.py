"""The size probe of one export: which sketch states to read, and how the answers become a motion. Pure: no Fusion.

The export reads the sketches of the part at its current settings (E0), at every row the size checks run (with a
STEP, or a rebuild only at the other end of a range) and at extra settings that only recompute, at the range ends no
row tried and with all sizes low or high (`probe_rows`). `SizeProbe` keeps that record and hands the states to
`probe.build`. Fusion is reached through the `read` callable given to `start`: `read(request)` returns one probe
state (`fusion_reader.probe_state.read_state`).

A step of the target can use a sketch of another component (a borrowed sketch). The probe reads it like the
target's own sketches: its frame is brought into the target's coordinates at every state, so the fit sees its
outline move with the sizes. The probe works on a view of the capture where such profiles are written as own ones.
A borrowed sketch that the fit cannot follow (it did not read back as captured) is watched instead: a size whose
check changes it, or leaves it unreadable, stays fixed.
"""
from ..probe import build, match, plan
from ..probe import motion as motion_module
from ..translator import borrowed
from .size_checks import size_entry

_STATE_KEYS = ("sketches", "points", "lines", "params", "box", "unread")


def kept_size_names(table, free_sizes):
    """Recipe names of the sizes to check: the free sizes of the first translation and every ticked size that
    reaches a sketch dimension or a construction plane."""
    names = plan.kept_sizes(table, free_sizes)
    return {table.size_name(n) for n in names if table.size_name(n)}


def _profile_lists(capture):
    """(item, profiles) of each item that has a profile list."""
    for item in capture.get("items") or []:
        data = item.get("data")
        if isinstance(data, dict) and isinstance(data.get("profiles"), list):
            yield item, data["profiles"]


def _is_borrowed(profile):
    return isinstance(profile, dict) and borrowed.usable(profile) and bool(profile.get("sketch_token"))


def borrowed_sketches(capture):
    """Sketch token to { path, sketch, component } of the borrowed sketches of a capture: the occurrence path the
    capture recorded, and the names for a reason."""
    out = {}
    for _, profiles in _profile_lists(capture):
        for profile in filter(_is_borrowed, profiles):
            out.setdefault(profile["sketch_token"], {
                "path": (profile.get("placement") or {}).get("path") or "", "sketch": profile.get("sketch") or "",
                "component": (profile.get("component") or {}).get("name") or ""})
    return out


def _as_own(profile):
    """A borrowed profile written as an own one: its `frame` is already in the target's coordinates. The sketch name
    also names the component, so a reason can say whose sketch it is."""
    component = (profile.get("component") or {}).get("name")
    name = profile.get("sketch") or "a sketch"
    own = {k: v for k, v in profile.items() if k not in borrowed.BORROWED_KEYS}
    return dict(own, sketch="%s of %s" % (name, component) if component else name)


def probe_view(capture):
    """The capture with each borrowed profile written as an own one, so the probe plans and fits it like the rest.
    The capture itself when nothing is borrowed."""
    if not borrowed_sketches(capture):
        return capture
    items = []
    for item in capture.get("items") or []:
        data = item.get("data")
        if isinstance(data, dict) and isinstance(data.get("profiles"), list) and any(
                map(_is_borrowed, data["profiles"])):
            profiles = [_as_own(p) if _is_borrowed(p) else p for p in data["profiles"]]
            item = dict(item, data=dict(data, profiles=profiles))
        items.append(item)
    return dict(capture, items=items)


def covers_a_sketch(capture):
    """True when the probe can follow or watch at least one sketch of the capture."""
    return bool(plan.scan(probe_view(capture)).covered) or bool(borrowed_sketches(capture))


def _with_borrowed(request, hints, watch):
    """`request` with the watched sketches added and the occurrence paths of its borrowed sketches."""
    sketches = list(request["sketches"]) + [t for t in watch if t not in request["sketches"]]
    out = dict(request, sketches=sketches)
    paths = {t: {"path": hints[t]["path"]} for t in sketches if t in hints}
    if paths:
        out["borrowed"] = paths
    return out


_UNTRIED = "it changes a sketch and could not be tried at other values"
_UNREADABLE = "a sketch it changes could not be read at other values"


def _watched_why(sketch):
    return "it changes the sketch %s, which could not be followed" % sketch


class SizeProbe:
    """One export's sketch states and what they gave. Build it with `start`, which returns None when there is
    nothing to follow."""

    def __init__(self, capture, table, read, request, e0, watch=None):
        self.capture = probe_view(capture)
        self.watch = dict(watch or {})  # borrowed sketch token to { sketch, component, path }
        self.table = table
        self.read = read
        self.request = request
        self.e0 = e0
        self.states = [{"values": {}, "built": True, "read": e0, "e0": True}]
        self.skip = set()
        self.dropped = []
        self.untried = []
        self.restore_gap_mm = None
        self.motion = None
        self.moved = []

    @classmethod
    def start(cls, capture, table, read):
        """Read E0 and keep the sketches whose first read matches the capture. None when no sketch stays covered or
        Fusion gave no read."""
        hints, view = borrowed_sketches(capture), probe_view(capture)
        bare = {"sketches": [], "points": [], "lines": [], "params": [], "target": True}
        wide = plan.request(view, table) or (bare if hints else None)
        if wide is None:
            return None
        e0 = read(_with_borrowed(wide, hints, hints))
        if not isinstance(e0, dict) or not e0.get("sketches") and not e0.get("points") and not e0.get("lines"):
            return None
        found = plan.scan(view)
        readable = match.readable(found, e0)
        watch = {t: h for t, h in hints.items() if t not in readable}
        request = plan.request(view, table, covered=readable) or (bare if watch else None)
        if request is None:
            return None
        probe = cls(capture, table, read, _with_borrowed(request, hints, watch), e0, watch)
        probe.skip = set(found.names(readable))
        return probe

    # ---- states -----------------------------------------------------------------------------------------------

    def read_now(self):
        """The probe state of the design as it is now."""
        return self.read(self.request)

    def add_states(self, entries):
        """Add one state per `(values, result, read)`: the size values a row set, its RowExport result and the probe
        state read there (None when it did not build)."""
        for values, result, read in entries:
            if result.get("error"):
                self.states.append({"values": values, "built": False})
                self.dropped.append({"name": result.get("name"), "error": result.get("error"),
                                     "detail": result.get("detail") or {}})
            else:
                self.states.append({"values": values, "built": True, "read": read})

    def _tried(self):
        """{Fusion name: [values]} of the states that built with that size alone changed."""
        tried = {}
        for state in self.states[1:]:
            values = state.get("values") or {}
            if state.get("built") is not False and len(values) == 1:
                for param, value in values.items():
                    tried.setdefault(param, []).append(value)
        return tried

    def probe_rows(self, sizes, unchecked):
        """The extra rows, at the range ends of `sizes`, for the ends no state has tried. `unchecked` lists the
        Fusion names of kept sizes that got no check."""
        current = {e.name: e.value for e in self.table.entries}
        self.moved = build.moved_sizes(self.capture, self.states, current)
        reach = set(plan.sketch_driven(self.table))
        moved = set(self.moved) | {p for p in unchecked if p in reach}
        rows, self.untried = plan.probe_rows(sizes, self._tried(), moved)
        return rows

    # ---- result -----------------------------------------------------------------------------------------------

    def finish(self, after, labels, loose=False):
        """Build the motion and compare the design after the restore with E0.

        Returns the sizes this probe cannot follow, as `size_checks.size_entry` entries (fixed ones, or kept free
        with a warning when `loose`): the ones left without rows, and the ones that moved a sketch when the motion
        could not be built. `labels` maps a recipe size name to the text for the person.
        """
        found = []
        for param in self.untried:
            found.append(self._entry(param, _UNTRIED, labels, loose))
        try:
            self.motion = motion_module.build(self.capture, self.table, self.states)
        except Exception:
            self.motion = None
            current = {e.name: e.value for e in self.table.entries}
            self.moved = list(dict.fromkeys(self.moved + build.moved_sizes(self.capture, self.states, current)))
            found.extend(self._entry(p, _UNREADABLE, labels, loose) for p in self.moved if p not in self.untried)
        found.extend(self._watched(labels, {f["param"] for f in found}, loose))
        self.measure_restore(after)
        return found

    def measure_restore(self, after):
        """Compare the sketches read after the parameters were put back with the first read. Keeps and returns the
        largest gap in mm, or None when the two reads cannot be compared."""
        self.restore_gap_mm = self._gap(after)
        return self.restore_gap_mm

    def _watched(self, labels, skip, loose):
        """Entries for the sizes that change a watched borrowed sketch, or leave it unreadable, in a state where
        that size alone differs. The sketch read at the first state is the reference."""
        out, done = [], set(skip)
        for token, hint in self.watch.items():
            before = (self.e0.get("sketches") or {}).get(token)
            if before is None:
                continue
            for state in self.states[1:]:
                values = state.get("values") or {}
                read = state.get("read")
                if state.get("built") is False or len(values) != 1 or not isinstance(read, dict):
                    continue
                param = next(iter(values))
                now = (read.get("sketches") or {}).get(token)
                if param in done or (now is not None and match.same_read(before, now)):
                    continue
                done.add(param)
                name = hint["sketch"] or "a sketch"
                sketch = "%s of %s" % (name, hint["component"]) if hint["component"] else name
                out.append(self._entry(param, _watched_why(sketch), labels, loose))
        return out

    def _entry(self, param, why, labels, loose):
        size = self.table.size_name(param) or param
        return size_entry(param, size, labels.get(size, param), why, loose)

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
