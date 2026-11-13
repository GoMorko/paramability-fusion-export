"""What a probe found: the motion, the loose sizes, the restore gap and the record for `report.json`."""
from ...package.manifest import MAX_FIXED_REASON
from ...package.text import clip
from ...probe import build, derived, match, plan, plane_sizes, ref_fit
from ...sketch_values.motion import SHAPE
from ...translator.notes import loose_reason
from ...translator.sizes import construction_only
from .reasons import _RESTORE_WHY, _UNREADABLE, _UNTRIED, _watched_why
from .states import body_changed

_STATE_KEYS = ("sketches", "points", "lines", "params", "box", "refs", "faces", "patterns", "unread")


class Findings:
    """The result calls of `SizeProbe`."""

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
