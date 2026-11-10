"""The export of several bodies in one file, run against a simulated Fusion."""
import contextlib
import copy
import json
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.schema_check import load_schema, validate
from tests.test_manifest import PACKAGE_SCHEMA
from tests.test_pipeline import MODEL, START, TICKED, USER, StuckStore
from tests.translator_helpers import load_capture

from lib.design_edit.errors import StepExportError
from lib.design_edit.runner import ExportCancelled
from lib.dialog_model.result_rows import parts_result_view
from lib.export_plan import recipe_export
from lib.export_plan.parts_pipeline import run_parts_pipeline
from lib.export_plan.part_names import unique_names
from lib.export_plan.pipeline import ExportRequest
from lib.export_plan.size_offers import table_for_bodies, table_for_body
from lib.package.manifest import validate_manifest

BASE = load_capture("sketch_rect_centred")


def renamed(capture, old, new):
    """The capture with the body `old` (token and name) called `new` everywhere."""
    text = json.dumps(capture).replace('"%s"' % old[0], '"%s"' % new[0]).replace('"%s"' % old[1], '"%s"' % new[1])
    return json.loads(text)


def second_body():
    return renamed(BASE, ("t1", "Body1"), ("t2", "Body2"))


def with_joint_on(capture, size):
    """The capture with a joint that reads the user parameter `size`."""
    other = copy.deepcopy(capture)
    reader = next(m for m in other["parameters"]["model"] if size in m.get("expression", ""))
    other["parameters"]["model"].append(dict(reader, name="joint_offset", created_by={"kind": "joint"}))
    return other


def stuck_body():
    """A body whose last step has a type nothing can copy."""
    capture = renamed(BASE, ("t1", "Body1"), ("t3", "Body3"))
    capture["items"][-1]["type"] = "MysteryFeature"
    return capture


class FakePartsPort:
    """Fusion as the parts pipeline sees it: one capture per body, one design with one parameter store.
    `fail_step_at` is the number of the STEP export that fails; `cancel_at` the number of the progress step that is
    cancelled; `fail_read_from` makes the n-th probe read of any body, and the ones after it, raise."""

    def __init__(self, captures, store=None, fail_step_at=None, cancel_at=None, fail_read_from=None):
        self.captures = captures
        self.count = len(captures)
        self.store = store or FakeStore(START)
        self.units = {p["name"]: p["unit"] for p in USER}
        self.steps, self.reads, self.progressed = 0, 0, 0
        self.logs, self.warned = [], []
        self.fail_step_at, self.cancel_at, self.fail_read_from = fail_step_at, cancel_at, fail_read_from

    def body_names(self):
        return [c["target"]["name"] if isinstance(c, dict) else "Broken" for c in self.captures]

    def export_step(self, index, path):
        self.steps += 1
        if self.fail_step_at == self.steps:
            raise StepExportError("Fusion did not write the STEP file.")
        with open(path, "wb") as f:
            f.write(b"ISO-10303-21;%d" % index)

    def read_capture(self, index):
        return self.captures[index]

    def probe_reader(self, index):
        capture = self.captures[index]
        e0 = {"sketches": {}, "points": {}, "lines": {}, "params": {}}
        for item in capture["items"]:
            for profile in (item.get("data") or {}).get("profiles") or []:
                e0["sketches"][profile["sketch_token"]] = {
                    "frame": profile["frame"], "profiles": [{"loops": profile["loops"]}]}

        def read(request):
            self.reads += 1
            if self.fail_read_from is not None and self.reads >= self.fail_read_from:
                raise RuntimeError("Fusion would not answer")
            return e0
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


def request(ticked=TICKED):
    return ExportRequest(
        title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL, design_unit="mm",
        ticked=ticked, ranges={})


def export(port, **options):
    with tempfile.TemporaryDirectory() as tmp:
        return run_parts_pipeline(port, request(**options), tmp)


def recipe_of(result, number):
    return json.loads(result.files["parts/%02d/recipe.json" % number])


class SharedSizesTest(unittest.TestCase):
    def test_two_bodies_that_read_one_size_make_one_size_in_both_recipes(self):
        port = FakePartsPort([BASE, second_body()])
        result = export(port)
        manifest = result.manifest
        self.assertEqual(manifest["kind"], "parts")
        self.assertEqual([p["name"] for p in manifest["parts"]], ["Body1", "Body2"])
        self.assertEqual(port.steps, 2)
        first, second = recipe_of(result, 1), recipe_of(result, 2)
        self.assertIn("wall_mm", first["sizes"])
        self.assertEqual(first["sizes"], second["sizes"])
        self.assertEqual([e.name for e in result.table.entries].count("wall_mm"), 1)
        self.assertEqual(result.report["sizes"]["free"].count("wall_mm"), 1)
        self.assertEqual(port.store.exprs, START)

    def test_the_package_follows_the_rules_and_the_schema_copy(self):
        result = export(FakePartsPort([BASE, second_body()]))
        self.assertEqual(validate_manifest(result.manifest), [])
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])
        self.assertEqual(sorted(result.files), [
            "parts/01/part.step", "parts/01/recipe.json", "parts/02/part.step", "parts/02/recipe.json", "report.json"])
        self.assertEqual([p["name"] for p in result.report["parts"]], ["Body1", "Body2"])
        self.assertTrue(all("capture" in p for p in result.report["parts"]))

    def test_every_listed_parameter_comes_along_once_for_the_file(self):
        result = export(FakePartsPort([BASE, second_body()]))
        self.assertEqual([p["name"] for p in result.manifest["parameters"]], [p["name"] for p in USER])

    def test_two_bodies_with_the_same_name_get_different_names(self):
        result = export(FakePartsPort([BASE, BASE]))
        self.assertEqual([p["name"] for p in result.manifest["parts"]], ["Body1", "Body1 2"])


class LooseAndFixedTest(unittest.TestCase):
    def test_a_size_loose_in_one_part_is_loose_in_every_part_that_has_it_and_names_the_parts(self):
        joined = with_joint_on(second_body(), "wall_mm")
        result = export(FakePartsPort([BASE, joined]))
        first, second = result.manifest["parts"]
        for part in (first, second):
            self.assertEqual([e["name"] for e in part["loose"]], ["wall_mm"])
        self.assertIn("joint", first["loose"][0]["reason"])
        self.assertTrue(first["loose"][0]["reason"].startswith("Body1, Body2: "))
        self.assertEqual([e["name"] for e in result.report["sizes"]["loose"]], ["wall_mm"])
        self.assertIn("wall_mm", recipe_of(result, 1)["sizes"])

    def test_a_size_that_one_part_has_to_fix_is_fixed_in_every_part(self):
        real = recipe_export.translate

        def fixes_wall_for_the_second_body(capture, size_table=None, motion=None):
            result = real(capture, size_table=size_table, motion=motion)
            if capture["target"]["name"] == "Body2" and "wall_mm" in size_table.ticked:
                result.fixed = [{"name": "wall_mm", "reason": "wall_mm stays fixed: a formula is too long."}]
            return result

        with mock.patch.object(recipe_export, "translate", side_effect=fixes_wall_for_the_second_body):
            result = export(FakePartsPort([BASE, second_body()]))
        for number in (1, 2):
            self.assertNotIn("wall_mm", recipe_of(result, number).get("sizes", {}))
        self.assertEqual([e["name"] for e in result.manifest["fixed"]], ["wall_mm"])
        self.assertTrue(result.manifest["fixed"][0]["reason"].startswith("Body2: "))
        self.assertNotIn("wall_mm", result.report["sizes"]["free"])
        self.assertIn("height_mm", result.report["sizes"]["free"])


class FixedShapeTest(unittest.TestCase):
    def test_a_body_that_cannot_be_copied_lands_as_a_fixed_shape_next_to_the_editable_part(self):
        port = FakePartsPort([BASE, stuck_body()])
        result = export(port)
        editable, fixed = result.manifest["parts"]
        self.assertIn("recipe", editable)
        self.assertNotIn("recipe", fixed)
        self.assertIn(result.report["parts"][1]["refusal"]["name"], fixed["note"])
        self.assertIn("parts/02/part.step", result.files)
        self.assertNotIn("parts/02/recipe.json", result.files)
        self.assertEqual(result.report["parts"][1]["outcome"], "stepOnly")
        self.assertIn("refusal", result.report["parts"][1])
        self.assertIn("wall_mm", recipe_of(result, 1)["sizes"])
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])

    def test_a_body_whose_steps_could_not_be_read_is_a_fixed_shape_and_the_others_still_measure(self):
        port = FakePartsPort([RuntimeError("no steps"), BASE])
        result = export(port)
        broken, editable = result.manifest["parts"]
        self.assertNotIn("recipe", broken)
        self.assertIn("recipe", editable)
        self.assertEqual(result.health["probe"], "measured")
        self.assertEqual(port.store.exprs, START)

    def test_when_no_body_can_be_copied_the_file_holds_only_fixed_shapes(self):
        result = export(FakePartsPort([stuck_body(), RuntimeError("no steps")]))
        self.assertEqual(["recipe" in p for p in result.manifest["parts"]], [False, False])
        self.assertNotIn("fixed", result.manifest)
        self.assertEqual(validate_manifest(result.manifest), [])


class MeasuringTest(unittest.TestCase):
    def test_the_sketches_of_all_bodies_are_measured_over_one_set_of_rows(self):
        both = FakePartsPort([BASE, second_body()])
        export(both)
        single = FakePartsPort([BASE])
        export(single)
        self.assertEqual(both.reads, 2 * single.reads)

    def test_a_probe_that_fails_stops_the_motions_of_all_parts_and_is_reported(self):
        port = FakePartsPort([BASE, second_body()], fail_read_from=3)
        result = export(port)
        self.assertEqual(result.health["probe"], "failed")
        self.assertEqual(result.manifest["kind"], "parts")
        self.assertTrue(all("recipe" in p for p in result.manifest["parts"]))
        self.assertEqual(port.store.exprs, START)


class RestoreTest(unittest.TestCase):
    def test_a_step_file_that_fails_on_the_second_body_leaves_the_parameters_as_they_were(self):
        port = FakePartsPort([BASE, second_body()], fail_step_at=2)
        with self.assertRaises(StepExportError):
            export(port)
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(port.warned, [])

    def test_a_cancel_while_the_shared_rows_run_puts_the_parameters_back(self):
        port = FakePartsPort([BASE, second_body()], cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_a_parameter_that_will_not_go_back_is_named_when_the_export_stops(self):
        port = FakePartsPort([BASE, second_body()], store=StuckStore(START, stuck=TICKED), cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(len(port.warned), 1)
        self.assertTrue(port.warned[0] and set(port.warned[0]) <= set(TICKED))

    def test_a_parameter_that_will_not_go_back_after_a_finished_export_is_in_the_health_record(self):
        port = FakePartsPort([BASE, second_body()], store=StuckStore(START, stuck=["height_mm"]))
        result = export(port)
        self.assertEqual(result.health["unrestored"], ["height_mm"])
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))


class NamesTest(unittest.TestCase):
    def test_names_are_made_unique_not_empty_and_short_enough(self):
        names = unique_names(["Lid", "LID", "", "x" * 100, "x" * 100])
        self.assertEqual(names[:3], ["Lid", "LID 2", "Body"])
        self.assertEqual(len({n.lower() for n in names}), 5)
        self.assertTrue(all(1 <= len(n) <= 60 for n in names))


class DialogTableTest(unittest.TestCase):
    def test_one_body_gives_the_table_of_that_body(self):
        alone = table_for_body(USER, "mm", MODEL, BASE)
        same = table_for_bodies(USER, "mm", MODEL, [BASE])
        self.assertEqual(same.ticked, alone.ticked)

    def test_a_parameter_that_any_picked_body_uses_is_ticked(self):
        a = table_for_body(USER, "mm", MODEL, BASE)
        only_height = copy.deepcopy(second_body())
        only_height["parameters"]["model"] = [m for m in only_height["parameters"]["model"]
                                              if "height_mm" in m["expression"]]
        b = table_for_body(USER, "mm", MODEL, only_height)
        both = table_for_bodies(USER, "mm", MODEL, [only_height, BASE])
        self.assertTrue(set(a.ticked) | set(b.ticked) <= set(both.ticked))
        self.assertGreater(len(both.ticked), len(b.ticked))

    def test_a_body_that_could_not_be_read_adds_nothing_unless_it_is_the_only_one(self):
        alone = table_for_body(USER, "mm", MODEL, BASE)
        self.assertEqual(table_for_bodies(USER, "mm", MODEL, [RuntimeError("x"), BASE]).ticked, alone.ticked)
        self.assertTrue(table_for_bodies(USER, "mm", MODEL, [RuntimeError("x")]).entries)


class ResultViewTest(unittest.TestCase):
    def test_the_view_lists_each_size_once_and_a_line_per_part(self):
        result = export(FakePartsPort([BASE, stuck_body()]))
        view = parts_result_view("box.paramability", result.manifest, result.report, result.table, TICKED)
        names = [row["name"] for row in view["rows"]]
        self.assertEqual(names.count("wall_mm"), 1)
        self.assertEqual(len(view["parts"]), 2)
        self.assertTrue(view["parts"][0].startswith("Body1: editable"))
        self.assertIn("fixed shape", view["parts"][1])
        self.assertIn("Saved box.paramability", view["message"])

    def test_a_package_of_another_kind_has_no_parts_view(self):
        result = export(FakePartsPort([BASE, second_body()]))
        self.assertIsNone(parts_result_view("x", {"kind": "recipe"}, result.report, result.table, TICKED))


if __name__ == "__main__":
    unittest.main()
