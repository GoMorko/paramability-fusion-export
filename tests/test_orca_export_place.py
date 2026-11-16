"""Where the Orca copy and the plate mesh sit when steps are left out (`orca_translate.place.copy_box`,
`export_plan/orca_export.py`), and the report written beside the `.3mf`."""
import json
import os
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.orca_sized import fixture

from lib.export_plan.orca_export import (OWN_BOX_NOTE, REPORT_ENTRY, plan_orca_export, report_path,
                                        write_orca_package)
from lib.geometry import mesh as meshes
from lib.orca_translate import translate

# A step Orca does not copy, which in Fusion takes the part 0.25 mm lower and 1 mm wider.
FUSION_BOX = {"min": [0.0, 0.0, -0.25], "max": [41.0, 20.0, 10.0]}


def left_out_plate():
    capture = fixture("extrude_plate")
    capture["items"].append({"index": 2, "name": "Scale1", "type": "ScaleFeature", "suppressed": False,
                             "health": "ok", "in_target_component": True,
                             "bodies_after": [{"token": "t1", "name": "Body1"}], "data": {}})
    capture["target"]["box"] = FUSION_BOX
    return capture


def package(capture):
    # The mesh is the Fusion body: a box of the Fusion part's size, in root coordinates.
    return plan_orca_export(capture, meshes.box_mesh(capture["target"]["box"]), "Plate", "test", "z")


class PlaceByTheCopyTest(unittest.TestCase):
    def test_a_copy_without_a_step_is_placed_on_the_bed_by_its_own_box(self):
        result = translate(left_out_plate())
        self.assertEqual(result.copy_box, {"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 10.0]})
        self.assertEqual(result.place.shift, (108.0, 118.0, 0.0))

    def test_a_whole_copy_is_placed_by_the_fusion_box(self):
        capture = fixture("extrude_plate")
        capture["target"]["box"] = FUSION_BOX
        result = translate(capture)
        self.assertIsNone(result.copy_box)
        self.assertEqual(result.place.shift, (107.5, 118.0, 0.25))

    def test_the_mesh_keeps_the_copy_move_across_the_bed_and_rests_on_the_bed(self):
        made = package(left_out_plate())
        box = meshes.bounds(made.objects[0].vertices)
        self.assertEqual(box, {"min": [108.0, 118.0, 0.0], "max": [149.0, 138.0, 10.25]})
        placement = made.report["placement"]
        self.assertEqual((placement["by"], placement["mesh_lift"], placement["off"]), ("copy", 0.25, 1.0))
        self.assertEqual(placement["copy_box"], {"min": [108.0, 118.0, 0.0], "max": [148.0, 138.0, 10.0]})
        self.assertLess(made.report["mesh_check"]["off"], 1e-9)
        self.assertTrue(any(n.startswith(OWN_BOX_NOTE.split("(")[0]) for n in made.notes))

    def test_a_whole_copy_and_its_mesh_take_the_same_move(self):
        made = package(fixture("extrude_plate"))
        self.assertEqual(made.report["placement"], {"by": "part", "mesh_lift": 0.0})
        self.assertEqual(meshes.bounds(made.objects[0].vertices), {"min": [108.0, 118.0, 0.0],
                                                                    "max": [148.0, 138.0, 10.0]})


class ReportBesideTest(unittest.TestCase):
    def test_the_report_is_written_inside_the_file_and_beside_it(self):
        made = package(fixture("extrude_plate"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Plate.3mf")
            write_orca_package(path, made)
            self.assertEqual(sorted(os.listdir(tmp)), ["Plate.3mf", "Plate.report.json"])
            with zipfile.ZipFile(path) as zf:
                inside = zf.read(REPORT_ENTRY)
            with open(os.path.join(tmp, "Plate.report.json"), "rb") as f:
                beside = f.read()
        self.assertEqual(inside, beside)
        self.assertEqual(json.loads(beside)["title"], "Plate")

    def test_the_report_name_follows_the_file_name(self):
        self.assertEqual(report_path("/a/b/Part.3MF"), "/a/b/Part.report.json")
        self.assertEqual(report_path("/a/b/Part"), "/a/b/Part.report.json")


if __name__ == "__main__":
    unittest.main()
