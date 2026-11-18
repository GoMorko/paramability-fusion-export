"""The health of the timeline items (errors and warnings) is read in one pass per read (`apply.Health`): one read per
clean try, and the same outcomes as when the errors and the warnings are read one after the other."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore

from lib.design_edit import metered
from lib.design_edit.apply import RowBuildError, apply_row, apply_row_values, measure_baseline
from lib.design_edit.runner import RowExport
from lib.export_plan.pipeline import try_summary
from lib.timing.timer import Timer

UNITS = {"w": "mm"}
START = {"w": "5 mm"}
OLD = (3, "Old")


class ViewStore(FakeStore):
    """A store that sets values in one change. `view(value, rebuilt)` gives `(errors, warnings)`, each a list of
    `(position, name)`, for the value of `w` in mm and whether a full recompute ran since it was set."""

    def __init__(self, view):
        super().__init__(START)
        self.view, self.rebuilt, self.passes = view, False, 0

    def _now(self):
        return self.view(self.read_value("w") * 10, self.rebuilt)

    def set_expressions(self, expressions):
        self.exprs.update(expressions)
        self.rebuilt = False
        return True

    def recompute(self):
        self.rebuilt = True
        return super().recompute()

    def timeline_health(self, known=None):
        return [{"index": 0, "name": "Sketch1", "type": "Sketch", "health": "ok", "message": "", "suppressed": False}]

    def error_entries(self):
        return self._now()[0]

    def warning_entries(self):
        return self._now()[1]


class OnePassStore(ViewStore):
    """The same, with the one-pass read of the Fusion store."""

    def health_entries(self):
        self.passes += 1
        return self._now()


def view(value, rebuilt):
    """Value 6: a warning on a step that counts and one that does not. 7: the old error clears. 8: a new error that a
    full recompute would clear (the add-in makes none, so the row fails). 9: a new error that stays. 10: a warning that counts and turns into an error on the
    recompute. Other values: nothing."""
    errors = [OLD] if value != 7 else []
    warnings = []
    if value == 6:
        warnings = [(4, "Fillet1"), (5, "Other")]
    if value == 8 and not rebuilt:
        errors = errors + [(6, "Extrude2")]
    if value == 9:
        errors = errors + [(6, "Extrude2")]
    if value == 10:
        warnings = [(4, "Fillet1")]
        if rebuilt:
            errors = errors + [(4, "Fillet1")]
    return errors, warnings


def run(store, values):
    timer = Timer()
    counted = metered.MeteredStore(store, timer)
    job = RowExport(counted, UNITS, lambda path: None, counts_warning=lambda step: step[1] == "Fillet1")
    rows = [{"name": f"r{v}", "values": {"w": float(v)}, "step": False} for v in values]
    with tempfile.TemporaryDirectory() as tmp:
        results = job.run(rows, tmp, lambda *a: True, tolerate_build_errors=True)
    return results, try_summary.calls(timer)


def outcome(result):
    keep = ("warned", "others_warned", "cleared")
    detail = result.get("detail") or {}
    return (result["name"], result["values"], {k: result[k] for k in keep if k in result},
            {k: detail[k] for k in ("reason", "items", "at") if k in detail})


class OnePassTest(unittest.TestCase):
    def test_a_clean_try_reads_the_health_once_and_the_baseline_once(self):
        _, calls = run(OnePassStore(lambda value, rebuilt: ([], [])), [11, 12, 13])
        self.assertEqual(calls["health_passes"]["count"], 1 + 3)

    def test_a_try_with_a_cleared_error_still_reads_once(self):
        results, calls = run(OnePassStore(view), [7])
        self.assertEqual(results[0]["cleared"], [(3, "Old")])
        self.assertEqual(calls["health_passes"]["count"], 2)

    def test_a_try_with_new_errors_makes_no_confirming_rebuild_and_the_next_row_starts_again(self):
        results, calls = run(OnePassStore(view), [8, 11])
        self.assertIsNone(results[0]["values"])
        self.assertEqual(results[1]["values"], {"w": 11.0})
        self.assertEqual(set(calls["computes"]), {"baseline"})
        self.assertEqual(calls["health_passes"]["count"], 1 + 2)

    def test_a_store_without_the_one_pass_read_gives_the_same_outcomes(self):
        for values in ([6], [7], [8], [9], [10], [11], [6, 7, 8, 9, 10]):
            one, _ = run(OnePassStore(view), values)
            two, _ = run(ViewStore(view), values)
            self.assertEqual([outcome(r) for r in one], [outcome(r) for r in two], values)

    def test_the_outcomes_of_each_case(self):
        results, calls = run(OnePassStore(view), [6, 7, 8, 9, 10])
        found = {r["name"]: outcome(r) for r in results}
        self.assertEqual(found["r6"][2], {"warned": [(4, "Fillet1")], "others_warned": [(5, "Other")]})
        self.assertEqual(found["r7"][2], {"cleared": [(3, "Old")]})
        self.assertEqual((found["r8"][1], found["r8"][3]["reason"], found["r8"][3]["items"]),
                         (None, "new_errors", ["Extrude2"]))
        self.assertIsNone(found["r9"][1])
        self.assertEqual(found["r9"][3]["reason"], "new_errors")
        self.assertEqual((found["r10"][1], found["r10"][3]["reason"], found["r10"][3]["items"]),
                         (None, "new_errors", ["Fillet1"]))
        self.assertEqual(calls["computes"]["counting_warning"]["count"], 2)  # r6 and r10

    def test_an_unreadable_one_pass_read_fails_the_row_as_unreadable_errors_do(self):
        store = OnePassStore(view)
        store.health_entries = lambda: (_ for _ in ()).throw(RuntimeError("no timeline"))
        baseline = measure_baseline(store)
        self.assertEqual((baseline.errors, baseline.warnings), ({}, {}))
        with self.assertRaises(RuntimeError):
            apply_row(store, UNITS, {"w": 11.0}, baseline)

    def test_a_walk_reads_only_the_errors(self):
        store = OnePassStore(view)
        baseline = measure_baseline(store)
        before = store.passes
        with self.assertRaises(RowBuildError):
            apply_row_values(store, UNITS, {"w": 9.0}, baseline)
        self.assertEqual(store.passes, before)


if __name__ == "__main__":
    unittest.main()
