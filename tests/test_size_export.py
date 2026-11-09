import json
import os
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.params_fixtures import CUBE, H, reader_dicts
from lib.export_plan import recipe_export
from lib.export_plan.apply import RowBuildError
from lib.export_plan.messages import fixed_note, recipe_saved_message
from lib.export_plan.recipe_export import plan_single_export
from lib.export_plan.runner import RowExport
from lib.export_plan.size_offers import MAX_TICKED, initial_table, labels, offers, probe_sizes
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


def sized_translate(capture, size_table=None, motion=None):
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

    def plan(self):
        return plan_single_export(
            load_capture("extrude_plate"), self.paths["part"], "Box", "w", "z", size_table=box_table())

    def test_package_has_no_check_steps_and_lists_the_fixed_numbers(self):
        manifest, files, report = self.plan()
        self.assertEqual(manifest["checks"], [])
        self.assertFalse([name for name in files if name.startswith("checks/")])
        self.assertEqual([f["name"] for f in manifest["fixed"]], ["corner", "pitch"])
        self.assertEqual(mf.validate_manifest(manifest), [])
        self.assertEqual(report["sizes"]["free"], ["wall"])
        self.assertNotIn("checks", report["sizes"])

    def test_saved_message_lists_why_numbers_stay_fixed(self):
        manifest, _, _ = self.plan()
        text = recipe_saved_message(manifest, "box.paramability")
        self.assertIn("pitch stays fixed", text)

    def test_a_part_that_stays_a_fixed_shape_has_no_fixed_list(self):
        manifest, files, _ = plan_single_export(
            RuntimeError("x"), self.paths["part"], "Box", "w", "z", size_table=box_table())
        self.assertEqual(manifest["kind"], "stepOnly")
        self.assertNotIn("fixed", manifest)

    def test_a_ticked_size_no_step_uses_is_named_in_a_note_and_the_report(self):
        def with_dropped(capture, size_table=None, motion=None):
            result = sized_translate(capture)
            result.dropped = [{"name": "width", "reason": "width is not used by any copied step, so it is not a size.",
                               "used": False}]
            return result

        recipe_export.translate = with_dropped
        manifest, _, report = plan_single_export(
            load_capture("extrude_plate"), self.paths["part"], "Box", "w", "z", size_table=box_table(("wall", "width")))
        self.assertIn("Not used by any copied step, so not sizes: width.", manifest["notes"])
        (dropped,) = report["sizes"]["dropped"]
        self.assertEqual((dropped["name"], dropped["used"]), ("width", False))
        self.assertEqual(dropped["reason"], "width is not used by any copied step, so it is not a size.")

    def test_fixed_entries_hold_the_recipe_name_and_keep_the_fusion_name_in_the_reason(self):
        long_name = "Filter box $ " + "x" * 58
        params = [length("wall"), length(long_name), length("a b")]
        table = size_table.build(params, ["wall", long_name, "a b"])
        recipe_export.translate = lambda capture, size_table=None, motion=None: self.translated(
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
        self.assertTrue(mf.validate_manifest(self.base(fixed=[{"name": "a", "reason": "r"}] * (mf.MAX_FIXED + 1))))
        self.assertTrue(mf.validate_manifest(self.base(checks=[{"values": {"w": 2e6}, "step": "checks/01.step"}])))


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


class SharedRunTest(unittest.TestCase):
    def test_runs_of_one_job_share_the_baseline(self):
        store = FakeStore({"width": "20 mm"}, bad_when=lambda e: e["width"] != "20 mm" and e["width"] != "30 mm")
        job = RowExport(store, {"width": "mm"}, lambda path: None)
        rows = [{"name": "w%d" % w, "values": {"width": float(w)}, "step": False} for w in (40, 30, 25)]
        first = job.run(rows[:1], "", lambda *a: True, tolerate_build_errors=True)
        recomputes = store.recomputes
        tried = job.run(rows[:2], "", lambda *a: True, tolerate_build_errors=True)
        self.assertTrue(first[0]["error"])
        self.assertEqual([bool(r.get("error")) for r in tried], [True, False])
        # Two rows, one restore between them and one at the end: no second baseline.
        self.assertEqual(store.recomputes - recomputes, 4)
        self.assertEqual(store.exprs, {"width": "20 mm"})


class RowStartTest(unittest.TestCase):
    def test_a_row_never_sees_the_values_of_the_row_before(self):
        store = FakeStore({"width": "20 mm", "wall": "2 mm"})
        seen = []
        original = store.recompute

        def recompute():
            seen.append(dict(store.exprs))
            return original()

        store.recompute = recompute
        job = RowExport(store, {"width": "mm", "wall": "mm"}, lambda path: None)
        rows = [{"name": "a", "values": {"width": 40.0}, "step": False},
                {"name": "b", "values": {"wall": 5.0}, "step": False}]
        job.run(rows, "", lambda *a: True)
        row_b = next(s for s in seen if s["wall"] == "5 mm")
        self.assertEqual(row_b["width"], "20 mm")
        self.assertEqual(store.exprs, {"width": "20 mm", "wall": "2 mm"})


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

    def test_favourites_the_body_reads_are_ticked_and_formulas_have_no_tick(self):
        lines = {o["param"]: o for o in offers(self.table, self.params)}
        self.assertTrue(lines[CUBE]["ticked"])
        self.assertEqual(lines[CUBE]["now"], "18 mm")
        self.assertFalse(lines["FilterBox_width_mm"]["enabled"])
        self.assertEqual(lines["FilterBox_width_mm"]["state"], "formula")

    def test_a_parameter_a_joint_reads_is_offered_unticked_with_a_warning(self):
        params = [length("wall"), length("height"), length("spare")]
        params[2]["is_favorite"] = False
        model = [dict(name="d1", expression="wall", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["wall"], created_by={"kind": "joint"}),
                 dict(name="d2", expression="height", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["height"], created_by={"kind": "feature"}),
                 dict(name="d3", expression="spare", value=0.2, unit="mm", kind="derived",
                      dependency_parameters=["spare"], created_by={"kind": "joint"})]
        lines = {o["param"]: o for o in offers(initial_table(params, model), params)}
        self.assertEqual((lines["wall"]["ticked"], lines["wall"]["enabled"]), (False, True))
        self.assertIn("moves a joint", lines["wall"]["doubt"])
        self.assertTrue(lines["height"]["ticked"] and lines["height"]["enabled"])
        self.assertEqual(lines["height"]["doubt"], "")
        self.assertIn("moves a joint", lines["spare"]["doubt"])

    def test_no_more_sizes_are_ticked_than_a_recipe_holds(self):
        params = [length("p%d" % i) for i in range(MAX_TICKED + 4)]
        table = initial_table(params)
        self.assertEqual(len(table.ticked), MAX_TICKED)
        lines = offers(table, params)
        self.assertEqual(sum(1 for o in lines if o["ticked"]), MAX_TICKED)
        self.assertTrue(all(o["enabled"] for o in lines))

    def test_probe_sizes_are_only_the_sizes_the_recipe_keeps(self):
        table = size_table.build(self.params, [CUBE, H])
        kept = probe_sizes(table, self.params, keep=[table.size_name(CUBE)])
        self.assertEqual([s["param"] for s in kept], [CUBE])

    def test_probe_sizes_come_from_free_sizes_with_their_range(self):
        table = size_table.build(self.params, [CUBE])
        cube = {s["param"]: s for s in probe_sizes(table, self.params)}[CUBE]
        self.assertEqual((cube["min"], cube["max"]), (9.0, 36.0))
        self.assertEqual(labels(table)[cube["size"]], CUBE)

    def test_the_fixed_note_fits_the_manifest_note_limit(self):
        self.assertLessEqual(len(fixed_note(["x" * 60] * 6)), 200)


if __name__ == "__main__":
    unittest.main()
