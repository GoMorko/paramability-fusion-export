"""Run every size row: apply, export a STEP, and always restore the parameters."""
import os

from ..package.caps import check_step_size, check_total_size
from .apply import RowBuildError, apply_row_values, measure_baseline
from .errors import StepExportError
from .restore import restore_parameters


class ExportCancelled(Exception):
    """The person cancelled during the export."""


class RowExport:
    """Runs of size rows over one design.

    store: parameter store (see apply.apply_row_values, plus saved_expressions and current_expressions).
    units: {parameter name: Fusion unit string}.
    export_step: callable(path) writing the STEP of the picked body for the current design state. A row with
    `"step": False` only recomputes: export_step is called with None, expects no file, and the result has no STEP.
    current_row is the name of the row being exported while export_step runs, current_key its `key` (the name when
    the row has none); a name is cut to the manifest limit, so use the key to tell rows apart.
    Before its first row the job measures a baseline (`apply.measure_baseline`) and notes the parameters: a design
    that already has warnings or errors elsewhere still gets its rows checked, against what it did before any change.
    Later runs of the same job reuse both. Every row starts from the saved expressions (one more recompute per row
    after the first), and every run puts the parameters back at its end. restore_failures lists
    the parameters that could not be put back by any run, whatever the outcome.
    before_row(row), when given, is called just before each row's values are set, once the parameters are back: the
    place to read the design the row starts from.
    """

    def __init__(self, store, units, export_step, before_row=None):
        self.store = store
        self.units = units
        self.export_step = export_step
        self.before_row = before_row
        self.current_row = ""
        self.current_key = ""
        self.restore_failures = []
        self._saved = None
        self._baseline = None
        self._total = 0

    def _back_to_current(self):
        """Put the parameters back to their saved expressions and recompute before the next row, so a row never builds
        on the values of the one before it: a sketch with two solutions can flip under a row and stay flipped.
        A parameter that cannot be put back is listed in restore_failures, and the run goes on."""
        failed = restore_parameters(self.store, self._saved)
        self.restore_failures = list(dict.fromkeys(self.restore_failures + failed))

    def run(self, rows, tmpdir, progress, tolerate_build_errors=False):
        """Return [{'name', 'values', 'step_file'}]. progress(index, total, name) returns False to cancel.

        With tolerate_build_errors a row Fusion cannot build gives {'name', 'values': None, 'step_file': None,
        'error': sentence, 'detail': why} and the run goes on (`why` is RowBuildError.detail). The next row must
        then set every parameter it needs.
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
                if not progress(index, count, row["name"]):
                    raise ExportCancelled()
                if index > 1:
                    self._back_to_current()
                if self.before_row is not None:
                    self.before_row(row)
                try:
                    values = apply_row_values(self.store, self.units, row["values"], self._baseline)
                except RowBuildError as exc:
                    if tolerate_build_errors:
                        results.append({"name": row["name"], "values": None, "step_file": None, "error": str(exc),
                                        "detail": exc.detail})
                        continue
                    raise RowBuildError(f"Size \"{row['name']}\": {exc}", exc.detail) from exc
                self.current_row = row["name"]
                self.current_key = row.get("key", row["name"])
                if row.get("step") is False:
                    self.export_step(None)
                    results.append({"name": row["name"], "values": values, "step_file": None})
                else:
                    path = os.path.join(tmpdir, f"{index:02d}.step")
                    self.export_step(path)
                    if not os.path.isfile(path):
                        raise StepExportError(f"Fusion did not write the STEP file for size \"{row['name']}\".")
                    size = os.path.getsize(path)
                    self._total += size
                    check_step_size(f"Size \"{row['name']}\"", size)
                    check_total_size(self._total)
                    results.append({"name": row["name"], "values": values, "step_file": path})
            return results
        finally:
            failed = restore_parameters(self.store, self._saved)
            self.restore_failures = list(dict.fromkeys(self.restore_failures + failed))
