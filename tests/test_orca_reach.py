"""Sizes the Orca copy cannot follow because of what they move, found by the shared reachability
(`design_model/reach.py`): a size that only a joint or a sketch text reads is told as fixed instead of unused, and a
step left out names the sizes of the sketches it uses, also those that reach a sketch through another component."""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture, table_of
from tests.probe_helpers import model, user
from tests.test_orca_holes import BOX_TICKED, box_hole, centre, outcome, run
from tests.translator_helpers import verdict_of

from lib.orca_translate import FIXED, PARTLY, UNUSED, VARIABLE, translate
from lib.orca_translate.translate import UNUSED_REASON
from lib.orca_translate.place import Placement


def with_user(capture, *params):
    found = capture.setdefault("parameters", {"user": [], "model": []})
    found["user"].extend(params)
    return found


def joint_on(capture, size, name="j1"):
    """A joint that reads the size `size`."""
    with_user(capture)["model"].append(model(name, size, 4, kind="joint"))
    return capture


def outcome_of(result, name):
    return next(p for p in result.parameters if p["name"] == name)


class JointAndTextTest(unittest.TestCase):
    def plate(self):
        capture = fixture("extrude_plate")
        with_user(capture, user("lid_mm", "4 mm", 4))
        return capture

    def test_a_size_only_a_joint_reads_is_fixed_with_a_reason_instead_of_unused(self):
        capture = joint_on(self.plate(), "lid_mm")
        result = translate(capture, table_of(capture))
        found = outcome_of(result, "lid_mm")
        self.assertEqual(found["outcome"], FIXED)
        self.assertNotEqual(found["reasons"], [UNUSED_REASON])

    def test_the_same_size_with_no_joint_is_unused(self):
        capture = self.plate()
        found = outcome_of(translate(capture, table_of(capture)), "lid_mm")
        self.assertEqual((found["outcome"], found["reasons"]), (UNUSED, [UNUSED_REASON]))

    def test_a_size_only_a_sketch_text_height_reads_is_fixed_with_a_reason(self):
        capture = self.plate()
        with_user(capture)["model"].append(model("d9", "lid_mm", 4, kind="sketchText", sketch="Sketch1"))
        capture["items"][1]["data"]["profiles"][0].update(text=True, text_params=["d9"])
        result = translate(capture, table_of(capture))
        found = outcome_of(result, "lid_mm")
        self.assertEqual(found["outcome"], FIXED)
        self.assertNotEqual(found["reasons"], [UNUSED_REASON])

    def test_a_size_a_step_follows_and_a_joint_reads_is_followed_in_part(self):
        capture = box_hole()
        joint_on(capture, "pipe_offset_mm")
        self.assertEqual(outcome(run(box_hole(), BOX_TICKED), "pipe_offset_mm")["outcome"], VARIABLE)
        result = run(capture, BOX_TICKED)
        self.assertEqual(outcome(result, "pipe_offset_mm")["outcome"], PARTLY)

    def test_a_joint_does_not_stop_the_hole_centre_from_following_the_size(self):
        capture = box_hole()
        joint_on(capture, "pipe_offset_mm")
        (hole,) = [f for f in run(capture, BOX_TICKED).recipe.features if "hole_x" in f.expr]
        place = Placement(capture)
        for offset in (20.0, 30.0):
            for a, b in zip(centre(hole, {"pipe_offset_mm": offset}), place.point([-offset, 0, 0])):
                self.assertAlmostEqual(a, b)


class LeftOutStepTest(unittest.TestCase):
    def left_out_plate(self, links):
        capture = fixture("extrude_plate")
        with_user(capture, user("lid_mm", "4 mm", 4))
        capture["items"][1]["health"] = "error"
        return capture, table_of(capture).with_links(links)

    def test_a_step_left_out_names_a_size_that_reaches_its_sketch_through_another_component(self):
        link = {"param": "lid_mm", "sketch": "Sketch1", "component": "Lid", "via": "x"}
        capture, table = self.left_out_plate([link])
        result = translate(capture, table)
        self.assertEqual(verdict_of(result, 1)["verdict"], "leftOut")
        self.assertEqual(outcome_of(result, "lid_mm")["outcome"], FIXED)

    def test_without_the_link_that_size_is_unused(self):
        capture, table = self.left_out_plate([])
        self.assertEqual(outcome_of(translate(capture, table), "lid_mm")["outcome"], UNUSED)


if __name__ == "__main__":
    unittest.main()
