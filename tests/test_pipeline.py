"""The export pipeline run against a simulated Fusion: plain and checked export, and every way a step can fail."""
import contextlib
import copy
import json
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.translator_helpers import load_capture

from lib.export_plan.errors import StepExportError
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.export_plan.result_rows import NOT_FOLLOWED, NOT_MEASURED, result_view
from lib.export_plan.runner import ExportCancelled

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

    def snapshot(self, skip, source):
        return {}

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


def request(check=False, ranges=None, keep_doubtful=False):
    return ExportRequest(
        title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL, design_unit="mm",
        ticked=TICKED, ranges=ranges or {}, check_sizes=check, keep_doubtful=keep_doubtful)


def export(port, check=False, **options):
    with tempfile.TemporaryDirectory() as tmp:
        result = run_pipeline(port, request(check, **options), tmp)
        # The files hold STEP paths of the temporary folder: read what the package keeps before it is gone.
        result.checks = [c["step"] for c in result.manifest.get("checks") or []]
    return result


def view(result):
    return result_view("box.paramability", result.manifest, result.report, result.table, TICKED)


class PlainExportTest(unittest.TestCase):
    def test_a_plain_export_measures_the_sketches_and_makes_no_check_step(self):
        port = FakePort()
        result = export(port)
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertEqual(port.steps, 1)
        self.assertEqual(result.checks, [])
        self.assertFalse(result.report["check_sizes"])
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


class CheckedExportTest(unittest.TestCase):
    def test_a_checked_export_makes_check_steps_and_measures_the_sketches(self):
        port = FakePort()
        result = export(port, check=True)
        self.assertTrue(result.report["check_sizes"])
        self.assertTrue(result.checks)
        self.assertGreater(port.steps, 1)
        self.assertIsNotNone(result.report["probe"])
        self.assertEqual(result.health["probe"], "measured")
        self.assertEqual(port.store.exprs, START)

    def test_a_checked_export_with_no_check_to_run_still_measures_the_sketches(self):
        single = {"height_mm": (32, 32), "wall_mm": (2, 2), "cube_mm": (26, 26), "depth_mm": (60, 60),
                  "box_count": (3, 3)}
        port = FakePort()
        result = export(port, check=True, ranges=single)
        self.assertEqual(result.checks, [])
        self.assertEqual(port.steps, 1)
        self.assertGreater(port.reads, 1)
        self.assertIsNotNone(result.report["probe"])
        self.assertEqual(port.store.exprs, START)

    def test_a_size_that_does_not_build_at_its_end_is_reported_and_the_parameters_come_back(self):
        port = FakePort(bad_when=lambda e: float(e["depth_mm"].split()[0]) > 80)
        result = export(port, check=True, ranges={"depth_mm": (30, 120)})
        sizes = result.report["sizes"]
        self.assertTrue(sizes["build_failures"] or sizes.get("narrowed"))
        self.assertEqual(result.manifest["kind"], "recipe")
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

    def test_a_probe_that_fails_while_the_checks_run_gives_a_recipe_and_a_warning(self):
        port = FakePort(fail_read_from=4)
        result = export(port, check=True)
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

    def test_a_clean_run_gives_no_warning_and_no_note_about_measuring(self):
        result = export(FakePort())
        self.assertEqual(result.health["unrestored"], [])
        self.assertFalse(result.health["sketch_drift"])
        self.assertFalse(any("may be off" in n for n in result.manifest["notes"]))


class FailingStepTest(unittest.TestCase):
    def test_a_check_step_that_fails_in_the_middle_still_puts_the_parameters_back(self):
        port = FakePort(fail_step_at=3)
        with self.assertRaises(StepExportError):
            export(port, check=True)
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(port.warned, [])

    def test_a_cancel_puts_the_parameters_back(self):
        port = FakePort(cancel_at=3)
        with self.assertRaises(ExportCancelled):
            export(port, check=True)
        self.assertEqual(port.store.exprs, START)

    def test_a_cancel_during_the_probe_rows_of_a_plain_export_puts_the_parameters_back(self):
        port = FakePort(cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_when_the_export_stops_and_a_parameter_will_not_go_back_it_is_named(self):
        port = FakePort(store=StuckStore(START, stuck=TICKED), fail_step_at=2)
        with self.assertRaises(StepExportError):
            export(port, check=True)
        self.assertEqual(len(port.warned), 1)
        self.assertTrue(port.warned[0] and set(port.warned[0]) <= set(TICKED))


if __name__ == "__main__":
    unittest.main()
