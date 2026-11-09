import json
import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.params_fixtures import CUBE, H, reader_dicts
from lib.export_plan import recipe_export
from lib.export_plan.apply import RowBuildError
from lib.export_plan.messages import fixed_note, recipe_saved_message, sizes_note
from lib.export_plan.recipe_export import plan_single_export
from lib.export_plan.runner import RowExport
from lib.export_plan.size_offers import MAX_TICKED, initial_table, labels, offers, sizes_for_checks
from lib.params import size_table
from lib.package import manifest as mf
from lib.translator.result import TranslateResult
from tests.translator_helpers import load_capture


def length(name):
    return dict(name=name, expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length")


def box_table(ticked=("wall",)):
    """A real table: `wall` free, `corner` fixed up front."""
    params = [length(n) for n in ("wall", "corner", "width", "pitch")]
    return size_table.build(params, list(ticked), fixed={"corner": "corner stays fixed."})


def sized_translate(capture, size_table=None):
    recipe = {"schema": "paramability.recipe", "version": 12, "sizesAsWritten": True,
              "sizes": {"wall": {"value": 2, "min": 1, "max": 4}, "tall": {"expr": "wall * 2"}},
              "features": [{"id": "extrude_1", "kind": "extrude"}]}
    result = TranslateResult(recipe=recipe)
    result.fixed = [{"name": "pitch", "reason": "pitch stays fixed."}]
    return result


class SizedPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = {}
        for name in ("part", "c1", "c2"):
            self.paths[name] = os.path.join(self.tmp.name, name + ".step")
            with open(self.paths[name], "wb") as f:
                f.write(b"ISO-10303-21;")
        original = recipe_export.translate
        recipe_export.translate = sized_translate
        self.addCleanup(setattr, recipe_export, "translate", original)

    def plan(self, **kwargs):
        checks = [{"size": "wall", "value": 4.0, "step_file": self.paths["c1"]},
                  {"size": "gone", "value": 9.0, "step_file": self.paths["c2"]}]
        return plan_single_export(
            load_capture("extrude_plate"), self.paths["part"], "Box", "w", "z", size_table=box_table(),
            checks=checks, fixed=[{"name": "width", "reason": "width stays fixed for now."}], **kwargs)

    def test_package_holds_checks_of_free_sizes_only_and_all_fixed_numbers(self):
        manifest, files, report = self.plan(unchecked=["depth"])
        self.assertEqual(manifest["checks"], [{"values": {"wall": 4.0}, "step": "checks/01.step"}])
        self.assertEqual(files["checks/01.step"], self.paths["c1"])
        self.assertNotIn("checks/02.step", files)
        self.assertEqual([f["name"] for f in manifest["fixed"]], ["width", "corner", "pitch"])
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(manifest["notes"][1], "1 size is ready to put on the form.")
        self.assertEqual(report["sizes"]["free"], ["wall"])
        self.assertEqual(report["sizes"]["unchecked"], ["depth"])
        self.assertEqual(json.loads(files["report.json"])["sizes"]["checks"], [{"size": "wall", "value": 4.0}])

    def test_saved_message_lists_why_numbers_stay_fixed(self):
        manifest, _, _ = self.plan()
        text = recipe_saved_message(manifest, "box.paramability")
        self.assertTrue(text.startswith("Saved box.paramability. 1 step copied from Fusion."))
        self.assertIn("- width: width stays fixed for now.", text)

    def test_a_part_that_stays_a_fixed_shape_has_no_checks_and_no_fixed_list(self):
        manifest, files, _ = plan_single_export(
            RuntimeError("x"), self.paths["part"], "Box", "w", "z", size_table=box_table(),
            checks=[{"size": "wall", "value": 4.0, "step_file": self.paths["c1"]}])
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertNotIn("checks/01.step", files)

    def test_a_ticked_size_no_step_uses_is_named_in_a_note_and_the_report(self):
        manifest, _, report = plan_single_export(
            load_capture("extrude_plate"), self.paths["part"], "Box", "w", "z", size_table=box_table(("wall", "width")))
        self.assertIn("Not used by any copied step, so not sizes: width.", manifest["notes"])
        self.assertEqual(report["sizes"]["dropped"], ["width"])

    def test_fixed_entries_hold_the_recipe_name_and_keep_the_fusion_name_in_the_reason(self):
        long_name = "Filter box $ " + "x" * 58
        params = [length("wall"), length(long_name), length("a b")]
        table = size_table.build(params, ["wall", long_name, "a b"])
        recipe_export.translate = lambda capture, size_table=None: self.translated(
            [{"name": long_name, "reason": long_name + " stays fixed: a sketch."}, {"name": "a b", "reason": "Why."}])
        manifest, _, _ = plan_single_export(
            load_capture("extrude_plate"), self.paths["part"], "Box", "w", "z", size_table=table)
        names = [f["name"] for f in manifest["fixed"]]
        self.assertEqual(names, [table.recipe_name(long_name), "a_b"])
        self.assertTrue(all(len(n) <= 64 for n in names))
        self.assertEqual(manifest["fixed"][1]["reason"], "a b: Why.")
        self.assertEqual(mf.validate_manifest(manifest), [])

    @staticmethod
    def translated(fixed):
        result = sized_translate(None)
        result.fixed = fixed
        return result


class ManifestFixedTest(unittest.TestCase):
    def base(self, **extra):
        m = mf.build_recipe_manifest("R", "w", checks=[{"values": {"wall": 4}, "step": "checks/01.step"}],
                                     fixed=[{"name": "a", "reason": "Because."}])
        m.update(extra)
        return m

    def test_valid_and_refused_shapes(self):
        self.assertEqual(mf.validate_manifest(self.base()), [])
        self.assertTrue(mf.validate_manifest(self.base(fixed=[{"name": "a"}])))
        self.assertTrue(mf.validate_manifest(self.base(fixed=[{"name": "a", "reason": "x" * 201}])))
        self.assertTrue(mf.validate_manifest(self.base(fixed=[{"name": "a", "reason": "r"}] * 33)))
        self.assertTrue(mf.validate_manifest(self.base(checks=[{"values": {"w": 2e6}, "step": "checks/01.step"}])))

    def test_empty_fixed_list_is_left_out(self):
        self.assertNotIn("fixed", mf.build_recipe_manifest("R", "w", fixed=[]))


class WriterTest(unittest.TestCase):
    def test_fixed_list_and_check_steps_reach_the_zip(self):
        import zipfile
        from lib.package.writer import write_package
        manifest = mf.build_recipe_manifest(
            "R", "w", checks=[{"values": {"wall": 4}, "step": "checks/01.step"}],
            fixed=[{"name": "a", "reason": "Because."}])
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.paramability")
            write_package(out, manifest, {"part.step": b"x", "recipe.json": b"{}", "checks/01.step": b"y"})
            with zipfile.ZipFile(out) as zf:
                written = json.loads(zf.read("manifest.json"))
                self.assertIn("checks/01.step", zf.namelist())
        self.assertEqual(written["fixed"], [{"name": "a", "reason": "Because."}])


class ToleratedBuildErrorTest(unittest.TestCase):
    def test_a_row_that_does_not_build_is_reported_and_the_run_goes_on(self):
        original = {"width": "20 mm", "wall": "2 mm"}
        store = FakeStore(original, bad_when=lambda e: e["width"] == "80 mm")
        written = []

        def export(path):
            written.append(path)
            with open(path, "wb") as f:
                f.write(b"x")

        rows = [{"name": "width", "values": {"width": 80.0, "wall": 2.0}},
                {"name": "wall", "values": {"width": 20.0, "wall": 4.0}}]
        job = RowExport(store, {"width": "mm", "wall": "mm"}, export)
        with tempfile.TemporaryDirectory() as tmp:
            results = job.run(rows, tmp, lambda i, n, name: True, tolerate_build_errors=True)
            with self.assertRaises(RowBuildError):
                job.run(rows, tmp, lambda i, n, name: True)
        self.assertIn("does not build", results[0]["error"])
        self.assertIsNone(results[0]["step_file"])
        self.assertTrue(results[1]["step_file"].endswith("02.step"))
        self.assertEqual(store.exprs, original)
        self.assertEqual(job.restore_failures, [])


class OffersTest(unittest.TestCase):
    def setUp(self):
        self.params = reader_dicts()
        self.table = initial_table(self.params)

    def test_without_model_parameters_the_favourites_are_ticked(self):
        self.assertIn(CUBE, self.table.ticked)

    def test_favourites_the_body_reads_are_ticked_and_formulas_have_no_tick(self):
        lines = {o["param"]: o for o in offers(self.table, self.params)}
        self.assertTrue(lines[CUBE]["ticked"])
        self.assertEqual(lines[CUBE]["text"], CUBE + ", 18 mm")
        self.assertFalse(lines["FilterBox_width_mm"]["enabled"])
        self.assertEqual(lines["FilterBox_width_mm"]["text"], "FilterBox_width_mm (formula)")

    def test_a_parameter_a_sketch_dimension_reads_is_greyed_out_before_the_export(self):
        params = [length("wall"), length("height"), length("spare")]
        model = [dict(name="d1", expression="wall", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["wall"], created_by={"kind": "sketchDimension"}),
                 dict(name="d2", expression="height + spare", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["height", "spare"], created_by={"kind": "feature"})]
        lines = {o["param"]: o for o in offers(initial_table(params, model), params)}
        self.assertEqual((lines["wall"]["ticked"], lines["wall"]["enabled"]), (False, False))
        self.assertIn("changes a sketch", lines["wall"]["reason"])
        self.assertTrue(lines["height"]["ticked"] and lines["height"]["enabled"])

    def test_a_parameter_that_is_not_ticked_by_default_but_moves_a_sketch_is_greyed_out_too(self):
        params = [length("wall"), length("spare")]
        params[1]["is_favorite"] = False
        model = [dict(name="d1", expression="wall", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["wall"], created_by={"kind": "feature"}),
                 dict(name="d2", expression="spare", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["spare"], created_by={"kind": "sketchDimension"})]
        lines = {o["param"]: o for o in offers(initial_table(params, model), params)}
        self.assertFalse(lines["spare"]["enabled"])
        self.assertTrue(lines["wall"]["ticked"])

    def test_no_more_sizes_are_ticked_than_there_are_check_slots(self):
        params = [length("p%d" % i) for i in range(20)]
        table = initial_table(params)
        self.assertEqual(len(table.ticked), MAX_TICKED)
        lines = offers(table, params)
        self.assertEqual(sum(1 for o in lines if o["ticked"]), MAX_TICKED)
        self.assertTrue(all(o["enabled"] for o in lines))

    def test_checks_go_only_to_sizes_the_recipe_keeps(self):
        table = size_table.build(self.params, [CUBE, H])
        kept = sizes_for_checks(table, self.params, keep=[table.size_name(CUBE)])
        self.assertEqual([s["param"] for s in kept], [CUBE])

    def test_check_sizes_come_from_free_sizes_with_their_range(self):
        table = size_table.build(self.params, [CUBE])
        cube = {s["param"]: s for s in sizes_for_checks(table, self.params)}[CUBE]
        self.assertEqual((cube["min"], cube["max"]), (9.0, 36.0))
        self.assertEqual(labels(table)[cube["size"]], CUBE)

    def test_messages(self):
        self.assertEqual(sizes_note(4), "4 sizes are ready to put on the form.")
        self.assertEqual(fixed_note(["a"]), "1 number stays fixed: a.")
        self.assertLessEqual(len(fixed_note(["x" * 60] * 6)), 200)


if __name__ == "__main__":
    unittest.main()
