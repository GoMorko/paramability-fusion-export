"""The size probe of one part: its states, the rows it plans, what the discovery rows show and the motion it
builds. The try runner and the pipeline call it through `interface.Probe`. Pure: no Fusion."""
from ...design_edit.marker import MARKER_LOST
from ...package.manifest import MAX_FIXED_REASON
from ...package.text import clip
from ...probe import build, derived, fit, match, plan, plane_sizes, ref_fit, series
from ...probe.state import ProbeState
from ...sketch_values.motion import SHAPE
from ...translator.notes import loose_reason
from ...translator.sizes import construction_only, probed_sizes
from .borrowed_view import borrowed_sketches, probe_view, with_borrowed
from .reasons import (NOT_READ_TRY, NOT_TRIED, NOT_TRIED_STOPPED, RESTORE_WHY, UNREADABLE, UNTRIED, not_built_try,
                      watched_why)
from .row_schedule import DONE, FAR, NEAR, RowSchedule
from .shared_reads import SharedReads
from .states import body_changed, box_numbers, marked_states, same_numbers

# What an outline read (`SizeProbe.read_now`) leaves out of the request.
OUTLINE_SKIPS = ("params", "refs", "target", "patterns")
# How far a followed value (mm or degrees) may read from E0 once the values are back before the sketch counts as on
# another solution; Fusion's own restore leaves up to about a hundredth of a degree on short lines.
FLIP_TOLERANCE = 0.05


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
        self.states = [ProbeState(read=e0, e0=True)]  # `probe.state.ProbeState`, E0 first
        self.dropped = []
        self.untried = []
        self.restore_gap_mm = None
        self.motion = None
        self.moved = []
        self.discovery = []
        self.schedule = RowSchedule()  # the row phase, the sizes the near rows tried, the nearer and check rows
        self.discovery_base = None  # the read the discovery rows are compared with
        self.rows_end = None  # the read once the measured rows were done and the parameters back
        self.after_rows = None  # what read differently from E0 once the parameters were put back after the rows
        self.restore_unchecked = []  # "<sketch>: <why>" for each sketch the restore check could not compare
        self.recovery = None  # what was done when a sketch stayed on another solution (`note_recovery`)
        self.stopped = None  # `{ after, items }` when a try left the design broken and the tries stopped (`note_stop`)
        self._unrun = []  # the sizes of the rows planned that did not run because the tries stopped
        self._changes = None  # (number of states, `outline_changes`) of the last time it was worked out
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
            put_back = more.get("put_back")
            kept = {"start": start if isinstance(start, dict) else None,
                    "put_back": put_back if isinstance(put_back, dict) else None, "again": bool(more.get("again"))}
            if result.get("error"):
                detail = result.get("detail") or {}
                state = ProbeState(values or {}, built=False, failed=(detail.get("items") or [""])[0], **kept)
                self.dropped.append({"name": result.get("name"), "error": result.get("error"), "detail": detail})
            else:
                state = ProbeState(values or {}, read=read, **kept)
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
            values, read = state.values, state.read
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

    # ---- rows ------------------------------------------------------------------------------------------------

    def probe_rows(self, sizes, extra=()):
        """The first extra rows, near the value of each size that moves a sketch: the sizes the states already show
        moving one, every size that reaches a sketch, and every size that may move the plane a sketch sits on
        (`plane_sizes`). Then the sizes in `extra` (Fusion names tried on a guess, `sizes_to_try`) while rows are
        left. Any other size that only feeds step values has no row. The far range ends come later (`far_rows`)."""
        current = {e.name: e.value for e in self.table.entries}
        self.moved = build.moved_sizes(self.capture, self.states, current)
        reach = set(probed_sizes(self.table)) | set(plane_sizes.plane_driven(self.capture, self.table))
        moved = set(self.moved) | {s["param"] for s in sizes if s["param"] in reach}
        rows, self.untried = plan.probe_rows(sizes, moved, extra=set(extra))
        self.schedule.planned(moved, extra)
        return rows

    def _marked(self):
        """The states after E0, those whose own size changed a followed outline marked (`marked_states`)."""
        return marked_states(self.states, self.outline_changes())

    def pair_rows(self, sizes, room, states=None):
        """The near pair rows of the sizes `probe_rows` tried, within `room` rows (`plan.pair_rows`). `states` are the
        marked states to judge by, this probe's own by default."""
        planned = self.schedule.take(NEAR)
        if planned is None:
            return []
        moved, extra = planned
        return plan.pair_rows(sizes, moved, self._marked() if states is None else states, room, extra=extra)

    def far_rows(self, sizes, room, states=None):
        """The rows at the far range ends of the sizes `probe_rows` tried, within `room` rows (`plan.far_rows`), and
        then the far pair rows (`far_pair_rows`) once."""
        planned = self.schedule.take(NEAR, then=FAR)
        if planned is None:
            return []
        moved, extra = planned
        return plan.far_rows(sizes, moved, room, extra=extra, states=self._marked() if states is None else states)

    def far_pair_rows(self, sizes, room, states=None):
        """Once, after the far rows: all sizes at their minimum, then at their maximum (`plan.far_pair_rows`)."""
        planned = self.schedule.take(FAR, then=DONE)
        if planned is None:
            return []
        moved, extra = planned
        return plan.far_pair_rows(sizes, moved, self._marked() if states is None else states, room, extra=extra)

    def nearer_rows(self, sizes, room):
        """The next rows that try the sizes nearer to their value now where rows did not build or changed a followed
        outline (`plan.nearer_rows`), within `room` rows and the export's `plan.MAX_NEARER_ROWS`."""
        rows = plan.nearer_rows(sizes, marked_states(self.states, self.outline_changes()), self.moving_sizes(),
                                self.schedule.nearer_room(room))
        self.schedule.count_nearer(rows)
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
        if not self.schedule.check_once():
            return []
        curved, partners = self.curved_sizes()
        return plan.check_rows(sizes, curved, self.spans_now(), room, partners) if curved else []

    # ---- discovery -------------------------------------------------------------------------------------------

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
        return isinstance(read, dict) and bool(read.get("sketches") or read.get("refs") or box_numbers(read))

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
                     ((read or {}).get(kind) or {}).get(token), same_numbers)
        for ref in self.refs:
            sort(ref["key"], ref_fit.state_values(ref, base)[0], ref_fit.state_values(ref, read)[0], same_numbers)
        if box_numbers(base) is None or box_numbers(read) is None:
            unread.append("the body")
        elif body_changed(base, read):
            changed.append("the body")
        return list(dict.fromkeys(changed)), list(dict.fromkeys(n for n in unread if n not in changed))

    @property
    def also_changes(self):
        """Fusion names of the unticked parameters that a discovery row showed moving the body's sketches or the
        references its steps use."""
        return [d["param"] for d in self.discovery if d["moved"]]

    # ---- findings --------------------------------------------------------------------------------------------

    def finish(self, after, labels):
        """Build the motion and compare the design after the restore with E0.

        Returns the sizes this probe cannot follow, as loose entries ({name, reason, param, size}): the ones left
        without rows, and the ones that moved a sketch when the motion could not be built. `labels` maps a recipe
        size name to the text for the person.
        """
        found = []
        alone = {name for state in self.states[1:] for name in state.values if len(state.values) == 1}
        tried = self.schedule.moved
        self.untried.extend(p for p in self._unrun if p in tried and p not in alone and p not in self.untried)
        for param in self.untried:
            found.append(self._entry(param, UNTRIED, labels))
        try:
            # The read once the measured rows were done and the parameters back tells whether the last row's sketch
            # came back; the discovery rows ran after it.
            settled = self.rows_end if isinstance(self.rows_end, dict) else after
            self.motion = build.build(self.capture, self.table, self.states, settled)
        except Exception:
            self.motion = None
            current = {e.name: e.value for e in self.table.entries}
            self.moved = list(dict.fromkeys(self.moved + build.moved_sizes(self.capture, self.states, current)))
            found.extend(self._entry(p, UNREADABLE, labels) for p in self.moved if p not in self.untried)
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
                values, read = state.values, state.read
                if not state.built or len(values) != 1 or not isinstance(read, dict):
                    continue
                param = next(iter(values))
                now = (read.get("sketches") or {}).get(token)
                if param in done or (now is not None and match.same_read(before, now)):
                    continue
                done.add(param)
                name = hint["sketch"] or "a sketch"
                sketch = "%s of %s" % (name, hint["component"]) if hint["component"] else name
                out.append(self._entry(param, watched_why(sketch), labels))
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
                why = RESTORE_WHY.get(cause, RESTORE_WHY[SHAPE])
                self.restore_unchecked.append("%s %s" % (target["sketch"] or "a sketch", why))
                continue
            gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
        self.restore_unchecked = list(dict.fromkeys(self.restore_unchecked))
        return None if self.restore_unchecked else gap

    def report(self):
        """The record kept in `report.json`: what was asked, what was read, and what was found."""
        out = {
            "request": self.request,
            "states": [s.json() for s in self.states],
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

    def _body_only(self, skip):
        """Fusion names of the sizes that changed the body in a state where they alone differ, and in no such state
        moved a sketch or reference the probe follows: the body changes by a route the copy does not model."""
        current = {e.name: e.value for e in self.table.entries}
        targets = self._followed_targets()
        body, followed = [], set()
        for state in self.states[1:]:
            read = state.read
            if not state.built or not isinstance(read, dict):
                continue
            varied = [n for n, v in state.values.items() if abs(v - current.get(n, v)) > 1e-9]
            if len(varied) != 1:
                continue
            if self._followed_moved(targets, read):
                followed.add(varied[0])
            elif body_changed(self.e0, read) and varied[0] not in body:
                body.append(varied[0])
        # A size tried only for a sketch plane, or only for the distance of an offset plane a step places, feeds
        # step values: those follow it (or mark it), so its body change is explained.
        placed = (set(plane_sizes.plane_driven(self.capture, self.table)) - set(probed_sizes(self.table))
                  | set(construction_only(self.table, self.capture)))
        return [n for n in body if n not in followed and n not in skip and n not in placed]
