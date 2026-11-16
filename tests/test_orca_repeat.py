"""Patterns and mirrors in the Orca copy (`orca_translate/repeat.py`): the repeated steps written again as a tool
body, the Orca Pattern or Mirror on it with the bound counts, spacings and angles, and the Boolean into the part."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import (circular_sized, fixture, grid_sized, placed_hole_pattern, sized, symmetric_sized,
                               table_of)
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType
from lib.orca_translate import causes, translate
from lib.orca_translate.formulas import orca_value
from lib.orca_translate.place import plane_point


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def run(name, edit=None, table=None):
    capture = fixture(name)
    if edit is not None:
        edit(capture)
    return translate(capture, table)


class RectangularTest(unittest.TestCase):
    def test_the_repeated_cut_becomes_a_tool_body_repeated_and_cut_away(self):
        result = run("rpattern_row")
        cut, tool = of_type(result, FeatureType.EXTRUDE)[1:]
        (pattern,) = of_type(result, FeatureType.PATTERN)
        (boolean,) = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual(tool.sketch_ref, cut.sketch_ref)
        self.assertEqual(tool.mode, BooleanMode.NEW)
        self.assertEqual((pattern.target_body, pattern.pattern_count, pattern.pattern_spacing), (1, 3, 20.0))
        self.assertFalse(pattern.pattern_circular)
        self.assertEqual(pattern.plane.x_axis, (1.0, 0.0, 0.0))
        self.assertEqual((boolean.target_body, boolean.bool_tool_body, boolean.mode, boolean.bool_keep_tool),
                         (0, 1, BooleanMode.CUT, False))
        self.assertEqual(verdict_of(result, 4)["verdict"], "copied")

    def test_copies_that_run_against_the_stored_direction_turn_it(self):
        (pattern,) = of_type(run("rpattern_negative"), FeatureType.PATTERN)
        self.assertEqual(pattern.plane.x_axis, (-1.0, 0.0, 0.0))

    def test_two_directions_are_two_orca_patterns_with_counts_and_spacings_that_follow(self):
        capture = grid_sized()
        result = translate(capture, table_of(capture))
        first, second = of_type(result, FeatureType.PATTERN)
        self.assertEqual((first.pattern_count, first.pattern_spacing), (3, 20.0))
        self.assertEqual(first.expr, {"pattern_count": "columns",
                                      "pattern_spacing": "row_reach_mm / max(columns - 1, 1)"})
        self.assertEqual(second.expr, {"pattern_count": "rows", "pattern_spacing": "row_gap_mm / max(rows - 1, 1)"})
        self.assertEqual(second.plane.x_axis, (0.0, 1.0, 0.0))
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters},
                         dict.fromkeys(("columns", "row_reach_mm", "rows", "row_gap_mm"), "variable"))

    def test_a_direction_to_both_sides_is_two_tools_whose_counts_split_the_quantity(self):
        capture = symmetric_sized()
        result = translate(capture, table_of(capture))
        ahead, back = of_type(result, FeatureType.PATTERN)
        self.assertEqual(len(of_type(result, FeatureType.BOOLEAN)), 2)
        self.assertEqual((ahead.pattern_count, back.pattern_count), (3, 3))
        self.assertEqual((ahead.plane.x_axis, back.plane.x_axis), ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)))
        # Orca rounds a half up: n // 2 + 1 copies on the side with the extra one, (n - 1) // 2 + 1 on the other.
        for n, wanted in ((5, (3, 3)), (4, (3, 2)), (6, (4, 3)), (1, (1, 1))):
            got = tuple(int(round(orca_value(f.expr["pattern_count"], {"hole_count": n}) + 1e-9))
                        for f in (ahead, back))
            self.assertEqual(got, wanted, n)

    def test_a_reach_to_both_sides_keeps_the_count_fixed(self):
        capture = sized(fixture("rpattern_symmetric_extent"), 4, "quantity_one", "hole_count", 5, unit="")
        result = translate(capture, table_of(capture))
        self.assertEqual([f.pattern_spacing for f in of_type(result, FeatureType.PATTERN)], [10.0, 10.0])
        self.assertEqual(result.parameters[0]["outcome"], "fixed")

    def test_patterns_orca_cannot_build_are_left_out_with_their_cause(self):
        for name, cause in (("rpattern_skip", causes.COPIES_SUPPRESSED), ("rpattern_rotated_element",
                                                                         causes.COPIES_TURNED),
                            ("rpattern_faces", gap_hints.REPEAT_FACES), ("rpattern_symmetric", causes.COPIES_UNEVEN),
                            ("rpattern_fillet", causes.REPEATS_FINISH)):
            with self.subTest(name):
                result = run(name)
                (gap,) = [g for g in result.left_out if g["type"] == "RectangularPatternFeature"]
                self.assertEqual(gap["cause"], cause)
                self.assertEqual(of_type(result, FeatureType.PATTERN), [])

    def test_a_pattern_of_a_copied_round_is_left_out(self):
        def round_top(capture):
            # The four top edges of the 40 by 20 by 10 plate: a round Orca copies as its top edge group.
            top = [[20, 0, 10], [40, 10, 10], [20, 20, 10], [0, 10, 10]]
            capture["items"][3]["data"]["sets"][0]["edges"] = [
                {"token": "e%d" % n, "closed": False, "points": [p]} for n, p in enumerate(top)]
        result = run("rpattern_fillet", round_top)
        self.assertEqual(verdict_of(result, 3)["verdict"], "copied")
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out],
                         [("RectangularPattern1", causes.REPEATS_FINISH)])
        self.assertEqual(of_type(result, FeatureType.PATTERN), [])

    def test_a_repeated_hole_whose_place_follows_a_size_keeps_its_place(self):
        capture = placed_hole_pattern()
        result = translate(capture, table_of(capture, ["pipe_offset_mm"]))
        (hole,) = of_type(result, FeatureType.HOLE)
        # The copies are drilled where the hole is now, so a size change must not move the hole away from them.
        self.assertEqual(hole.expr.keys() & {"hole_x", "hole_y"}, set())
        self.assertFalse([b for b in result.bound if b["feature"] == hole.name and b["field"] in ("hole_x", "hole_y")])
        self.assertEqual(result.parameters[0]["outcome"], "fixed")
        self.assertEqual(verdict_of(result, 6)["verdict"], "copied")
        (tool,) = [f for f in of_type(result, FeatureType.SKETCH) if f.name.startswith("RectangularPattern1")]
        for a, b in zip(tool.plane.origin, plane_point(hole.plane, (hole.hole_x, hole.hole_y))):
            self.assertAlmostEqual(a, b)

    def test_inside_a_tool_body_such_a_pattern_leaves_the_combine_out(self):
        capture = placed_hole_pattern()
        tool = {"token": "t2", "name": "Body2"}
        items = capture["items"]
        maker = copy.deepcopy(items[1])
        maker.update(index=2, name="Extrude2", bodies_before=[capture["target"]], bodies_after=[tool])
        maker["data"]["participants"] = [tool]
        for item in items[2:]:
            item["bodies_after"] = [tool]
            item["data"]["participants"] = [tool]
        items.insert(2, maker)
        items.append({"index": 7, "name": "Combine1", "type": "CombineFeature", "suppressed": False, "health": "ok",
                      "in_target_component": True, "bodies_after": [capture["target"]],
                      "data": {"target": capture["target"], "tools": [tool], "operation": "join",
                               "keep_tools": False}})
        result = translate(capture, table_of(capture, ["pipe_offset_mm"]))
        self.assertEqual([(g["name"], g["cause"]) for g in result.left_out],
                         [("Combine1", causes.HOLE_PLACE_IN_TOOL)])
        self.assertEqual(of_type(result, FeatureType.HOLE), [])

    def test_a_repeated_hole_is_drilled_as_cylinders_of_its_size(self):
        result = run("rpattern_multi_hole")
        holes = of_type(result, FeatureType.HOLE)
        tools = [f for f in of_type(result, FeatureType.EXTRUDE) if f.name.startswith("RectangularPattern1")]
        self.assertEqual(len(tools), len(holes))
        self.assertEqual([t.mode for t in tools], [BooleanMode.NEW] + [BooleanMode.ADD] * (len(tools) - 1))
        self.assertTrue(all(t.extrude_end == ExtrudeEnd.THROUGH_ALL for t in tools))
        sketch = result.recipe.features[tools[0].sketch_ref]
        self.assertAlmostEqual(sketch.radius, holes[0].hole_diameter / 2.0)
        self.assertEqual(sketch.plane.normal, holes[0].plane.normal)

    def test_steps_that_add_and_steps_that_cut_get_a_tool_each(self):
        def edit(capture):
            items = capture["items"]
            boss = copy.deepcopy(items[3])
            boss.update(index=5, name="Boss")
            boss["data"].update(operation="join", side_one={"kind": "distance", "distance": 3.0, "taper_deg": 0.0},
                                end_offset=3.0)
            boss["data"]["profiles"][0]["loops"][0]["curves"][0]["center"] = [35, 10]
            pattern = items.pop(4)
            pattern["index"] = 6
            pattern["data"]["sources"] = [3, 5]
            items += [boss, pattern]
        result = run("rpattern_row", edit)
        self.assertEqual([b.mode for b in of_type(result, FeatureType.BOOLEAN)], [BooleanMode.CUT, BooleanMode.ADD])
        self.assertEqual(len(of_type(result, FeatureType.PATTERN)), 2)


class CircularTest(unittest.TestCase):
    def test_a_turn_about_the_axis_follows_its_count_and_angle(self):
        capture = circular_sized()
        result = translate(capture, table_of(capture))
        (pattern,) = of_type(result, FeatureType.PATTERN)
        self.assertTrue(pattern.pattern_circular)
        self.assertEqual((pattern.pattern_count, pattern.pattern_angle), (4, 90.0))
        self.assertEqual(pattern.expr, {"pattern_count": "hole_count", "pattern_angle": "spread_deg"})
        self.assertTrue(pattern.pattern_inclusive)
        bed = result.place.point([20, 10, 0])
        self.assertEqual(tuple(round(v, 9) for v in pattern.plane.origin), tuple(round(v, 9) for v in bed))

    def test_the_turning_sense_comes_from_the_copies(self):
        def turn_back(capture):
            # Each copy turned the other way about the axis through (20, 10).
            for element in capture["items"][4]["data"]["elements"]:
                frame = element["frame"]
                back = {k: [frame[n][i] for n in "xyz"] for i, k in enumerate("xyz")}
                moved = [sum(back[n][i] * [20, 10, 0]["xyz".index(n)] for n in "xyz") for i in range(3)]
                element["frame"] = dict(back, origin=[a - b for a, b in zip([20, 10, 0], moved)])
        forward = of_type(run("cpattern_part"), FeatureType.PATTERN)[0]
        backward = of_type(run("cpattern_part", turn_back), FeatureType.PATTERN)[0]
        self.assertEqual(abs(forward.plane.normal[2]), 1.0)
        self.assertEqual(backward.plane.normal[2], -forward.plane.normal[2])

    def test_a_full_turn_is_spread_evenly(self):
        (pattern,) = of_type(run("cpattern_full"), FeatureType.PATTERN)
        self.assertEqual((pattern.pattern_count, pattern.pattern_angle), (6, 360.0))

    def test_a_part_turn_to_both_sides_is_two_tools_with_fixed_numbers(self):
        capture = sized(fixture("cpattern_symmetric_part"), 4, "quantity", "hole_count", 5, unit="")
        result = translate(capture, table_of(capture))
        patterns = of_type(result, FeatureType.PATTERN)
        self.assertEqual([(p.pattern_count, p.pattern_angle) for p in patterns], [(3, 45.0), (3, 45.0)])
        self.assertEqual([p.plane.normal[2] for p in patterns], [1.0, -1.0])
        self.assertEqual(result.parameters[0]["outcome"], "fixed")

    def test_suppressed_copies_leave_the_pattern_out(self):
        self.assertEqual(verdict_of(run("cpattern_skip"), 4)["verdict"], "leftOut")


class MirrorTest(unittest.TestCase):
    def test_a_mirror_of_features_joins_the_tool_with_its_image(self):
        result = run("mirror_features")
        (mirror,) = of_type(result, FeatureType.MIRROR)
        (boolean,) = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual((mirror.mode, mirror.target_body, mirror.mirror_keep_original), (BooleanMode.ADD, 1, True))
        self.assertEqual(mirror.plane.normal, (1.0, 0.0, 0.0))
        self.assertEqual(mirror.plane.origin[0], result.place.point([0, 0, 0])[0])
        self.assertEqual(boolean.mode, BooleanMode.ADD)

    def test_a_mirror_of_the_body_joined_to_it_mirrors_the_part(self):
        result = run("mirror_body")
        (mirror,) = of_type(result, FeatureType.MIRROR)
        self.assertEqual((mirror.mode, mirror.target_body), (BooleanMode.ADD, 0))
        self.assertEqual(of_type(result, FeatureType.BOOLEAN), [])

    def test_a_mirrored_copy_kept_apart_does_not_change_the_part(self):
        result = run("mirror_body", lambda c: c["items"][6]["data"].update(combine=False))
        verdict = verdict_of(result, 6)
        self.assertEqual(verdict["verdict"], "skipped")
        self.assertEqual(of_type(result, FeatureType.MIRROR), [])

    def test_a_mirror_of_a_step_left_out_is_left_out(self):
        thin = run("mirror_on_moved_face", lambda c: c["items"][3]["data"].update(thin=True))
        self.assertEqual(verdict_of(thin, 4)["verdict"], "leftOut")


class CopiesInTheShapeTest(unittest.TestCase):
    def test_a_cut_through_a_repeated_copy_meets_the_part(self):
        def edit(capture):
            items = capture["items"]
            items[3]["data"].update(operation="join", side_one={"kind": "distance", "distance": 4.0,
                                                                "taper_deg": 0.0}, end_offset=4.0)
            later = copy.deepcopy(items[3])
            later.update(index=5, name="CutTop")
            later["data"].update(operation="cut", side_one={"kind": "distance", "distance": -2.0, "taper_deg": 0.0},
                                 end_offset=-2.0)
            later["data"]["profiles"][0]["frame"]["origin"] = [0, 0, 14]
            later["data"]["profiles"][0]["loops"][0]["curves"][0]["center"] = [25, 10]
            items.append(later)
        result = run("rpattern_row", edit)
        self.assertEqual(verdict_of(result, 5)["verdict"], "copied")


if __name__ == "__main__":
    unittest.main()
