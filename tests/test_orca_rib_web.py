"""Ribs and webs in the Orca copy (`orca_translate/rib_web.py`): each wall is built as the thin extrude of an open
line it is; the variables follow where the thin extrude lets them, and the cases the faces Fusion made do not prove
are left out with the rib and web cause. Fixtures saved from Fusion exports of test designs."""
import unittest

from tests import context  # noqa: F401
from tests.orca_cuts import Section
from tests.translator_helpers import load_capture
from scripts.orca_live_check import table_for

from lib.capture_model import gap_hints
from lib.orca_translate import translate


def run(name):
    capture = load_capture(name)
    return translate(capture, table_for(capture))


def verdict(result, kind):
    (found,) = [i["verdict"] for i in result.items if i["type"] == kind]
    return found


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


class OrcaRibWebTest(unittest.TestCase):
    def test_a_web_on_a_plate_grows_with_its_depth_variable(self):
        result = run("web_on_plate")
        self.assertEqual(verdict(result, "WebFeature"), "copied")
        self.assertEqual(outcomes(result), {"wt": "variable", "wd": "variable"})
        depth = {p["name"]: p["variable"] for p in result.parameters}["wd"]
        above = result.place.point([30.0, 20.0, 19.0])
        self.assertFalse(Section(result.recipe).bodies[0](above))
        self.assertTrue(Section(result.recipe, {depth: 20.0}).bodies[0](above))

    def test_a_rib_follows_its_thickness_and_marks_a_depth_that_may_reach_the_part(self):
        result = run("rib_distance_channel")
        self.assertEqual(verdict(result, "RibFeature"), "copied")
        self.assertEqual(outcomes(result)["rt"], "variable")
        self.assertNotEqual(outcomes(result)["rd"], "variable")

    def test_walls_to_next_are_copied_with_the_sizes_before_them_marked(self):
        for name, kind, marked in (("rib_tonext_channel", "RibFeature", "bt"), ("web_tonext_grid", "WebFeature", "wt")):
            with self.subTest(name):
                result = run(name)
                self.assertEqual(verdict(result, kind), "copied")
                self.assertNotEqual(outcomes(result)[marked], "variable")

    def test_the_walls_fusion_does_not_build_as_bands_are_left_out(self):
        for name in ("rib_into_corner", "web_extended"):
            with self.subTest(name):
                result = run(name)
                self.assertEqual([g["cause"] for g in result.left_out], [gap_hints.RIB_WEB])


if __name__ == "__main__":
    unittest.main()
