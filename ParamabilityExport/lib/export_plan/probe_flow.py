"""The size probe of one export: which sketch states to read, and how the answers become a motion. Pure: no Fusion.

The export reads the sketches of the part, and the measured references of other components its steps use (a plane,
axis, direction or point), at its current settings (E0) and at extra settings that only recompute: the range ends of
the sizes that move a sketch or such a reference, and all sizes low or high (`probe_rows`). `SizeProbe` keeps that
record and hands the states to `probe.build`. Fusion is reached through the `read` callable given to `start`:
`read(request)` returns one probe state (`fusion_reader.probe_state.read_state`).

A step of the target can use a sketch of another component (a borrowed sketch). The probe reads it like the
target's own sketches: its frame is brought into the target's coordinates at every state, so the fit sees its
outline move with the sizes. The probe works on a view of the capture where such profiles are written as own ones.
A borrowed sketch that the fit cannot follow (it did not read back as captured) is watched instead: a size that
changes it, or leaves it unreadable, is loose. A reference that did not read back as captured is not read again; the
motion file says so (`Motion.refs`).
"""
from ..package.manifest import MAX_FIXED_REASON
from ..package.text import clip
from ..probe import build, fit, match, plan, ref_fit
from ..translator import borrowed
from ..translator.notes import loose_reason
from .part_names import tagged

_STATE_KEYS = ("sketches", "points", "lines", "params", "box", "refs", "unread")


def kept_size_names(table, free_sizes):
    """Recipe names of the sizes to probe: the free sizes of the first translation and every ticked size that
    reaches a sketch dimension, a construction plane or a sketch through the geometry of another component."""
    names = plan.kept_sizes(table, free_sizes)
    return {table.size_name(n) for n in names if table.size_name(n)}


def extra_size_params(table, free_sizes):
    """Fusion names of the ticked sizes tried on a guess (`plan.extra_sizes`): nothing ties them to a sketch, but
    the person ticked them, so a sketch may follow them in a way the capture cannot show."""
    return plan.extra_sizes(table, plan.kept_sizes(table, free_sizes))


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
    """True when the probe can follow or watch at least one sketch, or follow a measured reference, of the capture."""
    return (bool(plan.scan(probe_view(capture)).covered) or bool(borrowed_sketches(capture))
            or any(r["shape"] for r in plan.refs(capture)))


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

    def __init__(self, capture, table, read, request, e0, watch=None, refs=()):
        self.capture = probe_view(capture)
        self.refs = list(refs)  # the measured references that read back as captured (`plan.refs`)
        self.watch = dict(watch or {})  # borrowed sketch token to { sketch, component, path }
        self.table = table
        self.read = read
        self.request = request
        self.e0 = e0
        self.states = [{"values": {}, "built": True, "read": e0, "e0": True}]
        self.dropped = []
        self.untried = []
        self.restore_gap_mm = None
        self.motion = None
        self.moved = []
        self.discovery = []

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
        if not isinstance(e0, dict) or not (e0.get("sketches") or e0.get("points") or e0.get("lines")
                                            or e0.get("refs")):
            return None
        readable = match.readable(plan.scan(view), e0)
        watch = {t: h for t, h in hints.items() if t not in readable}
        measured = ref_fit.measurable(plan.refs(view), e0)
        keys = {r["key"] for r in measured.usable}
        request = plan.request(view, table, covered=readable, wanted=keys) or (bare if watch else None)
        if request is None:
            return None
        return cls(capture, table, read, _with_borrowed(request, hints, watch), e0, watch, measured.usable)

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

    def probe_rows(self, sizes, extra=()):
        """The extra rows, at the range ends of `sizes` that move a sketch: the sizes the states already show moving
        one, and every size that reaches a sketch. Then the sizes in `extra` (Fusion names tried on a guess,
        `extra_size_params`) while rows are left."""
        current = {e.name: e.value for e in self.table.entries}
        self.moved = build.moved_sizes(self.capture, self.states, current)
        reach = set(plan.sketch_driven(self.table))
        moved = set(self.moved) | {s["param"] for s in sizes if s["param"] in reach}
        rows, self.untried = plan.probe_rows(sizes, moved, extra=set(extra))
        return rows

    def discovery_rows(self, candidates, room):
        """Rows that try unticked parameters once each (`size_offers.discovery_sizes`), within `room` rows."""
        return plan.discovery_rows(candidates, room)

    def discover(self, entries):
        """Keep, per `(row, result, read)` of a discovery row, whether the body's sketches or the references of other
        components its steps use moved with its parameter: `{ param, moved }`, `moved` None when the row did not build
        or the read is missing. These reads are not states of the motion."""
        found = plan.scan(self.capture)
        targets = [t for t in found.targets if t["sketch_token"] in self.request["sketches"]]
        for row, result, read in entries:
            param = (row.get("varied") or [None])[0]
            if param is None:
                continue
            moved = None
            if not result.get("error") and isinstance(read, dict):
                moved = (any(self._target_moved(t, read) for t in targets)
                         or any(ref_fit.moved_in(r, read) for r in self.refs))
            self.discovery.append({"param": param, "moved": moved})

    def _target_moved(self, target, read):
        before, _ = match.state_values(target, self.e0, self.e0)
        now, _ = match.state_values(target, read, self.e0)
        if before is None:
            return False
        if now is None or now.keys() != before.keys():
            return True
        return any(abs(now[k] - v) > fit.TOLERANCE for k, v in before.items())

    @property
    def also_changes(self):
        """Fusion names of the unticked parameters that a discovery row showed moving the body's sketches or the
        references its steps use."""
        return [d["param"] for d in self.discovery if d["moved"]]

    # ---- result -----------------------------------------------------------------------------------------------

    def finish(self, after, labels):
        """Build the motion and compare the design after the restore with E0.

        Returns the sizes this probe cannot follow, as loose entries ({name, reason, param, size}): the ones left
        without rows, and the ones that moved a sketch when the motion could not be built. `labels` maps a recipe
        size name to the text for the person.
        """
        found = []
        for param in self.untried:
            found.append(self._entry(param, _UNTRIED, labels))
        try:
            self.motion = build.build(self.capture, self.table, self.states)
        except Exception:
            self.motion = None
            current = {e.name: e.value for e in self.table.entries}
            self.moved = list(dict.fromkeys(self.moved + build.moved_sizes(self.capture, self.states, current)))
            found.extend(self._entry(p, _UNREADABLE, labels) for p in self.moved if p not in self.untried)
        if self.motion is not None:
            self.motion.untried = list(self.untried)
        found.extend(self._watched(labels, {f["param"] for f in found}))
        self.measure_restore(after)
        return found

    def measure_restore(self, after):
        """Compare the sketches read after the parameters were put back with the first read. Keeps and returns the
        largest gap in mm, or None when the two reads cannot be compared."""
        self.restore_gap_mm = self._gap(after)
        return self.restore_gap_mm

    def _watched(self, labels, skip):
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
                out.append(self._entry(param, _watched_why(sketch), labels))
        return out

    def _entry(self, param, why, labels):
        size = self.table.size_name(param) or param
        reason = loose_reason(labels.get(size, param), why)
        return {"name": param, "reason": clip(reason, MAX_FIXED_REASON), "param": param, "size": size}

    def _gap(self, after):
        """Largest difference in mm between E0 and a read after the restore, over the covered values and the places of
        the measured references (one that cannot be read again is left out). None when the sketches cannot be
        compared."""
        if not isinstance(after, dict):
            return None
        found = plan.scan(self.capture)
        gap = 0.0
        for ref in self.refs:
            before, _ = ref_fit.state_values(ref, self.e0)
            now, _ = ref_fit.state_values(ref, after)
            if before is not None and now is not None:
                gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
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
            "discovery": list(self.discovery),
        }

    @staticmethod
    def _state_json(state):
        out = {"values": state.get("values") or {}, "built": state.get("built") is not False}
        if state.get("e0"):
            out["e0"] = True
        if isinstance(state.get("read"), dict):
            out["read"] = {k: v for k, v in state["read"].items() if k in _STATE_KEYS}
        return out


class ProbeGroup:
    """The probes of several parts of one export, run over one set of rows.

    Every part has its own `SizeProbe` (its sketches, references and motion), all over the same size table. The rows
    are the same for all of them (sizes that move a sketch of any part), so Fusion recomputes once per row and each
    probe reads its own part there. The row limit (`plan.MAX_PROBE_ROWS`) is for the whole export, not per part. It
    offers the calls of `SizeProbe` that `ProbeRun` and the pipeline use; a read is a list with one entry per probe.
    """

    def __init__(self, probes, names):
        self.probes = list(probes)
        self.names = list(names)
        self.table = self.probes[0].table

    def read_now(self):
        """The probe state of each part as the design is now."""
        return [probe.read_now() for probe in self.probes]

    def probe_rows(self, sizes, extra=()):
        """The extra rows. Every probe plans them (that sets what it leaves untried); they are the same for all."""
        return [probe.probe_rows(sizes, extra) for probe in self.probes][0]

    def add_states(self, entries):
        """Give each probe its own state per `(values, result, reads)`; `reads` has one read per probe."""
        for number, probe in enumerate(self.probes):
            probe.add_states([(values, result, reads[number] if reads else None) for values, result, reads in entries])

    def discovery_rows(self, candidates, room):
        return self.probes[0].discovery_rows(candidates, room)

    def discover(self, entries):
        """Give each probe its own reads of the discovery rows `(row, result, reads)`."""
        for number, probe in enumerate(self.probes):
            probe.discover([(row, result, reads[number] if reads else None) for row, result, reads in entries])

    @property
    def also_changes(self):
        return list(dict.fromkeys(name for probe in self.probes for name in probe.also_changes))

    def finish(self, afters, labels):
        """Build each part's motion. Returns the sizes the probes cannot follow, one entry per size. Its reason starts
        with the parts that have that same reason (the rows are shared, so a size left untried is untried for all)."""
        found = {}
        for name, probe, after in zip(self.names, self.probes, afters):
            for entry in probe.finish(after, labels):
                kept = found.setdefault(entry["param"], (entry, []))
                if kept[0]["reason"] == entry["reason"]:
                    kept[1].append(name)
        return [dict(entry, reason=tagged(names, entry["reason"])) for entry, names in found.values()]

    def measure_restore(self, afters):
        """The largest gap over the parts, or None when one part cannot be compared."""
        gaps = [probe.measure_restore(after) for probe, after in zip(self.probes, afters)]
        return None if any(gap is None for gap in gaps) else max(gaps)

    @property
    def motions(self):
        return [probe.motion for probe in self.probes]

    def reports(self):
        """The `SizeProbe.report` of each part."""
        return [probe.report() for probe in self.probes]
