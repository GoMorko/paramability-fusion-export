import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, translate_fixture

from lib.translator import translate, vec


def verdict_of(result, index):
    return [v for v in result.items if v["index"] == index][0]


def variant(name, edit):
    """Translate a fixture after `edit(data)` changed the data of its last item."""
    capture = load_capture(name)
    edit(capture["items"][-1]["data"])
    return translate(capture)


class FilletTest(unittest.TestCase):
    def test_four_edges_use_captured_points(self):
        result = translate_fixture("fillet_four_edges")
        (step,) = steps_of(result.recipe, "round")
        expected = [e["points"][0] for e in load_capture("fillet_four_edges")["items"][-1]["data"]["sets"][0]["edges"]]
        self.assertEqual(step["edges"]["near"], expected)
        self.assertEqual(step["size"], 2)
        self.assertNotIn("edgeSizes", step)
        self.assertEqual(verdict_of(result, 2)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_two_radii_list_a_size_per_point(self):
        (step,) = steps_of(translate_fixture("fillet_two_radii").recipe, "round")
        self.assertEqual((step["size"], step["edgeSizes"]), (2, [2, 2, 3, 3]))

    def test_closed_edge_gets_two_points(self):
        result = translate_fixture("fillet_closed_edge")
        (step,) = steps_of(result.recipe, "round")
        self.assertEqual(len(step["edges"]["near"]), 2)
        assert_schema_ok(self, result.recipe)

    def test_many_edges_split_into_steps_with_a_note(self):
        result = translate_fixture("fillet_many_edges")
        rounds = steps_of(result.recipe, "round")
        self.assertEqual([len(s["edges"]["near"]) for s in rounds], [32, 8])
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")
        self.assertEqual(verdict_of(result, 2)["steps"], ["round_2", "round_2_2"])
        assert_schema_ok(self, result.recipe)

    def test_setback_corners_translate_with_a_note(self):
        result = translate_fixture("fillet_setback")
        self.assertEqual(len(steps_of(result.recipe, "round")), 1)
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")

    def test_refusals(self):
        for name, word in (("fillet_variable", "changing radius"), ("fillet_g2", "curvature"),
                           ("fillet_feature_input", "another step")):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertIn(word, result.refusal["reason"], name)
            self.assertEqual(result.refusal["index"], 2)

    def test_other_set_kinds_and_bad_radius_refuse(self):
        for label, edit in (("chord length", lambda d: d["sets"][0].update(kind="chordLength")),
                            ("unknown kind", lambda d: d["sets"][0].update(kind="other")),
                            ("zero radius", lambda d: d["sets"][0].update(radius=0)),
                            ("edge without points", lambda d: d["sets"][0].update(
                                edges=[{"token": "x", "closed": False, "points": []}]))):
            with self.subTest(label):
                self.assertIsNone(variant("fillet_four_edges", edit).recipe)

    def test_unreadable_continuity_translates_with_a_note(self):
        result = variant("fillet_four_edges", lambda d: d["sets"][0].update(continuity="other"))
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")


class InputPickTest(unittest.TestCase):
    """A step that holds whole Fusion sets picks their edges as Fusion did: around the picked faces, or along the
    tangent chains of the picked edges."""

    @staticmethod
    def picked_by_top_face(data):
        data["sets"][0].update(input_kinds=["face"], faces=[{"token": "top", "point": [20.0, 10.0, 10.0]}])

    def test_a_set_picked_by_a_face_picks_the_edges_around_it(self):
        result = variant("chamfer_equal", self.picked_by_top_face)
        (step,) = steps_of(result.recipe, "bevel")
        self.assertEqual(step["edges"], {"faceEdges": {"near": [[20.0, 10.0, 10.0]]}})
        self.assertEqual(result.recipe["version"], 14)
        assert_schema_ok(self, result.recipe)

    def test_a_tangent_chain_set_writes_one_point_per_picked_edge(self):
        def edit(data):
            data["sets"][0]["tangent_chain"] = True
            data["sets"][0]["edges"][0]["seed"] = True
        result = variant("fillet_four_edges", edit)
        (step,) = steps_of(result.recipe, "round")
        first = load_capture("fillet_four_edges")["items"][-1]["data"]["sets"][0]["edges"][0]["points"]
        self.assertEqual(step["edges"], {"near": first, "chain": "tangent"})
        assert_schema_ok(self, result.recipe)

    def test_part_of_a_set_or_mixed_inputs_keep_a_point_per_edge(self):
        def mixed(data):
            data["sets"][0].update(input_kinds=["edge", "face"], faces=[{"token": "top", "point": [20.0, 10.0, 10.0]}])

        def chain_without_seeds(data):
            data["sets"][0]["tangent_chain"] = True
        for name, edit in (("chamfer_equal", mixed), ("fillet_four_edges", chain_without_seeds)):
            result = variant(name, edit)
            (step,) = [s for s in result.recipe["features"] if s["kind"] in ("round", "bevel")]
            self.assertEqual(list(step["edges"]), ["near"], name)
            self.assertEqual(result.recipe["version"], 12, name)

    def test_a_pattern_copies_a_face_pick_by_points(self):
        def edit(capture):
            data = capture["items"][3]["data"]
            data["sets"][0].update(input_kinds=["face"], faces=[{"token": "f", "point": [20.0, 0.0, 5.0]}])
        result = translate(edited_capture("rpattern_fillet", edit))
        source, copies = steps_of(result.recipe, "round")
        self.assertIn("faceEdges", source["edges"])
        self.assertEqual(len(copies["edges"]["near"]), 6)
        assert_schema_ok(self, result.recipe)


def edited_capture(name, edit):
    capture = load_capture(name)
    edit(capture)
    return capture


class ChamferTest(unittest.TestCase):
    def test_equal_distance(self):
        result = translate_fixture("chamfer_equal")
        (step,) = steps_of(result.recipe, "bevel")
        self.assertEqual(step["size"], 1)
        self.assertEqual(len(step["edges"]["near"]), 4)
        self.assertNotIn("sizeOn", step)
        assert_schema_ok(self, result.recipe)

    def test_equal_pair_and_45_degrees_give_one_size(self):
        self.assertEqual(steps_of(translate_fixture("chamfer_two_equal").recipe, "bevel")[0]["size"], 1.5)
        self.assertEqual(steps_of(translate_fixture("chamfer_angle_45").recipe, "bevel")[0]["size"], 2)

    def test_two_distances_name_the_face_of_the_first(self):
        result = translate_fixture("chamfer_two_sides")
        (step,) = steps_of(result.recipe, "bevel")
        self.assertEqual((step["size"], step["otherSize"], step["sizeOn"]), (1, 2, [0, 0, 1]))
        self.assertEqual(len(step["edges"]["near"]), 4)
        assert_schema_ok(self, result.recipe)

    def test_the_first_distance_on_the_sides_turns_size_on_away_from_the_top(self):
        def edit(data):
            for edge in data["sets"][0]["edges"]:
                edge["cut_normals"] = [[c * (2 if i == 2 else 0.5) for i, c in enumerate(edge["cut_normals"][0])]]
        (step,) = steps_of(variant("chamfer_two_sides", edit).recipe, "bevel")
        self.assertEqual(step["sizeOn"], [0, 0, -1])

    def test_a_distance_and_an_angle_write_the_angle(self):
        def edit(data):
            entry = data["sets"][0]
            entry.update(kind="distanceAngle", angle_deg=math.degrees(math.atan(2.0)))
            del entry["distance_two"]
        (step,) = steps_of(variant("chamfer_two_sides", edit).recipe, "bevel")
        self.assertEqual((step["size"], step["sizeOn"]), (1, [0, 0, 1]))
        self.assertAlmostEqual(step["cutAngleDeg"], 63.434949, 5)

    def test_faces_that_no_one_direction_tells_apart_split_the_step(self):
        def edit(data):
            edges = data["sets"][0]["edges"]
            for edge in (edges[1], edges[3]):
                side = edge["sides"][0][1]
                edge["cut_normals"] = [vec.unit([2 * side[0], 2 * side[1], 4])]
        bevels = steps_of(variant("chamfer_two_sides", edit).recipe, "bevel")
        self.assertEqual([len(b["edges"]["near"]) for b in bevels], [2, 2])
        self.assertTrue(vec.close(bevels[0]["sizeOn"], vec.scale(bevels[1]["sizeOn"], -1)))

    def test_uneven_without_measured_faces_refuses(self):
        result = translate_fixture("chamfer_uneven")
        self.assertIsNone(result.recipe)
        self.assertIn("face each size is on", result.refusal["reason"])

    def test_other_corner_type_notes(self):
        result = variant("chamfer_equal", lambda d: d.update(corner_type="miter"))
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")

    def test_sets_of_two_sizes_make_one_bevel_each(self):
        def edit(data):
            second = dict(data["sets"][0], distance=2.0, edges=[{"token": "x", "closed": False, "points": [[1, 2, 3]]}])
            data["sets"].append(second)
        result = variant("chamfer_equal", edit)
        self.assertEqual([s["size"] for s in steps_of(result.recipe, "bevel")], [1, 2])
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")


class ShellTest(unittest.TestCase):
    def test_open_top(self):
        result = translate_fixture("shell_open_top")
        (step,) = steps_of(result.recipe, "shell")
        self.assertEqual((step["thickness"], step["openFaces"]), (2, {"near": [[20, 10, 10]]}))
        assert_schema_ok(self, result.recipe)

    def test_refusals(self):
        for name, word in (("shell_outside", "outward"), ("shell_closed", "Closed hollow"),
                           ("shell_rounded", "rounded")):
            result = translate_fixture(name)
            self.assertIsNone(result.recipe, name)
            self.assertIn(word, result.refusal["reason"], name)

    def test_no_faces_no_thickness_or_too_many_faces_refuse(self):
        many = [{"token": "f%d" % i, "point": [i, 0, 10]} for i in range(33)]
        for label, edit in (("no faces", lambda d: d.update(faces=[])),
                            ("no thickness", lambda d: d.update(inside=0.0)),
                            ("too many faces", lambda d: d.update(faces=many))):
            with self.subTest(label):
                self.assertIsNone(variant("shell_open_top", edit).recipe)


if __name__ == "__main__":
    unittest.main()
