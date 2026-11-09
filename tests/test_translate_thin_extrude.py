"""Thin extrudes: a wall along one closed outline is copied with the side the measured end face shows; every case
the recipe's thin wall cannot hold is refused."""
import math
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.params import size_table
from lib.translator import meets_part, translate
from lib.translator.placer import ADD
from lib.translator.thin_wall import ThinWall
from lib.translator.values import Quantity

BOX = "thin_wall_box"
EXTRUDE = 1
# The 40 x 30 outline has a perimeter of 140 mm. A 2 mm wall: inside 264 mm2; outside 280 + 4 pi (round corners) or
# 296 (sharp corners); centered 280 + pi - 4 (round) or 280 (sharp).
INSIDE, OUTSIDE_ROUND, OUTSIDE_SHARP = 264.0, 280.0 + 4.0 * math.pi, 296.0
CENTRE_SHARP = 280.0


def data_of(capture):
    return capture["items"][EXTRUDE]["data"]


def with_edit(edit, name=BOX):
    capture = load_capture(name)
    edit(data_of(capture))
    return translate(capture)


def wall(location, end_area):
    def edit(data):
        data["thin_wall"]["location"] = location
        data["end_area"] = end_area
    return edit


def reason_of(result):
    assert result.recipe is None, "the thin extrude was copied"
    assert result.refusal["index"] == EXTRUDE
    return result.refusal["reason"]


def only_step(result):
    (step,) = steps_of(result.recipe, "extrude")
    return step


class ThinWallCopyTest(unittest.TestCase):
    def test_a_wall_on_the_inside_is_written_with_its_thickness_and_side(self):
        result = translate(load_capture(BOX))
        self.assertEqual(result.refusal, None)
        step = only_step(result)
        self.assertEqual((step["thin"], step["extent"], step["distance"]), ({"thickness": 2.0, "side": "inside"},
                                                                            "oneSide", 10.0))
        self.assertEqual(step["sketch"]["outer"]["kind"], "rect")
        assert_schema_ok(self, result.recipe)

    def test_the_side_follows_the_measured_end_face_whatever_side_one_or_two_says(self):
        for location in ("side1", "side2"):
            for area, side in ((INSIDE, "inside"), (OUTSIDE_ROUND, "outside"), (OUTSIDE_SHARP, "outside")):
                with self.subTest(location=location, area=area):
                    self.assertEqual(only_step(with_edit(wall(location, area))).get("thin", {}).get("side"), side)

    def test_a_centered_wall_is_the_middle(self):
        result = with_edit(wall("center", CENTRE_SHARP))
        self.assertEqual(only_step(result)["thin"]["side"], "middle")
        assert_schema_ok(self, result.recipe)

    def test_a_wall_whose_corners_are_sharp_in_fusion_is_copied_with_a_note(self):
        def note_of(result):
            return next(v["note"] for v in result.items if v["index"] == EXTRUDE)

        self.assertTrue(note_of(with_edit(wall("side2", OUTSIDE_SHARP))))
        self.assertFalse(note_of(with_edit(wall("side2", OUTSIDE_ROUND))))

    def test_a_round_outline_has_no_corners_to_round(self):
        def circle(data):
            data["profiles"][0]["loops"][0]["curves"] = [
                {"kind": "circle", "center": [20.0, 15.0], "radius": 10.0}]
            data["end_area"] = math.pi * (100.0 - 64.0)
        result = with_edit(circle)
        self.assertEqual(only_step(result)["thin"]["side"], "inside")
        self.assertEqual([v["note"] for v in result.items if v["index"] == EXTRUDE], [""])

    def test_a_symmetric_thin_extrude_is_copied(self):
        def symmetric(data):
            data.update(extent_type="symmetric", side_one=None, end_offset=5.0,
                        symmetric={"distance": 10.0, "full_length": True, "taper_deg": 0.0})
            data["params"] = {"thin.thickness": data["params"]["thin.thickness"]}
        step = only_step(with_edit(symmetric))
        self.assertEqual((step["extent"], step["distance"], step["thin"]["side"]), ("symmetric", 10.0, "inside"))


class ThinWallRefusalTest(unittest.TestCase):
    def test_refusals(self):
        def two_ways(data):
            data.update(extent_type="two", side_two=dict(data["side_one"]))

        def tapered(data):
            data["side_one"]["taper_deg"] = 5.0

        def through(data):
            data["side_one"] = {"kind": "all"}

        def open_line(data):
            data["profiles"] = [{"kind": "other", "type": "SketchLine"}]

        def holes(data):
            data["profiles"][0]["loops"].append({"outer": False, "curves": [
                {"kind": "circle", "center": [20.0, 15.0], "radius": 3.0}]})

        def two_outlines(data):
            data["profiles"].append(dict(data["profiles"][0]))

        def unknown_side(data):
            data["thin_wall"]["location"] = "other"

        cases = {"two sided": two_ways, "taper": tapered, "through": through, "open line": open_line,
                 "hole": holes, "two outlines": two_outlines, "unknown location": unknown_side}
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertTrue(reason_of(with_edit(edit)))

    def test_a_setting_that_could_not_be_read_refuses(self):
        for name, edit in {"location": wall(None, INSIDE),
                           "thickness": lambda d: d["thin_wall"].update(thickness=None),
                           "wall record": lambda d: d.update(thin_wall=None),
                           "taper": lambda d: d["side_one"].update(taper_deg=None)}.items():
            with self.subTest(name):
                self.assertTrue(reason_of(with_edit(edit)))

    def test_an_end_face_that_fits_no_wall_refuses(self):
        for area in (None, 0.0, 300.0, 150.0):
            with self.subTest(end_area=area):
                self.assertTrue(reason_of(with_edit(wall("side1", area))))

    def test_a_centered_wall_that_measures_as_one_sided_refuses(self):
        self.assertTrue(reason_of(with_edit(wall("center", INSIDE))))

    def test_a_wall_too_thin_to_tell_inside_from_outside_refuses(self):
        def thin(data):
            data["thin_wall"]["thickness"] = 0.02
            data["end_area"] = 2.8
        self.assertTrue(reason_of(with_edit(thin)))

    def test_an_outline_that_is_not_closed_lines_and_arcs_refuses(self):
        def spline(data):
            data["profiles"][0]["loops"][0]["curves"] = [{"kind": "other"}]
        self.assertTrue(reason_of(with_edit(spline)))


def sized(capture, ticked=("wall_mm", "height_mm"), ranges=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], list(ticked), params["model"], "mm", ranges=ranges)
    return translate(capture, size_table=table)


class ThinWallSizesTest(unittest.TestCase):
    def test_the_wall_thickness_is_a_size_the_recipe_reads(self):
        result = sized(load_capture(BOX))
        self.assertEqual(only_step(result)["thin"], {"thickness": {"expr": "wall_mm"}, "side": "inside"})
        self.assertIn("wall_mm", result.recipe["sizes"])
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))

    def test_a_wall_that_can_reach_zero_is_not_a_size(self):
        result = sized(load_capture(BOX), ranges={"wall_mm": (0.0, 5.0)})
        self.assertEqual(only_step(result)["thin"]["thickness"], 2.0)
        self.assertEqual([d["name"] for d in result.dropped], ["wall_mm"])

    def test_a_wall_driven_by_another_size_stays_a_formula(self):
        capture = load_capture(BOX)
        capture["parameters"]["model"][1].update(expression="height_mm / 5", dependency_parameters=["height_mm"])
        data_of(capture)["params"]["thin.thickness"]["expression"] = "height_mm / 5"
        step = only_step(sized(capture))
        self.assertEqual(step["thin"]["thickness"], {"expr": "height_mm / 5"})


class ThinWallPlacerTest(unittest.TestCase):
    def wall_at(self, side, combine="new"):
        capture = load_capture(BOX)
        profile = data_of(capture)["profiles"][0]
        on = {"origin": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0], "xDir": [1.0, 0.0, 0.0]}
        return ThinWall("e", on, "oneSide", Quantity(10.0), profile, side, 2.0, combine)

    def test_material_is_only_in_the_wall(self):
        wall_inside = self.wall_at("inside")
        self.assertEqual(wall_inside.material_at([1.0, 15.0, 5.0]), ADD)
        self.assertIsNone(wall_inside.material_at([20.0, 15.0, 5.0]))
        self.assertIsNone(wall_inside.material_at([-1.0, 15.0, 5.0]))
        self.assertIsNone(wall_inside.material_at([1.0, 15.0, 11.0]))
        self.assertEqual(self.wall_at("outside").material_at([-1.0, 15.0, 5.0]), ADD)

    def test_its_faces_are_not_placed(self):
        self.assertIsNone(self.wall_at("inside").place([0.0, 15.0, 5.0], False))

    def test_a_step_on_another_parts_sketch_cannot_check_that_it_meets_the_wall(self):
        marks = []
        ctx = SimpleNamespace(table=object(), motion=SimpleNamespace(), placers=[self.wall_at("inside")], slabs=[],
                              written_reads=("wall_mm",), doubt=lambda names, why: marks.append(tuple(names)))
        meets_part.check(ctx, "rail", None, "add", "Rail")
        self.assertEqual(marks, [("wall_mm",)])


if __name__ == "__main__":
    unittest.main()
