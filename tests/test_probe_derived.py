"""Derived values (shadow mode): what the sketch solver says about a sketch, set against what the probe read."""
import copy
import json
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.derived_fixtures import (
    ANGLE_MODEL, ANGLE_PARAMS, corner_capture, corner_states, dimension, plate_capture, plate_graph, plate_profile,
    plate_states, plate_table, row_of_rectangles, triangle_capture, triangle_states)
from tests.probe_helpers import line, profile, table

from lib.probe import build, derived, derived_sizes
from lib.sketch_solve.solve import solve_sketch


def block(capture, states, table=None):
    """The `derived` block and its first sketch record, with the measured motion of the same states."""
    table = table or plate_table()
    found = derived.shadow(capture, table, states, build.build(capture, table, states))
    return found, found["sketches"][0]


def text_of(sketch, key):
    return sketch["keys"][key]["formula"]


class AgreementTest(unittest.TestCase):
    def test_a_dimensioned_rectangle_agrees_with_every_state_the_probe_read(self):
        found, sketch = block(plate_capture(), plate_states())
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual((sketch["values"], sketch["reasons"]), ({"derived": 15, "not_derived": 0}, {}))
        compare = sketch["compare"]
        self.assertEqual((compare["agree"], compare["disagree"], compare["never_compared"]), (15, 0, 0))
        self.assertLess(compare["max_diff"], 1e-6)
        self.assertEqual(compare["states"], 5)
        self.assertEqual(found["summary"]["agree"], 15)

    def test_each_key_is_a_formula_over_the_size_names(self):
        sketch = block(plate_capture(), plate_states())[1]
        self.assertEqual(text_of(sketch, "4/p0/l0/center.0"), "0.5 * width")
        self.assertEqual(text_of(sketch, "4/p0/l0/height"), "height")
        self.assertEqual(text_of(sketch, "4/p0/l1/center.0"), "-margin + width")
        self.assertEqual(text_of(sketch, "4/p0/l1/radius"), "2")
        self.assertEqual(sketch["keys"]["4/p0/l1/radius"]["kind"], "const")

    def test_two_dimensions_that_read_one_size_move_together(self):
        """The height is dimensioned twice. Moved one dimension at a time the two disagree; moved by the size they
        read, they agree."""
        record = plate_graph()[0]
        self.assertEqual(solve_sketch(record).outcome, "not_derived")
        self.assertEqual(block(plate_capture(), plate_states())[1]["solver_outcome"], "derived")

    def test_the_measured_fit_and_the_derived_formula_name_the_same_sizes(self):
        sketch = block(plate_capture(), plate_states())[1]
        self.assertEqual(sketch["compare"]["measured_fit"], {"same": 15})

    def test_a_value_that_disagrees_with_a_read_state_is_recorded_and_not_fatal(self):
        found, sketch = block(plate_capture(), plate_states(follow_margin=False))
        compare = sketch["compare"]
        self.assertEqual((compare["agree"], compare["disagree"]), (14, 1))
        self.assertEqual(compare["listed"], [{"key": "4/p0/l1/center.0", "state": 4, "derived": 37.0, "read": 35.0,
                                              "sizes": {"margin": 3.0}}])
        self.assertAlmostEqual(compare["max_diff"], 2.0)
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(found["summary"]["disagree"], 1)
        again = compare["measured_fit_listed"][0]
        self.assertEqual((again["derived_sizes"], again["measured_sizes"]), (["margin", "width"], ["width"]))

    def test_without_a_measured_motion_the_comparison_still_runs(self):
        found = derived.shadow(plate_capture(), plate_table(), plate_states(), None)
        compare = found["sketches"][0]["compare"]
        self.assertEqual(compare["agree"], 15)
        self.assertNotIn("measured_fit", compare)

    def test_the_block_is_plain_data(self):
        found = block(plate_capture(), plate_states(follow_margin=False))[0]
        self.assertEqual(json.loads(json.dumps(found, allow_nan=False)), found)

    def test_a_capture_without_sketch_graphs_has_no_block(self):
        self.assertIsNone(derived.shadow(plate_capture(graph=False), plate_table(), plate_states()))


class KeyMappingTest(unittest.TestCase):
    def test_lines_arcs_and_circles_get_the_keys_the_translator_reads(self):
        found = block(corner_capture(), corner_states())
        sketch = found[1]
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(text_of(sketch, "4/p0/c0.1/center.0"), "-margin + width")
        self.assertEqual(text_of(sketch, "4/p0/c0.1/radius"), "margin")
        self.assertEqual(text_of(sketch, "4/p0/c0.2/offset"), "-width")
        self.assertEqual(text_of(sketch, "4/p0/l0/segments.1.to.1"), "margin")
        self.assertEqual(text_of(sketch, "4/p0/l0/segments.1.through.1"), "0.292893219 * margin")
        self.assertEqual(sketch["compare"]["disagree"], 0)
        plate = block(plate_capture(), plate_states())[1]
        self.assertEqual(text_of(plate, "4/p0/l1/center.1"), "0.5 * height")

    def test_every_key_the_probe_reads_is_derived_or_has_a_reason(self):
        from lib.probe import match, plan
        capture = corner_capture()
        sketch = block(capture, corner_states())[1]
        want = {k for t in plan.scan(capture).targets for k in match.captured_values(t)}
        self.assertEqual(want - {"4/p0/plane"}, set(sketch["keys"]))

    def test_a_profile_that_uses_only_part_of_a_sketch_keys_only_what_it_uses(self):
        """The step reads the circle alone; the rectangle of the sketch has no key."""
        capture = plate_capture()
        hole = plate_profile()["loops"][1]
        capture["items"][0]["data"]["profiles"] = [profile("Sketch1", "s1", [dict(hole, outer=True)])]
        sketch = block(capture, plate_states())[1]
        self.assertEqual(sorted(sketch["keys"]), ["4/p0/l0/center.0", "4/p0/l0/center.1", "4/p0/l0/radius"])
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(sketch["compare"]["agree"], 3)

    def test_a_profile_curve_that_is_only_a_piece_of_a_sketch_curve_stays_open(self):
        """The bottom edge is cut in two by another curve of the sketch: each piece ends at a crossing the solver has
        no point for."""
        capture = plate_capture()
        curves = capture["items"][0]["data"]["profiles"][0]["loops"][0]["curves"]
        curves[0:1] = [line((0, 0), (20, 0), "e0"), line((20, 0), (40, 0), "e0")]
        sketch = block(capture, plate_states())[1]
        self.assertEqual(sketch["outcome"], "partly")
        self.assertEqual(set(sketch["reasons"]), {"piece", "loop"})
        self.assertEqual(sketch["keys"]["4/p0/c0.0/offset"]["open"], "piece")
        self.assertEqual(sketch["keys"]["4/p0/l0/points.1.0"]["open"], "piece")
        self.assertEqual(sketch["keys"]["4/p0/l1/center.0"]["formula"], "-margin + width")
        self.assertEqual(sketch["keys"]["4/p0/c0.3/offset"]["open"], "loop")

    def test_a_profile_curve_that_is_not_in_the_graph_stays_open(self):
        capture = plate_capture()
        capture["items"][0]["data"]["profiles"][0]["loops"][1]["curves"][0]["entity"] = "gone"
        sketch = block(capture, plate_states())[1]
        self.assertEqual(sketch["reasons"], {"not_in_sketch": 3})
        self.assertEqual(sketch["outcome"], "partly")


class AngleTest(unittest.TestCase):
    """A triangle whose leg turns with an angle size: the points are products of a length and a cosine or sine."""

    def setUp(self):
        self.table = table(ANGLE_PARAMS, ["len", "leg", "ang"], ANGLE_MODEL)
        self.found = block(triangle_capture(), triangle_states(), self.table)[1]

    def test_a_point_that_moves_along_a_curve_is_a_formula_over_the_sizes(self):
        self.assertEqual(self.found["outcome"], "derived")
        self.assertEqual(text_of(self.found, "4/p0/l0/points.2.0"), "leg * cos(ang)")
        self.assertEqual(text_of(self.found, "4/p0/l0/points.2.1"), "leg * sin(ang)")
        self.assertEqual(self.found["keys"]["4/p0/l0/points.2.1"]["kind"], "curved")
        self.assertEqual(self.found["compare"]["disagree"], 0)
        self.assertEqual(self.found["compare"]["states"], 5)

    def test_a_value_that_is_not_a_sum_of_coordinates_keeps_its_numbers(self):
        turn = self.found["keys"]["4/p0/c0.1/turn"]
        self.assertTrue(turn["numbers"])
        self.assertEqual(self.found["formulas"]["numeric"], 2)
        self.assertGreater(self.found["compare"]["compared"], 10)

    def test_the_comparison_with_the_measured_fit_says_where_only_the_derived_side_has_a_formula(self):
        verdicts = self.found["compare"]["measured_fit"]
        self.assertGreater(verdicts["derived_only"], 0)
        self.assertEqual(verdicts["same"] + verdicts["derived_only"] + verdicts["numbers_only"], 12)


class SizeCapTest(unittest.TestCase):
    @staticmethod
    def sketch_of(count):
        capture = plate_capture(graph=False)
        record = row_of_rectangles(count)
        record["token"] = "s7"
        capture["sketch_graphs"] = [record]
        return derived.shadow(capture, plate_table(), plate_states())["sketches"][0], record

    def test_a_sketch_of_hundreds_of_entities_is_worked_out(self):
        sketch, record = self.sketch_of(45)
        self.assertGreater(len(record["points"]) + len(record["curves"]), 350)
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(sketch["solver"]["open"], 0)

    def test_a_sketch_past_the_cap_is_skipped(self):
        sketch, record = self.sketch_of(51)
        self.assertGreater(len(record["points"]) + len(record["curves"]), derived.MAX_ENTITIES)
        self.assertIn("skipped", sketch)
        self.assertNotIn("solver", sketch)


class NotDerivedTest(unittest.TestCase):
    def test_a_sketch_the_solver_cannot_work_out_gives_reasons_by_code(self):
        capture = plate_capture()
        record = capture["sketch_graphs"][0]
        record["dimensions"].append({"id": 9, "type": "other", "name": "SketchFutureDimension", "unknown": True,
                                     "on": [["curve", 0]], "param": None, "expression": None, "value": None,
                                     "driving": True, "token": ""})
        found, sketch = block(capture, plate_states())
        self.assertEqual(sketch["outcome"], "partly")
        self.assertEqual(sketch["solver_outcome"], "partly")
        self.assertIn("blocked", sketch["solver_open"])
        self.assertIn("blocked", sketch["reasons"])
        self.assertGreater(sketch["values"]["not_derived"], 0)
        self.assertEqual(found["summary"]["partly"], 1)

    def test_a_graph_that_could_not_be_read_is_not_derived_with_the_reason(self):
        capture = plate_capture()
        capture["sketch_graphs"][0] = {"sketch": "Sketch1", "token": "s1", "error": "The sketch could not be found."}
        sketch = block(capture, plate_states())[1]
        self.assertEqual(sketch["outcome"], "not_derived")
        self.assertIn("could not be found", sketch["reason"])
        self.assertEqual(sketch["values"]["derived"], 0)

    def test_a_sketch_past_the_size_cap_is_recorded_as_skipped(self):
        with mock.patch.object(derived, "MAX_ENTITIES", 5):
            found, sketch = block(plate_capture(), plate_states())
        self.assertEqual((sketch["outcome"], found["summary"]["skipped"]), ("not_derived", 1))
        self.assertIn("more than the 5", sketch["skipped"])

    def test_a_solver_that_raises_is_recorded_per_sketch_and_the_others_go_on(self):
        capture = plate_capture()
        second = copy.deepcopy(capture["sketch_graphs"][0])
        second.update(sketch="Sketch9", token="s9")
        capture["sketch_graphs"].append(second)
        real = derived.solve_sketch

        def solve(record, *args):
            if record["token"] == "s1":
                raise RuntimeError("boom")
            return real(record, *args)

        with mock.patch.object(derived, "solve_sketch", solve):
            found = derived.shadow(capture, plate_table(), plate_states())
        broken, fine = found["sketches"]
        self.assertEqual((broken["outcome"], broken["error"]), ("not_derived", "RuntimeError: boom"))
        self.assertEqual(fine["outcome"], "derived")
        self.assertEqual((found["summary"]["errors"], found["summary"]["derived"]), (1, 1))

    def test_a_record_that_is_not_a_sketch_does_not_stop_the_others(self):
        capture = plate_capture()
        capture["sketch_graphs"].insert(0, None)
        found = derived.shadow(capture, plate_table(), plate_states())
        self.assertEqual([s["outcome"] for s in found["sketches"]], ["not_derived", "derived"])


class ConstantsTest(unittest.TestCase):
    @staticmethod
    def record():
        axis = {"id": 0, "kind": "line", "points": [1, 2], "implicit": True, "reference": {"source": "own"}}
        other = {"id": 1, "kind": "circle", "center": 3, "radius": 2.0, "reference": {"source": "other"}}
        edge = {"id": 2, "kind": "circle", "center": 4, "radius": 2.0, "reference": {"source": "own"}}
        points = [{"id": 0, "xy": [0, 0], "origin": True}, {"id": 1, "xy": [-5, 0]}, {"id": 2, "xy": [5, 0]},
                  {"id": 3, "xy": [9, 9]}, {"id": 4, "xy": [7, 7]}]
        return {"points": points, "curves": [axis, other, edge]}

    def test_an_origin_axis_and_a_projection_no_size_reaches_are_constants(self):
        found = derived.constants_of(self.record(), linked=False)
        self.assertEqual(sorted(found), [("curve", 0), ("curve", 1), ("point", 1), ("point", 2), ("point", 3)])

    def test_a_projection_of_another_component_that_a_size_reaches_is_an_input(self):
        found = derived.constants_of(self.record(), linked=True)
        self.assertEqual(sorted(found), [("curve", 0), ("point", 1), ("point", 2)])


class ProjectionTest(unittest.TestCase):
    """The circle is projected from somewhere else instead of drawn with its own dimensions."""

    @staticmethod
    def projected(source):
        capture = plate_capture()
        record = capture["sketch_graphs"][0]
        record["dimensions"] = [d for d in record["dimensions"] if d["param"] in ("d1", "d2", "d3")]
        record["curves"][4]["reference"] = {"source": source, "component": "", "token": "x"}
        return capture

    def test_a_projection_a_size_can_move_is_a_measured_input(self):
        sketch = block(self.projected("own"), plate_states())[1]
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(sketch["leaves"]["@p4.x"]["kind"], "input")
        self.assertEqual(sketch["keys"]["4/p0/l1/center.0"]["inputs"], ["@p4.x"])
        self.assertEqual(text_of(sketch, "4/p0/l1/center.0"), "(@p4.x)")
        listed = sketch["compare"]["listed"]
        self.assertTrue(listed and all(item["reads_inputs"] for item in listed))
        self.assertEqual(text_of(sketch, "4/p0/l0/width"), "width")

    def test_a_projection_from_another_component_that_no_size_reaches_is_a_constant(self):
        sketch = block(self.projected("other"), plate_states())[1]
        self.assertEqual(sketch["constants"], ["c4", "p4"])
        self.assertNotIn("@p4.x", sketch["leaves"])
        self.assertEqual(text_of(sketch, "4/p0/l1/center.0"), "35")


class SizeSettingsTest(unittest.TestCase):
    def test_settings_move_each_size_a_quarter_either_way_then_all_together(self):
        table = plate_table()
        formulas = derived_sizes.dimension_formulas(table, plate_graph()[0])
        moving = derived_sizes.moving_sizes(table, formulas)
        self.assertEqual([s["param"] for s in moving], ["width", "height", "margin"])
        sets = derived_sizes.override_sets(moving)
        self.assertEqual(sets[:2], [{"width": 30.0}, {"width": 50.0}])
        self.assertEqual(sets[-2:], [{"width": 30.0, "height": 15.0, "margin": 3.75},
                                     {"width": 50.0, "height": 25.0, "margin": 6.25}])
        env = derived_sizes.size_env(table, sets[0])
        values = derived_sizes.leaf_values(formulas, env)
        self.assertEqual((values["d1"], values["d2"], values["d3"], values["d6"]), (30.0, 20.0, 20.0, 10.0))

    def test_a_dimension_that_cannot_be_written_is_left_out_with_the_reason(self):
        record = plate_graph()[0]
        dimension(_Wrapper(record), "linear", [], 1.0, "d9", "mystery_parameter")
        formulas = derived_sizes.dimension_formulas(plate_table(), record)
        self.assertFalse(formulas["d9"].usable)
        self.assertNotIn("d9", derived_sizes.leaf_values(formulas, derived_sizes.size_env(plate_table(), {})))


class _Wrapper:
    """Lets `dimension` append a bare dimension to a finished record."""

    def __init__(self, record):
        self.dimensions = record["dimensions"]

    def dim(self, kind, on, value, param, orientation=None):
        self.dimensions.append({"id": len(self.dimensions), "type": kind, "on": on, "param": param, "value": value,
                                "driving": True})
        return len(self.dimensions) - 1


if __name__ == "__main__":
    unittest.main()
