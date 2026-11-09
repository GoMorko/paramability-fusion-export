"""The export pipeline run against a simulated Fusion: the sketch scan, and every way a step can fail."""
import contextlib
import copy
import json
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.translator_helpers import load_capture

from lib.design_edit.errors import StepExportError
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.dialog_model.result_rows import NOT_FOLLOWED, NOT_MEASURED, result_view
from lib.design_edit.runner import ExportCancelled

CAPTURE = load_capture("sketch_rect_centred")
USER = CAPTURE["parameters"]["user"]
MODEL = CAPTURE["parameters"]["model"]
TICKED = ["box_count", "cube_mm", "depth_mm", "height_mm", "wall_mm"]
START = {p["name"]: p["expression"] for p in USER}


def shifted(read, dx):
    """The read with every sketch point moved `dx` along x."""
    out = copy.deepcopy(read)

    def move(node):
        if isinstance(node, dict):
            for key in ("start", "end", "center"):
                if isinstance(node.get(key), list):
                    node[key][0] += dx
            for value in node.values():
                move(value)
        elif isinstance(node, list):
            for value in node:
                move(value)

    move(out["sketches"])
    return out


class StuckStore(FakeStore):
    """A store where the named parameters can be changed but never set back to their saved expression."""

    def __init__(self, expressions, stuck=()):
        super().__init__(expressions)
        self.saved = dict(expressions)
        self.stuck = set(stuck)

    def set_expression(self, name, expression):
        if name in self.stuck and self.exprs[name] != self.saved[name] and expression == self.saved[name]:
            raise RuntimeError("refused")
        super().set_expression(name, expression)


class FakePort:
    """Fusion as the pipeline sees it. `reads` counts probe reads; `fail_read_from` makes the n-th read and the ones
    after it raise; `drift` makes every read at the start values after the first come back moved."""

    def __init__(self, capture=CAPTURE, store=None, bad_when=None, fail_read_from=None, drift=0.0,
                 fail_step_at=None, cancel_at=None):
        self.capture = capture
        self.store = store or FakeStore(START, bad_when=bad_when)
        self.units = {p["name"]: p["unit"] for p in USER}
        self.reads, self.steps, self.logs, self.warned = 0, 0, [], []
        self.fail_read_from, self.drift = fail_read_from, drift
        self.fail_step_at, self.cancel_at = fail_step_at, cancel_at
        self.progressed = 0
        self.e0 = {"sketches": {}, "points": {}, "lines": {}, "params": {}}
        for item in capture["items"] if isinstance(capture, dict) else []:
            for profile in (item.get("data") or {}).get("profiles") or []:
                self.e0["sketches"][profile["sketch_token"]] = {
                    "frame": profile["frame"], "profiles": [{"loops": profile["loops"]}]}

    def export_step(self, path):
        self.steps += 1
        if self.fail_step_at == self.steps:
            raise StepExportError("Fusion did not write the STEP file.")
        with open(path, "wb") as f:
            f.write(b"ISO-10303-21;")

    def read_capture(self):
        return self.capture

    def probe_reader(self):
        def read(request):
            self.reads += 1
            if self.fail_read_from is not None and self.reads >= self.fail_read_from:
                raise RuntimeError("Fusion would not answer")
            if self.drift and self.reads > 1 and self.store.exprs == START:
                return shifted(self.e0, self.drift)
            return self.e0
        return read

    def progress(self, verb):
        outer = self

        class Step:
            def step(self, *args):
                outer.progressed += 1
                return outer.cancel_at != outer.progressed

        return contextlib.nullcontext(Step())

    def warn_unrestored(self, names):
        self.warned.append(list(names))

    def log(self, text):
        self.logs.append(text)


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
    def test_an_export_measures_the_sketches_and_makes_one_step_file_and_no_check_step(self):
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
        self.assertEqual(view(result)["warnings"], [])
        self.assertEqual(port.store.exprs, START)

    def test_a_part_whose_steps_could_not_be_read_is_saved_as_a_fixed_shape(self):
        port = FakePort(capture=RuntimeError("no steps"))
        result = export(port)
        self.assertEqual(result.manifest["kind"], "stepOnly")
        self.assertEqual(port.reads, 0)
        self.assertEqual(port.store.exprs, START)


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
        port = FakePort(bad_when=lambda e: float(e["depth_mm"].split()[0]) > 80)
        result = export(port, ranges={"depth_mm": (30, 120)})
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual([d["name"] for d in result.report["probe"]["dropped"]], ["depth_mm (max)", "all max"])
        self.assertEqual(result.report["sizes"]["fixed"], [])
        self.assertEqual(port.store.exprs, START)


class ProbeFailureTest(unittest.TestCase):
    def test_a_probe_that_cannot_start_is_shown_in_the_result_rows(self):
        port = FakePort(fail_read_from=1)
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(result.health["probe"], "failed")
        shown = view(result)
        self.assertIn(NOT_MEASURED, [r["check"] for r in shown["rows"]])
        self.assertTrue(any("could not be measured" in line for line in shown["warnings"]))
        self.assertIsNone(result.report.get("probe"))
        self.assertEqual(port.store.exprs, START)

    def test_sizes_that_move_a_sketch_are_not_called_unused_when_the_sketches_were_not_measured(self):
        result = export(FakePort(fail_read_from=1))
        left_out = {r["name"]: r["check"] for r in view(result)["rows"]}
        self.assertEqual(left_out["depth_mm"], NOT_FOLLOWED)
        self.assertFalse(any("Not used by any copied step" in n and "depth_mm" in n for n in result.manifest["notes"]))

    def test_a_probe_that_fails_while_its_rows_run_gives_a_recipe_and_a_warning(self):
        port = FakePort(fail_read_from=3)
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(result.health["probe"], "failed")
        self.assertTrue(view(result)["warnings"])
        self.assertEqual(port.store.exprs, START)


class RestoreTest(unittest.TestCase):
    def test_a_parameter_that_will_not_go_back_is_named_and_the_person_is_told_what_to_do(self):
        port = FakePort(store=StuckStore(START, stuck=["height_mm"]))
        result = export(port)
        self.assertEqual(result.health["unrestored"], ["height_mm"])
        lines = view(result)["warnings"]
        self.assertIn("height_mm", lines[0])
        self.assertIn("Undo", lines[0])
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))
        self.assertEqual(port.warned, [])

    def test_sketches_that_do_not_come_back_to_their_start_are_reported(self):
        port = FakePort(drift=0.5)
        result = export(port)
        self.assertTrue(result.health["sketch_drift"])
        self.assertGreater(result.health["sketch_gap_mm"], 0.1)
        lines = view(result)["warnings"]
        self.assertTrue(any("did not come back" in line and "Undo" in line for line in lines))
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))
        self.assertEqual(json.loads(json.dumps(result.report["health"]))["sketch_drift"], True)


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
        port = FakePort(store=StuckStore(START, stuck=TICKED), cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(len(port.warned), 1)
        self.assertTrue(port.warned[0] and set(port.warned[0]) <= set(TICKED))


if __name__ == "__main__":
    unittest.main()
