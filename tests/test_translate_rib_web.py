"""Ribs and webs in the recipe: each wall is written as the thin extrude of an open line it is, with its thickness
and depth following their sizes, and the sizes marked where the wall may run into the part; the cases the faces
Fusion made do not prove are left out with the rib and web tip. Fixtures saved from Fusion exports of test designs."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, verdict_of

from lib.capture_model import gap_hints
from lib.translator import translate
from scripts.orca_live_check import table_for


def run(name, edit=None):
    capture = copy.deepcopy(load_capture(name))
    if edit is not None:
        edit(capture["items"][-1]["data"])
    return translate(capture, size_table=table_for(capture))


def walls_of(result):
    assert result.recipe is not None, result.refusal
    return [s for s in steps_of(result.recipe, "extrude") if s.get("label", "").startswith(("Rib", "Web"))]


def loose(result):
    return sorted(entry["name"] for entry in result.loose)


class RibWebCopyTest(unittest.TestCase):
    def test_a_web_on_a_plate_writes_one_centred_wall_per_line_that_follows_its_sizes(self):
        result = run("web_on_plate")
        assert_schema_ok(self, result.recipe)
        found = walls_of(result)
        self.assertEqual(len(found), 2)
        for step in found:
            self.assertEqual((step["combine"], step["extent"], step["distance"]), ("add", "oneSide", {"expr": "wd"}))
            self.assertEqual(step["thin"], {"thickness": {"expr": "wt"}, "side": "middle", "ends": "square",
                                            "corners": "sharp"})
        self.assertEqual(loose(result), [])

    def test_a_rib_writes_its_depth_as_the_wall_and_its_thickness_as_the_length(self):
        result = run("rib_distance_channel")
        assert_schema_ok(self, result.recipe)
        (step,) = walls_of(result)
        self.assertEqual(step["sketch"]["outer"], {"kind": "open", "start": [4.0, -30.0],
                                                   "segments": [{"kind": "line", "to": [56.0, -30.0]}]})
        self.assertEqual((step["extent"], step["distance"], step["thin"]["thickness"]),
                         ("oneSide", {"expr": "rt"}, {"expr": "rd"}))
        # Inside the channel a deeper rib could reach the base: the depth and the earlier sizes are marked.
        self.assertEqual(loose(result), ["bt", "rd"])

    def test_a_rib_to_next_keeps_the_measured_depth_and_marks_the_sizes_before_it(self):
        result = run("rib_tonext_channel")
        (step,) = walls_of(result)
        self.assertEqual((step["extent"], step["distance"]), ("symmetric", {"expr": "rt"}))
        self.assertAlmostEqual(step["thin"]["thickness"], 26.0, places=6)
        self.assertEqual(loose(result), ["bt"])

    def test_a_web_to_next_writes_every_line_to_the_floor_and_marks_its_thickness(self):
        result = run("web_tonext_grid")
        found = walls_of(result)
        self.assertEqual([s["distance"] for s in found], [17.0] * 3)
        self.assertEqual(loose(result), ["wt"])

    def test_a_plate_size_is_marked_when_the_web_sketch_is_not_on_the_plate(self):
        # The plate of the fixture made `T` thick, and the web sketched on a plane at its top that `T` does not move.
        capture = copy.deepcopy(load_capture("web_on_plate"))
        user = dict(capture["parameters"]["user"][0], name="T", expression="4 mm", value=0.4, dependent_parameters=[],
                    dependents=[])
        capture["parameters"]["user"].append(user)
        model = next(p for p in capture["parameters"]["model"] if p["name"] == "d3")
        model.update(expression="T", kind="derived", dependency_parameters=["T"])
        capture["items"][1]["data"]["params"]["side_one.distance"]["expression"] = "T"
        for path in capture["items"][-1]["data"]["paths"]:
            path["reference"] = {"kind": "constructionPlane", "token": "p1", "built_on": [{"origin": True}]}
        result = translate(capture, size_table=table_for(capture))
        self.assertEqual(len(walls_of(result)), 2)
        self.assertEqual(loose(result), ["T"])

    def test_a_web_of_one_line_on_one_side_follows_its_line_as_drawn(self):
        result = run("web_distance_l")
        (step,) = walls_of(result)
        self.assertEqual(len(step["sketch"]["outer"]["segments"]), 2)
        self.assertIn(step["thin"]["side"], ("inside", "outside"))
        self.assertEqual(loose(result), ["wd", "wt"])


class RibWebLeftOutTest(unittest.TestCase):
    def assert_left_out(self, result, index):
        self.assertIsNotNone(left_out(result, index))
        verdict = verdict_of(result, index)
        (record,) = [g for g in result.gaps if g["id"] == verdict["gap"]]
        self.assertEqual(record["hint"], gap_hints.HINTS[gap_hints.RIB_WEB])

    def test_a_gusset_to_next_a_band_into_the_part_and_an_extended_web_are_left_out(self):
        for name in ("rib_tonext_gusset", "rib_into_corner", "web_extended"):
            with self.subTest(name):
                capture = load_capture(name)
                self.assert_left_out(run(name), capture["items"][-1]["index"])

    def test_a_rib_with_a_draft_is_left_out_and_the_steps_before_it_are_copied(self):
        def edit(data):
            data["draft_deg"] = 1.5
        result = run("rib_distance_channel", edit)
        self.assert_left_out(result, 7)
        self.assertEqual(walls_of(result), [])
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 3)


if __name__ == "__main__":
    unittest.main()
