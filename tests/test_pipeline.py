"""The export pipeline run against a simulated Fusion: the sketch scan, and every way a step can fail."""
import json
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore, shifted
from tests.translator_helpers import load_capture

from lib.design_edit.errors import StepExportError
from lib.export_plan import health as health_module
from lib.export_plan import recipe_export
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.dialog_model.result_rows import NOT_FOLLOWED, NOT_MEASURED, result_view, section, section_lines
from lib.design_edit.runner import ExportCancelled

CAPTURE = load_capture("sketch_rect_centred")
USER = CAPTURE["parameters"]["user"]
MODEL = CAPTURE["parameters"]["model"]
TICKED = ["box_count", "cube_mm", "depth_mm", "height_mm", "wall_mm"]
START = {p["name"]: p["expression"] for p in USER}


def request(ranges=None):
    return ExportRequest(
        title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL, design_unit="mm",
        ticked=TICKED, ranges=ranges or {})


def export(port, **options):
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, request(**options), tmp)


def view(result):
    return result_view("box.paramability", result.manifest, result.report, result.table, TICKED)


class ExportTest(unittest.TestCase):
    def test_an_export_measures_the_sketches_and_makes_one_step_file(self):
        port = FakePort()
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(port.steps, 1)
        self.assertEqual(result.manifest["checks"], [])
        self.assertFalse([name for name in result.files if name.startswith("checks/")])
        self.assertNotIn("check_sizes", result.report)
        self.assertNotIn("keep_doubtful", result.report)
        self.assertGreater(port.reads, 2)
        self.assertIsNotNone(result.report["probe"])
        self.assertEqual(result.health["probe"], "measured")
        self.assertEqual(section_lines(view(result), "check"), [])
        self.assertEqual(port.store.exprs, START)

    def test_a_part_whose_steps_could_not_be_read_is_saved_as_a_fixed_shape(self):
        port = FakePort(capture=RuntimeError("no steps"))
        result = export(port)
        self.assertEqual(result.manifest["kind"], "stepOnly")
        self.assertEqual(port.reads, 0)
        self.assertEqual(port.store.exprs, START)


class RefusalTest(unittest.TestCase):
    def test_a_part_that_cannot_be_copied_is_translated_once(self):
        capture = load_capture("extrude_plate")
        capture["items"][-1]["type"] = "MysteryFeature"
        port = FakePort()
        port.capture = capture
        with mock.patch.object(recipe_export, "translate", wraps=recipe_export.translate) as translated:
            result = export(port)
        self.assertEqual(translated.call_count, 1)
        self.assertEqual(result.manifest["kind"], "stepOnly")
        self.assertIn("refusal", result.report)


class SizeRangeTest(unittest.TestCase):
    def test_sizes_with_a_single_value_still_measure_the_sketches(self):
        single = {"height_mm": (32, 32), "wall_mm": (2, 2), "cube_mm": (26, 26), "depth_mm": (60, 60),
                  "box_count": (3, 3)}
        port = FakePort()
        result = export(port, ranges=single)
        self.assertEqual(port.steps, 1)
        self.assertGreater(port.reads, 1)
        self.assertIsNotNone(result.report["probe"])
        self.assertEqual(port.store.exprs, START)

    def test_a_size_that_does_not_build_at_the_end_of_its_range_is_left_out_of_the_probe_and_the_export_goes_on(self):
        port = FakePort(bad_when=lambda e: float(e["depth_mm"].split()[0]) > 90)
        result = export(port, ranges={"depth_mm": (30, 120)})
        self.assertEqual(result.manifest["kind"], "recipe")
        dropped = [d["name"] for d in result.report["probe"]["dropped"]]
        self.assertEqual(dropped[0], "depth_mm (max)")
        # All sizes at their maximum take depth_mm only as far as it built on its own, so that row builds.
        self.assertNotIn("all max", dropped)
        # 75 builds and 120 does not: the values between are halved, so the size is measured up to the last of them
        # that builds, not just to 75. (The cut itself is in `test_geometry_links`.)
        span = result.report["probe"]["motion"]["spans"]["depth_mm"]
        self.assertEqual((span["low"], span["high"]), (30, 86.25))
        self.assertEqual([v for v, _ in span["failed"]], [120, 97.5, 91.875])
        self.assertEqual(result.report["sizes"]["fixed"], [])
        self.assertEqual(port.store.exprs, START)


class RowOrderTest(unittest.TestCase):
    @staticmethod
    def depth_values(result):
        return [s["values"]["depth_mm"] for s in result.report["probe"]["states"]
                if list(s["values"]) == ["depth_mm"]]

    def test_the_near_rows_run_before_the_far_ends(self):
        result = export(FakePort(), ranges={"depth_mm": (30, 120)})
        # 60 is the value: a quarter below and above first, then the range ends.
        self.assertEqual(self.depth_values(result), [45.0, 75.0, 30, 120])

    def test_a_near_value_that_does_not_build_is_tried_nearer_and_the_far_end_past_it_is_not_tried(self):
        port = FakePort(bad_when=lambda e: float(e["depth_mm"].split()[0]) > 70)
        result = export(port, ranges={"depth_mm": (30, 120)})
        values = self.depth_values(result)
        self.assertEqual(values[:2], [45.0, 75.0])
        # 75 does not build: a value between 60 and 75 is tried before the far end, and 120 is never tried.
        self.assertTrue(any(60 < v < 75 for v in values[2:values.index(30)]))
        self.assertNotIn(120, values)


class ProbeFailureTest(unittest.TestCase):
    def test_a_probe_that_cannot_start_is_shown_in_the_result_rows(self):
        port = FakePort(fail_read_from=1)
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(result.health["probe"], "failed")
        shown = view(result)
        self.assertIn(NOT_MEASURED, [r["check"] for r in section(shown, "sizes")["rows"]])
        self.assertTrue(any("could not be measured" in line for line in section_lines(shown, "check")))
        self.assertIsNone(result.report.get("probe"))
        self.assertEqual(port.store.exprs, START)

    def test_sizes_that_move_a_sketch_are_not_called_unused_when_the_sketches_were_not_measured(self):
        result = export(FakePort(fail_read_from=1))
        left_out = {r["name"]: r["check"] for r in section(view(result), "sizes")["rows"]}
        self.assertEqual(left_out["depth_mm"], NOT_FOLLOWED)
        self.assertFalse(any("Not used by any copied step" in n and "depth_mm" in n for n in result.manifest["notes"]))

    def test_a_probe_that_fails_while_its_rows_run_gives_a_recipe_and_a_warning(self):
        port = FakePort(fail_read_from=3)
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(result.health["probe"], "failed")
        self.assertTrue(section_lines(view(result), "check"))
        self.assertEqual(port.store.exprs, START)


class BrokenDesignTest(unittest.TestCase):
    def test_the_tries_stop_once_a_try_leaves_the_design_broken_and_the_person_is_told(self):
        port = FakePort(store=FakeStore(START, breaks=("depth_mm", 70)))
        result = export(port, ranges={"depth_mm": (30, 120)})
        states = result.report["probe"]["states"]
        failed = [n for n, s in enumerate(states) if not s["built"]]
        self.assertEqual(len(states) - 1, failed[0])  # nothing ran after the try that broke the design
        self.assertEqual(result.report["probe"]["stopped"]["items"], ["RemoveBody1"])
        self.assertEqual(result.health["tries_stopped"]["items"], ["RemoveBody1"])
        self.assertEqual(result.health["broken"], ["RemoveBody1"])
        lines = section_lines(view(result), "check")
        self.assertTrue(any("stopped early" in line for line in lines))
        self.assertTrue(any("RemoveBody1" in line and "Undo" in line for line in lines))

    def test_a_long_list_of_broken_steps_is_capped_and_its_line_kept_short(self):
        names = ["Step%d" % n for n in range(40)]
        health = health_module.make_health(health_module.HealthInputs(broken=names))
        self.assertEqual(len(health["broken"]), health_module.MAX_LISTED)
        self.assertLessEqual(len(health_module.health_lines(health)[0]), health_module.MAX_LINE)

    def test_sizes_whose_tries_never_ran_after_the_stop_are_untried_not_still(self):
        result = export(FakePort(store=FakeStore(START, breaks=("box_count", 3.5))))
        probe = result.report["probe"]
        self.assertEqual(probe["untried"], ["cube_mm", "depth_mm"])
        self.assertEqual(probe["motion"]["untried"], ["cube_mm", "depth_mm"])
        dropped = {d["name"]: d["used"] for d in result.report["sizes"]["dropped"]}
        self.assertEqual((dropped["cube_mm"], dropped["depth_mm"]), (True, True))


class RestoreTest(unittest.TestCase):
    def test_a_parameter_that_will_not_go_back_is_named_and_the_person_is_told_what_to_do(self):
        port = FakePort(store=FakeStore(START, stuck=["height_mm"]))
        result = export(port)
        self.assertEqual(result.health["unrestored"], ["height_mm"])
        lines = section_lines(view(result), "check")
        self.assertIn("height_mm", lines[0])
        self.assertIn("Undo", lines[0])
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))
        self.assertEqual(port.warned, [])

    def test_sketches_that_do_not_come_back_to_their_start_are_reported(self):
        port = FakePort(drift=0.5)
        result = export(port)
        self.assertTrue(result.health["sketch_drift"])
        self.assertGreater(result.health["sketch_gap_mm"], 0.1)
        lines = section_lines(view(result), "check")
        self.assertTrue(any("did not come back" in line and "Undo" in line for line in lines))
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))
        self.assertEqual(json.loads(json.dumps(result.report["health"]))["sketch_drift"], True)


def flip_port(keeper=True, fail_read_at=None, **options):
    """A design whose sketch goes to its other solution in the first try and stays there with the values back, until
    a keeper (when `keeper`) puts its points back. The read number `fail_read_at` raises."""
    def flip(store):
        port.flipped = port.flipped or store.exprs != START

    def read(request):
        if port.reads == fail_read_at:
            raise RuntimeError("Fusion would not answer")
        return shifted(port.e0, 0.5) if port.flipped and port.store.exprs == START else port.e0

    def keep(tokens):
        if not keeper:
            raise RuntimeError("no keeper")

        class Keeper:
            @staticmethod
            def put_back():
                port.flipped = False
                return 1

        return Keeper()

    port = FakePort(store=FakeStore(START, on_recompute=flip), reader=read, keeper=keep, **options)
    port.flipped = False
    return port


class TriesEndedEarlyTest(unittest.TestCase):
    def test_a_cancel_during_the_tries_puts_a_flipped_sketch_back(self):
        port = flip_port(cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertFalse(port.flipped)

    def test_failed_tries_that_leave_a_sketch_off_its_solution_are_reported(self):
        result = export(flip_port(keeper=False, fail_read_at=3))
        self.assertEqual(result.health["probe"], "failed")
        self.assertTrue(result.health["sketch_drift"])


class FailingStepTest(unittest.TestCase):
    def test_a_part_step_that_fails_stops_the_export_before_any_parameter_changes(self):
        port = FakePort(fail_step_at=1)
        with self.assertRaises(StepExportError):
            export(port)
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(port.warned, [])

    def test_a_cancel_during_the_probe_rows_puts_the_parameters_back(self):
        port = FakePort(cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_when_the_export_stops_and_a_parameter_will_not_go_back_it_is_named(self):
        port = FakePort(store=FakeStore(START, stuck=TICKED), cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(len(port.warned), 1)
        self.assertTrue(port.warned[0] and set(port.warned[0]) <= set(TICKED))


if __name__ == "__main__":
    unittest.main()
