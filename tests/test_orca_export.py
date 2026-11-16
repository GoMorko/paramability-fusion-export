"""The Orca output of the export pipeline (`ExportRequest.output`): the switch at the translation, the plate mesh
where the Design body appears, the report, the file and the result window."""
import json
import os
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.derived_fixtures import box_capture
from tests.fakes import FakePartsPort, FakePort

from lib.design_edit.errors import StepExportError
from lib.dialog_model.orca_result import LEFT_OUT_END, NEXT_LINES, orca_view, parameter_line
from lib.dialog_model.result_rows import section_lines
from lib.export_plan import health as health_module
from lib.export_plan import recipe_export
from lib.export_plan.orca_export import MESH_TOLERANCE, ORCA, REPORT_ENTRY, plan_orca_export, write_orca_package
from lib.export_plan.pipeline import ExportRequest, run_parts_pipeline, run_pipeline
from lib.geometry import mesh as meshes
from lib.orca_recipe.recipe import deserialize
from lib.orca_recipe.threemf import read_recipe_bytes
from lib.orca_translate import OrcaResult

CAPTURE = box_capture()
USER = CAPTURE["parameters"]["user"]
MODEL = CAPTURE["parameters"]["model"]
TICKED = ["box_count", "cube_mm", "depth_mm", "height_mm", "wall_mm"]
START = {p["name"]: p["expression"] for p in USER}


def request(output=ORCA):
    return ExportRequest(title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL,
                         design_unit="mm", ticked=TICKED, ranges={}, output=output)


def export(port, output=ORCA):
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, request(output), tmp)


class OrcaPipelineTest(unittest.TestCase):
    def test_the_orca_output_reads_a_mesh_translates_once_and_tries_nothing(self):
        port = FakePort(capture=CAPTURE)
        result = export(port)
        self.assertIsNone(result.manifest)
        self.assertIsInstance(result.orca.result, OrcaResult)
        self.assertEqual(port.steps, 1)  # the mesh read, no STEP
        self.assertEqual(port.reads, 0)  # no size tries
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(result.report["outcome"], "orcaRecipe")
        self.assertEqual(result.report["orca"]["variables"]["height_mm"], "32")
        self.assertEqual(result.health["probe"], health_module.NOT_NEEDED)

    def test_the_switch_sits_at_the_translation(self):
        found = recipe_export.translate_capture(CAPTURE, "z", output=ORCA)
        self.assertIsInstance(found, OrcaResult)
        self.assertIsNotNone(recipe_export.translate_capture(CAPTURE, "z").recipe)

    def test_the_plate_mesh_lies_where_the_design_body_is(self):
        result = export(FakePort(capture=CAPTURE))
        self.assertLess(result.report["mesh_check"]["off"], 1e-9)
        box = meshes.bounds(result.orca.objects[0].vertices)
        self.assertEqual(box, {"min": [88.0, 98.0, 0.0], "max": [168.0, 158.0, 32.0]})

    def test_a_mesh_that_does_not_fit_the_part_is_noted(self):
        vertices, triangles = meshes.box_mesh({"min": [0, 0, 0], "max": [8, 6, 3.2]})
        result = export(FakePort(capture=CAPTURE, mesh=(vertices, triangles)))
        self.assertGreater(result.report["mesh_check"]["off"], MESH_TOLERANCE)
        self.assertEqual(len(result.orca.notes), len(export(FakePort(capture=CAPTURE)).orca.notes) + 1)

    def test_a_part_whose_steps_could_not_be_read_keeps_its_shape(self):
        port = FakePort(capture=RuntimeError("no steps"))
        port.mesh = meshes.box_mesh({"min": [0, 0, 0], "max": [10, 10, 10]})
        result = export(port)
        self.assertEqual(result.report["outcome"], "meshOnly")
        self.assertEqual(deserialize(result.orca.recipe_bytes).features, [])
        self.assertEqual(meshes.bounds(result.orca.objects[0].vertices)["min"], [123.0, 123.0, 0.0])

    def test_a_mesh_that_fails_stops_the_export_with_the_parameters_back(self):
        port = FakePort(capture=CAPTURE, fail_step_at=1)
        with self.assertRaises(StepExportError):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_several_bodies_are_refused_for_orca(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_parts_pipeline(FakePartsPort([CAPTURE, CAPTURE]), request(), tmp)

    def test_the_paramability_output_is_unchanged(self):
        result = export(FakePort(capture=CAPTURE), output="paramability")
        self.assertEqual(result.manifest["kind"], "recipe")
        self.assertIsNone(result.orca)


class OrcaFileTest(unittest.TestCase):
    def test_the_file_holds_the_recipe_the_mesh_and_the_report(self):
        result = export(FakePort(capture=CAPTURE))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "box.3mf")
            write_orca_package(path, result.orca)
            recipe = deserialize(read_recipe_bytes(path))
            with zipfile.ZipFile(path) as zf:
                report = json.loads(zf.read(REPORT_ENTRY))
                model = zf.read("3D/3dmodel.model").decode("utf-8")
        self.assertEqual(recipe.variables, result.orca.result.variables)
        self.assertEqual(report["orca"]["features"][0]["expr"], {"width": "box_width_mm", "height": "depth_mm"})
        self.assertIn('orca_published">1', model)

    def test_the_plan_takes_a_translation_made_before(self):
        mesh = meshes.box_mesh(CAPTURE["target"]["box"])
        made = recipe_export.translate_capture(CAPTURE, "z", output=ORCA)
        package = plan_orca_export(CAPTURE, mesh, "Box", "test", "z", translated=made)
        self.assertIs(package.result, made)


class OrcaResultViewTest(unittest.TestCase):
    def view(self):
        result = export(FakePort(capture=CAPTURE))
        return orca_view("box.3mf", result.report, TICKED)

    def test_the_sections_follow_the_result_window_style(self):
        view = self.view()
        self.assertEqual([s["key"] for s in view["sections"]], ["result", "variables", "left_out", "next"])
        self.assertTrue(view["message"].startswith("# Result"))

    def test_each_parameter_and_each_formula_variable_gets_a_line(self):
        result = export(FakePort(capture=CAPTURE))
        lines = section_lines(orca_view("box.3mf", result.report, TICKED), "variables")
        names = [p["name"] for p in result.report["orca"]["parameters"]]
        formulas = [n for n in result.report["orca"]["variables"] if n not in names]
        self.assertEqual([line.split(":")[0] for line in lines[:len(names)]], names)
        self.assertEqual([line.split(" = ")[0] for line in lines[len(names):]], formulas)

    def test_a_long_reason_is_shown_whole(self):
        reason = " and ".join(["a reason that goes on"] * 20)
        line = parameter_line({"name": "wall_mm", "outcome": "fixed", "reasons": [reason]})
        self.assertIn(reason, line)

    def test_the_left_out_steps_and_the_next_steps_are_listed(self):
        report = export(FakePort(capture=CAPTURE)).report
        view = orca_view("box.3mf", report, TICKED)
        lines = section_lines(view, "left_out")
        # One line per step left out, in the report's order, each naming its step, then the closing line.
        names = [g["name"] for g in report["orca"]["left_out"]]
        self.assertEqual(lines[len(names):], [LEFT_OUT_END])
        self.assertTrue(all(name in line for name, line in zip(names, lines)))
        self.assertEqual(section_lines(view, "next")[:4], NEXT_LINES)

    def test_a_shape_only_file_says_so(self):
        port = FakePort(capture=RuntimeError("no steps"))
        port.mesh = meshes.box_mesh({"min": [0, 0, 0], "max": [10, 10, 10]})
        view = orca_view("box.3mf", export(port).report)
        self.assertEqual([s["key"] for s in view["sections"]], ["result", "next"])


if __name__ == "__main__":
    unittest.main()
