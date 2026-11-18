"""The size probe of one part: its states, the rows it plans, what the discovery rows show and the motion it
builds. The try runner and the pipeline call it through `interface.Probe`. Pure: no Fusion."""
from ...design_edit.marker import MARKER_LOST
from ...geometry.tolerances import FIT_TOLERANCE, FLIP_TOLERANCE, SAME_SIZE
from ...package.manifest import MAX_FIXED_REASON
from ...package.text import clip
from ...params.geometry_links import outside_drivers
from ...probe import build, derived, match, pieces, plan, plane_sizes, ref_fit, same_shape, series
from ...probe.state import ProbeState
from ...timing import trail
from ...design_edit.apply import as_step, detail_steps
from ...design_model.tried_ranges import part_step
from ...sketch_values.motion import ENDED_STOPPED, ENDED_TIME, SHAPE
from ...translator.notes import TIMED_OUT_WHY, loose_reason
from ...design_model.reach import probed_sizes
from ...translator.sizes import construction_only
from .borrowed_view import borrowed_sketches, probe_view, with_borrowed
from .differences import comparable, read_differences, sketch_names
from .reasons import (CLEARED_TRY, NOT_READ_TRY, NOT_TRIED, NOT_TRIED_ENDED, NOT_TRIED_STOPPED, NOT_TRIED_TIME,
                      UNREADABLE, UNTRIED, WARNED_TRY, not_built_try, watched_why)
from .restore_check import restore_gap
from .row_schedule import DONE, FAR, NEAR, RowSchedule
from .shared_reads import SharedReads
from .states import (BODY_REQUEST, body_changed, body_compared, body_difference, marked_states, moves_others,
                     same_numbers)

# What an outline read (`SizeProbe.read_now`) leaves out of the request.
OUTLINE_SKIPS = ("params", "refs", "target", "patterns")


class SizeProbe:
    """One export's sketch states and what they gave. Build it with `start`, which returns None when there is
    nothing to follow.

    The states, the rows, the discovery and the findings stay in one class: all four read the same E0, request,
    followed references and states, and the try runner and the pipelines ask each of them of the probe
    (`interface.Probe`). Collaborators for discovery and findings would need that state handed in and a forwarding
    method on the probe for most of their members."""

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
        self.restore_unchecked = []  # "<sketch> <why>" for each sketch the restore check could not compare
        self.restore_changed = []  # "<sketch> <why>" for each sketch the restore check found on another outline
        self.restore_body = []  # what of the body differs from its start once the design is back (`measure_body`)
        self.body_start = None  # the body read after the first rebuild of the tries (`keep_body_start`)
        self.recovery = None  # what was done when a sketch stayed on another solution (`note_recovery`)
        self.stopped = None  # `{ after, items }` when a try left the design broken and the tries stopped (`note_stop`)
        self._unrun = []  # the sizes of the rows planned that did not run because the tries stopped
        self.ended = []  # `{ after, items, steps, components, sizes }` of each try after which some sizes ended
        self._ended = []  # the sizes whose tries ended so (`note_ended`)
        self.time_limit = None  # `{ limit_seconds, hit, seconds }` of the tries' time limit (`note_time_limit`)
        self._timed_out = []  # the sizes of the rows the time limit kept from running
        self._unfinished = {}  # size to `{side: why}` of the sides whose nearer tries never ran (`note_unfinished`)
        self._changes = None  # (number of states, `outline_changes`) of the last time it was worked out
        self._mine = None  # `tried_ranges.part_step` of the capture, made once (`counts_warning`)
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
        before the row ran, and `again`, true for a row run a second time (`pipeline.ProbeRun`).

        A row that built the part in several separate pieces, while it was one at E0 (`pieces.came_apart`), is kept
        as a row that did not build, with the number of pieces: the app cannot build the part there. A row where a
        step the part is built from shows a new warning (the result's `warned`, `tried_ranges.part_step`) is kept
        as a row that did not build too, with that step: Fusion may have built something else there than the copy
        would, so the ranges stop before it as before a step in error. So is a row where a step the part is built
        from that is in error at the start builds (the result's `cleared`): the copy leaves that step out, so it
        lacks what the step makes there. A row in error keeps the first step in error
        that the part is built from (the first step in error when none is). Each step is kept with its timeline
        position (`ProbeState.failed_at`), since another component can have a step of the same name."""
        for values, result, read, *rest in entries:
            start = rest[0] if rest else None
            more = rest[1] if len(rest) > 1 and isinstance(rest[1], dict) else {}
            put_back = more.get("put_back")
            kept = {"start": start if isinstance(start, dict) else None,
                    "put_back": put_back if isinstance(put_back, dict) else None, "again": bool(more.get("again"))}
            apart = None if result.get("error") else pieces.came_apart(read, self.e0)
            warned = [step for step in map(as_step, result.get("warned") or ()) if self.counts_warning(step)]
            cleared = [step for step in map(as_step, result.get("cleared") or ()) if self.counts_warning(step)]
            if result.get("error"):
                detail = result.get("detail") or {}
                steps = detail_steps(detail)
                at, name = next((s for s in steps if self.counts_warning(s)), steps[0] if steps else (None, ""))
                state = ProbeState(values or {}, built=False, failed=name, failed_at=at, **kept)
                self.dropped.append({"name": result.get("name"), "error": result.get("error"), "detail": detail})
            elif warned:
                at, name = warned[0]
                state = ProbeState(values or {}, built=False, failed=name, failed_at=at, warned=True, **kept)
                self.dropped.append({"name": result.get("name"), "error": WARNED_TRY % name,
                                     "detail": {"reason": "new_warnings", "items": [n for _, n in warned],
                                                "at": [a for a, _ in warned]}})
            elif cleared:
                at, name = cleared[0]
                state = ProbeState(values or {}, built=False, failed=name, failed_at=at, cleared=True, **kept)
                self.dropped.append({"name": result.get("name"), "error": CLEARED_TRY % name,
                                     "detail": {"reason": "cleared_errors", "items": [n for _, n in cleared],
                                                "at": [a for a, _ in cleared]}})
            elif apart:
                state = ProbeState(values or {}, built=False, pieces=apart, **kept)
                self.dropped.append({"name": result.get("name"), "error": pieces.APART_ERROR % apart})
            else:
                state = ProbeState(values or {}, read=read, **kept)
            self.states.append(state)

    def counts_warning(self, step):
        """True when a new warning on the timeline item `step` (`(position, name)`) makes a row count as not built: a
        step the part is built from (`tried_ranges.part_step`)."""
        if self._mine is None:
            self._mine = part_step(self.capture)
        return self._mine(step)

    def followed_sketches(self):
        """Tokens of the sketches this probe reads at every row."""
        return list(self.request.get("sketches") or [])

    def left_start(self, read):
        """True when a followed sketch reads otherwise than at E0 in `read` (`off_start`)."""
        return bool(self.off_start(read))

    def off_start(self, read):
        """Tokens of the followed sketches that read otherwise than at E0 in `read`, a read taken with every value
        back: the sketch stayed on another solution (another outline, or the same outline more than `FLIP_TOLERANCE`
        away). A sketch that could not be read does not count, nor one whose curves are the curves of E0 within
        `FLIP_TOLERANCE` once their tokens, order and direction are set aside (`same_shape`): Fusion gave a curve a new
        token or listed it otherwise, and the outline is the same."""
        if not isinstance(read, dict):
            return []
        if self._e0_values is None:
            self._e0_values = [(t, match.state_values(t, self.e0, self.e0)[0]) for t in self._followed_targets()]
        found = []
        for target, before in self._e0_values:
            token = target["sketch_token"]
            if token in found or before is None:
                continue
            now, cause = match.state_values(target, read, self.e0)
            if now is None and cause != SHAPE:
                continue
            if now is not None and now.keys() == before.keys() and all(
                    abs(now[k] - v) <= FLIP_TOLERANCE for k, v in before.items()):
                continue
            if target["kind"] == "profile" and self._same_shape(token, read, FLIP_TOLERANCE) is not None:
                continue
            found.append(token)
        return found

    def _same_shape(self, token, read, tolerance):
        """The largest gap of the sketch `token` in `read` to its E0 read when their curves pair within `tolerance`
        whatever their tokens, order and direction (`same_shape.shape_gap`), else None."""
        before = (self.e0.get("sketches") or {}).get(token)
        now = ((read or {}).get("sketches") or {}).get(token)
        return same_shape.shape_gap(before, now, tolerance)

    def note_recovery(self, record):
        """Keep what `pipeline.ProbeRun` did when a sketch stayed on another solution, for `report`."""
        self.recovery = dict(record)

    def note_stop(self, record, unrun=()):
        """Keep the try after which a timeline step stayed worse than before the tries with the values back, the steps
        and their changes (`steps`), for `report`: the tries stopped there. `unrun` are the rows planned that did not
        run; `finish` lists a size of theirs that moves a sketch and has no try of its own as untried."""
        self.stopped = {"after": record.get("after"), "items": list(record.get("items") or [])}
        if record.get("steps"):
            self.stopped["steps"] = [dict(step) for step in record["steps"]]
        self._unrun.extend(p for row in unrun for p in row.get("varied") or [] if p not in self._unrun)

    def note_ended(self, record, unrun=()):
        """Keep a try after which steps of another component stayed worse with the values back, while the part read
        as at the start: `record` is `{ after, items, steps, components, sizes }`, and the tries of `sizes` ended
        there while the other sizes went on (`pipeline.ProbeRun`). `finish` lists such a size that moves a sketch and
        has no try of its own as untried, and `note_unfinished` marks its sides whose nearer tries never ran. `unrun`
        are rows that did not run because they move such a size or parameter; a discovery row among them is kept as
        not tried. `record` is None when only `unrun` is new."""
        if record is not None:
            self.ended.append({k: v for k, v in record.items() if k in ("after", "items", "steps", "components",
                                                                         "sizes")})
            self._ended.extend(p for p in record.get("sizes") or [] if p not in self._ended)
            self._unrun.extend(p for p in record.get("sizes") or [] if p not in self._unrun)
        for row in unrun:
            param = (row.get("varied") or [None])[0]
            if str(row.get("key", "")).startswith(plan.DISCOVERY_KEY) and param is not None and all(
                    d["param"] != param for d in self.discovery):
                self.discovery.append({"param": param, "moved": None, "tried": False, "reason": NOT_TRIED_ENDED})

    def reads_as_start(self, read):
        """True when `read`, taken with every value back, shows the part as at the start of the tries: every followed
        sketch as at E0 (`left_start`), the sketches, points, lines, references and box as at E0 (`matches_start`), and
        the body as at the start of the tries (`body_start`, else E0; `body_difference` finds nothing)."""
        if not isinstance(read, dict) or self.left_start(read) or not self.matches_start(read):
            return False
        found = body_difference(self.body_start if self.body_start is not None else self.e0, read)
        return found is not None and not found.texts

    def note_time_limit(self, record, unrun=()):
        """Keep the time limit of the tries for `report`: `record` is `{ limit_seconds, hit, seconds }`, `hit` true once
        the tries stopped because the limit was reached. `unrun` are the rows planned that did not run for that
        reason: a size of theirs that moves a sketch and has no built try of its own is listed as loose (`finish`), a
        discovery row among them is kept as not tried."""
        self.time_limit = dict(record)
        for row in unrun:
            if str(row.get("key", "")).startswith(plan.DISCOVERY_KEY):
                param = (row.get("varied") or [None])[0]
                if param is not None and all(d["param"] != param for d in self.discovery):
                    self.discovery.append({"param": param, "moved": None, "tried": False, "reason": NOT_TRIED_TIME})
            else:
                self._timed_out.extend(p for p in row.get("varied") or [] if p not in self._timed_out)

    def note_unfinished(self, sizes, states=None, moving=None):
        """After the tries stopped early (`note_stop`), ended for some sizes (`note_ended`, those sizes only) or ran
        out of time (`note_time_limit`): keep the sides of the sizes where the nearer tries were still to come
        (`plan.nearer_left`), so the values between the farthest value that built and the nearest one that did not
        were never tried. `finish` writes them into `Motion.spans`
        (`unfinished`). When the nearer tries had used their rows (`plan.MAX_NEARER_ROWS`), the search had ended
        anyway and nothing is kept. `states` and `moving` are the marked states and the moving sizes to judge by, this
        probe's own by default (`ProbeGroup` passes those of all parts)."""
        why = ENDED_STOPPED if self.stopped else ENDED_TIME if self._hit_limit() else None
        if (why is None and not self._ended) or (
                states is None and self.schedule.nearer_room(plan.MAX_NEARER_ROWS) <= 0):
            return
        states = self._marked() if states is None else states
        moving = self.moving_sizes() if moving is None else moving
        for param, sides in plan.nearer_left(sizes, states, moving).items():
            cause = ENDED_STOPPED if param in self._ended else why
            if cause is not None:
                self._unfinished.setdefault(param, {}).update((side, cause) for side in sides)

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
            varied = [n for n, v in values.items() if abs(v - current.get(n, v)) > SAME_SIZE]
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
        return any(abs(now[k] - v) > FIT_TOLERANCE for k, v in before.items())

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

    def far_order(self, sizes, late=(), captures=None):
        """The Fusion names of the sizes `probe_rows` tried, in the order their far rows run (`plan.far_order`): among
        the favourites and among the rest, those that drive a step outside the parts of `captures`
        (`geometry_links.outside_drivers`; this probe's capture by default) after the others, and the sizes in `late`
        and those whose tries so far moved a reference of another component (`moves_others`) last."""
        planned = self.schedule.take(NEAR)
        if planned is None:
            return []
        late = set(late) | set(moves_others(self.states, self.refs, {e.name: e.value for e in self.table.entries}))
        risky = outside_drivers([self.capture] if captures is None else captures)
        return plan.far_order(sizes, *planned, late=late, risky=risky)

    def far_rows(self, sizes, room, states=None, only=None):
        """The rows at the far range ends of the sizes `probe_rows` tried, within `room` rows (`plan.far_rows`): of the
        sizes in `only` (Fusion names), or of every size whose far rows were not planned yet, and then the far pair rows
        (`far_pair_rows`) once (`RowSchedule.far_sizes`)."""
        planned = self.schedule.take(NEAR)
        if planned is None:
            return []
        moved, extra = planned
        names = self.schedule.far_sizes(plan.far_order(sizes, moved, extra), only)
        return plan.far_rows(sizes, moved, room, extra, self._marked() if states is None else states, only=names)

    def far_pair_rows(self, sizes, room, states=None):
        """Once, after the far rows: all sizes at their minimum, then at their maximum (`plan.far_pair_rows`)."""
        planned = self.schedule.take(FAR, then=DONE)
        if planned is None:
            return []
        moved, extra = planned
        return plan.far_pair_rows(sizes, moved, self._marked() if states is None else states, room, extra=extra)

    def nearer_rows(self, sizes, room, only=None):
        """The next rows that try the sizes nearer to their value now where rows did not build or changed a followed
        outline (`plan.nearer_rows`; only the sizes in `only` when given), within `room` rows and the export's
        `plan.MAX_NEARER_ROWS`."""
        rows = plan.nearer_rows(sizes, marked_states(self.states, self.outline_changes()), self.moving_sizes(),
                                self.schedule.nearer_room(room), only)
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
        why = NOT_TRIED_STOPPED if self.stopped else NOT_TRIED_TIME if self._hit_limit() else NOT_TRIED
        self.discovery.extend({"param": c["param"], "moved": None, "tried": False, "reason": why}
                              for c in plan.discovery_left(candidates, room))
        return rows

    def _hit_limit(self):
        return bool(self.time_limit and self.time_limit.get("hit"))

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
                elif comparable(base):
                    entry["moved"] = False
            self.discovery.append(entry)

    def differences(self, base, read):
        """`(changed, unread)` between two reads of the design (`differences.read_differences`)."""
        return read_differences(self.request, self.refs, sketch_names(self.capture, self.watch), base, read)

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
        timed = self.time_left_out()
        self.untried.extend(p for p in timed if p not in self.untried)
        for param in self.untried:
            found.append(self._entry(param, TIMED_OUT_WHY if param in timed else UNTRIED, labels))
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
            self.motion.timed_out = list(timed)
            for param, sides in self._unfinished.items():
                if param in self.motion.spans:
                    self.motion.spans[param]["unfinished"] = dict(sides)
            self.motion.body_moved = self._body_only({f["param"] for f in found})
        self.measure_restore(after)
        return found

    def _built_alone(self):
        """Fusion names of the sizes with a try of their own that built."""
        return {name for state in self.states[1:] if state.built for name in state.values if len(state.values) == 1}

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

    @trail.staged("compare sketches with the start")
    def _gap(self, after):
        """Largest difference in mm between E0 and a read after the restore (`restore_check.restore_gap`), or None when
        a sketch cannot be compared; keeps `restore_unchecked` and `restore_changed`."""
        gap, self.restore_unchecked, self.restore_changed = restore_gap(self._followed_targets(), self.refs, self.e0,
                                                                         after)
        return gap

    @trail.staged("read body start")
    def keep_body_start(self):
        """Read the target body now and keep it as the start of the end check (`measure_body`). Called once, after the
        first rebuild of the tries with every value at its start: E0 is read before any rebuild, and a rebuild alone
        can change how Fusion reports the body. Never raises; a read without a box or a volume is not kept."""
        try:
            read = self.read(dict(BODY_REQUEST))
        except Exception:
            read = None
        if isinstance(read, dict) and MARKER_LOST not in (read.get("unread") or {}) and body_compared(read, read):
            self.body_start = read

    @trail.staged("read body at the end")
    def measure_body(self):
        """Read the target body now and compare it with its start (`body_start`, else E0): its box, its volume and
        the number of its solids, and the other bodies of its component against E0, which reads every timeline item
        (`body_difference`). Called once every value, timeline item and the timeline marker are back. Returns the
        `BodyCheck`, and keeps its texts (`restore_body`); None when the two reads cannot be compared."""
        try:
            now = self.read(dict(BODY_REQUEST))
        except Exception:
            now = None
        before = self.body_start if self.body_start is not None else self.e0
        found = body_difference(before, now, self.e0)
        self.restore_body = found.texts if found is not None else []
        return found

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
        if self.restore_changed:
            out["restore_changed"] = list(self.restore_changed)
        if self.restore_body:
            out["restore_body"] = list(self.restore_body)
        if self.recovery:
            out["recovery"] = dict(self.recovery)
        if self.stopped:
            out["stopped"] = dict(self.stopped)
        if self.ended:
            out["ended"] = [dict(record) for record in self.ended]
        if self.time_limit is not None:
            out["time_limit"] = dict(self.time_limit, left_out=self.time_left_out())
        return out

    def time_left_out(self):
        """Fusion names of the sizes that move a sketch or a measured place and that the time limit left without a try
        that built on its own: the copy cannot follow them, so `finish` lists them as loose. A size tried on a guess
        (`extra`) that got no try is not counted: nothing is known to move with it."""
        built = self._built_alone()
        return [p for p in self._timed_out if p in self.schedule.moved and p not in built]

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
            varied = [n for n, v in state.values.items() if abs(v - current.get(n, v)) > SAME_SIZE]
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
