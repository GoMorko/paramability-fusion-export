"""Run every size row: apply, export a STEP, and always restore the parameters."""
import os

from ..package.caps import check_step_size, check_total_size
from .apply import RowBuildError, apply_row_values
from .errors import StepExportError
from .restore import restore_parameters


class ExportCancelled(Exception):
    """The person cancelled during the export."""


class RowExport:
    """One export run over a list of rows.

    store: parameter store (see apply.apply_row_values, plus saved_expressions and current_expressions).
    units: {parameter name: Fusion unit string}.
    export_step: callable(path) writing the STEP of the picked body for the current design state.
    current_row is the name of the row being exported while export_step runs.
    After run(), restore_failures lists parameters that could not be put back, whatever the outcome.
    """

    def __init__(self, store, units, export_step):
        self.store = store
        self.units = units
        self.export_step = export_step
        self.current_row = ""
        self.restore_failures = []

    def run(self, rows, tmpdir, progress, tolerate_build_errors=False):
        """Return [{'name', 'values', 'step_file'}]. progress(index, total, name) returns False to cancel.

        With tolerate_build_errors a row Fusion cannot build gives {'name', 'values': None, 'step_file': None,
        'error': sentence} and the run goes on. The next row must then set every parameter it needs.
        """
        saved = self.store.saved_expressions()
        try:
            baseline = set(self.store.error_items())
            results = []
            count = len(rows)
            total = 0
            for index, row in enumerate(rows, start=1):
                if not progress(index, count, row["name"]):
                    raise ExportCancelled()
                try:
                    values = apply_row_values(self.store, self.units, row["values"], baseline)
                except RowBuildError as exc:
                    if tolerate_build_errors:
                        results.append({"name": row["name"], "values": None, "step_file": None, "error": str(exc)})
                        continue
                    raise RowBuildError(f"Size \"{row['name']}\": {exc}") from exc
                self.current_row = row["name"]
                path = os.path.join(tmpdir, f"{index:02d}.step")
                self.export_step(path)
                if not os.path.isfile(path):
                    raise StepExportError(f"Fusion did not write the STEP file for size \"{row['name']}\".")
                size = os.path.getsize(path)
                total += size
                check_step_size(f"Size \"{row['name']}\"", size)
                check_total_size(total)
                results.append({"name": row["name"], "values": values, "step_file": path})
            return results
        finally:
            self.restore_failures = restore_parameters(self.store, saved)
