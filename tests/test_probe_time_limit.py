"""The time limit of the size tries: the stop, the put back, the words, the progress line and the dialog choice."""
import dataclasses
import tempfile
import unittest

from tests import context  # noqa: F401
from tests import fakes
from tests.fakes import FakePartsPort, FakePort, FakeStore
from tests.test_parts_pipeline import BASE, second_body
from tests.test_pipeline import MODEL, START, TICKED, USER, export, request, view
from tests.test_probe_plan import size_dict

fakes.install_adsk_core()
from lib.dialog_model.result_rows import parts_result_view, section_lines  # noqa: E402
from lib.export_plan import health as health_module, messages, time_limit  # noqa: E402
from lib.export_plan.pipeline import ExportRequest, run_parts_pipeline, run_pipeline  # noqa: E402
from lib.fusion_ui import recipe_dialog  # noqa: E402
from lib.probe import plan  # noqa: E402
from lib.timing.export_timing import ExportTiming  # noqa: E402

ROW_SECONDS = 10.0  # each recompute of the fake design takes this long


class SlowDesign:
    """A fake port over a design whose every recompute takes `ROW_SECONDS` on the export's clock."""

    def __init__(self, port_class=FakePort, **options):
        self.now = 0.0
        store = options.pop("store", None) or FakeStore(START)
        store.on_recompute = self._tick
        self.port = port_class(store=store, **options)
        self.port.timing = ExportTiming(lambda: self.now)

    def _tick(self, _store):
        self.now += ROW_SECONDS


def single(limit, **options):
    """`(port, result)` of a single body export over a slow design with the time limit `limit` seconds."""
    design = SlowDesign(**options)
    asked = dataclasses.replace(request(), probe_time_limit=limit)
    with tempfile.TemporaryDirectory() as tmp:
        return design.port, run_pipeline(design.port, asked, tmp)


class TimeLimitWordsTest(unittest.TestCase):
    def test_every_choice_reads_back_as_itself_and_an_unknown_text_gives_the_default(self):
        for minutes in time_limit.CHOICES:
            self.assertEqual(time_limit.minutes_of(time_limit.choice_text(minutes)), minutes)
        self.assertEqual(time_limit.minutes_of("soon"), time_limit.DEFAULT_MINUTES)
        self.assertIn(time_limit.DEFAULT_MINUTES, time_limit.CHOICES)

    def test_a_duration_is_written_for_a_person(self):
        self.assertEqual([time_limit.duration_text(s) for s in (45, 130, 600, 3900, 7200)],
                         ["45 s", "2 min 10 s", "10 min", "1 h 5 min", "2 h"])


class StopOnTimeTest(unittest.TestCase):
    def test_the_tries_stop_at_the_limit_and_the_design_is_exactly_as_before(self):
        port, result = single(25)
        probe = result.report["probe"]
        self.assertTrue(probe["time_limit"]["hit"])
        self.assertEqual(len(probe["states"]) - 1, 2)  # E0 and the two tries that fit
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(result.health["probe"], "measured")
        self.assertTrue(health_module.back_as_it_was(result.health))
        self.assertNotIn("tries_stopped", result.health)

    def test_sizes_left_without_a_try_are_named_with_the_time_reason_and_a_tip(self):
        _, result = single(25)
        record = result.report["probe"]["time_limit"]
        self.assertEqual((record["limit_seconds"], record["left_out"]), (25, ["cube_mm", "depth_mm"]))
        reasons = {d["name"]: d["reason"] for d in result.report["sizes"]["dropped"]}
        for name in record["left_out"]:
            self.assertIn("ran out of time", reasons[name])
            self.assertIn("Tip: raise the time limit", reasons[name])
        self.assertEqual(result.report["probe"]["motion"]["timed_out"], record["left_out"])

    def test_the_limit_and_the_sizes_left_out_are_in_the_timing_and_the_result_window(self):
        _, result = single(25)
        self.assertEqual(result.report["timing"]["probe"]["time_limit"],
                         {"limit_seconds": 25, "hit": True, "left_out": ["cube_mm", "depth_mm"]})
        lines = section_lines(view(result), "result")
        self.assertTrue(any("stopped at the time limit (25 s). 2 sizes were not tried" in line for line in lines))

    def test_a_limit_that_is_not_reached_changes_nothing_and_says_so_in_the_report(self):
        port, result = single(100000)
        full = FakePort()
        export(full)
        self.assertEqual(port.progressed, full.progressed)
        self.assertEqual(result.report["probe"]["time_limit"], {"limit_seconds": 100000, "hit": False, "left_out": []})
        self.assertEqual(result.report["timing"]["probe"]["time_limit"], {"limit_seconds": 100000, "hit": False})
        self.assertFalse([line for line in section_lines(view(result), "result") if "time limit" in line])

    def test_no_limit_runs_every_try(self):
        port, result = single(None)
        self.assertFalse(result.report["probe"]["time_limit"]["hit"])
        self.assertIsNone(result.report["probe"]["time_limit"]["limit_seconds"])
        self.assertGreater(len(result.report["probe"]["states"]), 10)

    def test_the_export_asks_for_the_default_limit_unless_told_otherwise(self):
        asked = ExportRequest(title="Box", writer="t", up_axis="z", parameters=USER, model_params=MODEL,
                              design_unit="mm", ticked=TICKED, ranges={})
        self.assertEqual(asked.probe_time_limit, time_limit.DEFAULT_SECONDS)

    def test_a_try_that_did_not_build_before_the_stop_is_checked_so_a_broken_design_is_still_noticed(self):
        # The second try (box_count at 3.75) breaks the design for good; the limit is reached right after it.
        store = FakeStore(START, breaks=("box_count", 3.5))
        port, result = single(25, store=store)
        self.assertEqual(result.report["probe"]["stopped"]["items"], ["RemoveBody1"])
        self.assertEqual(result.health["tries_stopped"]["items"], ["RemoveBody1"])
        self.assertTrue(result.report["probe"]["time_limit"]["hit"])

    def test_several_bodies_stop_together_and_each_part_keeps_the_record(self):
        design = SlowDesign(FakePartsPort, captures=[BASE, second_body()])
        asked = dataclasses.replace(request(), probe_time_limit=25)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_parts_pipeline(design.port, asked, tmp)
        self.assertEqual(design.port.store.exprs, START)
        records = [part["probe"]["time_limit"] for part in result.report["parts"]]
        self.assertEqual([r["hit"] for r in records], [True, True])
        view_ = parts_result_view("box.paramability", result.manifest, result.report, result.table, TICKED)
        self.assertTrue(any("time limit" in line for line in section_lines(view_, "result")))


class ProgressTest(unittest.TestCase):
    def test_the_progress_window_gets_the_time_spent_and_left_from_the_tries_so_far(self):
        port, _ = single(600)
        self.assertEqual(port.notes[0], "Time limit: 10 min.")
        self.assertEqual(port.notes[2], "Time spent: 40 s. About 1 min 20 s left (limit: 10 min).")

    def test_the_estimate_never_passes_the_time_the_limit_leaves(self):
        self.assertEqual(messages.time_note(spent=100, done=1, left=50, limit=130),
                         "Time spent: 1 min 40 s. About 30 s left (limit: 2 min 10 s).")
        self.assertEqual(messages.time_note(spent=100, done=10, left=5, limit=None),
                         "Time spent: 1 min 40 s. About 50 s left.")


class OrderTest(unittest.TestCase):
    def test_favourites_of_the_design_are_tried_first_each_group_keeping_its_order(self):
        sizes = [size_dict("a", 10.0, 1.0, 20.0), dict(size_dict("b", 10.0, 1.0, 20.0), favorite=True),
                 size_dict("c", 10.0, 1.0, 20.0), dict(size_dict("d", 10.0, 1.0, 20.0), favorite=True)]
        rows, _ = plan.probe_rows(sizes, {"a", "b", "c"}, extra={"d"})
        self.assertEqual([p for p in dict.fromkeys(r["varied"][0] for r in rows)], ["b", "a", "c", "d"])


class DialogTest(unittest.TestCase):
    @staticmethod
    def form():
        command = fakes.FakeCommand()
        recipe_dialog.build(command, [], None, "z")
        return command.commandInputs

    def test_the_limit_starts_at_the_default_and_the_form_reads_the_chosen_one(self):
        inputs = self.form()
        self.assertEqual(recipe_dialog.read_form(inputs, [])["probe_time_limit"], time_limit.DEFAULT_SECONDS)
        for item in inputs.itemById(recipe_dialog.TIME_LIMIT_ID).listItems.items:
            item.isSelected = item.name == time_limit.choice_text(30)
        self.assertEqual(recipe_dialog.read_form(inputs, [])["probe_time_limit"], 1800)
        for item in inputs.itemById(recipe_dialog.TIME_LIMIT_ID).listItems.items:
            item.isSelected = item.name == time_limit.NO_LIMIT
        self.assertIsNone(recipe_dialog.read_form(inputs, [])["probe_time_limit"])
