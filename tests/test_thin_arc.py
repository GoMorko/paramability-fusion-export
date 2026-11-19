"""Thin extrudes along a line with arcs, in both exports: the wall is copied as the closed outline of its band (lines
and arcs, with numbers) when the faces Fusion made show one side and the part grew by the band's exact area times
the length; a corner next to an arc, a volume that differs and an arc whose moved radius reaches zero are left
out."""
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_thin_arcs as arcs
from tests.test_translate_sketch_motion import motion_of, run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of
from scripts.orca_live_check import table_for

from lib.capture_model import gap_hints
from lib.design_model.loops import loop_of
from lib.design_model.steps import thin as facts
from lib.design_model.steps import thin_arc
from lib.orca_recipe.enums import EntityType, FeatureType
from lib.orca_translate import VARIABLE
from lib.orca_translate import translate as orca_translate
from lib.translator import translate

TIP = gap_hints.HINTS[gap_hints.THIN_OUTLINE]
SIDES = (("side1", "inside"), ("side2", "outside"), ("center", "middle"))
# Right turn: line (0, 0) to (30, 0), a quarter arc of radius 10 about (30, -10) down to (40, -10), line to (40, -30).
RIGHT = [arcs.line((0.0, 0.0), (30.0, 0.0)), arcs.arc((30.0, -10.0), 10.0, 90.0, 0.0),
         arcs.line((40.0, -10.0), (40.0, -30.0))]


def data_of(capture):
    return capture["items"][-1]["data"]


def only_step(result):
    assert result.recipe is not None, result.refusal
    (step,) = steps_of(result.recipe, "extrude")
    return step


def orca(capture):
    return orca_translate(capture, table_for(capture))


def band_loop(pieces, side):
    return loop_of(thin_arc.band_curves(pieces, *facts.reaches(side, arcs.THICKNESS)))


def kinked():
    """The L with its last line turned 20 degrees off the end of the arc: a corner next to an arc. Its faces and
    volume are those of its own band, so only the joint is wrong."""
    turn = math.radians(20.0)
    end = [40.0 - 20.0 * math.sin(turn), 10.0 + 20.0 * math.cos(turn)]
    pieces = arcs.ELL[:2] + [arcs.line((40.0, 10.0), end)]
    return arcs.wall(pieces, "side1"), pieces


class BandTest(unittest.TestCase):
    def test_the_band_area_is_the_exact_area_of_lines_and_arc_sectors(self):
        for pieces, side, area in ((arcs.ELL, "inside", 100 + 9 * math.pi), (arcs.ELL, "outside", 100 + 11 * math.pi),
                                   (arcs.ELL, "middle", 100 + 10 * math.pi), (arcs.U, "middle", 120 + 20 * math.pi),
                                   (RIGHT, "inside", 100 + 11 * math.pi)):
            with self.subTest(side=side, area=area):
                curves = thin_arc.band_curves(pieces, *facts.reaches(side, 2.0))
                self.assertAlmostEqual(thin_arc.band_area(curves), area, places=9)

    def test_shapes_the_band_cannot_hold_are_problems_with_their_own_code(self):
        _, kink = kinked()
        short = [arcs.line((0.0, 0.0), (0.0, 0.0)), arcs.ELL[1]]
        wide = [arcs.arc((0.0, 0.0), 10.0, 0.0, 200.0)]
        for name, pieces, left, right, code in (
                ("kink", kink, 2.0, 0.0, "arc_corner"), ("short", short, 2.0, 0.0, "arc_piece_too_short"),
                ("wide", wide, 2.0, 0.0, "arc_turns_too_far"),
                ("thick", arcs.ELL, 10.0, 0.0, "arc_wall_too_thick"),
                ("near", arcs.U, 0.0, 10.0, "arc_pieces_too_near")):
            with self.subTest(name):
                found = thin_arc.check(pieces, left, right)
                self.assertEqual(found.code, code)
                self.assertEqual(found.cause, gap_hints.THIN_OUTLINE)
        self.assertIsNone(thin_arc.check(arcs.ELL, 0.0, 5.0))


class VolumeChangeTest(unittest.TestCase):
    def test_a_new_body_grows_from_nothing_whatever_body_was_measured_before(self):
        item = {"target_before": {"volume_mm3": 500.0}, "target_after": {"volume_mm3": 120.0}}
        self.assertEqual(thin_arc.volume_change(item, {"operation": "newBody"}), 120.0)
        self.assertEqual(thin_arc.volume_change(dict(item, target_before=None), {"operation": "newBody"}), 120.0)
        self.assertEqual(thin_arc.volume_change(item, {"operation": "join"}), -380.0)
        self.assertEqual(thin_arc.volume_change(item, {"operation": "newBody", "volume_before": 7.0,
                                                       "volume_after": 90.0}), 90.0)

    def test_a_volume_that_was_not_measured_gives_none(self):
        self.assertIsNone(thin_arc.volume_change({"target_before": None, "target_after": None}, {"operation": "join"}))


class ParamabilityTest(unittest.TestCase):
    def test_the_wall_along_an_ell_with_an_arc_is_the_band_on_the_side_its_faces_show(self):
        for location, side in SIDES:
            with self.subTest(location):
                result = translate(arcs.ell_arc(location))
                step = only_step(result)
                self.assertEqual(step["sketch"]["outer"], band_loop(arcs.ELL, side))
                self.assertEqual((step["combine"], step["distance"], "thin" in step), ("new", 15.0, False))
                assert_schema_ok(self, result.recipe)

    def test_a_u_and_an_arc_that_turns_right_are_copied(self):
        for capture, pieces, side in ((arcs.u_arc(), arcs.U, "middle"), (arcs.wall(RIGHT, "side2"), RIGHT, "outside")):
            with self.subTest(side):
                self.assertEqual(only_step(translate(capture))["sketch"]["outer"], band_loop(pieces, side))

    def test_the_line_and_the_thickness_keep_their_numbers_and_their_sizes_are_dropped(self):
        capture = load_capture("thin_line_corner")
        data = data_of(capture)
        built = arcs.ell_arc()
        item = built["items"][-1]
        data.update(path=item["data"]["path"], wall_faces=item["data"]["wall_faces"])
        capture["items"][-1].update(target_before=None, target_after=item["target_after"])
        result = run(capture, ["length_mm", "height_mm", "wall_mm"], motion_of("thin_line_corner"))
        step = only_step(result)
        self.assertEqual((step["sketch"]["outer"], step["distance"]), (band_loop(arcs.ELL, "inside"),
                                                                       {"expr": "height_mm"}))
        self.assertEqual(sorted(f["name"] for f in result.dropped), ["length_mm", "wall_mm"])

    def test_a_corner_next_to_an_arc_a_volume_that_differs_or_one_not_measured_is_left_out(self):
        kink, pieces = kinked()
        grown = arcs.ell_arc()
        grown["items"][-1]["target_after"]["volume_mm3"] *= 1.01
        unmeasured = arcs.ell_arc()
        unmeasured["items"][-1]["target_after"] = None
        for name, case, problem in (("kink", kink, thin_arc.problem(pieces, 2.0, 0.0)),
                                    ("volume", grown, thin_arc.VOLUME_DIFFERS.words),
                                    ("unmeasured", unmeasured, thin_arc.VOLUME_UNMEASURED.words)):
            with self.subTest(name):
                result = translate(case)
                self.assertIsNone(result.recipe)
                self.assertEqual(result.refusal.get("hint"), TIP)
                self.assertIn(problem, result.refusal["reason"])
        self.assertEqual(len({translate(c).refusal["reason"] for c in (kink, grown, unmeasured)}), 3)


class OrcaTest(unittest.TestCase):
    def test_the_ell_and_the_u_are_drawn_as_their_band_of_lines_and_arcs(self):
        for capture, radii in ((arcs.ell_arc(), [8.0, 10.0]), (arcs.u_arc(), [9.0, 11.0])):
            with self.subTest(capture["design"]):
                result = orca(capture)
                self.assertEqual(result.left_out, [])
                (sketch,) = [f for f in result.recipe.features if f.type == FeatureType.SKETCH]
                self.assertEqual(sorted(round(e.radius, 9) for e in sketch.entities if e.type == EntityType.ARC),
                                 radii)
                self.assertNotEqual({p["name"]: p["outcome"] for p in result.parameters}["wall_mm"], VARIABLE)

    def test_a_corner_next_to_an_arc_or_a_volume_that_differs_is_left_out(self):
        kink, pieces = kinked()
        grown = arcs.u_arc()
        grown["items"][-1]["target_after"]["volume_mm3"] *= 0.99
        for case, problem in ((kink, thin_arc.problem(pieces, 2.0, 0.0)), (grown, thin_arc.VOLUME_DIFFERS.words)):
            with self.subTest(case["design"]):
                (gap,) = orca(case).left_out
                self.assertEqual(gap["cause"], gap_hints.THIN_OUTLINE)
                self.assertIn(problem, gap["reason"])


if __name__ == "__main__":
    unittest.main()
