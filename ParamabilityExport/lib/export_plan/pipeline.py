"""The export of one body into a recipe package, from the capture to the manifest. Pure: no Fusion imports.

The sequence asks Fusion for the capture, the STEP of the part as it is and the sketch measuring. A size that a value
cannot follow is left free with a warning, and the ranges are the ones in the dialog table.

Steps, in order: read the capture, translate once to learn which sizes the recipe keeps, run the sketch probe (it
only recomputes), translate again with the motion it found, and assemble the package. The probe runs whenever a
sketch can be followed. When the first translation leaves steps out, or stops because the part holds too many gaps,
Fusion is asked which step made the faces each later step picks (`reach_pass`) before anything else, and the part is
translated again with the answer.

Fusion is reached only through the port the caller hands in (see `ExportPort`), so tests run the whole sequence with
fakes. Parameters are changed by the probe and put back on every way out: when a step fails, when the person
cancels, and before the probe's last read. What is left over (a parameter that would not go back, sketches that did
not return to their start, a probe that could not measure) goes into the `health` record of the result. Timeline items
suppressed for the tries (`timeline_trim`, unless the person turns it off) are turned back on in the same places,
before the timeline marker goes back, and before the discovery tries. Last, on every way out, the health of every
timeline step is compared with the start of the export and the design rebuilt when a step differs
(`design_edit.timeline_health`).
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..params import size_table as size_tables
from ..params.listing import list_parameters
from ..probe.plan import BISECT_STEPS, MAX_PROBE_ROWS, NEARER_STEPS
from ..sketch_values.motion import OPTIMISTIC
from ..timing.export_timing import ExportTiming
from ..timing.timer import Timer, rounded
from . import health as health_module
from . import messages
from .body_scope import body_links, scope_inputs
from .reach_pass import needs_reach, with_reach
from .probe_flow import SizeProbe, covers_a_sketch, extra_size_params, kept_size_names, shadow_of
from .recipe_export import free_sizes, plan_single_export, translate_capture
from ..design_edit.marker import MARKER_LOST
from ..design_edit.restore import restore_parameters
from ..design_edit.runner import ExportCancelled, RowExport
from ..design_edit.timeline_health import read_timeline, settle_timeline
from .size_offers import discovery_sizes, labels, probe_sizes
from .timeline_trim import TryTimeline


# The parts of a probe read the Fusion reader times (`fusion_reader.probe_state.read_state`).
READ_PARTS = ("sketches", "points", "params", "refs", "box", "faces")


def settle_after_tries(owner, run):
    """Put every parameter back, turn the suppressed items back on (`owner._restore`, `owner._end_trim`) and put a
    sketch left on another solution back (`ProbeRun.settle`). Never raises, so it also runs when the tries ended with
    an error or a cancel. The run's sketch keeper is kept as `owner.keeper` for the health record."""
    owner.keeper = run.keeper
    try:
        owner._restore()
        owner._end_trim()
    except Exception as exc:
        owner.port.log(f"putting the design back after the tries failed: {exc!r}")
    run.settle()


def plan_rows_left(rows):
    """How many probe rows the cap leaves after `rows`."""
    return max(0, MAX_PROBE_ROWS - len(rows))


class ExportPort(Protocol):
    """What the pipeline needs from Fusion. The command passes the real one, tests pass a fake.

    store: the parameter store (`apply.apply_row_values` and `restore.restore_parameters` list what it needs, plus
      `saved_expressions`).
    units: {parameter name: Fusion unit string}.
    export_step(path): write the STEP of the picked body as the design is now.
    read_capture(): the capture dict of the picked body, or the exception that stopped the read.
    read_reach(capture, gaps): the `reach` of the capture when the steps at the timeline indexes `gaps` are left out
      of the copy (`read_gap_reach.read_reach`); raises `MarkerError` when the timeline marker cannot go back.
    probe_reader(): a callable `read(request)` giving one probe state, or raising.
    sketch_keeper(tokens): optional; an object that keeps the sketches `tokens` as they are now and whose
      `put_back()` moves their points back there (`fusion_reader.sketch_keep.SketchKeeper`, `ProbeRun`).
    timing: optional; the `timing.export_timing.ExportTiming` of this export. The pipeline makes its own when the port
      has none; a port that reads the capture with a `CaptureTimer` hands its summary to it (`note_capture`).
    progress(verb): a context manager whose value has `step(index, total, name)`; the step returns False when the
      person cancelled.
    warn_unrestored(names): tell the person that these parameters could not be put back, when the export stops.
    warn_left_off(names): optional; tell the person that these timeline steps, turned off for the tries
      (`timeline_trim`), could not be turned back on.
    warn_steps(lines): optional; tell the person, when the export stops, the `health.health_lines` about steps that
      differ from the start of the export (`settle_steps`).
    log(text): a line for the log.
    """

    store: object
    units: dict

    def export_step(self, path): ...

    def read_capture(self): ...

    def read_reach(self, capture, gaps): ...

    def probe_reader(self): ...

    def progress(self, verb): ...

    def warn_unrestored(self, names): ...

    def log(self, text): ...


@dataclass
class ExportRequest:
    """The person's choices and the design's parameters for one export."""

    title: str
    writer: str
    up_axis: str
    parameters: list
    model_params: list
    design_unit: str
    ticked: list
    ranges: dict
    marker: Optional[dict] = None
    faster_tries: bool = True  # suppress the timeline items the tries do not use (`timeline_trim`)
    # The timeline steps before anything was read (`timeline_health.read_timeline`); None reads them when the export
    # starts.
    timeline_start: Optional[object] = None


@dataclass
class PipelineResult:
    """What `run_pipeline` made: the package parts, the report, and the size table the export ended with."""

    manifest: dict
    files: dict
    report: dict
    table: object
    health: dict = field(default_factory=dict)


def run_pipeline(port, request, tmp):
    """The package of one export. `tmp` is a folder that holds the STEP file of the part until the package is written.

    Raises what a failing step raises (`RowBuildError`, `StepExportError`, `PackageCapError`, `ExportCancelled`,
    `MarkerError`); the parameters are back by then and `port.warn_unrestored` has named any that are not."""
    return _Pipeline(port, request, tmp).run()


def warn_left_off(port, timeline):
    """Tell the person about timeline items that would not turn back on after the tries (`TryTimeline.left_off`)."""
    names = timeline.left_off if timeline is not None else []
    warn = getattr(port, "warn_left_off", None)
    if names and warn is not None:
        warn(names)


class MarkerNotHeld(Exception):
    """A probe read was asked for while the timeline marker sat before the position the tries need, or a read moved
    the marker and could not put it back."""


def start_steps(owner):
    """The timeline steps at the start of the export: the read the request carries, taken before the dialog read the
    design, else one read now."""
    start = getattr(owner.request, "timeline_start", None)
    return start if start is not None else read_timeline(owner.port.store)


def settle_steps(owner):
    """Compare the timeline steps with the start and bring back what differs (`timeline_health.settle_timeline`), once
    per export, after the parameters, the suppressed items, the sketches and the marker are back."""
    if owner.settled is None:
        owner.settled = settle_timeline(owner.port.store, owner.steps_start, owner.saved, owner.port.log)
    return owner.settled


def deferred_left(owner):
    """Sketches whose compute flag the keeper could not put back (`SketchKeeper.deferred_left`)."""
    return list(getattr(getattr(owner, "keeper", None), "deferred_left", None) or [])


def warn_steps(owner):
    """Tell the person, when the export stopped, which timeline steps differ from the start (`settle_steps`). Never
    raises: it runs while the export stops for another reason."""
    try:
        lines = health_module.steps_lines(settle_steps(owner), deferred_left(owner))
        warn = getattr(owner.port, "warn_steps", None)
        if lines and warn is not None:
            warn(lines)
    except Exception as exc:
        owner.port.log(f"checking the timeline steps after the export failed: {exc!r}")


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
    recompute (no STEP). It keeps the probe state read at every row that built, by row key, and `rows` lists
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
        self.undo = getattr(port, "undo_steps", None)  # `undo_steps.UndoSteps` when the person turned it on
        self.job = RowExport(port.store, port.units, self._export, self._before_row)

    def _keeper(self):
        """The port's keeper of the followed sketches as they are now, or None when the port has none."""
        make = getattr(self.port, "sketch_keeper", None)
        if make is None:
            return None
        try:
            return make(self.probe.followed_sketches())
        except Exception as exc:
            self.port.log(f"keeping the sketches failed: {exc!r}")
            return None

    def _can_park(self):
        return callable(getattr(self.port.store, "keep_marker", None))

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
        holds = getattr(self.port.store, "marker_holds", None)
        if holds is not None and not holds():
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
        key = row.get("key", row["name"])
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
        self._values.update((row.get("key", row["name"]), _row_values(row)) for row in rows)
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
            key = row.get("key", row["name"])
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
        key = row.get("key", row["name"])
        if at == 0 or row.get("again") or key in self.starts:
            return False
        read = self.reads.get(key)
        return bool(result.get("error")) or read is None or self.probe.off_outline(read)

    def _again(self, since):
        """`(key, copy)` of the rows run from number `since` on that may have started on another solution (`_suspect`,
        and the next read with the values back shows a sketch there), within the rows left."""
        keys = [row.get("key", row["name"]) for row, _ in self.rows]
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
            self._tails[last.get("key", last["name"])] = self._try_read()
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
        self.probe.discover([(row, result, self.reads.get(row.get("key", row["name"])))
                             for row, result in self.rows[done:]])
        return self.probe.also_changes


class _Pipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.saved = None
        self.unrestored = []
        self.table = None
        self.capture = None  # the capture the translations used, with `reach` when steps were left out
        self.probe = None
        self.roll = None
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motion = None
        self.doubtful = []
        self.also = []
        self.stopped = None  # `ProbeRun.stopped`
        self.keeper = None  # the sketch keeper of the tries (`settle_after_tries`)
        self.steps_start = None  # the timeline steps at the start (`start_steps`)
        self.settled = None  # `settle_steps`
        self.timing = getattr(port, "timing", None) or ExportTiming()

    def run(self):
        self.saved = self.port.store.saved_expressions()
        self.steps_start = start_steps(self)
        done = False
        try:
            result = self._run()
            done = True
            return result
        finally:
            failed = self._restore()
            self._end_roll()
            if not done:
                if failed:
                    self.port.warn_unrestored(failed)
                warn_steps(self)
            warn_left_off(self.port, self.roll)

    def _end_trim(self):
        """Turn back on the timeline items suppressed for the tries (a no-op when none were)."""
        if self.roll is not None:
            self.roll.end_trim()

    def _end_roll(self):
        """Turn the suppressed items back on and put the timeline marker back where the export found it (a no-op
        when nothing was changed)."""
        if self.roll is not None:
            self.roll.end()

    def _restore(self):
        """Put every parameter back to its saved expression. Returns the names that would not go back, and keeps
        them for the health record. Safe to call at any time."""
        self.unrestored = restore_parameters(self.port.store, self.saved)
        return self.unrestored

    # ---- stages -----------------------------------------------------------------------------------------------

    def _run(self):
        port, request = self.port, self.request
        timing = self.timing
        part_step = os.path.join(self.tmp, "part.step")
        with timing.span("step_export"):
            port.export_step(part_step)
        with timing.span("capture"):
            capture = port.read_capture()
        with timing.span("size_table"):
            model, quantities = scope_inputs(capture, request.model_params)
            self.table = size_tables.build(
                request.parameters, request.ticked, model, request.design_unit, quantity_params=quantities,
                ranges=request.ranges, links=body_links(capture))

        final = self._translate_and_measure(capture) if isinstance(capture, dict) else None

        with timing.span("restore"):
            self._restore()
            self._end_trim()
        with timing.span("probe"):
            gap = self._restore_gap()
        with timing.span("restore"):
            self._end_roll()
            settled = settle_steps(self)
        with timing.span("probe"):
            probe_report = self._close_probe()
            shadow = shadow_of(self.probe, port.log) if self.probe is not None else None
        health = health_module.make_health(self.unrestored, gap, self.probe_status, self.probe_error,
                                           self._unchecked(), self.motion.flipped if self.motion is not None else (),
                                           self.stopped, steps=settled, deferred_left=deferred_left(self))
        capture = self.capture if self.capture is not None else capture
        manifest, files, report = plan_single_export(
            capture if capture is not None else RuntimeError("The steps were not read."),
            part_step, request.title, request.writer, request.up_axis,
            size_table=self.table, listing=self._listing(), motion=self.motion, probe=probe_report,
            marker=request.marker, loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful],
            translated=final, health=health, also=self.also, derived=shadow, timing=self.timing)
        return PipelineResult(manifest, files, report, self.table, health)

    def _translate_and_measure(self, capture):
        """The stages that need a capture: the first translation, the sketch probe and the translation with the
        motion it found. Returns the final translation (a refusal included), or None when it failed."""
        self.capture = capture
        first_motion = OPTIMISTIC if covers_a_sketch(capture) else None
        first = self._translation(capture, first_motion, "translate_first")
        if first is None:
            return None
        if needs_reach(first):
            with self.timing.span("reach"):
                capture = self.capture = with_reach(self.port.read_reach, capture, first, self.port.log)
            first = self._translation(capture, first_motion, "translate_first")
            if first is None:
                return None
        if first.recipe is None:
            # The plan translates without a motion at this point, so the first look's refusal is its result only
            # when the first look had none either.
            return first if first_motion is None else None
        free = free_sizes(first.recipe)
        extra = extra_size_params(self.table, free)
        keep = kept_size_names(self.table, free) | {self.table.size_name(n) for n in extra}
        sizes = probe_sizes(self.table, self.request.parameters, keep=keep)

        with self.timing.span("probe"):
            self.probe = self._start_probe(capture)
            if self.probe is not None:
                self.roll = TryTimeline(self.port.store, self.port.log, self.request.faster_tries)
                probe = self.probe
                self.roll.begin([capture], lambda: probe.matches_start(probe.read_now()))
                tries = discovery_sizes(self.table, self.request.parameters, capture)
                run = ProbeRun(self.port, self.tmp, self.probe, before_discovery=self._end_trim)
                found = self._measure(run, sizes, extra, tries)
                if found is not None:
                    self.doubtful.extend(found)
        return self._translation(capture, self.motion, "translate_final")

    # ---- translation ------------------------------------------------------------------------------------------

    def _translation(self, capture, motion, phase):
        """The translator's result, a refusal included (the plan reports its reason without translating again), or
        None when the translator failed. Never raises. `phase` is the timing phase the time is added to."""
        try:
            with self.timing.span(phase):
                result = translate_capture(capture, self.request.up_axis, self.table, motion, timer=self.timing)
        except Exception as exc:
            self.port.log(f"translation failed: {exc!r}")
            return None
        return result

    def _listing(self):
        """The design's parameters for the manifest, or None when they cannot be listed. Never stops the export."""
        try:
            return list_parameters(self.request.parameters, self.request.model_params, self.request.design_unit)
        except Exception as exc:
            self.port.log(f"parameter list failed: {exc!r}")
            return None

    # ---- the sketch probe -------------------------------------------------------------------------------------

    def _start_probe(self, capture):
        """The size probe with its first read, or None when no sketch can be followed or it could not start. A probe
        that could not start is noted for the person; it never stops the export."""
        try:
            if not covers_a_sketch(capture):
                return None
            self.probe_status = health_module.FAILED
            self.probe_error = "The first read of the sketches did not work."
            probe = SizeProbe.start(capture, self.table, self.port.probe_reader())
        except Exception as exc:
            self.port.log(f"size probe could not start: {exc!r}")
            self.probe_error = repr(exc)
            return None
        if probe is not None:
            self.probe_status = health_module.MEASURED
            self.probe_error = ""
        return probe

    def _measure(self, run, sizes, extra=(), tries=()):
        """The probe's rows and its result: the sizes the probe cannot follow, or None when the probe failed.

        The rows put every size at the ends of its range where a size moves a sketch, then the sizes in `extra` (tried
        on a guess, `probe_flow.extra_size_params`) while rows are left. A row that does not build is tried again
        nearer to the value now (`ProbeRun.measure`). Rows still left try the unticked parameters
        in `tries` once each (`size_offers.discovery_sizes`); they only find which of them also change the part
        (`self.also`) and are not used for the motion. A failure other than a cancel
        leaves the translation without a motion (no size behind a sketch is then followed, by the translator's own
        rule) and is noted for the person. The parameters are put back, the suppressed items turned back on and
        a sketch left on another solution put back (`ProbeRun.settle`) before the last read, also when the tries fail
        or are cancelled."""
        probe = self.probe
        settled = False
        try:
            run.measure(probe.probe_rows(sizes, extra), sizes)
            self.also = run.discover(tries)
            if self.roll is not None:
                self.roll.tries_done()
            settled = True
            settle_after_tries(self, run)
            found = probe.finish(probe.read_now(), labels(self.table))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"size probe failed: {exc!r}")
            self.probe_status, self.probe_error = health_module.FAILED, repr(exc)
            self.motion = None
            return None
        finally:
            if not settled:
                settle_after_tries(self, run)
            self.stopped = run.stopped
            self.timing.note_probe(with_try_seconds(run.summary(), self.roll))
        self.motion = probe.motion
        return found

    def _restore_gap(self):
        """How far the sketches are from their start after the last restore, or None when that cannot be told. Read
        again here because the probe rows changed the design once more; also after tries that failed, which can
        leave a sketch on another solution."""
        if self.probe is None:
            return None
        try:
            return self.probe.measure_restore(self.probe.read_now())
        except Exception as exc:
            self.port.log(f"reading the sketches after the restore failed: {exc!r}")
            return None

    def _unchecked(self):
        """What the restore check could not compare, for the health record."""
        return list(self.probe.restore_unchecked) if self.probe is not None else []

    def _close_probe(self):
        """The probe's record for `report.json`, or None when it did not run or failed."""
        if self.probe is None or self.probe_status != health_module.MEASURED:
            return None
        report = self.probe.report()
        if self.roll is not None and self.roll.record is not None:
            report["timeline"] = self.roll.record
        return report
