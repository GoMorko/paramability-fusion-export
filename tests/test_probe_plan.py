import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import (
    capture, circle, extrude, loop, model, profile, read, rect_curves, size, sketch_state, table, user)

from lib.probe import match, plan

PARAMS = [user("count", "3", 3, ""), user("cube", "10 mm", 10), user("W", "count * cube + 2 mm", 32),
          user("off", "5 mm", 5), user("height", "20 mm", 20), user("wall", "2 mm", 2)]
MODEL = [model("d1", "W", 32, sketch="Sketch1"), model("d2", "height", 20, kind="constructionPlane", token="cp1"),
         model("d3", "wall", 2, kind="extrude")]


def square(token="sk1", name="Sketch1", **extra):
    out = profile(name, token, [loop(rect_curves("r", 0, 0, 10, 10))])
    out.update(extra)
    return out


class ScanTests(unittest.TestCase):
    def test_profile_hole_and_axis_records_with_tokens_are_covered(self):
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "sketch": "Holes",
                                                           "positions": [[1, 2, 3]], "point_tokens": ["p1"]}}
        axis = {"index": 3, "type": "RevolveFeature", "data": {"profiles": [], "axis": {
            "point": [0, 0, 0], "dir": [0, 1, 0], "entity": "l1", "sketch_token": "sk3"}}}
        found = plan.scan(capture(extrude(1, square()), hole, axis))
        self.assertEqual(found.covered, {"sk1": "Sketch1", "sk2": "Holes", "sk3": ""})
        self.assertEqual([t["kind"] for t in found.targets], ["profile", "hole", "axis"])
        self.assertEqual(found.names(), ["Holes", "Sketch1"])

    def test_a_profile_without_curve_tokens_leaves_its_sketch_uncovered(self):
        bare = square()
        for curve in bare["loops"][0]["curves"]:
            del curve["entity"]
        found = plan.scan(capture(extrude(1, bare), extrude(2, square())))
        self.assertEqual((found.covered, found.uncovered), ({}, {"sk1"}))

    def test_one_unknown_record_uncovers_the_sketch_for_every_record(self):
        pattern = {"index": 5, "type": "RectangularPatternFeature", "data": {"direction_one": {"sketch_token": "sk1"}}}
        found = plan.scan(capture(extrude(1, square()), pattern))
        self.assertEqual(found.covered, {})
        self.assertEqual(found.targets, [])

    def test_a_curve_the_translator_cannot_copy_is_not_covered(self):
        other = square()
        other["loops"][0]["curves"][0] = {"kind": "other", "entity": "x", "start": [0, 0], "end": [1, 1]}
        self.assertEqual(plan.scan(capture(extrude(1, other))).covered, {})

    def test_hole_point_tokens_must_match_the_positions(self):
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "positions": [[1, 2, 3]],
                                                           "point_tokens": []}}
        self.assertEqual(plan.scan(capture(hole)).covered, {})

    def test_suppressed_and_foreign_records_are_ignored(self):
        item = extrude(1, dict(square(), foreign=True))
        hidden = dict(extrude(2, square("sk9")), suppressed=True)
        self.assertEqual(plan.scan(capture(item, hidden)).covered, {})


class RequestTests(unittest.TestCase):
    def test_request_lists_tokens_and_parameters(self):
        tbl = table(PARAMS, ["count", "cube"], MODEL)
        hole = {"index": 2, "type": "HoleFeature", "data": {"sketch_token": "sk2", "positions": [[1, 2, 3]],
                                                           "point_tokens": ["p1"]}}
        asked = plan.request(capture(extrude(1, square()), hole), tbl)
        self.assertEqual((asked["sketches"], asked["points"], asked["lines"]), (["sk1", "sk2"], ["p1"], []))
        self.assertTrue(asked["target"])
        self.assertTrue({"count", "cube", "W", "d1", "d2"} <= set(asked["params"]))

    def test_no_covered_sketch_gives_no_request(self):
        self.assertIsNone(plan.request(capture(), table(PARAMS, ["count"], MODEL)))

    def test_only_the_sketches_that_matched_at_the_start_are_asked_for(self):
        tbl = table(PARAMS, ["count"], MODEL)
        cap = capture(extrude(1, square()), extrude(2, square("sk2", "Sketch2")))
        self.assertEqual(plan.request(cap, tbl, covered={"sk2"})["sketches"], ["sk2"])


class KeptSizesTests(unittest.TestCase):
    def setUp(self):
        self.tbl = table(PARAMS, ["count", "cube", "off", "height", "wall"], MODEL)

    def test_sizes_that_reach_a_sketch_dimension_or_plane_are_driven(self):
        self.assertEqual(plan.sketch_driven(self.tbl), ["count", "cube", "height"])

    def test_kept_are_the_free_sizes_of_the_recipe_plus_the_driven_ones(self):
        self.assertEqual(plan.kept_sizes(self.tbl, ["off"]), ["count", "cube", "off", "height"])


class ProbeRowTests(unittest.TestCase):
    def setUp(self):
        self.tbl = table(PARAMS, ["count", "cube", "off"], MODEL)
        self.sizes = [size(self.tbl, "count", ""), size(self.tbl, "cube"), size(self.tbl, "off")]

    def test_a_checked_size_gets_the_end_its_check_did_not_try(self):
        rows, untried = plan.probe_rows(self.sizes, {"count": 6}, {"count"})
        self.assertEqual([r["name"] for r in rows], ["count (min)"])
        self.assertEqual(rows[0]["state"], {"count": 1.5, "cube": 10, "off": 5})
        self.assertEqual(rows[0]["varied"], ["count"])
        self.assertFalse(rows[0]["step"])
        self.assertEqual(untried, [])

    def test_row_values_are_in_the_units_fusion_shows(self):
        rows, _ = plan.probe_rows(self.sizes, {}, {"cube"})
        self.assertEqual({r["name"]: r["values"]["cube"] for r in rows}, {"cube (min)": 5, "cube (max)": 20})

    def test_two_moved_sizes_add_one_row_with_all_at_min_and_one_at_max(self):
        rows, _ = plan.probe_rows(self.sizes, {"count": 6, "cube": 20}, {"count", "cube"})
        self.assertEqual([r["name"] for r in rows], ["count (min)", "cube (min)", "all min", "all max"])
        self.assertEqual(rows[-2]["state"], {"count": 1.5, "cube": 5, "off": 2.5})
        self.assertEqual(rows[-1]["state"], {"count": 6, "cube": 20, "off": 10})

    def test_the_row_limit_leaves_a_size_untried(self):
        rows, untried = plan.probe_rows(self.sizes, {}, {"count", "cube"}, limit=3)
        self.assertEqual(untried, ["cube"])
        self.assertEqual([r["name"] for r in rows], ["count (min)", "count (max)"])

    def test_no_moved_size_no_rows(self):
        self.assertEqual(plan.probe_rows(self.sizes, {"count": 6}, set()), ([], []))


class CandidateProfileTests(unittest.TestCase):
    def test_among_profiles_with_the_same_curves_the_nearest_to_the_capture_is_taken(self):
        cap = capture(extrude(1, square()))
        target = plan.scan(cap).targets[0]
        near = {"loops": [loop(rect_curves("r", 1, 0, 11, 10))]}
        far = {"loops": [loop(rect_curves("r", 50, 0, 60, 10))]}
        values, cause = match.state_values(target, read(sketch_state("sk1", [far, near])))
        self.assertIsNone(cause)
        self.assertEqual(values["1/p0/l0/center.0"], 6.0)

    def test_a_circle_and_its_sketch_frame_offset_in_plane_map_back(self):
        prof = profile("S", "s", [loop([circle((5, 5), 2, "c")])])
        target = plan.scan(capture(extrude(1, prof))).targets[0]
        shifted = {"origin": [3, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        state_profile = {"loops": [loop([circle((2, 5), 2, "c")])]}
        values, _ = match.state_values(target, read(sketch_state("s", [state_profile], shifted)))
        self.assertEqual(values["1/p0/l0/center.0"], 5.0)


if __name__ == "__main__":
    unittest.main()
