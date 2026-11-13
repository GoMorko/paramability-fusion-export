"""What the discovery rows show: which unticked parameters also change the part."""
from ...probe import match, plan, ref_fit
from .reasons import NOT_READ_TRY, NOT_TRIED, NOT_TRIED_STOPPED, not_built_try
from .states import body_changed, box_numbers, same_numbers


class Discovery:
    """The discovery calls of `SizeProbe`."""

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
