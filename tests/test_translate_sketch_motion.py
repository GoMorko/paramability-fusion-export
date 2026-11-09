"""Sketch values that follow sizes through the probe's motion file (lib/translator/sketch_motion.py)."""
import copy
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.probe.motion import OPTIMISTIC, Motion
from lib.translator import translate
from lib.translator.sizes import fallback_fixes

MOTION = os.path.join(os.path.dirname(FIXTURES), "motion")
BOX = "sketch_rect_centred"
BOX_SIZES = ["box_count", "cube_mm", "depth_mm", "height_mm", "wall_mm", "pipe_offset_mm", "pipe_d_mm"]
LIFTED = "sketch_offset_plane"


def motion_of(name, edit=None):
    with open(os.path.join(MOTION, name + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    if edit:
        edit(data["values"])
    return Motion.from_json(data)


def run(capture, ticked, motion):
    params = capture["parameters"]
    table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
    return translate(capture, size_table=table, motion=motion)


def reasons(result):
    return {f["name"]: f["reason"] for f in result.fixed}


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


class OutlineTest(unittest.TestCase):
    def test_outline_hole_and_corner_pick_follow_the_box_sizes(self):
        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX))
        self.assertEqual(result.fixed, [])
        assert_schema_ok(self, result.recipe)
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual((expr(outer["width"]), expr(outer["height"])), ("box_width_mm", "depth_mm"))
        corner = steps_of(result.recipe, "round")[0]["edges"]["near"][0]
        self.assertEqual([expr(c) for c in corner], ["0.5 * box_width_mm", "0.5 * depth_mm", "0.5 * height_mm"])
        self.assertEqual(expr(steps_of(result.recipe, "hole")[0]["origin"][0]), "-0.5 * box_width_mm + pipe_offset_mm")
        self.assertEqual(steps_of(result.recipe, "shell")[0]["openFaces"], {"featureFace": "extrude_1", "which": "end"})

    def test_without_a_motion_file_every_size_behind_a_sketch_is_fixed(self):
        result = run(load_capture(BOX), BOX_SIZES, None)
        self.assertEqual(sorted(reasons(result)), ["box_count", "cube_mm", "depth_mm", "pipe_offset_mm"])
        self.assertIn("could not be tried at other values", reasons(result)["depth_mm"])

    def test_the_first_translation_writes_numbers_and_fixes_nothing_for_sketches(self):
        result = run(load_capture(BOX), BOX_SIZES, OPTIMISTIC)
        self.assertEqual(result.fixed, [])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["width"], 80.0)

    def test_a_sketch_dimension_known_by_its_role_is_fixed_without_a_motion_file(self):
        capture = load_capture(BOX)
        capture["parameters"]["model"][1]["created_by"]["kind"] = "other"
        capture["parameters"]["model"][1]["role"] = "Linear Dimension-3"
        params = capture["parameters"]
        table = size_table.build(params["user"], ["depth_mm", "height_mm"], params["model"])
        self.assertEqual(list(fallback_fixes(table)), ["depth_mm"])

    def test_touching_profiles_take_the_merged_outline_from_their_parts(self):
        capture = load_capture(BOX)
        whole = capture["items"][1]["data"]["profiles"][0]
        halves = []
        for n, (x0, x1) in enumerate(((-40, 0), (0, 40))):
            corners = [[x0, -30], [x1, -30], [x1, 30], [x0, 30]]
            curves = [{"kind": "line", "start": corners[k], "end": corners[(k + 1) % 4], "entity": "h%d%d" % (n, k)}
                      for k in range(4)]
            halves.append(dict(whole, loops=[{"outer": True, "curves": curves}]))
        capture["items"][1]["data"]["profiles"] = halves

        def edit(values):
            del values["1/p0/l0/width"], values["1/p0/l0/height"]
            for n, sign in ((0, -0.25), (1, 0.25)):
                values["1/p%d/l0/center.0" % n] = {"const": 0, "terms": {"box_width_mm": sign}}
                values["1/p%d/l0/width" % n] = {"const": 0, "terms": {"box_width_mm": 0.5}}
                values["1/p%d/l0/height" % n] = {"const": 0, "terms": {"depth_mm": 1}}

        result = run(capture, BOX_SIZES, motion_of(BOX, edit))
        extrudes = steps_of(result.recipe, "extrude")
        self.assertEqual(len(extrudes), 1)
        corners = [[expr(c) for c in p] for p in extrudes[0]["sketch"]["outer"]["points"]]
        self.assertEqual(corners[2:4], [["0.5 * box_width_mm", "-0.5 * depth_mm"], ["0.5 * box_width_mm", "0.5 * depth_mm"]])
        self.assertEqual(corners[1], [0.0, "-0.5 * depth_mm"])


class StuckTest(unittest.TestCase):
    def test_a_stuck_value_fixes_every_size_that_moves_it_with_the_probe_cause(self):
        def edit(values):
            values["1/p0/l0/width"] = {"stuck": ["box_count", "cube_mm"], "cause": "curve", "sketch": "Sketch1"}

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertEqual(reasons(result)["cube_mm"],
                         "cube_mm stays fixed: it moves Sketch1 along a curve, which cannot be copied yet.")
        self.assertIn("box_count", reasons(result))
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual((outer["width"], expr(outer["height"])), (80.0, "depth_mm"))

    def test_an_outline_that_would_shrink_to_nothing_fixes_its_sizes(self):
        def edit(values):
            values["1/p0/l0/height"] = {"const": 120, "terms": {"depth_mm": -1}, "sketch": "Sketch1"}

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertEqual(reasons(result)["depth_mm"], "depth_mm stays fixed: an outline in Sketch1 would shrink to nothing.")

    def test_a_formula_that_misses_the_captured_number_is_not_written(self):
        def edit(values):
            values["5/positions/0/0"]["const"] = 7

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertIn("could not be read at other values", reasons(result)["pipe_offset_mm"])
        self.assertEqual(steps_of(result.recipe, "hole")[0]["origin"][0], -20.0)


class PlaneTest(unittest.TestCase):
    def test_a_sketch_on_a_lifted_plane_moves_with_it_and_flips_its_formulas(self):
        capture = load_capture(LIFTED)
        capture["items"].pop()

        def edit(values):
            values["4/p0/l0/center.1"] = {"const": 0, "terms": {"plate_mm": 1}}

        result = run(capture, ["lift_mm", "plate_mm"], motion_of(LIFTED, edit))
        self.assertEqual(result.fixed, [])
        pocket = steps_of(result.recipe, "extrude")[1]["sketch"]
        self.assertEqual(expr(pocket["on"]["origin"][2]), "lift_mm")
        self.assertEqual(expr(pocket["outer"]["center"][1]), "-plate_mm")

    def test_a_step_that_reaches_to_the_construction_plane_fixes_its_sizes(self):
        result = run(load_capture(LIFTED), ["lift_mm", "plate_mm"], motion_of(LIFTED))
        self.assertEqual(reasons(result), {"lift_mm": "lift_mm stays fixed: it moves the construction plane that "
                                                      "Extrude3 uses."})
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"][2], 8.0)


class RevolveAxisTest(unittest.TestCase):
    def test_an_axis_from_a_sketch_line_follows_its_size(self):
        capture = load_capture("revolve_quarter")
        capture["capture"] = 3
        capture["parameters"] = {"user": [{"name": "gap_mm", "expression": "5 mm", "value": 0.5, "unit": "mm",
                                           "kind": "length", "value_type": "numeric", "is_favorite": True,
                                           "dependency_parameters": []}], "model": []}
        capture["items"][1]["data"]["axis"].update(entity="l1", sketch_token="s1", sketch="Sketch1")
        motion = Motion.from_json({"values": {"1/axis/point/0": {"const": -5, "terms": {"gap_mm": 1}}}})
        result = run(capture, ["gap_mm"], motion)
        self.assertEqual(expr(steps_of(result.recipe, "revolve")[0]["axis"]["point"][0]), "gap_mm - 5")


class OwnerFilterBoxTest(unittest.TestCase):
    """The owner's FilterBox package (outside the repo) with a motion file written by hand (filter_box_motion.py)."""

    PACKAGE = os.path.expanduser("~/Documents/free-projects/3mf-compose/tmp/reports/"
                                 "Pat - Pipe, Filter (Box, Cylinder).paramability")
    TICKED = ["FilterBox_$_width__contains_CeramicMedium", "FilterBox_$_height__contains_CeramicMedium",
              "FilterBox_$_depth__contains_CeramicMedium", "_CeramicMedium__Cube_width_unitless",
              "_Filter__Wall_thickness_mm", "FilterBox__PipeTop_offsetFromCenter_mm"]

    def test_the_box_sizes_the_sketches_read_become_free(self):
        if not os.path.exists(self.PACKAGE):
            self.skipTest("the owner's package is not on this machine")
        from tests.filter_box_motion import filter_box_motion
        with zipfile.ZipFile(self.PACKAGE) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        capture["items"] = [i for i in capture["items"] if i["index"] < 92]  # the steps before OffsetFaces3
        result = run(copy.deepcopy(capture), self.TICKED, filter_box_motion(capture))
        self.assertIsNone(result.refusal)
        free = [name for name, size in result.recipe["sizes"].items() if "value" in size]
        self.assertEqual(sorted(free), sorted(["FilterBox___height__contains_CeramicMedium",
                                               "_CeramicMedium__Cube_width_unitless", "_Filter__Wall_thickness_mm",
                                               "FilterBox__PipeTop_offsetFromCenter_mm"]))
        self.assertTrue(all("picks a copy made by" in f["reason"] for f in result.fixed))


if __name__ == "__main__":
    unittest.main()
