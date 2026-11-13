"""The size probe of one export: which sketch states to read, and how the answers become a motion. Pure: no Fusion.

The export reads the sketches of the part, the measured references of other components its steps use (a plane,
axis, direction or point) and the flat faces its steps use as outlines, at its current settings (E0) and at extra
settings that only recompute: the range ends of the sizes that move a sketch or such a reference, and all sizes low or
high (`probe_rows`). `SizeProbe` keeps that
record and hands the states to `probe.build`. Fusion is reached through the `read` callable given to `start`:
`read(request)` returns one probe state (`fusion_reader.probe_state.read_state`).

A step of the target can use a sketch of another component (a borrowed sketch). The probe reads it like the
target's own sketches: its frame is brought into the target's coordinates at every state, so the fit sees its
outline move with the sizes. The probe works on a view of the capture where such profiles are written as own ones.
A borrowed sketch that the fit cannot follow (it did not read back as captured) is watched instead: a size that
changes it, or leaves it unreadable, is loose. A reference that did not read back as captured is not read again; the
motion file says so (`Motion.refs`).
"""
import hashlib
import json

from ..package.manifest import MAX_FIXED_REASON
from ..design_edit.marker import MARKER_LOST
from ..package.text import clip
from ..params.expressions import format_number
from ..probe import build, derived, fit, match, plan, plane_sizes, ref_fit
from ..sketch_values.motion import CURVE, SHAPE, TURNS, UNREAD, Stuck, Terms
from ..translator import borrowed
from ..translator.notes import loose_reason
from ..translator.sizes import construction_only
from .part_names import tagged

_STATE_KEYS = ("sketches", "points", "lines", "params", "box", "refs", "faces", "unread")
BODY_TOLERANCE_MM = 1e-4
# How far a followed value (mm or degrees) may read from E0 once the values are back before the sketch counts as on
# another solution; Fusion's own restore leaves up to about a hundredth of a degree on short lines.
FLIP_TOLERANCE = 0.05
VOLUME_TOLERANCE_MM3 = 1e-4
VOLUME_RELATIVE = 1e-6
# Why a parameter of another component got no try; kept in the discovery record of `report.json`.
NOT_TRIED = "not tried: the export tries only a limited number of parameters of other components"
NOT_READ_TRY = "not tried: the design could not be read at the value tried"
NOT_TRIED_STOPPED = "not tried: the tries stopped early, after a try left a step in error"


def _box_numbers(read):
    box = read.get("box") if isinstance(read, dict) else None
    if not isinstance(box, dict):
        return None
    low, high = box.get("min"), box.get("max")
    if not all(isinstance(v, (list, tuple)) and len(v) == 3 for v in (low, high)):
        return None
    numbers = list(low) + list(high)
    return numbers if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers) else None


def _volume(read):
    value = read.get("volume_mm3") if isinstance(read, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _numbers(node, out):
    if isinstance(node, dict):
        for key in sorted(node):
            _numbers(node[key], out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _numbers(value, out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append(float(node))
    return out


def _same_numbers(a, b):
    """True when two records hold the same numbers in the same places, within the fit tolerance."""
    x, y = _numbers(a, []), _numbers(b, [])
    return len(x) == len(y) and all(abs(p - q) <= fit.TOLERANCE for p, q in zip(x, y))


def not_built_try(value, step):
    """Why a discovery row gave no answer: Fusion did not rebuild the design at the value tried."""
    at = " at %s" % format_number(value) if isinstance(value, (int, float)) else ""
    return "not tried: the design does not rebuild in Fusion%s%s" % (at, " (%s)" % step if step else "")


def body_changed(before, now):
    """True when the body reads differently in two probe states: its box moved, or its volume changed when both states
    read it. False when they agree or the body cannot be compared (a state without a box)."""
    a, b = _box_numbers(before), _box_numbers(now)
    if a is not None and b is not None and any(abs(x - y) > BODY_TOLERANCE_MM for x, y in zip(a, b)):
        return True
    va, vb = _volume(before), _volume(now)
    return va is not None and vb is not None and abs(va - vb) > max(VOLUME_TOLERANCE_MM3, VOLUME_RELATIVE * abs(va))


def marked_states(states, changed):
    """The states after E0, each one whose number is in `changed` marked `changed` for `plan.nearer_rows`."""
    return [dict(state, changed=True) if at in changed else state for at, state in enumerate(states) if at]


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
    """True when the probe can follow or watch at least one sketch, or follow a measured reference or a face used as an
    outline, of the capture."""
    found = plan.scan(probe_view(capture))
    return (bool(found.covered) or bool(found.faces) or bool(borrowed_sketches(capture))
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
# Why a sketch could not be compared with its first read after the parameters were put back, by `match` cause.
_RESTORE_WHY = {SHAPE: "reads another outline", TURNS: "lies on a turned plane", UNREAD: "could not be read"}
_UNREADABLE = "a sketch it changes could not be read at other values"


def _watched_why(sketch):
    return "it changes the sketch %s, which could not be followed" % sketch


class SharedReads:
    """One copy of each part of a probe read that reads the same in several states. Most tries read most sketches
    exactly as E0 or as an earlier try did; the states keep every read, so a long probe would otherwise hold the same
    sketch many times over. `share(read)` puts the copy already kept in place of each equal sketch, face, point, line
    and reference of `read`, and returns `read`."""

    KEYS = ("sketches", "faces", "points", "lines", "refs")

    def __init__(self):
        self._kept = {}  # (key, name, digest) to the copy kept
        self._last = {}  # (key, name) to the copy kept or given last: most reads equal it, so it is compared first

    def share(self, read):
        if not isinstance(read, dict):
            return read
        for key in self.KEYS:
            part = read.get(key)
            if not isinstance(part, dict):
                continue
            for name, value in part.items():
                last = self._last.get((key, name))
                if last is not None and (last is value or last == value):
                    part[name] = last
                    continue
                try:
                    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
                except (TypeError, ValueError):
                    continue
                kept = self._kept.setdefault((key, name, hashlib.sha1(text.encode("utf-8")).digest()), value)
                if kept is not value and kept == value:
                    part[name] = kept
                self._last[(key, name)] = part[name]
        return read


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
        self.nearer_count = 0
        self.checked = False
        self._far = None  # (moved, extra) of the near rows, until the far rows are asked for
        self._pairs = None  # the same, from the far rows until the far pair rows are asked for
        self.discovery_base = None  # the read the discovery rows are compared with
        self.rows_end = None  # the read once the measured rows were done and the parameters back
        self.after_rows = None  # what read differently from E0 once the parameters were put back after the rows
        self.restore_unchecked = []  # "<sketch>: <why>" for each sketch the restore check could not compare
        self.recovery = None  # what was done when a sketch stayed on another solution (`note_recovery`)
        self.stopped = None  # `{ after, items }` when a try left the design broken and the tries stopped (`note_stop`)
        self._unrun = []  # the sizes of the rows planned that did not run because the tries stopped
        self._changes = None  # (number of states, `outline_changes`) of the last time it was worked out
        self._moving = set()  # the sizes `probe_rows` tried because they move a sketch or a measured place
        self.face_sizes = plane_sizes.face_sizes(self.capture, table)  # face key to the sizes that may change it
        self.shared = SharedReads()
        self.shared.share(e0)

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
        if not isinstance(e0, dict) or MARKER_LOST in (e0.get("unread") or {}) or not (
                e0.get("sketches") or e0.get("points") or e0.get("lines") or e0.get("refs") or e0.get("faces")):
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

    def read_now(self, values=None):
        """The probe state of the design as it is now. `values` are the sizes set to other values now ({} with every
        value back): a face a step uses as its outline is read only when one of them may change it, since each face
        read rolls the timeline back and forth; the others take their E0 read. None reads every face."""
        faces = self.request.get("faces") or {}
        moved = set(values or ())
        wanted = {k: v for k, v in faces.items() if values is None or self.face_sizes.get(k, set()) & moved}
        if len(wanted) == len(faces):
            return self.shared.share(self.read(self.request))
        request = dict(self.request, faces=wanted) if wanted else {k: v for k, v in self.request.items()
                                                                   if k != "faces"}
        read = self.read(request)
        if isinstance(read, dict):
            same = {k: v for k, v in (self.e0.get("faces") or {}).items() if k in faces and k not in wanted}
            read["faces"] = dict(same, **(read.get("faces") or {}))
        return self.shared.share(read)

    def add_states(self, entries):
        """Add one state per `(values, result, read)`, `(values, result, read, start)` or `(values, result, read,
        start, more)`: the size values a row set, its RowExport result, the probe state read there (None when it did
        not build), the read of the design before the row ran, once the parameters were back (None when it was not
        read), and `more`: `put_back`, the read once the followed sketches were put back on their first solution
        before the row ran, and `again`, true for a row run a second time (`pipeline.ProbeRun`)."""
        for values, result, read, *rest in entries:
            start = rest[0] if rest else None
            more = rest[1] if len(rest) > 1 and isinstance(rest[1], dict) else {}
            if result.get("error"):
                detail = result.get("detail") or {}
                state = {"values": values, "built": False, "failed": (detail.get("items") or [""])[0]}
                self.dropped.append({"name": result.get("name"), "error": result.get("error"), "detail": detail})
            else:
                state = {"values": values, "built": True, "read": read}
            if isinstance(start, dict):
                state["start"] = start
            if isinstance(more.get("put_back"), dict):
                state["put_back"] = more["put_back"]
            if more.get("again"):
                state["again"] = True
            self.states.append(state)

    def followed_sketches(self):
        """Tokens of the sketches this probe reads at every row."""
        return list(self.request.get("sketches") or [])

    def left_start(self, read):
        """True when a followed sketch reads otherwise than at E0 in `read`, a read taken with every value back: the
        sketch stayed on another solution (another outline, or the same outline more than `FLIP_TOLERANCE` away). A
        sketch that could not be read does not count."""
        if not isinstance(read, dict):
            return False
        for target in self._followed_targets():
            before, _ = match.state_values(target, self.e0, self.e0)
            now, cause = match.state_values(target, read, self.e0)
            if before is None or (now is None and cause != SHAPE):
                continue
            if now is None or now.keys() != before.keys() or any(
                    abs(now[k] - v) > FLIP_TOLERANCE for k, v in before.items()):
                return True
        return False

    def note_recovery(self, record):
        """Keep what `pipeline.ProbeRun` did when a sketch stayed on another solution, for `report`."""
        self.recovery = dict(record)

    def note_stop(self, record, unrun=()):
        """Keep the try after which the design did not rebuild with the values back, and the steps in error, for
        `report`: the tries stopped there. `unrun` are the rows planned that did not run; `finish` lists a size of
        theirs that moves a sketch and has no try of its own as untried."""
        self.stopped = {"after": record.get("after"), "items": list(record.get("items") or [])}
        self._unrun.extend(p for row in unrun for p in row.get("varied") or [] if p not in self._unrun)

    def matches_start(self, read):
        """True when `read` has the same sketches, points, lines, references and body box as the first read (E0), within
        the fit tolerance: the design reads the same at another timeline marker."""
        if not isinstance(read, dict):
            return False
        keys = ("sketches", "points", "lines", "refs", "box")
        before = {k: self.e0.get(k) or {} for k in keys}
        now = {k: read.get(k) or {} for k in keys}
        return all(set(before[k]) == set(now[k]) for k in keys) and _same_numbers(before, now)

    def off_outline(self, read):
        """True when a sketch the probe follows reads as another outline than captured in `read` (a sketch on its
        other solution, or one whose outline changed)."""
        if not isinstance(read, dict):
            return False
        for target in self._followed_targets():
            values, cause = match.state_values(target, read, self.e0)
            if values is None and cause == SHAPE:
                return True
        return False

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

    def outline_changes(self):
        """Numbers in `states` of the rows whose own size changed a followed outline (`build.outline_changes`). Worked
        out once per number of states, since only `add_states` changes them."""
        if self._changes is None or self._changes[0] != len(self.states):
            try:
                found = build.outline_changes(self.capture, self.states, {e.name: e.value for e in self.table.entries})
            except Exception:
                found = set()
            self._changes = (len(self.states), found)
        return set(self._changes[1])

    def curved_sizes(self):
        """`(curved, partners)` from the states so far: the Fusion names of the sizes that move a value along a curve
        on their own (a `Stuck` with `rest` blames them, or a `Terms` value reads them through an angle function),
        and the other sizes of those values."""
        try:
            motion = build.build(self.capture, self.table, self.states)
        except Exception:
            return [], []
        curved, partners = [], []
        for value in motion.values.values():
            if isinstance(value, Stuck) and value.cause == CURVE and value.rest is not None:
                curved.extend(value.movers)
                partners.extend(value.rest.terms)
            elif isinstance(value, Terms):
                curved.extend(f[1] for _, factors in value.parts for f in factors if f[0])
                partners.extend(value.names())
        curved = list(dict.fromkeys(curved))
        return curved, [n for n in dict.fromkeys(partners) if n not in curved]

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

    def moving_sizes(self):
        """Fusion names of the sizes whose state (the only size that differs) moved a followed sketch or reference."""
        current = {e.name: e.value for e in self.table.entries}
        targets = self._followed_targets()
        found = []
        for state in self.states[1:]:
            values, read = state.get("values") or {}, state.get("read")
            varied = [n for n, v in values.items() if abs(v - current.get(n, v)) > 1e-9]
            if (len(varied) == 1 and varied[0] not in found and isinstance(read, dict)
                    and self._followed_moved(targets, read)):
                found.append(varied[0])
        return found

    def discovery_rows(self, candidates, room):
        """Rows that try unticked parameters once each (`size_offers.discovery_sizes`), within `room` rows. The
        candidates left without a row are kept in the discovery record as not tried."""
        rows = plan.discovery_rows(candidates, room)
        why = NOT_TRIED_STOPPED if self.stopped else NOT_TRIED
        self.discovery.extend({"param": c["param"], "moved": None, "tried": False, "reason": why}
                              for c in plan.discovery_left(candidates, room))
        return rows

    def set_discovery_base(self, read, put_back=None):
        """Keep the read of the design once the parameters are back after the measured rows, and `put_back`, the read
        once a sketch left on another solution there was put back. The discovery rows are compared with the last of
        them, not with E0: a sketch that Fusion left on another solution, or a place it left elsewhere, must not count
        as moved by every parameter tried later. What `read` shows differently from E0 is kept in the report
        (`after_rows`)."""
        self.rows_end = read
        self.discovery_base = put_back if isinstance(put_back, dict) else read
        changed, unread = self.differences(self.e0, read)
        self.after_rows = {"changed": changed, "unread": unread}

    def discover(self, entries):
        """Keep, per `(row, result, read)` of a discovery row, whether the body moved with its parameter: its sketches,
        the references of other components its steps use, or its box and volume, against `discovery_base` (E0 when
        there is none). `{ param, value, built, moved, changed, unread }`; `changed` and `unread` name what read
        differently and what could not be compared. A row that did not build or gave no read is not tried
        (`moved` None, `tried` false, with the reason); a row where nothing could be compared has `moved` None.
        These reads are not states of the motion."""
        base = self.discovery_base if isinstance(self.discovery_base, dict) else self.e0
        for row, result, read in entries:
            param = (row.get("varied") or [None])[0]
            if param is None:
                continue
            value = (row.get("state") or {}).get(param)
            entry = {"param": param, "value": value, "built": not result.get("error"), "moved": None}
            if result.get("error"):
                step = ((result.get("detail") or {}).get("items") or [""])[0]
                entry.update(failed=step, tried=False, reason=not_built_try(value, step))
            elif not isinstance(read, dict):
                entry.update(tried=False, reason=NOT_READ_TRY)
            else:
                changed, unread = self.differences(base, read)
                entry.update(changed=changed, unread=unread)
                if changed:
                    entry["moved"] = True
                elif self._comparable(base):
                    entry["moved"] = False
            self.discovery.append(entry)

    def _names(self):
        """Sketch token to the name a reason uses."""
        named = dict(plan.scan(self.capture).named)
        for token, hint in self.watch.items():
            named[token] = "%s of %s" % (hint["sketch"], hint["component"]) if hint.get("component") else (
                hint.get("sketch") or named.get(token, ""))
        return named

    def _comparable(self, read):
        """True when `read` holds anything the discovery compares."""
        return isinstance(read, dict) and bool(read.get("sketches") or read.get("refs") or _box_numbers(read))

    def differences(self, base, read):
        """`(changed, unread)` between two reads of the design: names of the sketches, hole points, axis lines and
        measured references the probe follows, and "the body" (its box and volume), that read differently in `read`,
        and of those that one of the two reads does not hold. Sketches are compared as read (frame and curves within
        1e-4 mm), so a sketch on another outline in both reads is the same."""
        changed, unread = [], []
        names = self._names()

        def sort(name, a, b, same):
            if a is None or b is None:
                unread.append(name)
            elif not same(a, b):
                changed.append(name)

        for token in self.request.get("sketches") or []:
            sort(names.get(token) or "a sketch", ((base or {}).get("sketches") or {}).get(token),
                 ((read or {}).get("sketches") or {}).get(token), match.same_read)
        for kind in ("points", "lines"):
            for token in self.request.get(kind) or []:
                sort("a sketch %s" % kind[:-1], ((base or {}).get(kind) or {}).get(token),
                     ((read or {}).get(kind) or {}).get(token), _same_numbers)
        for ref in self.refs:
            sort(ref["key"], ref_fit.state_values(ref, base)[0], ref_fit.state_values(ref, read)[0], _same_numbers)
        if _box_numbers(base) is None or _box_numbers(read) is None:
            unread.append("the body")
        elif body_changed(base, read):
            changed.append("the body")
        return list(dict.fromkeys(changed)), list(dict.fromkeys(n for n in unread if n not in changed))

    def _followed_targets(self):
        return [t for t in plan.scan(self.capture).targets if t["sketch_token"] in self.request["sketches"]
                and (t["kind"] != "path" or match.matches_capture(t, self.e0))]

    def _followed_moved(self, targets, read):
        """True when a sketch or a measured reference the probe follows reads differently in `read` than at E0."""
        return (any(self._target_moved(t, read) for t in targets)
                or any(ref_fit.moved_in(r, read) for r in self.refs))

    def _body_only(self, skip):
        """Fusion names of the sizes that changed the body in a state where they alone differ, and in no such state
        moved a sketch or reference the probe follows: the body changes by a route the copy does not model."""
        current = {e.name: e.value for e in self.table.entries}
        targets = self._followed_targets()
        body, followed = [], set()
        for state in self.states[1:]:
            read = state.get("read")
            if state.get("built") is False or not isinstance(read, dict):
                continue
            varied = [n for n, v in (state.get("values") or {}).items() if abs(v - current.get(n, v)) > 1e-9]
            if len(varied) != 1:
                continue
            if self._followed_moved(targets, read):
                followed.add(varied[0])
            elif body_changed(self.e0, read) and varied[0] not in body:
                body.append(varied[0])
        # A size tried only for a sketch plane, or only for the distance of an offset plane a step places, feeds
        # step values: those follow it (or mark it), so its body change is explained.
        placed = (set(plane_sizes.plane_driven(self.capture, self.table)) - set(plan.sketch_driven(self.table))
                  | set(construction_only(self.table, self.capture)))
        return [n for n in body if n not in followed and n not in skip and n not in placed]

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
        alone = {name for state in self.states[1:] for name in (state.get("values") or {})
                 if len(state.get("values") or {}) == 1}
        self.untried.extend(p for p in self._unrun if p in self._moving and p not in alone and p not in self.untried)
        for param in self.untried:
            found.append(self._entry(param, _UNTRIED, labels))
        try:
            # The read once the measured rows were done and the parameters back tells whether the last row's sketch
            # came back; the discovery rows ran after it.
            settled = self.rows_end if isinstance(self.rows_end, dict) else after
            self.motion = build.build(self.capture, self.table, self.states, settled)
        except Exception:
            self.motion = None
            current = {e.name: e.value for e in self.table.entries}
            self.moved = list(dict.fromkeys(self.moved + build.moved_sizes(self.capture, self.states, current)))
            found.extend(self._entry(p, _UNREADABLE, labels) for p in self.moved if p not in self.untried)
        found.extend(self._watched(labels, {f["param"] for f in found}))
        if self.motion is not None:
            self.motion.untried = list(self.untried)
            self.motion.body_moved = self._body_only({f["param"] for f in found})
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

    def derived_record(self):
        """The `derived` block of `report.json` (`probe.derived.shadow`): what reading the sketch graphs gives, set
        against the states this probe read. None when the capture has no sketch graphs."""
        return derived.shadow(self.capture, self.table, self.states, self.motion)

    def _gap(self, after):
        """Largest difference in mm between E0 and a read after the restore, over the covered values and the places of
        the measured references (one that cannot be read again is left out). None when a sketch cannot be compared;
        `restore_unchecked` then says which and why."""
        self.restore_unchecked = []
        if not isinstance(after, dict):
            self.restore_unchecked = ["the design could not be read after the tries"]
            return None
        found = plan.scan(self.capture)
        gap = 0.0
        for ref in self.refs:
            before, _ = ref_fit.state_values(ref, self.e0)
            now, _ = ref_fit.state_values(ref, after)
            if before is not None and now is not None:
                gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
        for target in found.targets:
            if target["sketch_token"] not in self.request["sketches"] or (
                    target["kind"] == "path" and not match.matches_capture(target, self.e0)):
                continue
            before, _ = match.state_values(target, self.e0, self.e0)
            now, cause = match.state_values(target, after, self.e0)
            if before is None or now is None or before.keys() != now.keys():
                why = _RESTORE_WHY.get(cause, _RESTORE_WHY[SHAPE])
                self.restore_unchecked.append("%s %s" % (target["sketch"] or "a sketch", why))
                continue
            gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
        self.restore_unchecked = list(dict.fromkeys(self.restore_unchecked))
        return None if self.restore_unchecked else gap

    def report(self):
        """The record kept in `report.json`: what was asked, what was read, and what was found."""
        out = {
            "request": self.request,
            "states": [self._state_json(s) for s in self.states],
            "dropped": list(self.dropped),
            "untried": list(self.untried),
            "restore_gap_mm": self.restore_gap_mm,
            "motion": self.motion.json() if self.motion is not None else None,
            "discovery": list(self.discovery),
        }
        if self.after_rows is not None:
            out["after_rows"] = dict(self.after_rows)
        if self.restore_unchecked:
            out["restore_unchecked"] = list(self.restore_unchecked)
        if self.recovery:
            out["recovery"] = dict(self.recovery)
        if self.stopped:
            out["stopped"] = dict(self.stopped)
        return out

    @staticmethod
    def _state_json(state):
        out = {"values": state.get("values") or {}, "built": state.get("built") is not False}
        if state.get("failed"):
            out["failed"] = state["failed"]
        if state.get("e0"):
            out["e0"] = True
        if state.get("again"):
            out["again"] = True
        for key in ("read", "start", "put_back"):
            if isinstance(state.get(key), dict):
                out[key] = {k: v for k, v in state[key].items() if k in _STATE_KEYS}
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

    def read_now(self, values=None):
        """The probe state of each part as the design is now (`SizeProbe.read_now`)."""
        return [probe.read_now(values) for probe in self.probes]

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
        rows = plan.nearer_rows(sizes, marked_states(first.states, changed), moving,
                                min(room, plan.MAX_NEARER_ROWS - first.nearer_count))
        for probe in self.probes:
            probe.nearer_count += len(rows)
        return rows

    def check_rows(self, sizes, room):
        """The check rows for all parts: a size curved in any part counts as curved for all."""
        first = self.probes[0]
        if first.checked:
            return []
        for probe in self.probes:
            probe.checked = True
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


def shadow_of(probe, log, name=""):
    """The `derived` block of a probe, or `{ "error": text }` when working it out failed: shadow mode never stops an
    export. `log(text)` gets one line about it (`name` leads the line of a part)."""
    try:
        block = probe.derived_record()
    except Exception as exc:
        block = {"error": ("%s: %s" % (type(exc).__name__, exc))[:300]}
        line = "sketch reading, shadow: failed (%s)" % block["error"]
    else:
        line = derived.log_line(block) if block is not None else ""
    if log is not None and line:
        log("%s%s" % ("%s: " % name if name else "", line))
    return block
