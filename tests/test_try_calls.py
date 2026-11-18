"""The counts of what the tries ask of Fusion (`design_edit.metered`, `timing.probe.calls`): the full rebuilds by the
part of the export that asked, the parameter sets, the health passes and timeline reads, and the outcome."""
import json
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.test_pipeline import export

from lib.design_edit import metered
from lib.design_edit.runner import RowExport
from lib.export_plan.pipeline import try_summary
from lib.timing.export_timing import ExportTiming
from lib.timing.timer import Timer

UNITS = {"w": "mm"}
START = {"w": "5 mm"}


class BatchStore(FakeStore):
    """A store that sets values in one change (as Fusion's `modifyParameters`) and reads a timeline of steps.
    `shows`: the step that goes into error after a change; `clears`: whether a full recompute clears it."""

    def __init__(self, shows=None, clears=True, **options):
        super().__init__(START, errors=[], **options)
        self.shows, self.clears = shows, clears
        self.reads = 0
        self.steps = [{"index": i, "name": n, "type": "ExtrudeFeature", "health": "ok", "message": "",
                       "suppressed": False} for i, n in enumerate(("Sketch1", "Extrude1", "Fillet1"))]

    def set_expressions(self, expressions):
        for name, text in expressions.items():
            self.exprs[name] = text
        if self.shows is not None and self.exprs != self.first:
            self.errors = [self.shows]
        return True

    def recompute(self):
        super().recompute()
        if self.clears and self.exprs != self.first or self.exprs == self.first:
            self.errors = []
        return True

    def timeline_health(self, known=None):
        self.reads += 1
        return [dict(step) for step in self.steps]


def run(store, rows=2, step=False, tolerate=True):
    timer = Timer()
    counted = metered.MeteredStore(store, timer)
    job = RowExport(counted, UNITS, lambda path: None)
    job.timer = timer
    rows = [{"name": f"r{i}", "values": {"w": 6.0 + i}, "step": step} for i in range(rows)]
    with tempfile.TemporaryDirectory() as tmp:
        results = job.run(rows, tmp, lambda *a: True, tolerate_build_errors=tolerate)
    return job, results, timer


class CallsTest(unittest.TestCase):
    def test_a_clean_run_counts_the_baseline_and_the_calls_of_each_row(self):
        store = BatchStore()
        _, results, timer = run(store, rows=3)
        calls = try_summary.calls(timer)
        self.assertEqual([r["values"] for r in results], [{"w": 6.0}, {"w": 7.0}, {"w": 8.0}])
        self.assertEqual({name: entry["count"] for name, entry in calls["computes"].items()}, {"baseline": 1})
        self.assertEqual(calls["param_sets"]["count"], 3)
        self.assertEqual(calls["param_put_backs"]["count"], 3)
        self.assertEqual(calls["timeline_reads"]["count"], 1)
        # The baseline reads errors and warnings; each row reads errors, then warnings.
        self.assertEqual(calls["health_passes"]["count"], 2 + 2 * 3)
        self.assertEqual(calls["check_cleared"], 0)

    def test_a_row_with_new_errors_fails_with_no_extra_rebuild_even_when_a_rebuild_would_clear_them(self):
        store = BatchStore(shows=(2, "Fillet1"), clears=True)
        _, results, timer = run(store, rows=1)
        calls = try_summary.calls(timer)
        self.assertIsNone(results[0]["values"])
        self.assertEqual(results[0]["detail"]["items"], ["Fillet1"])
        self.assertEqual(set(calls["computes"]), {"baseline"})

    def test_a_failed_row_leaves_the_values_as_they_were(self):
        store = BatchStore(shows=(2, "Fillet1"), clears=False)
        job, _, _ = run(store, rows=1)
        self.assertEqual(store.exprs, store.first)
        self.assertEqual(job.restore_failures, [])
        self.assertFalse(job.check_pending())  # the check after the row finds the design back

    def test_a_check_that_finds_the_steps_fine_after_the_rebuild_counts_as_cleared(self):
        store = BatchStore(shows=(2, "Fillet1"), clears=False)
        job, _, timer = run(store, rows=1)
        store.errors, store.steps[2]["health"] = [], "error"
        store.on_recompute = lambda s: s.steps[2].update(health="ok")
        job.check_back()
        self.assertFalse(job.check_pending())
        calls = try_summary.calls(timer)
        self.assertEqual(calls["computes"]["check_after_row"]["count"], 1)
        self.assertEqual(calls["check_cleared"], 1)

    def test_a_walk_back_whose_step_fails_makes_no_extra_rebuild(self):
        store = BatchStore(shows=(2, "Fillet1"), clears=True)
        job, _, timer = run(store, rows=1)
        job.walk_back({"name": "r0", "values": {"w": 6.0}}, 0)
        calls = try_summary.calls(timer)
        self.assertEqual(set(calls["computes"]), {"baseline"})  # the failed step asked for no rebuild
        self.assertEqual(job.walks[0]["failed"], 1)

    def test_a_baseline_measured_again_after_a_rebase_counts_as_a_rebase(self):
        store = BatchStore()
        job, _, timer = run(store, rows=1)
        job.rebase()
        with tempfile.TemporaryDirectory() as tmp:
            job.run([{"name": "r", "values": {"w": 9.0}, "step": False}], tmp, lambda *a: True,
                    tolerate_build_errors=True)
        calls = try_summary.calls(timer)
        self.assertEqual({n: e["count"] for n, e in calls["computes"].items()}, {"baseline": 1, "rebase": 1})

    def test_the_summary_holds_the_calls_and_stays_plain_json(self):
        store = BatchStore()
        _, _, timer = run(store, rows=1)
        found = try_summary.summary(timer, 1, None, None, lambda: [])
        self.assertEqual(set(found["calls"]), {"computes", "param_sets", "param_put_backs", "health_passes",
                                               "timeline_reads", "check_cleared"})
        self.assertEqual(json.loads(json.dumps(found)), found)

    def test_the_calls_after_the_tries_are_kept_apart_and_set_again_each_time(self):
        store = BatchStore()
        _, _, timer = run(store, rows=1)
        found = try_summary.summary(timer, 1, None, None, lambda: [])
        after = Timer()
        counted = metered.MeteredStore(store, after)
        with metered.caller(counted, metered.END_CHECK):
            counted.recompute()
        counted.timeline_health()
        try_summary.note_after_tries(found, after)
        try_summary.note_after_tries(found, after)
        self.assertEqual(found["calls"]["after_tries"]["computes"]["end_check"]["count"], 1)
        self.assertEqual(found["calls"]["after_tries"]["timeline_reads"]["count"], 1)
        self.assertEqual(found["calls"]["timeline_reads"]["count"], 1)  # the tries' own count is untouched

    def test_an_export_keeps_the_calls_after_the_tries_apart(self):
        port = FakePort()
        port.timing = ExportTiming()
        calls = export(port).report["timing"]["probe"]["calls"]
        self.assertGreater(calls["param_sets"]["count"], 0)
        self.assertIn("param_put_backs", calls["after_tries"])  # nothing differs once each try put its values back
        self.assertGreater(calls["after_tries"]["health_passes"]["count"], 0)  # the end check read the steps

    def test_a_store_without_a_member_still_lacks_it_through_the_wrapper(self):
        counted = metered.MeteredStore(FakeStore(START), Timer())
        self.assertFalse(hasattr(counted, "timeline_health"))
        self.assertTrue(callable(counted.error_entries))


if __name__ == "__main__":
    unittest.main()
