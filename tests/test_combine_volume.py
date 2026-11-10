import math
import unittest

from tests import context  # noqa: F401

from lib.translator.combine_volume import exceeds, step_volume


def extrude(loops, distance=10.0, **more):
    data = {"profiles": [{"loops": loops}], "extent_type": "one",
            "side_one": {"kind": "distance", "distance": distance, "taper_deg": 0.0}}
    data.update(more)
    return {"type": "ExtrudeFeature", "data": data}


CIRCLE = {"outer": True, "curves": [{"kind": "circle", "center": [3, 4], "radius": 2.0}]}
# The half disc of radius 2 above the x axis, drawn clockwise.
HALF_DISC = {"outer": True, "curves": [
    {"kind": "arc", "start": [2, 0], "end": [-2, 0], "mid": [0, 2], "center": [0, 0], "radius": 2.0},
    {"kind": "line", "start": [-2, 0], "end": [2, 0]}]}


class StepVolumeTest(unittest.TestCase):
    def test_outlines_of_lines_arcs_and_circles_give_their_area_times_the_length(self):
        self.assertAlmostEqual(step_volume(extrude([CIRCLE])), math.pi * 4 * 10)
        self.assertAlmostEqual(step_volume(extrude([HALF_DISC])), math.pi * 2 * 10)

    def test_an_inner_outline_takes_its_area_away(self):
        hole = {"outer": False, "curves": [{"kind": "circle", "center": [3, 4], "radius": 1.0}]}
        self.assertAlmostEqual(step_volume(extrude([CIRCLE, hole])), math.pi * 3 * 10)

    def test_a_symmetric_extrude_counts_both_halves(self):
        item = extrude([CIRCLE], extent_type="symmetric", symmetric={"distance": 3.0, "full_length": False})
        self.assertAlmostEqual(step_volume(item), math.pi * 4 * 6)

    def test_what_cannot_be_worked_out_gives_none(self):
        self.assertIsNone(step_volume({"type": "RevolveFeature", "data": {}}))
        self.assertIsNone(step_volume(extrude([CIRCLE], thin=True)))
        self.assertIsNone(step_volume(extrude([{"outer": True, "curves": [{"kind": "other"}]}])))
        tapered = extrude([CIRCLE])
        tapered["data"]["side_one"]["taper_deg"] = 3.0
        self.assertIsNone(step_volume(tapered))


class ExceedsTest(unittest.TestCase):
    def test_a_change_past_the_tool_volume_exceeds_and_one_within_it_does_not(self):
        items = [extrude([CIRCLE])]
        fill = math.pi * 40
        self.assertTrue(exceeds({"volume_before": 1000.0, "volume_after": 1000.0 - fill - 10}, items))
        self.assertFalse(exceeds({"volume_before": 1000.0, "volume_after": 1000.0 - fill}, items))
        self.assertFalse(exceeds({"volume_before": 1000.0, "volume_after": 1000.0}, items))

    def test_without_volumes_or_with_a_tool_that_cannot_be_measured_nothing_is_checked(self):
        self.assertFalse(exceeds({}, [extrude([CIRCLE])]))
        self.assertFalse(exceeds({"volume_before": 1.0, "volume_after": 500.0}, [{"type": "RevolveFeature"}]))


if __name__ == "__main__":
    unittest.main()
