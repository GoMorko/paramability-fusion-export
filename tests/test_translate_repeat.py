import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_copies import counted
from tests.test_translate_sized import table_of
from tests.translator_helpers import assert_schema_ok, edited, left_out, load_capture, steps_of, translate_fixture, verdict_of

from lib.translator import translate


def pattern_data(capture):
    return capture["items"][-1]["data"]


class RectangularPatternTest(unittest.TestCase):
    def test_row_repeats_the_source_step(self):
        result = translate_fixture("rpattern_row")
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["of"], verdict_of(result, 3)["steps"])
        self.assertEqual(pattern["linear"], {"dir": [1, 0, 0], "count": 3, "step": 20})
        self.assertNotIn("linear2", pattern)
        self.assertNotIn("skip", pattern)
        assert_schema_ok(self, result.recipe)

    def test_extent_distance_divides_by_the_gaps(self):
        result = translate_fixture("rpattern_grid_extent")
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["linear"]["step"], 20)
        self.assertEqual(pattern["linear2"], {"dir": [0, 1, 0], "count": 2, "step": 10})
        assert_schema_ok(self, result.recipe)

    def test_an_unread_distance_kind_is_told_by_the_copies(self):
        for name, step in (("rpattern_row", 20), ("rpattern_grid_extent", 20)):
            with self.subTest(name):
                result = edited(name, lambda capture: pattern_data(capture).update(distance_type="other"))
                self.assertEqual(steps_of(result.recipe, "pattern")[0]["linear"]["step"], step)

    def test_suppressed_and_missing_copies_are_skipped_by_number(self):
        for name in ("rpattern_skip", "rpattern_missing_element"):
            with self.subTest(name):
                result = translate_fixture(name)
                self.assertEqual(steps_of(result.recipe, "pattern")[0]["skip"], [5])
                assert_schema_ok(self, result.recipe)

    def test_missing_original_refuses(self):
        def edit(capture):
            del pattern_data(capture)["elements"][0]
        result = edited("rpattern_row", edit)
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 4)

    def test_copies_running_against_the_direction_negate_it(self):
        (pattern,) = steps_of(translate_fixture("rpattern_negative").recipe, "pattern")
        self.assertEqual(pattern["linear"], {"dir": [-1, 0, 0], "count": 3, "step": 10})

    def test_second_direction_alone_becomes_the_row(self):
        def edit(capture):
            data = pattern_data(capture)
            data.update({"quantity_one": 1, "direction_two": [0, 1, 0], "quantity_two": 3, "distance_two": 5.0,
                         "elements": [dict(e, frame=dict(e["frame"], origin=[0, 5.0 * n, 0]))
                                      for n, e in enumerate(data["elements"])]})
        (pattern,) = steps_of(edited("rpattern_row", edit).recipe, "pattern")
        self.assertEqual(pattern["linear"], {"dir": [0, 1, 0], "count": 3, "step": 5})
        self.assertNotIn("linear2", pattern)

    def test_refusals(self):
        def both_sides(capture):
            for e, x in zip(pattern_data(capture)["elements"], (0, -20, 20)):
                e["frame"]["origin"] = [x, 0, 0]

        def off_grid(capture):
            pattern_data(capture)["elements"][1]["frame"]["origin"] = [20, 1, 0]

        def wrong_count(capture):
            pattern_data(capture)["quantity_one"] = 2

        def source_without_step(capture):
            pattern_data(capture)["sources"] = [2]

        cases = [
            ("symmetric", translate_fixture("rpattern_symmetric")),
            ("faces", translate_fixture("rpattern_faces")),
            ("turned copy", translate_fixture("rpattern_rotated_element")),
            ("both sides", edited("rpattern_row", both_sides)),
            ("off grid", edited("rpattern_row", off_grid)),
            ("count mismatch", edited("rpattern_row", wrong_count)),
            ("source made no step", edited("rpattern_row", source_without_step)),
        ]
        for label, result in cases:
            with self.subTest(label):
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 4)

    def test_drill_tip_and_multi_point_holes(self):
        tip = translate_fixture("rpattern_drill_tip")
        self.assertEqual(steps_of(tip.recipe, "pattern")[0]["of"], verdict_of(tip, 3)["steps"])
        multi = translate_fixture("rpattern_multi_hole")
        self.assertEqual(steps_of(multi.recipe, "pattern")[0]["of"], ["hole_3", "hole_3_2"])
        assert_schema_ok(self, multi.recipe)

    def test_pattern_of_a_pattern_names_the_inner_one(self):
        def edit(capture):
            outer = copy.deepcopy(capture["items"][-1])
            outer.update({"index": 5, "name": "RectangularPattern2"})
            outer["data"]["sources"] = [4]
            capture["items"].append(outer)
        result = edited("rpattern_row", edit)
        self.assertEqual(steps_of(result.recipe, "pattern")[1]["of"], ["pattern_4"])


class PatternOfFinishTest(unittest.TestCase):
    def test_fillet_copies_get_their_own_round(self):
        result = translate_fixture("rpattern_fillet")
        source, copies = steps_of(result.recipe, "round")
        self.assertEqual(steps_of(result.recipe, "pattern"), [])
        self.assertEqual(copies["edges"]["near"], [
            [0, 3, 5], [40, 3, 5], [0, 6, 5], [40, 6, 5], [0, 9, 5], [40, 9, 5]])
        self.assertEqual(copies["size"], source["size"])
        assert_schema_ok(self, result.recipe)

    def test_skipped_copies_get_no_round_points(self):
        def edit(capture):
            data = pattern_data(capture)
            data["elements"][2]["suppressed"] = True
        (_, copies) = steps_of(edited("rpattern_fillet", edit).recipe, "round")
        self.assertEqual([p[1] for p in copies["edges"]["near"]], [3, 3, 9, 9])

    def test_chamfer_becomes_bevel(self):
        def edit(capture):
            chamfer = load_capture("chamfer_equal")["items"][-1]
            chamfer["index"] = 3
            capture["items"][3] = chamfer
        result = edited("rpattern_fillet", edit)
        self.assertEqual([s["kind"] for s in result.recipe["features"][-2:]], ["bevel", "bevel"])
        assert_schema_ok(self, result.recipe)

    def test_sizes_follow_each_point_into_every_copy(self):
        def edit(capture):
            sets = capture["items"][3]["data"]["sets"]
            sets.append(copy.deepcopy(sets[0]))
            sets[1]["radius"] = 3.0
        source, copies = steps_of(edited("rpattern_fillet", edit).recipe, "round")
        self.assertEqual(source["edgeSizes"], [2, 2, 3, 3])
        self.assertEqual(copies["edgeSizes"], [2, 2, 3, 3] * 3)

    def test_long_copy_lists_split_without_cutting_a_copy(self):
        def edit(capture):
            edges = capture["items"][3]["data"]["sets"][0]["edges"]
            edges[:] = [{"token": "e%d" % n, "closed": False, "points": [[n, 0, 5]]} for n in range(12)]
        result = edited("rpattern_fillet", edit)
        rounds = steps_of(result.recipe, "round")
        self.assertEqual([len(s["edges"]["near"]) for s in rounds[1:]], [24, 12])
        assert_schema_ok(self, result.recipe)


class CircularPatternTest(unittest.TestCase):
    def test_full_turn_has_no_angle(self):
        result = translate_fixture("cpattern_full")
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["polar"], {"axisPoint": [20, 10, 0], "axis": [0, 0, 1], "count": 6})
        self.assertEqual(pattern["of"], verdict_of(result, 3)["steps"])
        assert_schema_ok(self, result.recipe)

    def test_part_turn_the_negative_way_negates_the_axis(self):
        result = translate_fixture("cpattern_part")
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["polar"]["axis"], [0, 0, -1])
        self.assertEqual(pattern["polar"]["angleDeg"], 90)
        self.assertEqual(pattern["polar"]["count"], 4)
        assert_schema_ok(self, result.recipe)

    def test_skip_lists_turn_numbers(self):
        result = translate_fixture("cpattern_skip")
        self.assertEqual(steps_of(result.recipe, "pattern")[0]["skip"], [2, 4])
        assert_schema_ok(self, result.recipe)

    def test_refusals(self):
        def uneven(capture):
            pattern_data(capture)["elements"][1]["frame"] = copy.deepcopy(pattern_data(capture)["elements"][2]["frame"])
            pattern_data(capture)["elements"][2]["suppressed"] = True

        def other_axis(capture):
            pattern_data(capture)["axis"]["point"] = [0, 0, 0]

        cases = [
            ("uneven spread", edited("cpattern_full", lambda c: pattern_data(c)["elements"][1]["frame"].update(
                x=[0.8, 0.6, 0], y=[-0.6, 0.8, 0]))),
            ("other axis point", edited("cpattern_full", other_axis)),
            ("no axis", edited("cpattern_full", lambda c: pattern_data(c).update(axis={"kind": "other"}))),
        ]
        for label, result in cases:
            with self.subTest(label):
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 4)

    def test_fillet_points_turn_with_each_copy(self):
        def edit(capture):
            fillet = load_capture("rpattern_fillet")["items"][3]
            capture["items"][3] = fillet
            data = pattern_data(capture)
            data.update(quantity=2, elements=data["elements"][:0] + [
                {"id": 1, "suppressed": False, "frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}},
                {"id": 2, "suppressed": False, "frame": {"origin": [40, 20, 0], "x": [-1, 0, 0], "y": [0, -1, 0], "z": [0, 0, 1]}}])
            data["total_angle_deg"] = 360.0
        result = edited("cpattern_full", edit)
        source, copy_step = steps_of(result.recipe, "round")
        self.assertEqual(copy_step["edges"]["near"], [[40, 20, 5], [0, 20, 5]])
        assert_schema_ok(self, result.recipe)


class MirrorTest(unittest.TestCase):
    def test_features_mirror_across_the_plane(self):
        result = translate_fixture("mirror_features")
        (mirror,) = steps_of(result.recipe, "mirror")
        self.assertEqual(mirror["of"], verdict_of(result, 3)["steps"])
        self.assertEqual(mirror["plane"], {"origin": [0, 0, 0], "normal": [1, 0, 0]})
        assert_schema_ok(self, result.recipe)

    def test_a_plane_on_a_face_that_a_size_moves_follows_the_size(self):
        capture = load_capture("mirror_on_moved_face")
        result = translate(capture, size_table=table_of(capture, ["h"]))
        self.assertEqual((result.fixed, result.loose), ([], []))
        (mirror,) = steps_of(result.recipe, "mirror")
        self.assertEqual(mirror["plane"]["origin"], [0, 0, {"expr": "h"}])
        assert_schema_ok(self, result.recipe)

    def test_fillet_points_are_reflected(self):
        result = translate_fixture("mirror_fillet")
        source, copy_step = steps_of(result.recipe, "round")
        self.assertEqual(source["edges"]["near"], [[-20, -10, 5]])
        self.assertEqual(copy_step["edges"]["near"], [[20, -10, 5]])
        assert_schema_ok(self, result.recipe)

    def test_fillet_on_the_plane_refuses_instead_of_rounding_twice(self):
        self.assertIsNotNone(left_out(translate_fixture("mirror_fillet_on_plane")))

    def test_fillet_partly_on_the_plane_copies_only_the_off_plane_edge_with_its_size(self):
        source, copy_step = steps_of(translate_fixture("mirror_fillet_partly_on_plane").recipe, "round")
        self.assertEqual(len(source["edges"]["near"]), 2)
        self.assertEqual(copy_step["edges"]["near"], [[20, -10, 5]])

        def edit(capture):
            sets = capture["items"][3]["data"]["sets"]
            sets.append(copy.deepcopy(sets[0]))
            sets[0]["radius"], sets[1]["radius"] = 2.0, 3.0
            sets[0]["edges"][0]["points"] = [[0, -10, 5]]
            sets[1]["edges"][0]["points"] = [[-20, -10, 5]]
        _, copy_step = steps_of(edited("mirror_fillet_partly_on_plane", edit).recipe, "round")
        self.assertEqual((copy_step["edges"]["near"], copy_step["edgeSizes"]), ([[20, -10, 5]], [3]))

    def test_body_mirror_of_a_part_on_one_side(self):
        result = translate_fixture("mirror_body")
        (mirror,) = steps_of(result.recipe, "mirror")
        self.assertEqual(mirror["of"], [s["id"] for s in result.recipe["features"][:-1]])
        assert_schema_ok(self, result.recipe)

    def test_body_mirror_bounds_a_drill_tip_cut(self):
        result = translate_fixture("mirror_body_tip_hole")
        self.assertEqual(steps_of(result.recipe, "mirror")[0]["of"], ["extrude_1", "revolve_3"])

        def across(capture):
            data = capture["items"][3]["data"]
            data["positions"] = [[1, 0, 10]]
            data["side_cylinders"][0]["origin"] = [1, 0, 10]
        self.assertEqual(steps_of(edited("mirror_body_tip_hole", across).recipe, "mirror")[0]["of"], ["body_4"])

    def test_a_body_its_steps_cannot_mirror_one_by_one_is_gathered_into_one_tool_and_mirrored(self):
        no_box = edited("mirror_body", lambda c: pattern_data(c).pop("target_box_before"))
        cases = [
            ("straddles the plane", translate_fixture("mirror_body_straddling")),
            ("a cut reaches across", translate_fixture("mirror_body_cut_across")),
            ("part not measured", no_box),
            ("round before it", translate_fixture("mirror_body_after_round")),
        ]
        for label, result in cases:
            with self.subTest(label):
                gathered = result.recipe["features"][0]
                self.assertEqual((gathered["kind"], gathered["combine"]), ("toolBody", "new"))
                self.assertEqual(steps_of(result.recipe, "mirror")[0]["of"], [gathered["id"]])
                assert_schema_ok(self, result.recipe)

    def test_a_mirrored_body_not_joined_to_the_part_is_left_out(self):
        result = edited("mirror_body", lambda c: pattern_data(c).update(combine=False))
        self.assertEqual(left_out(result)["type"], "MirrorFeature")

    def test_other_refusals(self):
        no_plane = edited("mirror_features", lambda c: pattern_data(c).update(plane=None))
        faces = edited("mirror_features", lambda c: pattern_data(c).update(entity_type="faces"))
        for result in (no_plane, faces):
            self.assertIsNotNone(left_out(result))


class RepeatedStepsTest(unittest.TestCase):
    def test_steps_that_grow_with_the_part_refuse(self):
        def through(capture):
            capture["items"][3]["data"]["side_one"] = {"kind": "throughAll", "positive": False, "taper_deg": 0.0}

        def to_face(capture):
            capture["items"][3]["data"]["side_one"] = {"kind": "toEntity", "plane": {"point": [0, 0, 6], "normal": [0, 0, 1]}, "offset": 0.0}

        def separate_body(capture):
            pattern_data(capture)["sources"] = [1]

        for label, edit in (("through all", through), ("to a face", to_face), ("new body", separate_body)):
            with self.subTest(label):
                result = edited("rpattern_row", edit)
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 4)


class CopyCapTest(unittest.TestCase):
    """The app counts a repeat among the sources as all the bodies it makes, original included."""

    def nested(self, outer_count):
        def edit(capture):
            first = pattern_data(capture)
            first.update(quantity_one=8, quantity_two=8, direction_two=[0, 1, 0], distance_one=5.0, distance_two=5.0,
                         elements=[{"id": n + 1, "suppressed": False,
                                    "frame": {"origin": [5.0 * (n % 8), 5.0 * (n // 8), 0], "x": [1, 0, 0],
                                              "y": [0, 1, 0], "z": [0, 0, 1]}} for n in range(64)])
            outer = copy.deepcopy(capture["items"][-1])
            outer.update({"index": 5, "name": "RectangularPattern2"})
            outer["data"].update(sources=[4], quantity_one=outer_count, quantity_two=1, direction_two=None,
                                 distance_one=50.0, elements=[
                                     {"id": n + 1, "suppressed": False,
                                      "frame": {"origin": [0, 0, 50.0 * n], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
                                     for n in range(outer_count)])
            outer["data"]["direction_one"] = [0, 0, 1]
            capture["items"].append(outer)
        return edited("rpattern_row", edit)

    def test_nested_pattern_under_the_cap(self):
        # 63 copies, then 3 copies of the 64 bodies: 63 + 192 = 255
        self.assertIsNotNone(self.nested(4).recipe)

    def test_nested_pattern_over_the_cap(self):
        # 63 + 4 * 64 = 319
        result = self.nested(5)
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 5)


def _grid(capture, columns, rows):
    pattern_data(capture).update(
        quantity_one=columns, quantity_two=rows, direction_two=[0, 1, 0], distance_one=5.0, distance_two=5.0,
        elements=[{"id": n + 1, "suppressed": False,
                   "frame": {"origin": [5.0 * (n % columns), 5.0 * (n // columns), 0], "x": [1, 0, 0],
                             "y": [0, 1, 0], "z": [0, 0, 1]}} for n in range(columns * rows)])


class CountVersionTest(unittest.TestCase):
    """Recipes before version 15 take at most 64 copies per pattern count."""

    def test_a_pattern_of_more_than_64_copies_is_a_version_15_recipe(self):
        for columns, rows, wide in ((64, 1, False), (65, 1, True), (8, 9, True)):
            with self.subTest(columns=columns, rows=rows):
                result = edited("rpattern_row", lambda capture: _grid(capture, columns, rows))
                self.assertEqual(result.recipe["version"] >= 15, wide)
                assert_schema_ok(self, result.recipe)

    def test_a_count_whose_size_range_passes_64_copies_is_a_version_15_recipe(self):
        capture, table = counted(ranges={"holes_count": (1, 80)})
        self.assertEqual(translate(capture, size_table=table).recipe["version"], 15)


if __name__ == "__main__":
    unittest.main()
