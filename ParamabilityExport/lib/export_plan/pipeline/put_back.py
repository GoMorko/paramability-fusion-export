"""The put back of one export: what the export changed in the design and brings back, in one order, on every way the
export ends. Both export pipelines hold one. Pure: no Fusion imports."""
import dataclasses

from ...design_edit.restore import restore_parameters
from ...design_edit.timeline_health import FULL_COMPUTE, VALUES_AGAIN, read_timeline, settle_timeline
from ...geometry.tolerances import RESTORE_TOLERANCE_MM
from ...timing import trail
from .. import health as health_module
from ..timeline_trim import TryTimeline
from ..undo_steps import drop_after
from .probe_run import with_try_seconds


class PutBack:
    """What one export changed and must put back: the parameter values (`saved`), the timeline of the tries (the
    marker held early and the unused items turned off, `TryTimeline`), the sketches the tries moved (the try runner's
    sketch keeper), the timeline steps compared with the start (`timeline_health.settle_timeline`) and the last Undo
    drop (`undo_steps.drop_after`).

    The pipeline calls, in this order:
    - `start` before it changes anything;
    - `hold_timeline` before the tries; the try runner calls `end_trim` before the discovery tries;
    - `tries_done(run)` once the tries ran and `tries_ended(run)` on every way out of them: the values and the items go
      back and a sketch left on another solution is put back (`ProbeRun.settle`) before the probe's last read;
    - `settle(read_gap, read_outline_gap, read_body)` once the export is made: values and items back, the sketch gap
      read, the marker back, the body compared with its start, the end check, then the outlines and the body read
      again when the end check rebuilt the design;
    - `close(health)` when the export is made, `close_failed()` when it stops: the values and the marker go back once
      more and the person is told what did not; a made export then drops its last Undo step when the design is as it
      was.
    `health_inputs` gives the `health.HealthInputs` of the export."""

    def __init__(self, port, request, timing, saved, steps_start):
        self.port, self.request, self.timing = port, request, timing
        self.saved = saved  # {name: expression} before the export changed anything
        self.steps_start = steps_start  # the timeline steps at the start (`timeline_health.read_timeline`)
        self.unrestored = []
        self.roll = None  # `TryTimeline` of the tries, once they hold the timeline
        self.keeper = None  # the sketch keeper of the tries
        self.stopped = None  # `ProbeRun.stopped`
        self.settled = None  # `TimelineSettle` of the end check
        self.gap_mm = None
        self.gap_after_mm = None
        self.body_changed = []  # what of the body clearly differs from its start once the design is back
        self.body_small = []  # small differences of the body (`states.BodyCheck.small`)
        self.body_unconfirmed = []  # differences of the body that only the end rebuild brought
        self.body_unchecked = False  # the body could not be compared at the end
        self._tries_back = None  # the try run the design was put back after
        self.outcome = getattr(request, "outcome", None)  # the `rollback.ExportOutcome` this export fills in

    @classmethod
    def start(cls, port, request, timing):
        """The put back of an export that starts now: the parameter expressions, then the timeline steps (the read the
        request carries, taken before the dialog read the design, else one read now)."""
        saved = port.store.saved_expressions()
        start = request.timeline_start
        return cls(port, request, timing, saved, start if start is not None else read_timeline(port.store))

    def restore(self):
        """Put every parameter back to its saved expression. Returns the names that would not go back and keeps them
        for the health record. Safe to call at any time."""
        self.unrestored = restore_parameters(self.port.store, self.saved)
        return self.unrestored

    # ---- the tries ---------------------------------------------------------------------------------------------

    def hold_timeline(self, captures, unchanged):
        """Hold the marker early and turn off the items the tries of `captures` do not use (`TryTimeline.begin`;
        `unchanged()` tells the design reads as at the start)."""
        self._note_tries()
        self.roll = TryTimeline(self.port.store, self.port.log, self.request.faster_tries)
        self.roll.begin(captures, unchanged)

    def end_trim(self):
        """Turn back on the timeline items suppressed for the tries (a no-op when none were)."""
        if self.roll is not None:
            self.roll.end_trim()

    def _end_roll(self):
        """Turn the suppressed items back on and put the timeline marker back where the export found it (a no-op
        when nothing was changed)."""
        if self.roll is not None:
            self.roll.end()

    @property
    def timeline_record(self):
        """`TryTimeline.record` for `report.json` (`probe.timeline`), or None when the tries held no timeline."""
        return self.roll.record if self.roll is not None else None

    def tries_done(self, run):
        """The tries of `run` (`ProbeRun`) ran: note their time and put the design back (`_after_tries`)."""
        if self.roll is not None:
            self.roll.tries_done()
        self._after_tries(run)

    def tries_ended(self, run):
        """On every way out of the tries: put the design back when `tries_done` did not, keep how the tries stopped
        and note their time in the export timing."""
        if self._tries_back is not run:
            self._after_tries(run)
        self.stopped = run.stopped
        self.timing.note_probe(with_try_seconds(run.summary(), self.roll))

    def _after_tries(self, run):
        """Put every parameter back, run the check of the steps the last try asked for (`ProbeRun.check_pending`), turn
        the suppressed items back on and put a sketch left on another solution back (`ProbeRun.settle`). Never raises, so it also runs when the tries ended with an error or a cancel. The run's
        sketch keeper is kept for the health record."""
        self._note_tries()
        self._tries_back = run
        self.keeper = run.keeper
        try:
            with trail.stage("put back values after the tries"):
                self.restore()
        except Exception as exc:
            self.port.log(f"putting the design back after the tries failed: {exc!r}")
        # The check the last try asked for compares with the baseline of the tries, read with the same items off.
        run.check_pending()
        try:
            self.end_trim()
        except Exception as exc:
            self.port.log(f"putting the design back after the tries failed: {exc!r}")
        run.settle()
        self._note_undo()

    # ---- the end of the export ---------------------------------------------------------------------------------

    def settle(self, read_gap, read_outline_gap, read_body=None):
        """Bring the design back once the export is made. `read_gap()` is the sketch gap after the restore (None when
        it cannot be told; never raises), `read_outline_gap()` the gap from a read of the outlines only (None without
        a probe), `read_body()` what of the body differs from its start (`states.BodyCheck`, None when it cannot be
        compared; not given without a probe). The body is read once the marker is back, before the end check, and
        again after it when the end check rebuilt the whole design (`_body_after`)."""
        with self.timing.span("restore"), trail.stage("put back values at the end"):
            self.restore()
            self.end_trim()
        with self.timing.span("probe"), trail.stage("read sketches at the end"):
            gap = read_gap()
        with self.timing.span("restore"), trail.stage("put back the marker at the end"):
            self._end_roll()
        with self.timing.span("probe"), trail.stage("read body before the end check"):
            before = self._body(read_body)
        with self.timing.span("restore"):
            self._settle_steps()
        with self.timing.span("probe"):
            self.gap_mm, self.gap_after_mm = self._gap_after_settle(gap, read_outline_gap)
            self._body_after(read_body, before)

    def _body_after(self, read_body, before):
        """Keep what of the body differs at the end: from `before`, or from a read after the end check when it rebuilt
        the whole design. A difference that the rebuild alone brought, with the body read as at its start before it,
        is kept as not confirmed (`body_unconfirmed`), not as a change. Without `read_body` nothing is kept."""
        if read_body is None:
            return
        end = before
        if self.settled is not None and FULL_COMPUTE in self.settled.actions:
            with trail.stage("read body after the end rebuild"):
                end = self._body(read_body)
            if end is not None and before is not None and not before.texts and end.texts:
                self.body_unconfirmed = end.texts
                return
        if end is None:
            self.body_unchecked = True
            return
        self.body_changed, self.body_small = list(end.clear), list(end.small)

    def _body(self, read_body):
        """The `BodyCheck` that `read_body()` gives, or None without it or when it fails. Never raises."""
        if read_body is None:
            return None
        try:
            return read_body()
        except Exception as exc:
            self.port.log(f"reading the body after the export failed: {exc!r}")
            return None

    def _settle_steps(self):
        """Compare the timeline steps with the start and bring back what differs (`timeline_health.settle_timeline`),
        once per export, after the parameters, the suppressed items, the sketches and the marker are back. Items of
        the tries that would not turn back on and that this turned on leave `TryTimeline.left_off`."""
        if self.settled is None:
            self.settled = settle_timeline(self.port.store, self.steps_start, self.saved, self.port.log)
            if self.roll is not None and self.settled.recovered:
                self.roll.back_on(self.settled.recovered)
        return self.settled

    def _gap_after_settle(self, gap, measure):
        """`(gap, gap after)`: the sketch gap of the export once the end check is done. When it rebuilt the design,
        the outlines are read again (`measure()` reads and compares, None when it cannot tell) and the larger of the
        two gaps is kept, so a sketch that the rebuild moved counts as drift; `gap after` is that second gap, else
        None."""
        settled = self.settled
        if settled is None or not any(a in (FULL_COMPUTE, VALUES_AGAIN) for a in settled.actions):
            return gap, None
        try:
            with trail.stage("read sketches after the end rebuild"):
                after = measure()
        except Exception as exc:
            self.port.log(f"reading the sketches after the end rebuild failed: {exc!r}")
            return gap, None
        if after is None:
            return gap, None
        return (after if gap is None else max(gap, after)), after

    def undo_dropped(self):
        """True when Fusion forgot Undo data during the export (Lighter on memory, `undo_steps.UndoSteps`)."""
        steps = self.port.undo_steps
        return bool(steps is not None and steps.record.get("applied"))

    def _note_undo(self):
        """Tell the outcome that Fusion forgot Undo data (`rollback.ExportOutcome.undo_dropped`), so the export is never
        aborted, also when no health record can be made. Never raises."""
        try:
            if self.outcome is not None and self.undo_dropped():
                self.outcome.undo_dropped = True
        except Exception as exc:
            self.port.log(f"reading the undo steps failed: {exc!r}")

    def left_off(self):
        """The items of the tries still turned off (`TryTimeline.left_off`)."""
        return list(self.roll.left_off) if self.roll is not None else []

    def deferred_left(self):
        """Sketches whose compute flag the keeper could not put back (`SketchKeeper.deferred_left`)."""
        return list(getattr(self.keeper, "deferred_left", None) or [])

    def health_inputs(self, probe, probe_error, unchecked, flipped, changed=()):
        """The `health.HealthInputs` of the export, with what the probe tells: its status and error, what the restore
        check could not compare, the sketches that stayed on another outline for a while and those it found on
        another outline at the end (`changed`)."""
        return health_module.HealthInputs(
            unrestored=self.unrestored, gap_mm=self.gap_mm, probe=probe, probe_error=probe_error, unchecked=unchecked,
            flipped=flipped, stopped=self.stopped, steps=self.settled, deferred_left=self.deferred_left(),
            gap_after_mm=self.gap_after_mm, left_off=self.left_off(), undo_dropped=self.undo_dropped(),
            outlines_changed=changed, body_changed=self.body_changed, body_small=self.body_small,
            body_unconfirmed=self.body_unconfirmed, body_unchecked=self.body_unchecked)

    def _note_tries(self):
        """Tell the outcome that the tries changed the design from here on (`rollback.ExportOutcome.touched`)."""
        if self.outcome is not None:
            self.outcome.touched = True

    def _note_health(self, make):
        """Give the outcome the health that `make()` returns. A failure is logged and leaves the outcome without one,
        which counts as a design that is not confirmed back (`rollback.decide`)."""
        if self.outcome is None:
            return
        try:
            self.outcome.health = make()
        except Exception as exc:
            self.port.log(f"the health of the export could not be made: {exc!r}")

    def _failed_health(self):
        """The health record of an export that stopped. The end check must have run: without it nothing says the steps
        are as before, so this raises and the outcome keeps no health. The sketches are not read again here: when the
        tries ran, the read of the put back after them (`ProbeRun.end`) tells whether they came back. When it could not
        tell, the record says the sketches are not confirmed back (`restore_unverified`); when they read off their
        start, it carries the gap and the sketches on another outline from that read."""
        if self.settled is None:
            raise RuntimeError("the timeline steps were not compared with the start")
        run = self._tries_back
        end = getattr(run, "end", None) if run is not None else None
        if run is None or (end is not None and end.back is True):
            return health_module.make_health(self.health_inputs(health_module.NOT_NEEDED, "", [], ()))
        gap, changed = (end.gap_mm, end.changed) if end is not None else (None, [])
        if end is not None and end.back is False and not changed and (
                gap is None or gap <= RESTORE_TOLERANCE_MM):
            gap = None  # off its start by the probe's own test: never let the gap alone say "back"
        inputs = self.health_inputs(health_module.MEASURED, "", [], (), changed)
        return health_module.make_health(dataclasses.replace(inputs, gap_mm=gap, gap_after_mm=None))

    def close(self, health):
        """The export is made: values and marker back, the items that stayed off named, then the last Undo step dropped
        when `health` says the design is as it was (`undo_steps.drop_after`)."""
        self._note_undo()
        self._note_health(lambda: health)
        self.restore()
        with trail.stage("put back the marker"):
            self._end_roll()
        self._warn_left_off()
        drop_after(self.port.undo_steps, health)

    def close_failed(self):
        """The export stopped: values and marker back, then the person is told which parameters did not go back,
        which timeline steps differ from the start (the end check runs here when it has not yet) and which items stayed
        off. The warnings never raise, so the reason the export stopped is the one that reaches the person."""
        self._note_undo()
        failed = self.restore()
        self._end_roll()
        if failed:
            self._tell("the parameters that did not go back", lambda: self.port.warn_unrestored(failed))
        self._warn_steps()
        self._tell("the timeline items left off", self._warn_left_off)
        self._note_health(self._failed_health)

    def _tell(self, what, warn):
        """Run `warn()`; a failure is logged, not raised."""
        try:
            warn()
        except Exception as exc:
            self.port.log(f"telling the person about {what} failed: {exc!r}")

    def _warn_left_off(self):
        """Tell the person about timeline items that would not turn back on after the tries, leaving out the steps the
        end check still lists as changed: its own lines name them."""
        told = {c["name"] for c in self.settled.changed} if self.settled is not None else set()
        names = [name for name in self.left_off() if name not in told]
        if names:
            self.port.warn_left_off(names, self.undo_dropped())

    def _warn_steps(self):
        """Tell the person, when the export stopped, which timeline steps differ from the start. Never raises: it runs
        while the export stops for another reason."""
        try:
            lines = health_module.steps_lines(self._settle_steps(), self.deferred_left(), self.undo_dropped())
            if lines:
                self.port.warn_steps(lines)
        except Exception as exc:
            self.port.log(f"checking the timeline steps after the export failed: {exc!r}")
