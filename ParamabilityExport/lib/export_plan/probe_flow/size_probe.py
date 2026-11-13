"""The size probe of one part: its states, and the calls the try runner and the pipeline use."""
from ...design_edit.marker import MARKER_LOST
from ...probe import build, fit, match, plan, plane_sizes, ref_fit
from ...sketch_values.motion import SHAPE
from .borrowed_view import borrowed_sketches, probe_view, with_borrowed
from .discovery import Discovery
from .findings import Findings
from .row_planning import RowPlanning
from .shared_reads import SharedReads
from .states import same_numbers

# What an outline read (`SizeProbe.read_now`) leaves out of the request.
OUTLINE_SKIPS = ("params", "refs", "target", "patterns")
# How far a followed value (mm or degrees) may read from E0 once the values are back before the sketch counts as on
# another solution; Fusion's own restore leaves up to about a hundredth of a degree on short lines.
FLIP_TOLERANCE = 0.05


class SizeProbe(RowPlanning, Discovery, Findings):
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
        self._targets = None  # the followed targets (`_followed_targets`), worked out once
        self._e0_values = None  # (target, its E0 values) of each followed target (`left_start`), worked out once

    @classmethod
    def start(cls, capture, table, read):
        """Read E0 and keep the sketches whose first read matches the capture. None when no sketch stays covered or
        Fusion gave no read."""
        hints, view = borrowed_sketches(capture), probe_view(capture)
        bare = {"sketches": [], "points": [], "lines": [], "params": [], "target": True}
        wide = plan.request(view, table) or (bare if hints else None)
        if wide is None:
            return None
        e0 = read(with_borrowed(wide, hints, hints))
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
        return cls(capture, table, read, with_borrowed(request, hints, watch), e0, watch, measured.usable)

    # ---- states -----------------------------------------------------------------------------------------------

    def read_now(self, values=None, outline=False, park=False):
        """The probe state of the design as it is now. `values` are the sizes set to other values now ({} with every
        value back): a face a step uses as its outline is read only when one of them may change it, since each face
        read rolls the timeline back and forth; the others take their E0 read. None reads every face. With `outline`
        only what tells the outlines apart is read (sketches, points, lines and those faces): no parameters,
        references or body box, which a read that only checks where the design starts from does not use. With `park`
        a face read leaves the marker before the face's step (`read_face.read_faces`); the caller brings it back."""
        asked = {k: v for k, v in self.request.items() if not outline or k not in OUTLINE_SKIPS}
        faces = asked.get("faces") or {}
        moved = set(values or ())
        wanted = {k: v for k, v in faces.items() if values is None or self.face_sizes.get(k, set()) & moved}
        if park and wanted:
            asked = dict(asked, park=True)
        if len(wanted) == len(faces):
            return self.shared.share(self.read(asked))
        request = dict(asked, faces=wanted) if wanted else {k: v for k, v in asked.items() if k != "faces"}
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
        if self._e0_values is None:
            self._e0_values = [(t, match.state_values(t, self.e0, self.e0)[0]) for t in self._followed_targets()]
        for target, before in self._e0_values:
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
        return all(set(before[k]) == set(now[k]) for k in keys) and same_numbers(before, now)

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

    def _followed_targets(self):
        """The targets of the followed sketches (a sweep path only when it read as captured at E0). The capture, the
        request and E0 do not change after `start`, so they are worked out once."""
        if self._targets is None:
            self._targets = [t for t in plan.scan(self.capture).targets if t["sketch_token"] in self.request["sketches"]
                             and (t["kind"] != "path" or match.matches_capture(t, self.e0))]
        return list(self._targets)

    def _followed_moved(self, targets, read):
        """True when a sketch or a measured reference the probe follows reads differently in `read` than at E0."""
        return (any(self._target_moved(t, read) for t in targets)
                or any(ref_fit.moved_in(r, read) for r in self.refs))

    def _target_moved(self, target, read):
        before, _ = match.state_values(target, self.e0, self.e0)
        now, _ = match.state_values(target, read, self.e0)
        if before is None:
            return False
        if now is None or now.keys() != before.keys():
            return True
        return any(abs(now[k] - v) > fit.TOLERANCE for k, v in before.items())
