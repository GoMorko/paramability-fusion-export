"""Sketch values that follow sizes through the probe's motion file (lib/translator/sketch_motion.py)."""
import copy
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.translator_helpers import FIXTURES, assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.sketch_values.motion import OPTIMISTIC, Motion
from lib.translator import translate
from lib.translator.sizes import untried_reasons

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
    """Why each size that stays free with a warning may give unexpected results, by Fusion name."""
    return {f["name"]: f["reason"] for f in result.loose}


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

    def test_without_a_motion_file_no_size_behind_a_sketch_is_a_size(self):
        result = run(load_capture(BOX), BOX_SIZES, None)
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual(sorted(result.recipe["sizes"]), ["height_mm", "pipe_d_mm", "wall_mm"])
        dropped = {d["name"]: d for d in result.dropped}
        self.assertEqual(sorted(dropped), ["box_count", "cube_mm", "depth_mm", "pipe_offset_mm"])
        for name, entry in dropped.items():
            self.assertTrue(entry["used"], name)
            self.assertIn("could not be tried", entry["reason"])
            self.assertNotIn("not used by any copied step", entry["reason"])
            self.assertIn(entry["reason"], result.notes)

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
        self.assertEqual(list(untried_reasons(table)), ["depth_mm"])

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

    def test_a_line_between_merged_profiles_that_moves_along_a_curve_does_not_hold_the_outline(self):
        capture = load_capture(BOX)
        whole = capture["items"][1]["data"]["profiles"][0]
        halves = []
        for n, (x0, x1) in enumerate(((-40, 0), (0, 40))):
            corners = [[x0, -30], [x1, -30], [x1, 30], [x0, 30]]
            curves = [{"kind": "line", "start": corners[k], "end": corners[(k + 1) % 4],
                       "entity": "mid" if corners[k][0] == corners[(k + 1) % 4][0] == 0 else "h%d%d" % (n, k)}
                      for k in range(4)]
            halves.append(dict(whole, loops=[{"outer": True, "curves": curves}]))
        capture["items"][1]["data"]["profiles"] = halves

        def edit(values):
            # Only the shared line moves, along a curve of the cube size; the outer lines stay where they are.
            for key in [k for k in values if k.startswith("1/")]:
                del values[key]
            stuck = {"stuck": ["cube_mm"], "cause": "curve", "sketch": whole["sketch"]}
            for n in (0, 1):
                values["1/p%d/l0/center.0" % n] = stuck
                values["1/p%d/l0/width" % n] = stuck

        motion = motion_of(BOX, edit)
        motion.curves = {"1/p0", "1/p1"}
        result = run(capture, BOX_SIZES, motion)
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual({tuple(p) for p in outer["points"]}, {(-40.0, -30.0), (0.0, -30.0), (40.0, -30.0),
                                                                (40.0, 30.0), (0.0, 30.0), (-40.0, 30.0)})
        self.assertNotIn("cube_mm", reasons(result))


class StuckTest(unittest.TestCase):
    def test_a_stuck_value_marks_the_sizes_that_move_it_with_the_probe_cause(self):
        def edit(values):
            values["1/p0/l0/width"] = {"stuck": ["box_count", "cube_mm"], "cause": "curve", "sketch": "Sketch1"}

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertIn("Sketch1 along a curve", reasons(result)["cube_mm"])
        outer = steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]
        self.assertEqual((outer["width"], expr(outer["height"])), (80.0, "depth_mm"))
        self.assertIn("cube_mm", result.recipe["sizes"])
        self.assertEqual(expr(steps_of(result.recipe, "hole")[0]["origin"][0]), "-0.5 * box_width_mm + pipe_offset_mm")

    def test_a_stuck_value_follows_the_other_sizes_once_its_own_are_marked(self):
        def edit(values):
            values["1/p0/l0/width"] = {"stuck": ["pipe_offset_mm"], "cause": "shape", "sketch": "Sketch1",
                                       "rest": values["1/p0/l0/width"]}

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertEqual(sorted(reasons(result)), ["pipe_offset_mm"])
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["width"]), "box_width_mm")

    def test_an_outline_that_would_shrink_to_nothing_marks_its_sizes(self):
        def edit(values):
            values["1/p0/l0/height"] = {"const": 120, "terms": {"depth_mm": -1}, "sketch": "Sketch1"}

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertIn("outline in Sketch1 would shrink to nothing", reasons(result)["depth_mm"])

    def test_a_formula_that_misses_the_captured_number_is_not_written(self):
        def edit(values):
            values["5/positions/0/0"]["const"] = 7

        result = run(load_capture(BOX), BOX_SIZES, motion_of(BOX, edit))
        self.assertIn("could not be read at other values", reasons(result)["cube_mm"])
        self.assertNotIn("pipe_offset_mm", result.recipe["sizes"])
        self.assertEqual(steps_of(result.recipe, "hole")[0]["origin"][0], -20.0)


class JointTest(unittest.TestCase):
    def test_a_size_that_moves_a_joint_stays_free_with_the_reason(self):
        capture = load_capture(BOX)
        model = capture["parameters"]["model"]
        depth = next(m for m in model if "depth_mm" in m.get("expression", ""))
        model.append(dict(depth, name="joint_offset", created_by={"kind": "joint"}))
        result = run(capture, BOX_SIZES, motion_of(BOX))
        self.assertEqual(list(reasons(result)), ["depth_mm"])
        self.assertIn("joint", reasons(result)["depth_mm"])
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["height"]), "depth_mm")


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

    def test_a_step_that_reaches_to_the_construction_plane_follows_its_distance(self):
        result = run(load_capture(LIFTED), ["lift_mm", "plate_mm"], motion_of(LIFTED))
        self.assertEqual(reasons(result), {})
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"][2]), "lift_mm")
        self.assertEqual(expr(steps_of(result.recipe, "extrude")[2]["distance"]), "lift_mm")

    def test_a_construction_plane_record_without_a_token_marks_every_plane_size(self):
        capture = load_capture(LIFTED)
        del capture["items"][-1]["data"]["side_one"]["token"]
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][1], name="d21",
                                                   expression="plate_mm", dependency_parameters=["plate_mm"],
                                                   created_by=dict(capture["parameters"]["model"][1]["created_by"],
                                                                   token="cp9")))
        result = run(capture, ["lift_mm", "plate_mm"], motion_of(LIFTED))
        self.assertEqual(sorted(reasons(result)), ["lift_mm", "plate_mm"])
        self.assertIn("construction plane that Extrude3 uses", reasons(result)["plate_mm"])


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


def depth_drives_sketch_and_extrude():
    """The centred box whose extrude length is `depth_mm - 28 mm`, so depth_mm moves both Sketch1 and the extrude."""
    capture = load_capture(BOX)
    extrude = next(i for i in capture["items"] if i["type"] == "ExtrudeFeature")["data"]
    extrude["params"]["side_one.distance"]["expression"] = "depth_mm - 28 mm"
    for param in capture["parameters"]["model"]:
        if param["name"] == "d3":
            param.update(expression="depth_mm - 28 mm", dependency_parameters=["depth_mm"])
    return capture


def unmeasured(*sketches, drop=()):
    """The box motion where the probe did not measure `sketches` (it has no values for the keys in `drop`)."""
    with open(os.path.join(MOTION, BOX + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    for key in [k for k in data["values"] if k.startswith(tuple(drop))]:
        del data["values"][key]
    data["unmeasured"] = {name: "its first read did not match the capture" for name in sketches}
    return Motion.from_json(data)


class UnmeasuredSketchTest(unittest.TestCase):
    """A sketch the probe skipped says nothing about its sizes: they are loose, never silently free."""

    def test_sizes_behind_a_skipped_sketch_stay_free_with_a_warning(self):
        capture = depth_drives_sketch_and_extrude()
        params = capture["parameters"]
        table = size_table.build(params["user"], BOX_SIZES, params["model"], capture.get("design_units", "mm"))
        result = translate(capture, size_table=table, motion=unmeasured("Sketch1", drop=("1/",)))
        self.assertEqual(sorted(f["name"] for f in result.loose), ["box_count", "cube_mm", "depth_mm"])
        self.assertEqual(result.fixed, [])
        self.assertIn("depth_mm", result.recipe["sizes"])
        self.assertIn("could not be tried at other values", reasons(result)["depth_mm"])
        self.assertIn("Sketch1", reasons(result)["depth_mm"])

    def test_a_skipped_hole_sketch_writes_its_points_as_numbers_and_leaves_its_size_out(self):
        result = run(load_capture(BOX), BOX_SIZES, unmeasured("Sketch2", drop=("5/",)))
        self.assertEqual(reasons(result), {})
        self.assertNotIn("pipe_offset_mm", result.recipe["sizes"])
        self.assertEqual(steps_of(result.recipe, "hole")[0]["origin"][0], -20.0)

    def test_a_measured_sketch_that_did_not_move_leaves_a_size_free(self):
        result = run(depth_drives_sketch_and_extrude(), BOX_SIZES, unmeasured(drop=("1/p0/l0/height",)))
        self.assertNotIn("depth_mm", reasons(result))

    def test_a_motion_file_without_coverage_data_reads_as_measured(self):
        motion = motion_of(BOX, lambda values: [values.pop(k) for k in [k for k in values if k.startswith("1/")]])
        self.assertEqual(motion.unmeasured, {})
        self.assertNotIn("depth_mm", reasons(run(depth_drives_sketch_and_extrude(), BOX_SIZES, motion)))


class OwnerFilterBoxTest(unittest.TestCase):
    """The owner's FilterBox package (outside the repo, 0.4.0 capture) with a motion file written by hand
    (filter_box_motion.py): supports cross the walls, and pipe circles cross each other. The motion has no values for
    the lid steps drawn on BoxLid's sketches, so they are copied as numbers."""

    PACKAGE = os.path.expanduser("~/Documents/free-projects/3mf-compose/tmp/reports/"
                                 "Pat -22 Pipe, Filter (Box, Cylinder).paramability")
    TICKED = ["FilterBox_$_width__contains_CeramicMedium", "FilterBox_$_height__contains_CeramicMedium",
              "FilterBox_$_depth__contains_CeramicMedium", "_CeramicMedium__Cube_width_unitless",
              "_Filter__Wall_thickness_mm", "FilterBox__PipeTop_offsetFromCenter_mm"]

    def test_box_sizes_stay_free_unless_the_lid_steps_copied_as_numbers_would_come_off_the_box(self):
        if not os.path.exists(self.PACKAGE):
            self.skipTest("the owner's package is not on this machine")
        from tests.filter_box_motion import filter_box_motion
        with zipfile.ZipFile(self.PACKAGE) as package:
            capture = json.loads(package.read("report.json"))["capture"]
        result = run(copy.deepcopy(capture), self.TICKED, filter_box_motion(capture))
        self.assertIsNone(result.refusal)
        # The lid steps lie on the box walls, which move with the sizes: each size they read is marked, with the value
        # past which they may come off. The ranges stay as the table gives them.
        self.assertEqual(result.fixed, [])
        reasons = {f["name"]: f["reason"] for f in result.loose}
        self.assertEqual(sorted(reasons), sorted([self.TICKED[0], self.TICKED[2], self.TICKED[3], self.TICKED[4]]))
        self.assertIn("may give unexpected results past 1.8:", reasons[self.TICKED[0]])
        self.assertIn("LidAndRail of BoxLid", reasons[self.TICKED[2]])
        sizes = result.recipe["sizes"]
        width = sizes["FilterBox___width__contains_CeramicMedium"]
        self.assertEqual((width["min"], width["max"]), (0.9, 3.6))
        support = steps_of(result.recipe, "extrude")[1]["sketch"]["outer"]
        self.assertEqual((support["kind"], expr(support["center"][0])),
                         ("circle", "-0.5 * FilterBox_width_mm + 0.5 * _Filter__Wall_thickness_mm"))


if __name__ == "__main__":
    unittest.main()
