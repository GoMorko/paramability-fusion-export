import os
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from lib.design_edit.apply import RowBuildError
from lib.export_plan.assemble import build_package
from lib.params.expressions import format_expression, is_plain_number
from lib.package.naming import addin_version, body_file_title, design_title, package_file_name, with_extension
from lib.design_edit.errors import StepExportError
from lib.design_edit.restore import restore_order, restore_parameters
from lib.design_edit.runner import ExportCancelled, RowExport
from lib.dialog_model.sizes_text import others_line, prefill_sizes_text, read_sizes
from lib.package.manifest import validate_manifest
from lib.package.writer import write_package

PARAMS = [
    {"name": "width", "expression": "20 mm", "value": 2.0, "display_value": 20.0, "unit": "mm",
     "comment": "Clip width", "is_favorite": True, "kind": "length"},
    {"name": "angle", "expression": "30 deg", "value": 0.5236, "display_value": 30.0, "unit": "deg",
     "comment": "", "is_favorite": True, "kind": "angle"},
    {"name": "depth", "expression": "width / 2", "value": 1.0, "display_value": 10.0, "unit": "mm",
     "comment": "", "is_favorite": True, "kind": "derived"},
    {"name": "wall", "expression": "2 mm", "value": 0.2, "display_value": 2.0, "unit": "mm",
     "comment": "", "is_favorite": False, "kind": "length"},
]
UNITS = {p["name"]: p["unit"] for p in PARAMS}
ORIGINAL = {"width": "20 mm", "angle": "30 deg", "depth": "width / 2", "wall": "2 mm"}


def step_writer(store=None, fail_on=None):
    calls = []

    def export(path):
        if fail_on is not None and len(calls) == fail_on:
            raise RuntimeError("export failed")
        calls.append(path)
        with open(path, "wb") as f:
            f.write(b"ISO-10303-21;")
    export.calls = calls
    return export


def rows():
    return [
        {"name": "Small", "values": {"width": 20.0, "angle": 30.0}},
        {"name": "Large", "values": {"width": 40.0, "angle": 45.0}},
        {"name": "Huge", "values": {"width": 80.0, "angle": 45.0}},
    ]


class ExpressionsTest(unittest.TestCase):
    def test_plain_number_vs_formula(self):
        for text in ("20", "20 mm", "-1.5e2 deg", ".5 in"):
            self.assertTrue(is_plain_number(text), text)
        for text in ("width / 2", "20 mm + 1 mm", "d1", ""):
            self.assertFalse(is_plain_number(text), text)

    def test_format_expression(self):
        self.assertEqual(format_expression(40.0, "mm"), "40 mm")
        self.assertEqual(format_expression(12.5, "deg"), "12.5 deg")
        for unit in ("", "unitless", "no units"):
            self.assertEqual(format_expression(3.6, unit), "3.6")


class SizesTextTest(unittest.TestCase):
    def test_fallback_prefill_holds_every_settable_parameter(self):
        speed = {"name": "speed", "expression": "5 mm/s", "value": 5.0, "display_value": 5.0, "unit": "mm/s",
                 "comment": "", "is_favorite": True, "kind": "unsupported"}
        params = PARAMS + [speed]
        text = prefill_sizes_text(params)
        self.assertEqual(text, "name,width,angle,wall\nDefault,20,30,2\n")
        self.assertEqual(read_sizes(text, params).problems, [])
        line = others_line(params, ["width", "angle", "wall"])
        self.assertIn("depth (formula", line)
        self.assertIn("speed (unit mm/s not supported)", line)

    def test_formula_and_unsupported_unit_columns_are_refused(self):
        speed = {"name": "speed", "expression": "5 mm/s", "value": 5.0, "display_value": 5.0, "unit": "mm/s",
                 "comment": "", "is_favorite": True, "kind": "unsupported"}
        for text, name in (("name,depth\nA,5", "depth"), ("name,speed\nA,5", "mm/s")):
            with self.subTest(name):
                self.assertIn(name, read_sizes(text, PARAMS + [speed]).problems[0])

    def test_columns_are_needed_only_when_there_are_several_sizes(self):
        self.assertEqual(len(read_sizes("name\nA\nB", PARAMS).problems), 1)
        self.assertEqual(read_sizes("name\nA", PARAMS).problems, [])

    def test_blank_cell_keeps_current_display_value(self):
        read = read_sizes("name,wall\nA,\nB,3", PARAMS)
        self.assertEqual(read.rows[0]["values"], {"wall": 2.0})


class RestoreTest(unittest.TestCase):
    def test_plain_numbers_restore_before_formulas(self):
        self.assertEqual(restore_order(ORIGINAL), ["width", "angle", "wall", "depth"])

    def test_restores_changed_only_and_recomputes(self):
        store = FakeStore(ORIGINAL)
        store.exprs["width"] = "99 mm"
        self.assertEqual(restore_parameters(store, dict(ORIGINAL)), [])
        self.assertEqual(store.exprs, ORIGINAL)
        self.assertEqual(store.recomputes, 1)

    def test_refused_parameter_is_retried_once(self):
        store = FakeStore(ORIGINAL, flaky=["width"])
        store.exprs["width"] = "99 mm"
        self.assertEqual(restore_parameters(store, dict(ORIGINAL)), [])
        self.assertEqual(store.exprs["width"], "20 mm")

    def test_reports_parameters_that_never_restore(self):
        store = FakeStore(ORIGINAL, reject=["20 mm"])
        store.exprs["width"] = "99 mm"
        self.assertEqual(restore_parameters(store, dict(ORIGINAL)), ["width"])


class RunnerRestoreGuaranteeTest(unittest.TestCase):
    def run_job(self, store, export, progress=lambda i, n, name: True, row_list=None):
        job = RowExport(store, UNITS, export)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                return job, job.run(row_list or rows(), tmp, progress), None
            except Exception as exc:
                return job, None, exc

    def test_success_restores_and_exports_each_row(self):
        store = FakeStore(ORIGINAL)
        export = step_writer()
        job, results, error = self.run_job(store, export)
        self.assertIsNone(error)
        self.assertEqual([r["name"] for r in results], ["Small", "Large", "Huge"])
        self.assertEqual(results[1]["values"], {"width": 40.0, "angle": 45.0})
        self.assertEqual(store.exprs, ORIGINAL)
        self.assertEqual(job.restore_failures, [])

    def test_cancel_restores(self):
        store = FakeStore(ORIGINAL)
        job, _, error = self.run_job(store, step_writer(), progress=lambda i, n, name: i < 2)
        self.assertIsInstance(error, ExportCancelled)
        self.assertEqual(store.exprs, ORIGINAL)

    def test_row_that_does_not_build_restores_and_names_the_row(self):
        store = FakeStore(ORIGINAL, bad_when=lambda e: e["width"] == "80 mm")
        job, _, error = self.run_job(store, step_writer())
        self.assertIsInstance(error, RowBuildError)
        self.assertIn("Huge", str(error))
        self.assertEqual(store.exprs, ORIGINAL)

    def test_failed_step_export_restores(self):
        store = FakeStore(ORIGINAL)
        job, _, error = self.run_job(store, step_writer(fail_on=1))
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(store.exprs, ORIGINAL)

    def test_missing_step_file_is_an_error(self):
        store = FakeStore(ORIGINAL)
        job, _, error = self.run_job(store, lambda path: None)
        self.assertIsInstance(error, StepExportError)
        self.assertEqual(store.exprs, ORIGINAL)

    def test_formula_overwritten_by_a_row_is_restored_after_its_inputs(self):
        store = FakeStore(ORIGINAL)
        unit_map = dict(UNITS)
        job = RowExport(store, unit_map, step_writer())
        with tempfile.TemporaryDirectory() as tmp:
            job.run([{"name": "A", "values": {"depth": 5.0}}], tmp, lambda i, n, name: True)
        self.assertEqual(store.exprs["depth"], "width / 2")

    def test_restore_failure_is_reported_not_raised(self):
        store = FakeStore(ORIGINAL, reject=["30 deg"])
        only = [{"name": "A", "values": {"angle": 45.0}}]
        job, results, error = self.run_job(store, step_writer(), row_list=only)
        self.assertIsNone(error)
        self.assertEqual(len(results), 1)
        self.assertEqual(job.restore_failures, ["angle"])


class NamingTest(unittest.TestCase):
    def test_design_title_drops_version(self):
        self.assertEqual(design_title("Cable clip v12"), "Cable clip")
        self.assertEqual(design_title("  "), "Design")

    def test_file_title_names_the_body_component(self):
        self.assertEqual(body_file_title("Aquarium v4", ["Light holder v2", "Light holder v2"]), "Light holder")
        self.assertEqual(body_file_title("Aquarium v4", ["Lid", "Pipe"]), "Aquarium")
        self.assertEqual(body_file_title("Aquarium v4", [None]), "Aquarium")

    def test_file_name_is_safe(self):
        self.assertEqual(package_file_name('a/b:c?'), "a_b_c_.paramability")
        self.assertEqual(package_file_name(""), "design.paramability")

    def test_extension_added_once(self):
        self.assertEqual(with_extension("x"), "x.paramability")
        self.assertEqual(with_extension("x.PARAMABILITY"), "x.PARAMABILITY")

    def test_addin_version_from_manifest_file(self):
        path = os.path.join(context.ADDIN_DIR, "ParamabilityExport.manifest")
        self.assertRegex(addin_version(path), r"^\d+\.\d+\.\d+$")
        self.assertEqual(addin_version("/no/such/file"), "unknown")


class AssembleTest(unittest.TestCase):
    def results(self, tmp, count):
        out = []
        for i in range(count):
            path = os.path.join(tmp, f"{i + 1:02d}.step")
            with open(path, "wb") as f:
                f.write(b"step")
            out.append({"name": f"S{i + 1}", "values": {"width": 20.0 * (i + 1)}, "step_file": path})
        return out

    def test_two_rows_make_a_valid_value_rows_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, files = build_package("Clip", "w", self.results(tmp, 2), ["width"], PARAMS, 1, "Size", "z")
            self.assertEqual(validate_manifest(manifest), [])
            self.assertEqual(manifest["kind"], "valueRows")
            self.assertEqual(manifest["parameters"], [{"name": "width", "unit": "mm", "label": "Clip width"}])
            self.assertTrue(manifest["rows"][1]["default"])
            self.assertEqual(sorted(files), ["rows/01.step", "rows/02.step"])
            out = os.path.join(tmp, "clip.paramability")
            write_package(out, manifest, files)
            with zipfile.ZipFile(out) as zf:
                self.assertEqual(zf.namelist()[0], "manifest.json")
                self.assertEqual(zf.read("rows/02.step"), b"step")

    def test_one_row_makes_step_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, files = build_package("Clip", "w", self.results(tmp, 1), ["width"], PARAMS, 0, "Size", "y")
            self.assertEqual(manifest["kind"], "stepOnly")
            self.assertEqual(manifest["upAxis"], "y")
            self.assertEqual(list(files), ["part.step"])

    def test_rule_breaking_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = self.results(tmp, 2)
            results[1]["name"] = results[0]["name"].lower()
            with self.assertRaises(ValueError):
                build_package("Clip", "w", results, ["width"], PARAMS, 0, "Size", "z")


if __name__ == "__main__":
    unittest.main()
