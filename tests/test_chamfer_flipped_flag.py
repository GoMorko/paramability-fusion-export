"""Fusion's `isFlipped` on an uneven chamfer is not trusted: the measured faces decide which side takes the first
distance, and a flag that cannot be read does not stop the set from being read."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj, feature, param
from tests.test_capture_reader_finish import edge, read_data, with_edges
from tests.translator_helpers import load_capture, steps_of

from lib.translator import translate


class FlagWithoutValue(Obj):
    """An uneven chamfer set whose `isFlipped` raises."""

    @property
    def isFlipped(self):
        raise RuntimeError("not available")


class ChamferFlippedFlagTest(unittest.TestCase):
    def test_a_flag_that_cannot_be_read_reads_as_not_flipped_and_keeps_the_sizes(self):
        sets = [FlagWithoutValue("fusion::TwoDistancesChamferEdgeSet", edges=Coll([edge("a", 1)]),
                                 distanceOne=param(0.1), distanceTwo=param(0.3)),
                FlagWithoutValue("fusion::DistanceAndAngleChamferEdgeSet", edges=Coll([edge("b", 1)]),
                                 distance=param(0.2), angle=param(0.5))]
        data = read_data(feature("ChamferFeature", "Chamfer1", edgeSets=Coll(sets), cornerType="ChamferCornerType"))
        self.assertEqual([(s["kind"], s["flipped"]) for s in data["sets"]],
                         [("twoDistances", False), ("distanceAngle", False)])
        self.assertEqual((data["sets"][0]["distance"], data["sets"][0]["distance_two"]), (1.0, 3.0))

    def test_the_recipe_is_the_same_whichever_way_the_flag_says(self):
        recipes = []
        for flag in (False, True, None):
            capture = load_capture("chamfer_two_sides")
            entry = capture["items"][-1]["data"]["sets"][0]
            entry["flipped"] = flag
            recipes.append(steps_of(translate(capture).recipe, "bevel"))
        self.assertEqual(recipes[0], recipes[1])
        self.assertEqual(recipes[0], recipes[2])
        self.assertTrue(recipes[0])


if __name__ == "__main__":
    unittest.main()
