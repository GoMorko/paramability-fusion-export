"""Run every size row: apply, export a STEP, and always restore the parameters."""
import os

from ..package.caps import check_step_size, check_total_size
from ..timing import trail
from . import metered, walk_back
from .apply import Health, RowBuildError, apply_row, cleared_errors, measure_baseline, new_warnings
from .errors import StepExportError
from .restore import restore_parameters
from .timeline_health import changes, is_worse, read_timeline


class ExportCancelled(Exception):
    """The person cancelled during the export."""


def row_key(row):
    """The key of a row: its `key`, or its name when it has none."""
    return row.get("key", row["name"])


class RowExport:
    """Runs of size rows over one design.

    store: parameter store (see apply.apply_row_values, plus saved_expressions and current_expressions).
    units: {parameter name: Fusion unit string}.
    export_step: callable(path) writing the STEP of the picked body for the current design state. A row with
    `"step": False` only recomputes: export_step is called with None, expects no file, and the result has no STEP.
    A row with a STEP is recomputed in full before its STEP is written (`apply_row_values` with `full`).
    current_row is the name of the row being exported while export_step runs, current_key its `key` (the name when
    the row has none); a name is cut to the manifest limit, so use the key to tell rows apart.
    Before its first row the job measures a baseline (`apply.measure_baseline`) and notes the parameters: a design
    that already has warnings or errors elsewhere still gets its rows checked, against what it did before any change.
    Later runs of the same job reuse both. Every row starts from the saved expressions (one more recompute per row
    after the first), and every run puts the parameters back at its end. restore_failures lists
    the parameters that could not be put back by any run, whatever the outcome.
    before_row(row), when given, is called just before each row's values are set, once the parameters are back: the
    place to read the design the row starts from.
    counts_warning(step), when given, says which steps in a new warning count for a row (`apply.new_warnings`; `step`
    is `(timeline position, name)`); the others are not named and cost no recompute. `rebase()` measures the baseline again before the next row, for a
    caller that turned timeline items back on between runs.
    stop_when(), when given, is asked before each row; when it answers true the run ends there, cleanly: no later row
    runs, the parameters are put back as at the end of any run, and `halted` stays true for every later run of the
    job. A row that did not build is still checked first (`not_back`), so a stop never hides a broken design.
    With build errors tolerated, the row after a row that may have left the design changed first checks, with the
    parameters back and before `before_row`, that every timeline step is as in the baseline (`_worse`): the row did not
    build, a step showed a new warning that counts, or the caller asked for the check (`check_back`, a row that read a
    sketch on another outline). A row that showed only new warnings that do not count is checked so only when, with
    the parameters back, an item is still in a warning or an error the baseline did not have (`_others_left`, a read
    of the health of the items alone). The steps are read (`timeline_health.read_timeline`) and compared, by step,
    with their read at the baseline; a warning or an error the baseline already had does not count. A step that is
    worse (`timeline_health.is_worse`) is read again after one full recompute. When one is still worse, the job tries
    to bring the design back the way the row took it away (`walk_back`, at most `walk_back.ATTEMPTS` times, each
    followed by the parameters back and a check, `at_start()` included). When a step is still worse after that, every
    later row would run on a changed design: the run stops and `not_back` says `{ after, items, steps }`, the row run
    last, the names of the steps still worse and their changes (`timeline_health.changes`). No later run of the job
    runs a row. `before_check()`, when given, runs before the steps are read (the place to bring the timeline marker
    back where the tries hold it); `at_start()`, when given, says whether the followed sketches read as at the start.
    `back_clean` is False once a check found a step worse or could not read the steps (nor the steps of the
    baseline), until a later check finds the steps as in the baseline. Steps that cannot be read never stop the run.
    `check_pending()` runs the check the row run last asked for, for a caller that ends the tries or measures the
    baseline again (`rebase`) and must not leave that row unchecked.
    `contain(worse, row)`, when given, is asked when steps stay worse after the walks back (`worse`, the changes of
    `timeline_health.changes`; `row`, the row run last). A dict means the caller ends the tries of the sizes behind
    it and goes on with the others: instead of `not_back`, `ended` gets `{ after, items, steps }` with the dict's
    keys, the run ends there (the caller runs the rows it keeps), and the baseline is measured again, so later rows
    are compared with the design as it is now. `back_clean` then stays False for good: the undo data holds a change
    the job does not undo.
    """

    def __init__(self, store, units, export_step, before_row=None, stop_when=None, counts_warning=None,
                 before_check=None, at_start=None, contain=None):
        self.store = store
        self.counts_warning = counts_warning
        self.units = units
        self.export_step = export_step
        self.before_row = before_row
        self.before_check = before_check
        self.at_start = at_start
        self.stop_when = stop_when
        self.halted = False  # `stop_when` ended a run: no later run of this job runs a row
        self.current_row = ""
        self.current_key = ""
        self.restore_failures = []
        self.not_back = None
        self.contain = contain
        self.ended = []  # the checks after which the tries of some sizes ended and the others went on (`contain`)
        self._ended_now = False  # the check run last ended the tries of some sizes (`_stopped`)
        self._last = None  # the label of the row run last
        self._last_row = None  # the row run last
        self._check_next = False  # whether the design is checked before the next row (`_stopped`)
        self._check_others = False  # the row run last showed only new warnings that do not count (`_others_left`)
        self.back_clean = True  # False while the last check found a step worse than in the baseline
        self.recoveries = 0  # attempts made to bring the design back the way a row took it away (`walk_back`)
        self.walks = []  # the first `walk_back.KEPT` of those attempts, for the report (`walk_back`)
        self._saved = None
        self._baseline = None
        self._rebased = False  # the baseline is measured again because `rebase` was asked
        self._steps = None  # the timeline steps read with the baseline (`timeline_health.read_timeline`)
        self._total = 0

    def rebase(self):
        """Measure the baseline again before the next row: timeline items were turned back on since it was measured,
        and the errors and warnings they already had are not the rows' doing."""
        self._baseline = None
        self._rebased = True

    def _measure(self):
        """Measure the baseline and read the steps with it, counted as the baseline, or as a `rebase` when that was
        asked since the last measure."""
        label = metered.REBASE if self._rebased else metered.BASELINE
        self._rebased = False
        with metered.caller(self.store, label):
            self._baseline = measure_baseline(self.store)
            self._steps = read_timeline(self.store)

    def check_pending(self):
        """Run the check of the steps that the row run last asked for (`_stopped`), with the parameters back; nothing
        when no check is pending or the job has not run. True when the run stopped (`not_back`)."""
        if self._saved is None or self._baseline is None:
            return self.not_back is not None
        return self._stopped()

    def check_back(self):
        """Check the design against the baseline before the next row (`_stopped`), as after a row that did not build:
        the caller saw the row run last leave a sketch on another outline."""
        self._check_next = True

    def _back_to_current(self):
        """Put the parameters back to their saved expressions and recompute before the next row, so a row never builds
        on the values of the one before it: a sketch with two solutions can flip under a row and stay flipped.
        A parameter that cannot be put back is listed in restore_failures, and the run goes on."""
        trail.line("parameters back before the next try")
        failed = restore_parameters(self.store, self._saved)
        self.restore_failures = list(dict.fromkeys(self.restore_failures + failed))

    def _pending(self):
        """True when the row run last asked for the check of the steps (`_stopped`)."""
        return self._check_next or self._check_others

    def _others_left(self):
        """For a row that showed only new warnings that do not count: True when, with the parameters back, a timeline
        item is still in a warning or an error it did not have in the baseline. Reads only the health of the items
        (`apply.Health`, one pass), not the whole timeline; True when that read fails."""
        base = self._baseline
        try:
            health = Health(self.store)
            if health.warnings is None:
                return True
            warned = [k for k in health.warnings if k not in base.warnings and k not in base.errors]
            return bool(warned or [k for k in health.errors if k not in base.errors])
        except Exception:
            return True

    def _stopped(self):
        """True when an earlier row left the design changed with the parameters back (`not_back`), or this check ended
        the tries of the sizes behind such a row (`ended`, see `contain`). Only a row that asked for the check
        (`_check_next`) is followed by it; a row that showed only new warnings that do not count is followed by it when
        one is still there with the parameters back (`_others_left`)."""
        self._ended_now = False
        if self.not_back is None and self._check_others and not self._check_next:
            self._check_others = False
            self._check_next = self._others_left()
        if self.not_back is None and self._check_next:
            self._check_next = self._check_others = False
            with trail.stage("check after a row"):
                if self.before_check is not None:
                    self.before_check()
                worse = self._worse()
                if worse:
                    worse = self._recover(worse)
            if worse:
                record = {"after": self._last, "items": [c["name"] for c in worse],
                          "steps": [{"name": c["name"], "before": c["before"], "after": c["after"]} for c in worse]}
                if not self._contained(worse, record):
                    self.not_back = record
            self.back_clean = worse == [] and not self.ended  # None: the steps could not be read
        return self.not_back is not None or self._ended_now

    def _contained(self, worse, record):
        """True when `contain` takes the steps still `worse` after the row run last: the run ends, `ended` keeps
        `record` with what `contain` gave, and the baseline and its steps are measured again with the parameters
        back. A `contain` that raises takes nothing."""
        if self.contain is None:
            return False
        try:
            more = self.contain(worse, self._last_row)
        except ExportCancelled:
            raise
        except Exception:
            more = None
        if not isinstance(more, dict):
            return False
        self.ended.append(dict(record, **more))
        self._ended_now = True
        self._measure()
        return True

    def _worse_now(self):
        """The changes of the steps now against the baseline (`timeline_health.changes`) that are worse. None when the
        steps cannot be read."""
        now = read_timeline(self.store, self._steps)
        if now is None or self._steps is None:
            return None
        return [c for c in changes(self._steps, now) if is_worse(c)]

    @trail.staged("read steps against the baseline")
    def _worse(self):
        """The steps worse than in the baseline with the parameters back, read again after one full recompute when
        any is: a rebuild of only the changed steps can leave a state that a full one clears. None when the steps
        cannot be read."""
        worse = self._worse_now()
        if not worse:
            return worse
        with metered.caller(self.store, metered.CHECK_AFTER_ROW):
            try:
                self.store.recompute()
            except Exception:
                pass
        worse = self._worse_now()
        if worse == []:
            metered.note(self.store, metered.CHECK_CLEARED)
        return worse

    @trail.staged("walk back")
    def walk_back(self, row, attempt, at=None):
        """Attempt number `attempt` to bring the design back the way `row` took it away (`walk_back.settings`): its
        sizes set from the other side of their start values, or in steps from the values tried, then every parameter
        put back. False, with nothing changed, when the attempt has nothing to set or the job has not run a row.
        The first `walk_back.KEPT` attempts are kept in `walks` (`walk_back.record`), with `at`, where the attempt
        ran, when given, and `failed`, the steps Fusion refused or could not build."""
        if self._saved is None or not row:
            return False
        values = row.get("values") or {}
        steps = walk_back.settings(values, walk_back.start_values(self.store, values, self.units), self.units, attempt)
        if not steps:
            return False
        self.recoveries += 1
        entry = walk_back.record(row.get("key", row.get("name")), attempt, steps, at)
        if len(self.walks) < walk_back.KEPT:
            self.walks.append(entry)
        trail.line("bringing the design back after %r, attempt %d" % (row.get("label") or row.get("name"), attempt + 1))
        try:
            with metered.caller(self.store, metered.WALK_STEP):
                failed = walk_back.walk(self.store, self.units, steps, self._baseline)
        finally:
            self._back_to_current()
        if failed:
            entry["failed"] = failed
        return True

    @trail.staged("recover steps")
    def _recover(self, worse):
        """Try to bring the design back the way the row run last took it away (`walk_back`), at most
        `walk_back.ATTEMPTS` times, the parameters put back after each attempt. Stops at the first attempt after which
        no step is worse and the followed sketches read as at the start (`at_start`). Returns the steps still worse, or
        None when the last read of the steps failed."""
        for attempt in range(walk_back.ATTEMPTS):
            if not self.walk_back(self._last_row, attempt, walk_back.AT_CHECK):
                break
            worse = self._worse()
            if worse == [] and (self.at_start is None or self.at_start()):
                return []
        return worse

    def _halt(self, index):
        """True when `stop_when` asks the run to end before row number `index`. A row that did not build is checked
        first, with the parameters back, so the design it may have left broken is still noticed."""
        if not self.halted and (self.stop_when is None or not self.stop_when()):
            return False
        self.halted = True
        if self._pending() and self._saved is not None:
            if index > 1:
                self._back_to_current()
            self._stopped()
        return True

    def run(self, rows, tmpdir, progress, tolerate_build_errors=False):
        """Return [{'name', 'values', 'step_file'}]. progress(index, total, text) returns False to cancel; `text` is
        the row's `label` (what the person reads) or its name.

        With tolerate_build_errors a row Fusion cannot build gives {'name', 'values': None, 'step_file': None,
        'error': sentence, 'detail': why} and the run goes on (`why` is RowBuildError.detail). The next row must
        then set every parameter it needs. A row that builds with timeline items in warning that were not in warning
        or in error in the baseline (`apply.new_warnings`) also gives 'warned': `(timeline position, name)` of each,
        in timeline order. A row that builds a step that was in error in the baseline (`apply.cleared_errors`) gives
        'cleared': `(timeline position, name)` of each. The new warnings that `counts_warning` does not count give
        'others_warned', from the same read.
        A row without a STEP gives 'step_file': None as well.
        """
        if self._saved is None:
            self._saved = self.store.saved_expressions()
        try:
            if self._baseline is None:
                self._measure()
                if self._steps is None:
                    self.back_clean = False  # no check can confirm the steps against this baseline
            results = []
            count = len(rows)
            for index, row in enumerate(rows, start=1):
                if self._halt(index):
                    break
                if not progress(index, count, row.get("label") or row["name"]):
                    raise ExportCancelled()
                if index > 1:
                    self._back_to_current()
                if tolerate_build_errors and self._stopped():
                    break
                if self.before_row is not None:
                    self.before_row(row)
                self._last, self._last_row = row.get("label") or row["name"], row
                self._check_next = self._check_others = False
                trail.line("try %d of %d %r: %s" % (index, count, self._last, row["values"]))
                others = []
                try:
                    values, health = apply_row(self.store, self.units, row["values"], self._baseline,
                                               full=row.get("step") is not False)
                    warned = new_warnings(self.store, self._baseline, self.counts_warning, others, health) \
                        if tolerate_build_errors else []
                    cleared = cleared_errors(self.store, self._baseline, health) if tolerate_build_errors else []
                    self._check_next, self._check_others = bool(warned), bool(others)
                except RowBuildError as exc:
                    if tolerate_build_errors:
                        self._check_next = True
                        results.append({"name": row["name"], "values": None, "step_file": None, "error": str(exc),
                                        "detail": exc.detail})
                        continue
                    raise RowBuildError(f"Size \"{row['name']}\": {exc}", exc.detail) from exc
                self.current_row = row["name"]
                self.current_key = row_key(row)
                result = {"name": row["name"], "values": values, "step_file": None}
                if warned:
                    result["warned"] = warned
                if cleared:
                    result["cleared"] = cleared
                if others:
                    result["others_warned"] = others
                if row.get("step") is False:
                    self.export_step(None)
                    results.append(result)
                else:
                    path = os.path.join(tmpdir, f"{index:02d}.step")
                    self.export_step(path)
                    if not os.path.isfile(path):
                        raise StepExportError(f"Fusion did not write the STEP file for size \"{row['name']}\".")
                    size = os.path.getsize(path)
                    self._total += size
                    check_step_size(f"Size \"{row['name']}\"", size)
                    check_total_size(self._total)
                    results.append(dict(result, step_file=path))
            return results
        finally:
            failed = restore_parameters(self.store, self._saved)
            self.restore_failures = list(dict.fromkeys(self.restore_failures + failed))
