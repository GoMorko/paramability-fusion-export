"""Path patterns on one straight line, arc or circle, written as the rectangular or circular pattern they equal."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.derived_fixtures import dimension
from tests.sketch_solve_helpers import L, P, Sketch
from tests.test_translate_sized import table_of
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, translate_fixture

from lib.capture_model import gap_hints
from lib.design_model import words as shared
from lib.geometry import vec
from lib.design_model.problem import is_problem
from lib.design_model.steps import path_pattern
from lib.params.expressions import evaluate
from lib.probe.plan.covered import scan
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate
from lib.translator.ranges.range_check import recipe_size_values

LINE, ARC = "ppattern_line", "ppattern_arc"
SIZES = ["count", "pitch"]


def capture_of(name, edit=None):
    capture = copy.deepcopy(load_capture(name))
    if edit:
        edit(capture["items"][-1]["data"])
    return capture


def sized(name, edit=None, ticked=SIZES):
    capture = capture_of(name, edit)
    table = table_of(capture, ticked)
    return translate(capture, size_table=table), table


def gap_of(result):
    return next(g for g in result.gaps if g["name"] == "PathPattern1")


class PathPatternTest(unittest.TestCase):
    def test_a_line_path_is_a_row_along_the_line(self):
        result = translate_fixture(LINE)
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertEqual(pattern["linear"], {"dir": [1, 0, 0], "count": 3, "step": 15})
        self.assertEqual(pattern["of"], ["extrude_3"])
        assert_schema_ok(self, result.recipe)

    def test_an_arc_path_is_a_turn_about_the_arc_centre(self):
        result = translate_fixture(ARC)
        (pattern,) = steps_of(result.recipe, "pattern")
        polar = pattern["polar"]
        self.assertEqual((polar["axisPoint"], polar["axis"], polar["count"]), ([20, 10, 10], [0, 0, 1], 3))
        self.assertAlmostEqual(polar["angleDeg"], 60.0, places=6)
        assert_schema_ok(self, result.recipe)

    def test_a_full_circle_path_turns_evenly_and_keeps_its_distance(self):
        def full(data):
            data["path"]["curves"][0].update(kind="circle")
            data["distance_type"] = "extent"
            data["distance"] = 2 * math.pi * 8.0
            data["params"]["distance"] = {"name": "d4", "expression": "pitch * 12", "value": 2 * math.pi * 8.0}
            data["path"]["closed"] = True
            turn = data["elements"]
            for element, angle in zip(turn, (0, 120, 240)):
                a = math.radians(angle)
                ca, sa = math.cos(a), math.sin(a)
                element["frame"] = {"origin": [20 - (ca * 20 - sa * 10), 10 - (sa * 20 + ca * 10), 0.0],
                                    "x": [ca, sa, 0.0], "y": [-sa, ca, 0.0], "z": [0.0, 0.0, 1.0]}
        result, _ = sized(ARC, full)
        (pattern,) = steps_of(result.recipe, "pattern")
        self.assertNotIn("angleDeg", pattern["polar"])
        self.assertEqual(pattern["polar"]["count"], {"expr": "count"})
        self.assertNotIn("pitch", result.recipe.get("sizes") or {})
        self.assertIn("pitch", [entry["name"] for entry in result.loose + result.dropped])

    def test_count_and_spacing_follow_and_the_ranges_keep_the_copies_on_the_path(self):
        for name in (LINE, ARC):
            with self.subTest(name):
                result, table = sized(name)
                (pattern,) = steps_of(result.recipe, "pattern")
                self.assertEqual(sorted(c["name"] for c in result.cuts), SIZES)
                self.assertEqual(result.loose, [])
                if name == ARC:
                    angle = pattern["polar"]["angleDeg"]["expr"]
                    env = recipe_size_values(table, {})
                    self.assertAlmostEqual(evaluate(angle, env), 60.0, places=4)
                    env = dict(env, count=4)
                    self.assertAlmostEqual(evaluate(angle, env), 90.0, places=4)

    def test_a_size_that_moves_the_path_sketch_is_marked(self):
        capture = capture_of(ARC)
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][3], name="d5",
                                                   expression="pitch * 2",
                                                   created_by={"kind": "sketchDimension", "sketch": "Sketch4"}))
        capture["parameters"]["user"][1]["dependent_parameters"].append("d5")
        result = translate(capture, size_table=table_of(capture, SIZES), motion=Motion({}))
        self.assertEqual(len(steps_of(result.recipe, "pattern")), 1)
        self.assertEqual([entry["name"] for entry in result.loose], ["pitch"])

    def test_a_size_the_probe_tried_on_the_path_sketch_is_marked_only_when_it_moved_the_path(self):
        capture = capture_of(ARC)
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][3], name="d5",
                                                   expression="pitch * 2",
                                                   created_by={"kind": "sketchDimension", "sketch": "Sketch4"}))
        capture["parameters"]["user"][1]["dependent_parameters"].append("d5")
        tried = {"states": [{"values": {"pitch": 5.0}}], "curves": ["5/path"]}
        still = translate(capture, size_table=table_of(capture, SIZES), motion=Motion({}, **tried))
        moved = Motion({"5/path/c0/radius": Affine(0.0, {"pitch": 2.0}, "Sketch4")}, **tried)
        bent = translate(capture, size_table=table_of(capture, SIZES), motion=moved)
        self.assertEqual([[entry["name"] for entry in result.loose] for result in (still, bent)], [[], ["pitch"]])

    def test_a_line_path_marks_only_the_sizes_that_turn_or_stretch_the_line(self):
        def line_sized_by(reads_pitch):
            # Sketch4 holds the path line from (5, 10) to (35, 10); d5 = pitch - 5 sets the dimension `reads_pitch`.
            capture = capture_of(LINE)
            capture["parameters"]["model"].append(dict(capture["parameters"]["model"][3], name="d5",
                                                       expression="pitch - 5",
                                                       created_by={"kind": "sketchDimension", "sketch": "Sketch4"}))
            capture["parameters"]["user"][1]["dependent_parameters"].append("d5")
            sketch = Sketch()
            start, end = sketch.point(5.0, 10.0), sketch.point(35.0, 10.0)
            sketch.con("horizontal", L(sketch.line(start, end)))
            for on, value, orientation, name in (((0, start), 5.0, "horizontal", "place"),
                                                 ((0, start), 10.0, "vertical", "height"),
                                                 ((start, end), 30.0, "horizontal", "length")):
                param, expression = ("d5", "pitch - 5") if name == reads_pitch else ("g_" + name, "%g mm" % value)
                dimension(sketch, "linear", [P(on[0]), P(on[1])], value, param, expression, orientation)
            capture["sketch_graphs"] = [dict(sketch.record(), sketch="Sketch4", token="s4")]
            result = translate(capture, size_table=table_of(capture, SIZES), motion=Motion({}))
            self.assertEqual(len(steps_of(result.recipe, "pattern")), 1)
            return [entry["name"] for entry in result.loose]
        self.assertEqual([line_sized_by(name) for name in ("height", "length")], [[], ["pitch"]])

    def test_the_path_sketch_stays_followed_by_the_size_probe(self):
        self.assertIn("s4", scan(load_capture(LINE)).covered)


def turned_copies(*angles):
    """Frames of the original and its copies on the arc of `ppattern_arc`, turned `angles` degrees about its centre."""
    frames = []
    for angle in (0,) + angles:
        a = math.radians(angle)
        ca, sa = math.cos(a), math.sin(a)
        frames.append({"origin": [20 - (ca * 20 - sa * 10), 10 - (sa * 20 + ca * 10), 0.0],
                       "x": [ca, sa, 0.0], "y": [-sa, ca, 0.0], "z": [0.0, 0.0, 1.0]})
    return frames


class OpposedArcTest(unittest.TestCase):
    """An arc path whose sense is opposed to the arc's: the start point still counts from the start of the path."""

    def opposed(self, start_point):
        def edit(data):
            data["path"]["curves"][0]["opposed"] = True
            data["start_point"] = start_point
            for element, frame in zip(data["elements"], turned_copies(-30, -60)):
                element["frame"] = frame
        return translate(capture_of(ARC, edit))

    def test_the_copies_turn_the_way_of_the_path(self):
        (pattern,) = steps_of(self.opposed(0.0).recipe, "pattern")
        self.assertEqual(pattern["polar"]["axis"], [0, 0, -1])

    def test_a_start_point_part_way_along_the_arc_leaves_the_step_out(self):
        # Fusion has been seen to put such copies off the arc.
        self.assertEqual(left_out(self.opposed(0.25))["index"], 5)


SOURCE_FACES = [{"center": [5.0, 5.0, 5.0], "area": 30.0}, {"center": [8.0, 5.0, 5.0], "area": 20.0}]


def with_faces(data, moves=None, source=SOURCE_FACES):
    """Give the original its faces and each copy the faces its frame puts them at. `moves` maps a copy id to the
    frame whose places the faces take instead."""
    data["source_faces"] = source
    for element in data["elements"]:
        frame = (moves or {}).get(element["id"], element["frame"])
        element["faces"] = [{"center": vec.frame_apply(frame, f["center"]), "area": f["area"]} for f in source]


class PathPatternFacesTest(unittest.TestCase):
    """The faces of the copies check the places that the transforms give, as for the plain patterns."""

    def test_faces_that_sit_where_the_transforms_put_them_copy(self):
        result = translate(capture_of(LINE, with_faces))
        self.assertEqual(len(steps_of(result.recipe, "pattern")), 1)

    def test_a_copy_whose_faces_sit_off_its_place_leaves_the_step_out(self):
        def shifted(data):
            moved = {"origin": [30.0 + 3.0, 0.0, 0.0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
            with_faces(data, {3: moved})
        result = translate(capture_of(LINE, shifted))
        self.assertEqual(left_out(result)["index"], 5)
        self.assertEqual(gap_of(result)["reason"], shared.PATTERN_FACES_DISAGREE)

    def test_the_faces_pick_the_turn_of_a_round_path(self):
        # The transforms turn one way and the faces the other: the faces say where Fusion put the copies.
        def opposite(data):
            back = dict(zip((0, 1, 2), turned_copies(-30, -60)))
            with_faces(data, back, [{"center": [28.0, 12.0, 5.0], "area": 30.0}])
        (pattern,) = steps_of(translate(capture_of(ARC, opposite)).recipe, "pattern")
        self.assertEqual(pattern["polar"]["axis"], [0, 0, -1])


class PathPatternLeftOutTest(unittest.TestCase):
    def assert_left_out(self, name, edit, problem=None):
        """The step is left out with the path pattern's hint, and, for a path the layout cannot read, the problem
        it names (`problem`, a code of `path_pattern`)."""
        capture = capture_of(name, edit)
        result = translate(capture)
        self.assertEqual(left_out(result)["index"], 5)
        self.assertEqual(gap_of(result)["hint"], gap_hints.HINTS[gap_hints.PATH_PATTERN])
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 2)
        found = path_pattern.layout(capture["items"][-1]["data"])
        self.assertEqual(found.code if is_problem(found) else None, problem)

    def test_a_path_of_two_curves(self):
        def two(data):
            data["path"]["curves"].append(copy.deepcopy(data["path"]["curves"][0]))
        self.assert_left_out(LINE, two, path_pattern.CURVE.code)

    def test_copies_to_both_sides_of_the_start_point(self):
        self.assert_left_out(LINE, lambda data: data.update(symmetric=True), path_pattern.BOTH_SIDES.code)

    def test_copies_that_keep_their_direction_on_a_round_path(self):
        self.assert_left_out(ARC, lambda data: data.update(along_path=False), path_pattern.SLIDES.code)

    def test_a_setting_that_could_not_be_read(self):
        self.assert_left_out(LINE, lambda data: data.update(start_point=None), path_pattern.UNREAD.code)

    def test_copies_past_the_end_of_the_path(self):
        self.assert_left_out(LINE, lambda data: data.update(start_point=0.5))

    def test_copies_that_run_against_the_way_the_path_was_read(self):
        self.assert_left_out(LINE, lambda data: data.update(flip=True))

    def test_copies_flipped_against_a_round_path(self):
        self.assert_left_out(ARC, lambda data: data.update(flip=True))

    def test_copies_that_do_not_turn_by_the_distance_along_the_arc(self):
        self.assert_left_out(ARC, lambda data: data.update(distance=data["distance"] * 1.01))


if __name__ == "__main__":
    unittest.main()
