"""The walks back of the try runner: a followed sketch left on its other solution is brought back the way the rows
run since it last read as at its start took it away (`ProbeRun`)."""
from ...design_edit import walk_back
from ...timing import trail


class WalkBacks:
    """The walks back of `ProbeRun`, which holds the job (`job`, a `RowExport`), the probe, the port, the rows run in
    order (`_ran`), where each sketch last read as at its start (`_clean_at`, `_since`), the read with the values back
    (`_try_read`) and the record of what was done (`_note`)."""

    @trail.staged("walk back after the tries")
    def _walk_back(self, read):
        """After the tries: for the sketches still off their start in `read`, walk back alone each size that the rows
        run since they last read as at E0 moved (`walk_back.one_size_moves`: once per side of its start value, the last
        rows first), from the other side of its start value, until they read as at E0, at most `walk_back.END_TRIES`
        walks in all. Sketches that last read as at E0 at the same point share their walks. Returns the last read, or
        None when a read failed."""
        groups = {}
        for token in self.probe.off_start(read):
            groups.setdefault(self._clean_at.get(token, 0), []).append(token)
        left = walk_back.END_TRIES
        for since, tokens in sorted(groups.items()):
            ran = self._ran[since:]
            names = list(dict.fromkeys(n for row in ran for n in row.get("values") or {}))
            start = walk_back.start_values(self.port.store, names, self.port.units)
            for row, values in walk_back.one_size_moves(ran, start):
                if left <= 0 or not set(tokens) & set(self.probe.off_start(read)):
                    break
                found = self._walk(dict(row, values=values), 0, walk_back.AT_END, tokens)
                if found is False:
                    continue
                left -= 1
                if found is None:
                    return None
                read = found
        self._note()
        return read

    def _walk_rows(self, tokens, read, at):
        """Bring the sketches `tokens`, off their start in `read`, back the way the rows run since they last read as
        at E0 took them away (`_walk_row`), the last row first, at most `walk_back.ROWS_BACK` rows, a row that repeats
        a later row's values left out. `at` is the key of the row about to run. Returns the last read, or None when a
        read failed."""
        for row in walk_back.distinct_last(self._since(tokens), walk_back.ROWS_BACK):
            if not set(tokens) & set(self.probe.off_start(read)):
                break
            read = self._walk_row(row, tokens, read, at)
            if read is None:
                return None
        return read

    def _walk_row(self, row, tokens, read, at=None):
        """Bring the sketches `tokens`, off their start in `read`, back the way `row` took them away
        (`RowExport.walk_back`), at most `walk_back.ATTEMPTS` times, reading the outlines after each attempt. Returns
        the last read, or None when a read failed."""
        for attempt in range(walk_back.ATTEMPTS):
            if not set(tokens) & set(self.probe.off_start(read)):
                break
            found = self._walk(row, attempt, at, tokens)
            if found is False:
                break
            if found is None:
                return None
            read = found
        self._note()
        return read

    def _walk(self, row, attempt, at, tokens):
        """Attempt number `attempt` of `RowExport.walk_back` for `row`, then a read of the outlines; the attempt's
        report entry gets whether the sketches `tokens` read as at E0 (`back`). Returns the read, False when the
        attempt had nothing to set, or None when the read failed."""
        kept = len(self.job.walks)
        if not self.job.walk_back(row, attempt, at):
            return False
        read = self._try_read()
        if read is not None and len(self.job.walks) > kept:
            self.job.walks[-1]["back"] = not set(tokens) & set(self.probe.off_start(read))
        return read
