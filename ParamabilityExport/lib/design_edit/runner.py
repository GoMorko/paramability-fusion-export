"""Run every size row: apply, export a STEP, and always restore the parameters."""
import os

from ..package.caps import check_step_size, check_total_size
from .apply import RowBuildError, apply_row_values, measure_baseline, new_errors, new_warnings
from .errors import StepExportError
from .restore import restore_parameters


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
    stop_when(), when given, is asked before each row; when it answers true the run ends there, cleanly: no later row
    runs, the parameters are put back as at the end of any run, and `halted` stays true for every later run of the
    job. A row that did not build is still checked first (`not_back`), so a stop never hides a broken design.
    With build errors tolerated, every row after a row that did not build first checks, with the parameters back and
    before `before_row`, that the design rebuilds as in the baseline (`apply.new_errors`, which recomputes in full once
    when a step reads in error). When a step is still in error, the failed row has left the design broken, so every
    later row would fail for that reason and not for its own values: the run stops and `not_back` says
    `{ after, items }`, the row run last and the steps in error. No later run of the job runs a row.
    """

    def __init__(self, store, units, export_step, before_row=None, stop_when=None):
        self.store = store
        self.units = units
        self.export_step = export_step
        self.before_row = before_row
        self.stop_when = stop_when
        self.halted = False  # `stop_when` ended a run: no later run of this job runs a row
        self.current_row = ""
        self.current_key = ""
        self.restore_failures = []
        self.not_back = None
        self._last = None  # the label of the row run last
        self._last_failed = False  # whether that row did not build
        self._saved = None
        self._baseline = None
        self._total = 0

    def _back_to_current(self):
        """Put the parameters back to their saved expressions and recompute before the next row, so a row never builds
        on the values of the one before it: a sketch with two solutions can flip under a row and stay flipped.
        A parameter that cannot be put back is listed in restore_failures, and the run goes on."""
        failed = restore_parameters(self.store, self._saved)
        self.restore_failures = list(dict.fromkeys(self.restore_failures + failed))

    def _stopped(self):
        """True when an earlier row left the design broken with the parameters back (`not_back`). Only a row that did
        not build is followed by the check."""
        if self.not_back is None and self._last_failed:
            self._last_failed = False
            broken = new_errors(self.store, self._baseline.errors)
            if broken:
                self.not_back = {"after": self._last, "items": broken}
        return self.not_back is not None

    def _halt(self, index):
        """True when `stop_when` asks the run to end before row number `index`. A row that did not build is checked
        first, with the parameters back, so the design it may have left broken is still noticed."""
        if not self.halted and (self.stop_when is None or not self.stop_when()):
            return False
        self.halted = True
        if self._last_failed and self._saved is not None:
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
        or in error in the baseline (`apply.new_warnings`) also gives 'warned': their names, in timeline order.
        A row without a STEP gives 'step_file': None as well.
        """
        if self._saved is None:
            self._saved = self.store.saved_expressions()
        try:
            if self._baseline is None:
                self._baseline = measure_baseline(self.store)
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
                self._last, self._last_failed = row.get("label") or row["name"], False
                try:
                    values = apply_row_values(self.store, self.units, row["values"], self._baseline,
                                              full=row.get("step") is not False)
                except RowBuildError as exc:
                    if tolerate_build_errors:
                        self._last_failed = True
                        results.append({"name": row["name"], "values": None, "step_file": None, "error": str(exc),
                                        "detail": exc.detail})
                        continue
                    raise RowBuildError(f"Size \"{row['name']}\": {exc}", exc.detail) from exc
                warned = new_warnings(self.store, self._baseline) if tolerate_build_errors else []
                self.current_row = row["name"]
                self.current_key = row_key(row)
                result = {"name": row["name"], "values": values, "step_file": None}
                if warned:
                    result["warned"] = warned
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
