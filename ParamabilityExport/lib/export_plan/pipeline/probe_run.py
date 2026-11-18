"""The try runner: runs the probe rows in one job, reads each state and puts the followed sketches back."""
from dataclasses import dataclass, field
from typing import Optional

from ...design_edit import metered
from ...design_edit.marker import MARKER_LOST
from ...design_edit.runner import ExportCancelled, RowExport, row_key
from ...design_edit.store import timeline_control
from ...probe.plan.nearer import BISECT_STEPS, MAX_NEARER_ROWS, NEARER_STEPS
from ...probe.plan.rows import MAX_PROBE_ROWS
from ...timing import trail
from ...timing.timer import Timer, rounded
from .. import messages
from ..time_limit import limit_text
from . import try_summary
from .far_phase import late_sizes, nearer_share
from .outside_damage import OutsideDamage
from .ended_sizes import EndedSizes
from .walk_backs import WalkBacks


def plan_rows_left(rows):
    """How many probe rows the cap leaves after `rows`."""
    return max(0, MAX_PROBE_ROWS - len(rows))


class MarkerNotHeld(Exception):
    """A probe read was asked for while the timeline marker sat before the position the tries need, or a read moved
    the marker and could not put it back."""


def _marker_lost(read):
    """True when a probe read (one state, or one per part) says it could not put the timeline marker back."""
    reads = read if isinstance(read, list) else [read]
    return any(isinstance(r, dict) and MARKER_LOST in (r.get("unread") or {}) for r in reads)


@dataclass
class EndRead:
    """What the read of the put back after the tries (`ProbeRun.settle`) found.

    back: True when every followed sketch reads as at the start, False when one reads off it, None when the read
      failed or did not run.
    gap_mm: the gap to the start in that read (`Probe.measure_restore`), only worked out when `back` is False; None
      when it cannot be told.
    changed: the sketches that read another outline in it (`Probe.restore_changed`), only when `back` is False.
    """

    back: Optional[bool] = None
    gap_mm: Optional[float] = None
    changed: list = field(default_factory=list)


def _row_values(row):
    """The sizes a row sets to other values, by Fusion name."""
    state = row.get("state") or {}
    return {param: state[param] for param in row.get("varied") or [] if param in state}


class ProbeRun(EndedSizes, WalkBacks):
    """Runs the probe's rows in one job: one baseline, and the parameters put back after every row. The rows only
    recompute (no STEP). `probe` is a `probe_flow.Probe` (one part, or a group of parts over shared rows). It keeps
    the probe state read at every row that built, by row key, and `rows` lists (row, result) of every row run.
    `read_failure` holds the first probe read that failed: the probe is then not used.

    A row that did not build, or left a followed sketch on another outline, may leave that sketch there after the
    parameters are put back: a sketch with two solutions keeps the one it was last solved to. The design is then read
    again before the next row (`starts`, by row key). When a followed sketch reads otherwise than at E0 there
    (`Probe.off_start`, which compares the curves when only their tokens, order or direction differ), the port's
    sketch keeper (`port.sketch_keeper(tokens)`, kept at E0) moves its points back to where they were and the design
    is rebuilt once (`backs`, by row key), so the row starts from the first solution. The put backs that do not bring
    a sketch back are counted per sketch: after `MAX_PUT_BACK_MISSES` of them in a row for every sketch now off its
    start, no more are tried for them, and a sketch that cannot be brought back does not stop the put backs of the
    others.

    After a row that did not build, warned, or read a followed sketch on another outline, the job checks the timeline
    steps against its baseline with the values back (`RowExport.check_back`, `RowExport._stopped`); when a step stays
    worse, it tries to bring the design back the way the row took it away (`RowExport.walk_back`, checked with
    `_at_start`), and when a step is still worse the tries stop (`RowExport.not_back`): no later batch runs, and the
    probe keeps the states read before (`stopped`). The undo data of the tries is dropped before a row only when no
    check found a step worse and the row starts with every followed sketch as at E0.

    A sketch that a start read first shows off its start and that the keeper does not bring back is brought back,
    once, before the next row, the way the rows run since it last read as at its start took it away (`_walk_rows`:
    each row, the last first, at most `walk_back.ROWS_BACK` of them, `RowExport.walk_back` at most
    `walk_back.ATTEMPTS` times each): tries run on a sketch left on its other solution can damage the steps built on
    it, and the row that flipped it may be one before the last when a start was not read. After the tries (`settle`),
    a followed sketch still off its start is put back by the keeper and then, when it stays off, each size those rows
    moved is walked back alone from the other side of its start value (`_walk_back`, at most `walk_back.END_TRIES`).

    With a `time_limit` (seconds, from when the runner is made), the tries stop at the first row that would start after
    it (`RowExport.halted`): no later row runs, the rows planned are left out (`_left` is 0) and the probe is told which
    sizes got no try (`SizeProbe.note_time_limit`); `timed_out` holds the record. The parameters, the sketches and the
    timeline are put back by the same calls as after tries that ended on their own. `clock` is the clock of the
    timers (the export's, so tests can drive it).

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
    When that second run reads another outline too, the outline change is its own size's (`again` in its state).

    With the `captures` of the parts, a try that leaves only steps outside what the tries need worse with the values
    back (`outside_damage.OutsideDamage`), while the part reads as at the start (`Probe.reads_as_start`), ends only
    the tries of the sizes behind it (`ended_names`) and the others go on (`RowExport.contain`): no later row moves
    one of them, and the probe is told (`Probe.note_ended`). Without captures every such try stops the tries."""

    MAX_PUT_BACK_MISSES = 2

    def __init__(self, port, tmp, probe, before_discovery=None, time_limit=None, clock=None, captures=(),
                 parts=None):
        self.port, self.tmp, self.probe = port, tmp, probe
        self.before_discovery = before_discovery
        self.time_limit = time_limit  # seconds the tries may take from now on, or None for no limit
        self.timed_out = None  # `{ limit_seconds, hit, seconds }` once the limit stopped the tries
        self._halt_logged = False
        self._parked = False  # a row read may have left the marker before an outline face's step
        self.timer = Timer(clock) if clock else Timer()  # where the time of the tries goes (`summary`)
        self._started = self._now()
        self.reads, self.rows, self.starts, self.backs = {}, [], {}, {}
        self._values = {}  # key of a row to the sizes it sets (`_row_values`)
        self.read_failure = None
        self.put_backs = 0  # design rebuilds made to put a sketch back
        self.redone = []  # keys of the rows run a second time
        self._tails = {}  # key of a batch's last row: the read once the values were back after it
        self._misses = {}  # sketch token to the put backs in a row that left it off its start
        self._ran = []  # the rows run, in order (`_before_row`)
        self._clean_at = {}  # token of a sketch to the number of rows run when it last read as at E0, values back
        self._flipped = set()  # tokens of the sketches the last start read showed off their start (`_note_off`)
        self._previous = None  # key of the row run last
        self._nearer = 0  # nearer rows planned for the tries (`_retry`), against `MAX_NEARER_ROWS`
        self.keeper = self._keeper()
        self.end = None  # `EndRead` of the put back after the tries (`settle`)
        self.undo = port.undo_steps
        self.damage = OutsideDamage(captures, parts) if captures else None
        self._walked = []  # Fusion names of the sizes walked back before the row run last (`_before_row`)
        self.ended = []  # the records of the tries after which the tries of some sizes ended (`_take_ended`)
        self.ended_names = []  # Fusion names of the sizes and parameters whose tries ended, in order
        self._tried = set()  # Fusion names of the sizes `measure` was given
        # The job and the sketch put back go through a store that counts their calls (`summary`, `calls`).
        self.metered = metered.MeteredStore(port.store, self.timer)
        self.job = RowExport(self.metered, port.units, self._export, self._before_row, self._out_of_time,
                             counts_warning=self.probe.counts_warning, before_check=self._home,
                             at_start=self._at_start, contain=self._contain if self.damage is not None else None)
        self.probe.note_time_limit({"limit_seconds": time_limit, "hit": False})

    def _now(self):
        try:
            return self.timer.clock()
        except Exception:
            return None

    def _elapsed(self):
        """Seconds since the runner was made, or None when the clock failed."""
        now = self._now()
        return None if now is None or self._started is None else max(0.0, now - self._started)

    def _out_of_time(self):
        """`RowExport`'s `stop_when`: true once the tries have taken the time limit. The record of the first time it
        was true stays in `timed_out`. Never raises: a clock that fails never stops the tries."""
        if self.time_limit is None:
            return False
        spent = self._elapsed()
        if spent is None or spent < self.time_limit:
            return False
        if self.timed_out is None:
            self.timed_out = {"limit_seconds": self.time_limit, "hit": True, "seconds": rounded(spent)}
        return True

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
        each such row reads its own start, also once put backs are given up. The undo data is dropped when the
        design is known to be as at the start (`_drop_undo`). Before the first row the body is read for the end check
        (`Probe.keep_body_start`)."""
        self._home()
        self._walked = []
        key = row_key(row)
        previous, self._previous = self._previous, key
        if previous is None and self.read_failure is None:
            # The first row starts after the baseline rebuild with every value at its start: the start of the end
            # check of the body is read here, in the state the end check reads it in.
            self.probe.keep_body_start()
        back = self._start_of(row, key, previous) if self.read_failure is None else False
        self._ran.append(row)
        if back and self.job.back_clean:
            self._drop_undo()

    def _start_of(self, row, key, previous):
        """Read where `row` starts from when it needs it (see `_before_row`) and put a sketch off its start back.
        True when the row starts with every followed sketch as at E0, or nothing showed a reason to read it."""
        if previous is None and not row.get("again"):
            return True
        read = self.reads.get(previous)
        if not row.get("again") and read is not None and not self.probe.off_outline(read):
            return True
        known = set(self._flipped)
        start = self._try_read()
        if start is None:
            return False
        self.starts[key] = start
        off = self._note_off(self.probe.off_start(start))
        if not off:
            return True
        back = self._put_back(key, off=off)
        left = self._note_off(self.probe.off_start(back)) if back is not None else off
        fresh = [t for t in left if t not in known]
        if fresh and self.read_failure is None:
            back = self._walk_rows(fresh, back if back is not None else start, key)
            if back is None:
                return False
            self.backs[key] = back
            left = self._note_off(self.probe.off_start(back))
        return not left

    def _note_off(self, off):
        """Keep the sketches a start read shows off their start (`_flipped`): a sketch not among them before was first
        seen off by this read. Returns `off`."""
        self._flipped = set(off)
        return off

    def _mark(self, read):
        """Note, for each followed sketch that `read` (taken with the values back) shows as at E0, the number of rows
        run so far (`_clean_at`): the rows run after it are those that may have taken it away."""
        if read is None:
            return read
        off = set(self.probe.off_start(read))
        for token in self.probe.followed_sketches():
            if token not in off:
                self._clean_at[token] = len(self._ran)
        return read

    def _since(self, tokens):
        """The rows run since the first of the sketches `tokens` last read as at E0 with the values back."""
        return self._ran[min(self._clean_at.get(t, 0) for t in tokens):] if tokens else []

    def _at_start(self):
        """`RowExport`'s check after it brought the design back: True when the followed sketches read as at E0 with
        the values back, or the read failed (`read_failure` then stops the probe). The attempt's report entry gets
        what the read showed."""
        read = self._try_read()
        back = read is None or not self.probe.left_start(read)
        if read is not None and self.job.walks and "back" not in self.job.walks[-1]:
            self.job.walks[-1]["back"] = back
        return back

    def _drop_undo(self):
        """Let Fusion forget the undo data of the tries so far (`undo_steps`); only called with every value back, no
        step worse than in the baseline and the followed sketches as at E0."""
        if self.undo is not None:
            self.undo.drop()

    def _try_read(self, outline=True):
        """`_read_now` with every value back (only the outlines with `outline`), or None with `read_failure` set when
        the read failed."""
        try:
            return self._mark(self._read_now({}, outline=outline))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.read_failure = exc
            self.port.log(f"size probe read failed: {exc!r}")
            return None

    @trail.staged("put sketches back")
    def _put_back(self, key=None, last=False, full=False, off=()):
        """Move every point of the kept sketches that left its place back to it and rebuild once, then read the
        outlines again (the whole state with `full`); the read is kept in `backs` under `key`. The rebuild runs also
        when no point moved: the keeper cannot move a point that is gone or a sketch it does not keep, and a rebuild may
        still bring it back. `off` are the tokens of the sketches off their start: when each of them has had
        `MAX_PUT_BACK_MISSES` put backs in a row that left it there, none is tried; `last` tries even then. Returns
        the read, or None."""
        if self.keeper is None or (not last and off and all(
                self._misses.get(t, 0) >= self.MAX_PUT_BACK_MISSES for t in off)):
            return None
        self.put_backs += 1
        try:
            with self.timer.span("put_back"):
                self.keeper.put_back()
                with metered.caller(self.metered, metered.SKETCH_PUT_BACK):
                    self.metered.recompute()
        except Exception as exc:
            self.port.log(f"putting a sketch back failed: {exc!r}")
        read = self._try_read(outline=not full)
        if read is None:
            return None
        if key is not None:
            self.backs[key] = read
        still = set(self.probe.off_start(read))
        for token in set(off) | still:
            self._misses[token] = self._misses.get(token, 0) + 1 if token in still else 0
        self._note()
        return read

    def _note(self):
        record = {"put_backs": self.put_backs, "again": len(self.redone)}
        if self.job.recoveries:
            record["walked_back"] = self.job.recoveries
        if self.job.walks:
            record["attempts"] = [dict(walk) for walk in self.job.walks]
        self.probe.note_recovery(record)

    def _export(self, path):
        """`RowExport`'s step callback: a probe row has no STEP, so `path` is None and only the state is read."""
        key = self.job.current_key
        if self.read_failure is None:
            try:
                read = self.reads[key] = self._read_now(self._values.get(key), park=self._can_park())
            except ExportCancelled:
                raise
            except Exception as exc:
                self.read_failure = exc
                self.port.log(f"size probe read failed: {exc!r}")
                return
            if self.probe.off_outline(read):
                self.job.check_back()

    def _left(self):
        """How many rows the cap leaves; none once a row left the design broken (`RowExport.not_back`) or the time limit
        stopped the tries."""
        return 0 if self.job.not_back is not None or self.job.halted else plan_rows_left(self.rows)

    @property
    def stopped(self):
        """`{ after, items }` when the tries stopped because a row left the design broken, else None."""
        return self.job.not_back

    def try_rows(self, rows):
        """Run the probe's rows. Returns their results. A row that moves a size whose tries ended (`ended_names`) does
        not run; when a check ends the tries of some sizes on the way, the rows left that do not move them run on."""
        results = []
        rest = rows = self._without_ended(rows)
        while rows:
            got = self._run_job(rows)
            self.rows.extend(zip(rows, got))
            results.extend(got)
            rest = rows[len(got):]
            if not self._take_ended():
                break
            rest = rows = self._without_ended(rest)
            if self._ended():
                break
        if self.job.recoveries:
            self._note()
        if self.job.not_back is not None:
            self._note_stop(rest)
        if self.job.halted:
            self._note_halt(rest)
        return results

    def _run_job(self, rows):
        """One run of the job over `rows`, with the progress window. Returns the results of the rows that ran."""
        done = len(self.rows)
        self._values.update((row_key(row), _row_values(row)) for row in rows)
        with self.port.progress(messages.TRY_VERB) as progress:
            def step(index, total, label):
                # The window counts the tries of the whole export, not of this batch.
                return progress.step(done + index, done + total, label, self._time_note(done + index, done + total))

            with self.timer.span("rows"):
                try:
                    return self.job.run(rows, self.tmp, step, tolerate_build_errors=True)
                finally:
                    self._home()

    def _note_stop(self, unrun):
        """Log the stop of the tries on a broken design and tell the probe, with the rows that did not run."""
        self.port.log("tries stopped: %s stayed worse with the values back after %s"
                      % (", ".join(self.job.not_back["items"]), self.job.not_back["after"]))
        self.probe.note_stop(self.job.not_back, unrun)

    def _time_note(self, at, total):
        """The time line of the progress window for try number `at` of `total` (`messages.time_note`). Never raises."""
        try:
            spent = self._elapsed()
            return "" if spent is None else messages.time_note(spent, at - 1, total - at + 1, self.time_limit)
        except Exception:
            return ""

    def _note_halt(self, unrun):
        """Tell the probe the time limit stopped the tries, with the rows that did not run."""
        if self.timed_out is None:
            return
        if not self._halt_logged:
            self._halt_logged = True
            self.port.log("tries stopped at the time limit of %s" % limit_text(self.time_limit))
        self.probe.note_time_limit(self.timed_out, unrun)

    def summary(self):
        """How the time of the tries went, for `report.json` (`timing.probe`, `try_summary.summary`). Never raises."""
        return try_summary.summary(self.timer, len(self.rows), self.time_limit, self.timed_out,
                                   self.probe.time_left_out)

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
        # A row that moves a size whose tries ended does not run again: it keeps its first run, as a row the room
        # left out does.
        ended = set(self.ended_names)
        again = [(key, row) for key, row in self._again(done) if not ended & set(row.get("varied") or ())]
        if again:
            self.redone.extend(key for key, _ in again)
            self._note()
            self.try_rows([row for _, row in again])
            self._check_reads()
        self.probe.add_states(self.probe_states(done))

    @trail.staged("check after the last try")
    def check_pending(self):
        """Run the check of the timeline steps that the row run last asked for (`RowExport.check_pending`), with every
        value back. A step that stays worse stops the tries there, and the probe is told (`note_stop`). Never raises: a
        failure leaves the steps not known to be clean."""
        stopped = self.job.not_back is not None
        try:
            self.job.check_pending()
            self._take_ended()
            if self.job.not_back is not None and not stopped:
                self._note_stop([])
        except Exception as exc:
            self.job.back_clean = False
            self.port.log(f"checking the steps after the last try failed: {exc!r}")

    @trail.staged("put sketches back after the tries")
    def settle(self):
        """Run the check the last row asked for (`check_pending`), then put the followed sketches back when they read
        otherwise than at E0 now, with the values back, so the design is left on the solution it had: the keeper first,
        then, for a sketch still off its start, the way back of the row after which it was first seen off
        (`_walk_back`). `end` keeps what the last read found (`EndRead`). Then drop the undo data of the tries
        (`_drop_undo`) when the sketches read as at E0 and no check found a step worse or could not read the steps.
        Never raises."""
        self.check_pending()
        self.end = EndRead()
        try:
            with trail.stage("read outlines after the tries"):
                read = self._mark(self._read_now({}, outline=True))
            if self.probe.left_start(read):
                read = self._put_back(last=True, off=self.probe.off_start(read)) or read
                read = self._walk_back(read)
            if read is not None:
                self.end.back = not self.probe.left_start(read)
                if not self.end.back:
                    self.end.gap_mm = self.probe.measure_restore(read)
                    self.end.changed = list(self.probe.restore_changed)
        except Exception as exc:
            self.port.log(f"putting a sketch back after the tries failed: {exc!r}")
        if self.end.back is True and self.job.back_clean and self.job.not_back is None:
            self._drop_undo()

    def _retry(self, sizes, only=None, most=None):
        """Rows nearer to the value for the sizes whose rows did not build (`SizeProbe.nearer_rows`; only the Fusion
        names in `only` when given), one step per batch, while rows and steps are left (the steps toward the value,
        then the halving between a value that built and one that did not). With `most`, at most that many rows in all."""
        used = 0
        for _ in range(len(NEARER_STEPS) + BISECT_STEPS + 1):
            room = self._left() if most is None else max(0, min(self._left(), most - used))
            nearer = self.probe.nearer_rows(self._live(sizes), room, only=only)
            if not nearer:
                break
            used += len(nearer)
            self._nearer += len(nearer)
            self.run_rows(nearer)

    def _ended(self):
        """True once a row left the design broken (`RowExport.not_back`) or the time limit stopped the tries."""
        return self.job.not_back is not None or self.job.halted

    def _far_by_size(self, sizes):
        """The far rows one size at a time (`SizeProbe.far_order`), each size's nearer rows right after its far rows,
        so a far try that leaves the design broken later still finds the sizes before it narrowed. The sizes whose
        tries so far showed trouble outside the part go last (`far_phase.late_sizes`), and each size takes at most its
        share of the nearer rows (`far_phase.nearer_share`). Then the nearer rows of every size in the room left, one
        step per size and side in turn.

        When the tries end on the way (`_ended`), the far rows of the sizes still to come are planned and noted as
        rows that did not run, as when they were left in one batch."""
        if self._ended():
            return
        order = self.probe.far_order(self._live(sizes), late_sizes(self.rows, self.job.walks,
                                                                   self.probe.counts_warning))
        for at, name in enumerate(order):
            if name in self.ended_names:
                continue
            far = self.probe.far_rows(self._live(sizes), self._left(), only=[name])
            if far:
                self.run_rows(far)
            to_come = sum(1 for n in order[at:] if n not in self.ended_names)
            most = nearer_share(MAX_NEARER_ROWS - self._nearer, to_come, self._left())
            self._retry(sizes, only=[name], most=most)
            if self._ended():
                self._note_unrun(self.probe.far_rows(self._live(sizes), plan_rows_left(self.rows)))
                return
        rest = self.probe.far_rows(self._live(sizes), self._left())
        if rest:
            self.run_rows(rest)
        self._retry(sizes)

    def _note_unrun(self, rows):
        """Tell the probe that `rows`, planned once the tries had ended, did not run (`note_stop`, `_note_halt`)."""
        if rows and self.job.not_back is not None:
            self.probe.note_stop(self.job.not_back, rows)
        if rows and self.job.halted:
            self._note_halt(rows)

    def measure(self, rows, sizes):
        """The near rows, then the near pair rows, rows nearer still for the sizes whose rows did not build, then the
        far range ends one size at a time while rows are left, each size followed by its nearer rows (`_far_by_size`),
        and the far pair rows, then the rows that check the other sizes of a value that one size moves along a curve
        (`SizeProbe.check_rows`). Each batch is planned once the batch before it has run, so no row repeats a value
        known not to build. When the tries stopped early or ran out of time, the probe keeps the sides whose nearer
        tries never ran (`SizeProbe.note_unfinished`)."""
        self._tried = {size["param"] for size in sizes}
        if rows:
            self.run_rows(rows)
        pairs = self.probe.pair_rows(self._live(sizes), self._left())
        if pairs:
            self.run_rows(pairs)
        self._retry(sizes)
        self._far_by_size(sizes)
        far_pairs = self.probe.far_pair_rows(self._live(sizes), self._left())
        if far_pairs:
            self.run_rows(far_pairs)
        check = self.probe.check_rows(self._live(sizes), self._left())
        if check:
            self.run_rows(check)
        # The check the last row asked for, so a stop or an end it finds is known to the marks below.
        self.check_pending()
        if self.job.halted or self.job.not_back is not None or self.ended:
            # Before `_note_unplanned`: planning the nearer rows there counts them against `plan.MAX_NEARER_ROWS`.
            self.probe.note_unfinished(sizes)
        if self.job.halted:
            self._note_unplanned(self._live(sizes))

    def _note_unplanned(self, sizes):
        """After the time limit stopped the tries: the sizes whose last try did not build and whose nearer tries were
        still to come count as left out like those whose rows did not run."""
        self._note_halt(self.probe.nearer_rows(sizes, MAX_PROBE_ROWS))

    def discover(self, tries):
        """Read the design once the parameters are back, then run the discovery rows in the room the other rows left
        and keep what they found. `before_discovery` runs first when rows are left for them. Returns the parameters that
        changed the part. The check the last measured row asked for runs first (`check_pending`), against the baseline
        of those rows: a lasting damage stops the tries here instead of becoming the baseline of the discovery rows.
        After the tries stopped on a broken design (`stopped`) or on the time limit nothing is read: every candidate is
        kept as not tried."""
        self.check_pending()
        if self.job.not_back is not None or self.job.halted:
            self.probe.discovery_rows(list(tries), 0)
            return []
        if tries and self._left() and self.before_discovery is not None:
            self.before_discovery()
            # Items that were off for the tries are back on, with any warning or error they had all along.
            self.job.rebase()
        base = self._mark(self._read_now({}))
        off = self.probe.off_start(base)
        back = self._put_back(full=True, off=off) if off else None
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
