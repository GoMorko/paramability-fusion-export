"""Run every size row: apply, export a STEP, and always restore the parameters."""
import os

from .apply import RowBuildError, apply_row_values
from .restore import restore_parameters


class ExportCancelled(Exception):
    """The person cancelled during the export."""


class RowExport:
    """One export run over a list of rows.

    store: parameter store (see apply.apply_row_values, plus saved_expressions and current_expressions).
    units: {parameter name: Fusion unit string}.
    export_step: callable(path) writing the STEP of the picked body for the current design state.
    After run(), restore_failures lists parameters that could not be put back, whatever the outcome.
    """

    def __init__(self, store, units, export_step):
        self.store = store
        self.units = units
        self.export_step = export_step
        self.restore_failures = []

    def run(self, rows, tmpdir, progress):
        """Return [{'name', 'values', 'step_file'}]. progress(index, total, name) returns False to cancel."""
        saved = self.store.saved_expressions()
        try:
            baseline = set(self.store.error_items())
            results = []
            total = len(rows)
            for index, row in enumerate(rows, start=1):
                if not progress(index, total, row["name"]):
                    raise ExportCancelled()
                try:
                    values = apply_row_values(self.store, self.units, row["values"], baseline)
                except RowBuildError as exc:
                    raise RowBuildError(f"Size \"{row['name']}\": {exc}") from exc
                path = os.path.join(tmpdir, f"{index:02d}.step")
                self.export_step(path)
                if not os.path.isfile(path):
                    raise RuntimeError(f"Fusion did not write the STEP file for size \"{row['name']}\".")
                results.append({"name": row["name"], "values": values, "step_file": path})
            return results
        finally:
            self.restore_failures = restore_parameters(self.store, saved)
