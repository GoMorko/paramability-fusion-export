"""The try runner: runs the probe rows in one job, reads each state and puts the followed sketches back."""
from ...design_edit.marker import MARKER_LOST
from ...design_edit.runner import ExportCancelled, RowExport, row_key
from ...design_edit.store import timeline_control
from ...probe.plan.nearer import BISECT_STEPS, NEARER_STEPS
from ...probe.plan.rows import MAX_PROBE_ROWS
from ...timing.timer import Timer, rounded
from .. import messages

# The parts of a probe read the Fusion reader times (`fusion_reader.probe_state.read_state`).
READ_PARTS = ("sketches", "points", "params", "refs", "box", "faces")


def plan_rows_left(rows):
    """How many probe rows the cap leaves after `rows`."""
    return max(0, MAX_PROBE_ROWS - len(rows))


class MarkerNotHeld(Exception):
    """A probe read was asked for while the timeline marker sat before the position the tries need, or a read moved
    the marker and could not put it back."""


def with_try_seconds(summary, roll):
    """The probe's timing summary with the time the tries took as `TryTimeline` counted it (`probe.timeline`)."""
    try:
        return dict(summary, try_seconds=roll.seconds) if summary is not None and roll is not None else summary
    except Exception:
        return summary


def _marker_lost(read):
    """True when a probe read (one state, or one per part) says it could not put the timeline marker back."""
    reads = read if isinstance(read, list) else [read]
    return any(isinstance(r, dict) and MARKER_LOST in (r.get("unread") or {}) for r in reads)


def _row_values(row):
    """The sizes a row sets to other values, by Fusion name."""
    state = row.get("state") or {}
    return {param: state[param] for param in row.get("varied") or [] if param in state}


class ProbeRun:
    """Runs the probe's rows in one job: one baseline, and the parameters put back after every row. The rows only
    recompute (no STEP). `probe` is a `probe_flow.Probe` (one part, or a group of parts over shared rows). It keeps the probe state read at every row that built, by row key, and `rows` lists
    (row, result) of every row run. `read_failure` holds the first probe read that failed: the probe is then not
    used.

    A row that did not build, or left a followed sketch on another outline, may leave that sketch there after the
    parameters are put back: a sketch with two solutions keeps the one it was last solved to. The design is then read
    again before the next row (`starts`, by row key). When a followed sketch reads otherwise than at E0 there, the
    port's sketch keeper (`port.sketch_keeper(tokens)`, kept at E0) moves its points back to where they were and the
    design is rebuilt once (`backs`, by row key), so the row starts from the first solution. After
    `MAX_PUT_BACK_MISSES` put backs in a row that do not bring the sketch back, no more are tried.

    A row that leaves the design broken with the parameters back stops the tries (`RowExport.not_back`): no later
    batch runs, and the probe keeps the states read before (`stopped`).

    The read inside a row may leave the timeline marker before an outline face's step (`SizeProbe.read_now` with
    `park`), when the store can bring it back (`keep_marker`): the change that puts the values back then rebuilds the
    items after the face only once, with the values back, instead of once with the row's values (the marker going back
    after the face read) and once more with the values back. The marker is brought back before any other read and when
    the rows of a batch end.

    `before_discovery()`, when given, runs before the discovery rows read their base: the pipeline turns the
    suppressed items back on there, so those rows see every component.

    A row whose start was not read, and after which the sketch was found on another solution (it read another outline
    or did not build, and the next read with the values back shows it), may itself have started there. It runs once
    more right after its batch, from a checked start, within the row limit; its first run is left out of the states.
    When that second run reads another outline too, the outline change is its own size's (`again` in its state)."""

    MAX_PUT_BACK_MISSES = 2

    def __init__(self, port, tmp, probe, before_discovery=None):
        self.port, self.tmp, self.probe = port, tmp, probe
        self.before_discovery = before_discovery
        self._parked = False  # a row read may have left the marker before an outline face's step
        self.timer = Timer()  # where the time of the tries goes (`summary`)
        self.reads, self.rows, self.starts, self.backs = {}, [], {}, {}
        self._values = {}  # key of a row to the sizes it sets (`_row_values`)
        self.read_failure = None
        self.put_backs = 0  # design rebuilds made to put a sketch back
        self.redone = []  # keys of the rows run a second time
        self._tails = {}  # key of a batch's last row: the read once the values were back after it
        self._misses = 0
        self._previous = None  # key of the row run last
        self.keeper = self._keeper()
        self.undo = port.undo_steps
        self.job = RowExport(port.store, port.units, self._export, self._before_row)

    def _keeper(self):
        """The port's keeper of the followed sketches as they are now, or None when the port keeps none."""
        try:
            return self.port.sketch_keeper(self.probe.followed_sketches())
        except Exception as exc:
            self.port.log(f"keeping the sketches failed: {exc!r}")
            return None

    def _can_park(self):
        return timeline_control(self.port.store, "keep_marker") is not None

    def _home(self):
        """Bring the marker back where the tries hold it after a row read that may have left it before an outline face's
        step. When it does not go back, the probe stops (`read_failure`)."""
        if not self._parked:
            return
        self._parked = False
        try:
            back = self.port.store.keep_marker() is not False
        except Exception:
            back = False
        if not back and self.read_failure is None:
            self.read_failure = MarkerNotHeld("The timeline marker did not go back after an outline face was read.")

    def _read_now(self, values=None, outline=False, park=False):
        """The probe state of the design now, with `values` the sizes set to other values (`SizeProbe.read_now`;
        `outline` reads only the outlines, `park` may leave the marker before an outline face's step).
        Raises when the timeline marker is not where the tries keep it, before or after the read: a read before it
        would miss items the sketches need, so the row counts as not read and the probe stops."""
        self._home()
        if not self.port.store.marker_holds():
            raise MarkerNotHeld("The timeline marker was not where the tries keep it.")
        with self.timer.span("read"):
            with self.timer.span("read_in_rows" if self.timer.is_open("rows") else "read_outside"):
                self._lend_timer(self.timer)
                self._parked = park
                try:
                    read = self.probe.read_now(values, outline, park) if park else self.probe.read_now(values, outline)
                finally:
                    self._lend_timer(None)
        if _marker_lost(read):
            raise MarkerNotHeld("The timeline marker did not go back after an outline face was read.")
        return read

    def _lend_timer(self, timer):
        """Give the port's reader `timer` for the parts of the read made now (`read_parts`), or None after it: reads
        made elsewhere (the marker roll check, the read after the tries) are not counted."""
        try:
            self.port.read_timer = timer
        except Exception:
            pass

    def _before_row(self, row):
        """`RowExport`'s hook once the parameters are back: read the outlines of the design when the row before did
        not build or read a followed sketch on another outline, and always before a row run again; put the sketch
        back when that read shows it on another solution. A row may bring a sketch back as well as move it away, so
        each such row reads its own start, also once put backs are given up."""
        self._home()
        self._drop_undo()
        key = row_key(row)
        previous, self._previous = self._previous, key
        if self.read_failure is not None or (previous is None and not row.get("again")):
            return
        read = self.reads.get(previous)
        if not row.get("again") and read is not None and not self.probe.off_outline(read):
            return
        start = self._try_read()
        if start is None:
            return
        self.starts[key] = start
        if self.probe.left_start(start):
            self._put_back(key)

    def _drop_undo(self):
        """Let Fusion forget the undo data of the tries so far (`undo_steps`); only called with every value back."""
        if self.undo is not None:
            self.undo.drop()

    def _try_read(self, outline=True):
        """`_read_now` with every value back (only the outlines with `outline`), or None with `read_failure` set when
        the read failed."""
        try:
            return self._read_now({}, outline=outline)
        except ExportCancelled:
            raise
        except Exception as exc:
            self.read_failure = exc
            self.port.log(f"size probe read failed: {exc!r}")
            return None

    def _put_back(self, key=None, last=False, full=False):
        """Move every point of the kept sketches that left its place back to it and rebuild once, then read the
        outlines again (the whole state with `full`); the read is kept in `backs` under `key`. The rebuild runs also
        when no point moved: the keeper cannot move a point that is gone or a sketch it does not keep, and a rebuild may
        still bring it back. `last` tries even after `MAX_PUT_BACK_MISSES`. Returns the read, or None."""
        if self.keeper is None or (self._misses >= self.MAX_PUT_BACK_MISSES and not last):
            return None
        self.put_backs += 1
        try:
            with self.timer.span("put_back"):
                self.keeper.put_back()
                self.port.store.recompute()
        except Exception as exc:
            self.port.log(f"putting a sketch back failed: {exc!r}")
        read = self._try_read(outline=not full)
        if read is None:
            return None
        if key is not None:
            self.backs[key] = read
        self._misses = self._misses + 1 if self.probe.left_start(read) else 0
        self._note()
        return read

    def _note(self):
        self.probe.note_recovery({"put_backs": self.put_backs, "again": len(self.redone)})

    def _export(self, path):
        """`RowExport`'s step callback: a probe row has no STEP, so `path` is None and only the state is read."""
        key = self.job.current_key
        if self.read_failure is None:
            try:
                self.reads[key] = self._read_now(self._values.get(key), park=self._can_park())
            except ExportCancelled:
                raise
            except Exception as exc:
                self.read_failure = exc
                self.port.log(f"size probe read failed: {exc!r}")

    def _left(self):
        """How many rows the cap leaves; none once a row left the design broken (`RowExport.not_back`)."""
        return 0 if self.job.not_back is not None else plan_rows_left(self.rows)

    @property
    def stopped(self):
        """`{ after, items }` when the tries stopped because a row left the design broken, else None."""
        return self.job.not_back

    def try_rows(self, rows):
        """Run the probe's rows. Returns their results."""
        done = len(self.rows)
        self._values.update((row_key(row), _row_values(row)) for row in rows)
        with self.port.progress(messages.TRY_VERB) as progress:
            def step(index, total, label):
                # The window counts the tries of the whole export, not of this batch.
                return progress.step(done + index, done + total, label)

            with self.timer.span("rows"):
                try:
                    results = self.job.run(rows, self.tmp, step, tolerate_build_errors=True)
                finally:
                    self._home()
        self.rows.extend(zip(rows, results))
        if self.job.not_back is not None:
            self.port.log("tries stopped: the design did not rebuild with the values back after %s"
                          % self.job.not_back["after"])
            self.probe.note_stop(self.job.not_back, rows[len(results):])
        return results

    def summary(self):
        """How the time of the tries went, for `report.json` (`timing.probe`): `tries` rows run, `rebuild` (the rows
        without the reads made inside them: setting the sizes, rebuilding the design, putting them back), the state
        `read`s with the time of their parts (`read_parts`: sketches, points and lines, params, refs, box, faces) and
        the `put_back` of sketches. Never raises."""
        try:
            timer = self.timer
            return {
                "tries": len(self.rows),
                "tries_seconds": rounded(timer.seconds("rows")),
                "rebuild": rounded(max(0.0, timer.seconds("rows") - timer.seconds("read_in_rows"))),
                "read": timer.entry("read"),
                "read_parts": {name: timer.entry("read_" + name) for name in READ_PARTS
                               if timer.count("read_" + name)},
                "put_back": timer.entry("put_back"),
            }
        except Exception:
            return None

    def probe_states(self, since=0):
        """(values, result, read, start, more) of the rows run from number `since` on, for `SizeProbe.add_states`;
        a row run again replaces its first run."""
        out = []
        for row, result in self.rows[since:]:
            key = row_key(row)
            if key in self.redone:
                continue
            more = {"put_back": self.backs.get(key), "again": bool(row.get("again"))}
            out.append((_row_values(row), result, self.reads.get(key), self.starts.get(key), more))
        return out

    def _check_reads(self):
        if self.read_failure is not None:
            raise self.read_failure

    def _suspect(self, at):
        """True when row number `at` did not start from a checked read (its start was not read, and it is not the
        first row) and did not end on the first solution: it read another outline or did not build."""
        row, result = self.rows[at]
        key = row_key(row)
        if at == 0 or row.get("again") or key in self.starts:
            return False
        read = self.reads.get(key)
        return bool(result.get("error")) or read is None or self.probe.off_outline(read)

    def _again(self, since):
        """`(key, copy)` of the rows run from number `since` on that may have started on another solution (`_suspect`,
        and the next read with the values back shows a sketch there), within the rows left."""
        keys = [row_key(row) for row, _ in self.rows]
        out = []
        for at in range(since, len(self.rows)):
            if not self._suspect(at):
                continue
            after = self.starts.get(keys[at + 1]) if at + 1 < len(keys) else self._tails.get(keys[at])
            if after is not None and self.probe.left_start(after):
                out.append((keys[at], dict(self.rows[at][0], key=keys[at] + " (again)", again=True)))
        return out[:self._left()]

    def run_rows(self, rows):
        """Run `rows`, run again those that may have started on another solution (`_again`), and give the probe the
        states they gave. Raises the first failed read."""
        done = len(self.rows)
        self.try_rows(rows)
        self._check_reads()
        if self.rows and self.job.not_back is None and self._suspect(len(self.rows) - 1):
            last = self.rows[-1][0]
            self._tails[row_key(last)] = self._try_read()
            self._check_reads()
        again = self._again(done)
        if again:
            self.redone.extend(key for key, _ in again)
            self._note()
            self.try_rows([row for _, row in again])
            self._check_reads()
        self.probe.add_states(self.probe_states(done))

    def settle(self):
        """Put the followed sketches back when they read otherwise than at E0 now, with the values back, so the design
        is left on the solution it had, then drop the undo data of the tries (`_drop_undo`). Never raises."""
        try:
            if self.probe.left_start(self._read_now({}, outline=True)):
                self._put_back(last=True)
        except Exception as exc:
            self.port.log(f"putting a sketch back after the tries failed: {exc!r}")
        self._drop_undo()

    def _retry(self, sizes):
        """Rows nearer to the value for the sizes whose rows did not build (`SizeProbe.nearer_rows`), one step per
        batch, while rows and steps are left (the steps toward the value, then the halving between a value that built
        and one that did not)."""
        for _ in range(len(NEARER_STEPS) + BISECT_STEPS + 1):
            nearer = self.probe.nearer_rows(sizes, self._left())
            if not nearer:
                break
            self.run_rows(nearer)

    def measure(self, rows, sizes):
        """The near rows, then the near pair rows, rows nearer still for the sizes whose rows did not build, then the
        far range ends while rows are left (and nearer rows for those that did not build) and the far pair rows, then
        the rows that check the other sizes of a value that one size moves along a curve (`SizeProbe.check_rows`).
        Each batch is planned once the batch before it has run, so no row repeats a value known not to build."""
        if rows:
            self.run_rows(rows)
        pairs = self.probe.pair_rows(sizes, self._left())
        if pairs:
            self.run_rows(pairs)
        self._retry(sizes)
        far = self.probe.far_rows(sizes, self._left())
        if far:
            self.run_rows(far)
            self._retry(sizes)
        far_pairs = self.probe.far_pair_rows(sizes, self._left())
        if far_pairs:
            self.run_rows(far_pairs)
        check = self.probe.check_rows(sizes, self._left())
        if check:
            self.run_rows(check)

    def discover(self, tries):
        """Read the design once the parameters are back, then run the discovery rows in the room the other rows left
        and keep what they found. `before_discovery` runs first when rows are left for them. Returns the parameters that
        changed the part. After the tries stopped on a broken design (`stopped`) nothing is read: every candidate is
        kept as not tried."""
        if self.job.not_back is not None:
            self.probe.discovery_rows(list(tries), 0)
            return []
        if tries and self._left() and self.before_discovery is not None:
            self.before_discovery()
        base = self._read_now({})
        back = self._put_back(full=True) if self.probe.left_start(base) else None
        self.probe.set_discovery_base(base, back)
        found = self.probe.discovery_rows(list(tries), self._left())
        if not found:
            return []
        done = len(self.rows)
        self.try_rows(found)
        if self.read_failure is not None:
            raise self.read_failure
        self.probe.discover([(row, result, self.reads.get(row_key(row)))
                             for row, result in self.rows[done:]])
        return self.probe.also_changes
