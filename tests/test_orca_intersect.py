"""Extrude intersects in the Orca copy (`orca_translate/steps.py`): several outlines or two tapered halves are joined
in a tool body that one Boolean intersects with the part; one outline is one intersect extrude. The recipe is read
back with `orca_cuts.Section`, and its volume is counted on a 0.25 mm grid of cell centres.
"""
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_intersects as oi
from tests.orca_cuts import Section
from tests.orca_extents import B1, side
from tests.test_orca_finishes import finish_item
from tests.test_orca_extents import run

from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes

STEP = 0.25


def modes(result):
    return [(f.type, f.mode) for f in result.recipe.features if f.type in (FeatureType.EXTRUDE, FeatureType.BOOLEAN)]


def volume(result, changed=None, reach=20.0):
    """The volume of Orca's only body, counted on layers through the block's height (capture coordinates)."""
    (body,) = Section(result.recipe, changed).bodies
    cells = int(2 * reach / STEP)
    layer = sum(1 for i in range(cells) for j in range(cells)
                if body(list(result.place.point([-reach + (i + 0.5) * STEP, -reach + (j + 0.5) * STEP, 5.0]))))
    return layer * STEP * STEP * 10.0


class SeveralOutlinesTest(unittest.TestCase):
    def test_separate_outlines_are_joined_in_a_tool_body_that_one_intersect_applies(self):
        result = run(oi.two_circles())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result), [(FeatureType.EXTRUDE, BooleanMode.NEW), (FeatureType.EXTRUDE, BooleanMode.NEW),
                                         (FeatureType.EXTRUDE, BooleanMode.ADD),
                                         (FeatureType.BOOLEAN, BooleanMode.INTERSECT)])
        self.assertAlmostEqual(volume(result), 2 * math.pi * 64 * 10, delta=40.0)

    def test_the_size_of_the_outlines_follows_a_variable(self):
        result = run(oi.two_circles())
        self.assertAlmostEqual(volume(result, {"hole_d": 12.0}), 2 * math.pi * 36 * 10, delta=40.0)

    def test_an_outline_in_the_hole_of_another_keeps_both(self):
        result = run(oi.ring_and_disc())
        self.assertEqual(result.left_out, [])
        self.assertAlmostEqual(volume(result), math.pi * (225 - 64 + 16) * 10, delta=40.0)

    def test_an_outline_that_misses_the_part_adds_nothing(self):
        capture = oi.two_circles()
        far = capture["items"][-1]["data"]["profiles"][1]["loops"][0]["curves"][0]
        far["center"] = [100.0, 0.0]
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertAlmostEqual(volume(result), math.pi * 64 * 10, delta=30.0)

    def test_an_outline_over_material_that_only_a_round_covers_stays_in_the_tool(self):
        # A 4 high block with its top edges rounded by 3.5: every line through the small circle at its corner
        # runs where the round may have taken material, so the copy cannot be sure the circle meets the part.
        capture = oi.two_circles()
        block = capture["items"][1]["data"]
        block.update(side_one=side(4.0), end_offset=4.0)
        trim = capture["items"][-1]
        trim["data"]["target_box_before"] = {"min": [-20.0, -20.0, 0.0], "max": [20.0, 20.0, 4.0]}
        trim["data"]["profiles"][1]["loops"][0]["curves"][0].update(center=[19.0, 19.0], radius=0.5)
        top = [[x, y, 4.0] for x, y in ((0, -20), (20, 0), (0, 20), (-20, 0))]
        trim["index"] = 4
        capture["items"].insert(3, finish_item(3, "FilletFeature", top, 3.5))
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result)[-1], (FeatureType.BOOLEAN, BooleanMode.INTERSECT))
        self.assertEqual([t for t, _ in modes(result)].count(FeatureType.EXTRUDE), 3)

    def test_outlines_that_all_miss_the_part_leave_the_step_out(self):
        capture = oi.two_circles()
        for found in capture["items"][-1]["data"]["profiles"]:
            found["loops"][0]["curves"][0]["center"][1] = 100.0
        self.assertEqual([g["cause"] for g in run(capture).left_out], [causes.MISSES_PART])

    def test_an_intersect_that_leaves_another_body_is_left_out(self):
        capture = oi.two_circles()
        capture["items"][-1]["bodies_after"] = [dict(B1), {"token": "t2", "name": "Body2"}]
        result = run(capture)
        self.assertEqual([g["index"] for g in result.left_out], [3])
        self.assertNotIn(BooleanMode.INTERSECT, [mode for _, mode in modes(result)])


class OneOutlineTest(unittest.TestCase):
    def test_a_ring_is_one_intersect_extrude_of_an_outline_with_a_hole(self):
        result = run(oi.ring())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result), [(FeatureType.EXTRUDE, BooleanMode.NEW),
                                         (FeatureType.EXTRUDE, BooleanMode.INTERSECT)])
        self.assertAlmostEqual(volume(result), math.pi * 200 * 10, delta=40.0)


class TaperedHalvesTest(unittest.TestCase):
    def test_the_two_halves_of_a_tapered_intersect_are_joined_before_it(self):
        result = run(oi.tapered_both_sides())
        self.assertEqual(result.left_out, [])
        self.assertEqual(modes(result)[1:], [(FeatureType.EXTRUDE, BooleanMode.NEW),
                                             (FeatureType.EXTRUDE, BooleanMode.ADD),
                                             (FeatureType.BOOLEAN, BooleanMode.INTERSECT)])


if __name__ == "__main__":
    unittest.main()
