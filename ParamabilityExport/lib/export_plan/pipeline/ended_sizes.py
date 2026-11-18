"""The sizes whose tries ended after a lasting change outside what the tries need: the part of the try runner that
decides it, keeps the record and keeps their rows from running (`ProbeRun`, `outside_damage`)."""
from ...design_edit.runner import ExportCancelled


class EndedSizes:
    """The ended sizes of `ProbeRun`, which holds the job (`job`, a `RowExport`), the probe, the port, the judge of
    the steps a try left worse (`damage`, `outside_damage.OutsideDamage`), the sizes `measure` was given (`_tried`),
    the records noted so far (`ended`), the names whose tries ended (`ended_names`) and the read with the values back
    (`_read_now`, `_mark`)."""

    def _contain(self, worse, row):
        """`RowExport`'s `contain`: what ends with `row` (`OutsideDamage.judge`, the sizes it gives that `measure` was
        given) when every step in `worse` is outside what the tries need and the part reads as at the start with the
        values back (`Probe.reads_as_start`); else None, and the tries stop."""
        found = self.damage.judge(worse, row)
        if found is None:
            return None
        try:
            read = self._mark(self._read_now({}))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"reading the part after a lasting change failed: {exc!r}")
            return None
        if not self.probe.reads_as_start(read):
            return None
        found["sizes"] = list(dict.fromkeys(found["sizes"] + [p for p in found["params"] if p in self._tried]))
        return found

    def _take_ended(self):
        """Note the checks that ended the tries of some sizes since the last call (`RowExport.ended`): their sizes and
        parameters join `ended_names`, and the probe is told. True when there was one."""
        new = self.job.ended[len(self.ended):]
        for record in new:
            self.ended.append(record)
            self.ended_names.extend(n for n in record["sizes"] + record["params"] if n not in self.ended_names)
            self.port.log("tries of %s ended: %s of %s stayed worse with the values back after %s"
                          % (", ".join(record["sizes"]), ", ".join(record["items"]),
                             ", ".join(record["components"]), record["after"]))
            self.probe.note_ended(record)
        return bool(new)

    def _without_ended(self, rows):
        """`rows` without those that move a size or parameter whose tries ended (`ended_names`); the probe is told of
        those left out."""
        ended = set(self.ended_names)
        left = [row for row in rows if ended & set(row.get("varied") or ())]
        if left:
            self.probe.note_ended(None, left)
        return [row for row in rows if not ended & set(row.get("varied") or ())]

    def _live(self, sizes):
        """The probe sizes whose tries did not end (`ended_names`)."""
        ended = set(self.ended_names)
        return [size for size in sizes if size["param"] not in ended]
