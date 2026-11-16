"""Planes, faces, axes, directions and points of other components that move with sizes (lib/design_model/refs.py and lib/translator/ref_motion.py).

The probe's motion file says how far each reference moves from the captured place. The fixtures: `component_ref_reach`
(a boss that reaches to a face of Cover), `component_ref_hole` (a hole on a sketch point of Cover) and
`component_foreign_mirror` (a mirror across a plane of Cover). gap_mm moves the reference, ear_mm acts on Cover
without moving it, lid_mm acts on another component.
"""
import copy
import json
import os
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.translator_helpers import left_out
from tests.translator_helpers import FIXTURES, load_capture, steps_of

from lib.design_model import refs
from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import OPTIMISTIC, Motion
from lib.translator import ref_motion, translate
from lib.design_model.values import Quantity

MOTION = os.path.join(os.path.dirname(FIXTURES), "motion")
SIZES = ["gap_mm", "ear_mm", "lid_mm"]
COVER = {"token": "cmp_cover", "name": "Cover"}
MOVES = {"const": -10, "terms": {"gap_mm": 1}}
TURNS = {"stuck": ["gap_mm"], "cause": "turns"}


def motion_with(name, values=None, refs=None):
    """The motion file `name`, with `values` and `refs` replacing its own when given."""
    with open(os.path.join(MOTION, name + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    if values is not None:
        data["values"] = values
    if refs is not None:
        data["refs"] = refs
    return Motion.from_json(data)


def run(capture, motion, ticked=SIZES):
    params = capture["parameters"]
    table = size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))
    return translate(capture, size_table=table, motion=motion)


def marked(result):
    """{ size: reason } of the sizes that are loose or left out because a step could not follow them."""
    found = {d["name"]: d["reason"] for d in result.dropped if d.get("used")}
    found.update({d["name"]: d["reason"] for d in result.loose})
    found.update({d["name"]: d["reason"] for d in result.fixed})
    return found


def value_at(written, gap):
    """A written number or formula worked out with gap_mm at `gap`."""
    return evaluate(written["expr"], {"gap_mm": gap}) if isinstance(written, dict) else written


def with_users(name, edit=None):
    """A fixture with the three sizes of `component_ref_reach`."""
    capture = load_capture(name)
    capture["capture"] = 3
    capture["parameters"] = load_capture("component_ref_reach")["parameters"]
    if edit:
        edit(capture)
    return capture


def ref(kind, slot, **extra):
    return dict({"slot": slot, "type": kind, "token": "tok_" + slot, "component": dict(COVER), "path": "Cover:1"}, **extra)


class ReachTest(unittest.TestCase):
    NAME = "component_ref_reach"

    def run_reach(self, motion=None, edit=None, ticked=SIZES):
        capture = load_capture(self.NAME)
        if edit:
            edit(capture)
        return run(capture, motion if motion is not None else motion_with(self.NAME), ticked)

    def boss(self, result):
        return steps_of(result.recipe, "extrude")[1]

    def test_a_face_that_moves_with_a_size_gives_the_length_a_formula_and_the_size_stays_free(self):
        result = self.run_reach()
        self.assertIsNone(result.refusal)
        self.assertEqual((result.loose, result.fixed), ([], []))
        length = self.boss(result)["distance"]
        self.assertEqual([value_at(length, gap) for gap in (10, 14, 20)], [15, 19, 25])
        self.assertIn("gap_mm", result.recipe["sizes"])

    def test_the_component_whose_sizes_the_copy_follows_is_named(self):
        self.assertEqual(self.run_reach().follows_components, [{"token": "cmp_cover", "name": "Cover"}])
        for label, result in (("a size that does not move it", self.run_reach(ticked=["ear_mm"])),
                              ("the first translation", self.run_reach(OPTIMISTIC)),
                              ("a face that cannot be followed", self.run_reach(
                                  motion_with(self.NAME, {"3/r/side_one/offset": TURNS})))):
            with self.subTest(label):
                self.assertEqual(result.follows_components, [])

    def test_a_size_that_acts_on_the_component_without_moving_the_face_is_not_marked(self):
        result = self.run_reach()
        self.assertEqual(marked(result), {})
        self.assertNotIn("ear_mm", result.recipe["sizes"])
        (ear,) = [d for d in result.dropped if d["name"] == "ear_mm"]
        self.assertTrue(ear["tried"])

    def test_the_first_translation_marks_nothing_and_writes_the_measured_length(self):
        result = self.run_reach(OPTIMISTIC)
        self.assertEqual((marked(result), self.boss(result)["distance"]), ({}, 15.0))

    def test_a_face_that_cannot_be_followed_marks_the_sizes_that_turn_it_and_keeps_its_place(self):
        values = {"3/r/side_one/offset": TURNS}
        result = self.run_reach(motion_with(self.NAME, values))
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertIn("turns", marked(result)["gap_mm"])
        self.assertIn("Cover", marked(result)["gap_mm"])
        self.assertEqual(self.boss(result)["distance"], 15.0)

    def test_a_face_the_probe_could_not_measure_or_did_not_look_at_marks_every_size_that_acts_on_its_component(self):
        measured = {"3.side_one": "its first read did not match the capture"}
        for refs, said in ((measured, "first read"), ({}, "Extrude2")):
            with self.subTest(said):
                result = self.run_reach(motion_with(self.NAME, values={}, refs=refs))
                self.assertEqual(sorted(marked(result)), ["ear_mm", "gap_mm"])
                self.assertIn(said, marked(result)["gap_mm"])
                self.assertEqual(self.boss(result)["distance"], 15.0)

    def test_a_size_the_probe_left_without_rows_is_marked(self):
        motion = motion_with(self.NAME)
        motion.untried.append("gap_mm")
        result = self.run_reach(motion)
        self.assertEqual(list(marked(result)), ["gap_mm"])

    def test_without_a_motion_file_the_sizes_are_marked_as_before(self):
        capture = load_capture(self.NAME)
        params = capture["parameters"]
        table = size_table.build(params["user"], SIZES, params["model"])
        result = translate(capture, size_table=table)
        self.assertEqual(sorted(marked(result)), ["ear_mm", "gap_mm"])

    def test_a_length_that_would_pass_the_start_cuts_the_range_where_it_stays_positive(self):
        values = {"3/r/side_one/offset": {"const": -30, "terms": {"gap_mm": 3}}}
        result = self.run_reach(motion_with(self.NAME, values))
        self.assertEqual(marked(result), {})
        (cut,) = result.cuts
        self.assertEqual(cut["name"], "gap_mm")
        self.assertIn("reach past", cut["reason"])
        self.assertGreater(value_at(self.boss(result)["distance"], cut["min"]), 0)

    def test_a_curved_face_of_another_component_is_refused_with_that_reason(self):
        def edit(capture):
            side = capture["items"][3]["data"]["side_one"]
            side["plane"] = None
            for key in ("point", "normal", "face_point"):
                del side["ref"][key]
        result = self.run_reach(edit=edit)
        self.assertEqual(left_out(result)["index"], 3)
        self.assertIn("curved face", left_out(result)["reason"])

    def test_a_tilted_face_of_another_component_is_refused(self):
        def edit(capture):
            side = capture["items"][3]["data"]["side_one"]
            side["ref"]["normal"] = side["plane"]["normal"] = [0, 0.6, 0.8]
        self.assertIn("tilted", left_out(self.run_reach(edit=edit))["reason"])

    def test_a_face_whose_place_was_not_brought_in_is_refused(self):
        def edit(capture):
            for key in ("point", "normal", "face_point"):
                del capture["items"][3]["data"]["side_one"]["ref"][key]
        self.assertIn("could not be read", left_out(self.run_reach(edit=edit))["reason"])

    def test_a_start_on_a_plane_of_another_component_moves_the_sketch_origin(self):
        def edit(capture):
            data = capture["items"][3]["data"]
            data["start"] = {"kind": "fromEntity", "entity_type": "ConstructionPlane", "foreign": True,
                             "plane": {"point": [0, 0, 112], "normal": [0, 0, 1]},
                             "ref": ref("ConstructionPlane", "start", point=[0, 0, 12], normal=[0, 0, 1])}
            data["side_one"] = {"kind": "distance", "distance": 5.0, "taper_deg": 0.0}
            data["end_offset"] = 7.0
        values = {"3/r/start/offset": MOVES}
        result = self.run_reach(motion_with(self.NAME, values, {"3.start": ""}), edit)
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), {})
        origin = self.boss(result)["sketch"]["on"]["origin"]
        self.assertEqual([value_at(origin[2], gap) for gap in (10, 16)], [12, 18])


class MirrorTest(unittest.TestCase):
    NAME = "component_foreign_mirror"

    def mirror(self, result):
        return steps_of(result.recipe, "mirror")[0]

    def test_a_plane_that_moves_with_a_size_gives_the_mirror_a_formula(self):
        result = run(load_capture(self.NAME), motion_with(self.NAME), ["gap_mm", "depth_mm"])
        self.assertIsNone(result.refusal)
        self.assertEqual((result.loose, result.fixed), ([], []))
        origin = self.mirror(result)["plane"]["origin"]
        self.assertEqual([value_at(origin[0], gap) for gap in (10, 15)], [0, 5])
        self.assertEqual(origin[1:], [0.0, 0.0])

    def test_an_origin_plane_of_another_component_follows_the_occurrence_like_any_plane(self):
        capture = load_capture(self.NAME)
        capture["items"][4]["data"]["plane"]["ref"]["origin"] = True
        result = run(capture, motion_with(self.NAME), ["gap_mm", "depth_mm"])
        origin = self.mirror(result)["plane"]["origin"]
        self.assertEqual([value_at(origin[0], gap) for gap in (10, 15)], [0, 5])

    def test_a_plane_that_turns_marks_its_sizes_and_the_mirror_stays_put(self):
        motion = motion_with(self.NAME, {"4/r/plane/offset": TURNS})
        result = run(load_capture(self.NAME), motion, ["gap_mm", "depth_mm"])
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertIn("turns", marked(result)["gap_mm"])
        self.assertEqual(self.mirror(result)["plane"]["origin"], [0.0, 0.0, 0.0])

    def test_a_plane_that_was_not_measured_marks_its_sizes(self):
        motion = motion_with(self.NAME, {}, {"4.plane": "its first read did not match the capture"})
        result = run(load_capture(self.NAME), motion, ["gap_mm", "depth_mm"])
        self.assertEqual(list(marked(result)), ["gap_mm"])

    def test_a_pick_on_a_copy_follows_twice_the_move_of_the_plane(self):
        def edit(capture):
            fillet = load_capture("mirror_fillet")["items"][3]
            capture["items"][3] = fillet
            capture["items"][4]["data"]["sources"] = [3]
        capture = with_users(self.NAME, edit)
        capture["items"][4]["data"]["plane"]["ref"] = ref("ConstructionPlane", "plane", point=[0, 0, 0], normal=[1, 0, 0])
        motion = motion_with(self.NAME)
        result = run(capture, motion)
        self.assertIsNone(result.refusal)
        source, copy_step = steps_of(result.recipe, "round")
        near = copy_step["edges"]["near"][0]
        self.assertEqual([value_at(near[0], gap) for gap in (10, 15)], [20, 30])
        self.assertEqual(source["edges"]["near"][0][:2], [-20, -10])


class AxisTest(unittest.TestCase):
    def axis_ref(self, slot="axis"):
        return ref("ConstructionAxis", slot, point=[20, 10, 0], dir=[0, 0, 1])

    def pattern(self, values, refs=None):
        def edit(capture):
            capture["items"][4]["data"]["axis"].update(assembly=True, ref=self.axis_ref())
        capture = with_users("cpattern_full", edit)
        motion = Motion.from_json({"version": 1, "values": values, "states": [], "refs": {"4.axis": ""} if refs is None else refs})
        return run(capture, motion)

    def test_a_pattern_axis_that_moves_gives_the_axis_point_a_formula(self):
        result = self.pattern({"4/r/axis/point/0": MOVES})
        self.assertIsNone(result.refusal)
        self.assertEqual((result.loose, result.fixed), ([], []))
        point = steps_of(result.recipe, "pattern")[0]["polar"]["axisPoint"]
        self.assertEqual([value_at(point[0], gap) for gap in (10, 14)], [20, 24])
        self.assertEqual(point[1:], [10.0, 0.0])

    def test_a_pattern_axis_that_turns_marks_its_sizes(self):
        result = self.pattern({"4/r/axis/point/%d" % c: TURNS for c in range(3)})
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertEqual(steps_of(result.recipe, "pattern")[0]["polar"]["axisPoint"], [20.0, 10.0, 0.0])

    def revolve(self, values, edit=None):
        def change(capture):
            capture["items"][1]["data"]["axis"].update(
                assembly=True, ref=ref("ConstructionAxis", "axis", point=[0, 0, 0], dir=[0, 1, 0]))
            if edit:
                edit(capture)
        capture = with_users("revolve_full", change)
        motion = Motion.from_json({"version": 1, "values": values, "states": [], "refs": {"1.axis": ""}})
        return run(capture, motion)

    def test_a_revolve_axis_that_moves_in_its_sketch_gives_the_axis_point_a_formula(self):
        result = self.revolve({"1/r/axis/point/0": MOVES})
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), {})
        point = steps_of(result.recipe, "revolve")[0]["axis"]["point"]
        self.assertEqual([value_at(point[0], gap) for gap in (10, 13)], [0, 3])

    def test_a_revolve_axis_that_leaves_the_plane_of_its_sketch_marks_its_sizes(self):
        result = self.revolve({"1/r/axis/point/2": MOVES})
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertIn("plane", marked(result)["gap_mm"])


class DirectionTest(unittest.TestCase):
    def pattern(self, values, refs):
        def edit(capture):
            capture["items"][4]["data"]["direction_one_place"] = {
                "assembly": True, "dir": [1, 0, 0], "ref": ref("ConstructionAxis", "direction_one", dir=[1, 0, 0])}
        motion = Motion.from_json({"version": 1, "values": values, "states": [], "refs": refs})
        return run(with_users("rpattern_row", edit), motion)

    def test_a_direction_that_turns_marks_the_sizes_that_turn_it(self):
        result = self.pattern({"4/r/direction_one/dir": TURNS}, {"4.direction_one": ""})
        self.assertIsNone(result.refusal)
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertIn("turns", marked(result)["gap_mm"])

    def test_a_direction_that_was_not_measured_marks_the_sizes_that_act_on_its_component(self):
        result = self.pattern({}, {})
        self.assertEqual(sorted(marked(result)), ["ear_mm", "gap_mm"])


class HoleTest(unittest.TestCase):
    NAME = "component_ref_hole"

    def origin(self, result):
        return steps_of(result.recipe, "hole")[0]["origin"]

    def test_a_point_that_moves_gives_the_hole_a_formula_for_that_coordinate(self):
        result = run(load_capture(self.NAME), motion_with(self.NAME))
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), {})
        origin = self.origin(result)
        self.assertEqual([value_at(origin[0], gap) for gap in (10, 15)], [10, 15])
        self.assertEqual(origin[1:], [10.0, 10.0])

    def test_a_point_that_cannot_be_followed_marks_its_sizes_and_the_hole_stays(self):
        motion = motion_with(self.NAME, {"3/r/positions.0/point/0": {"stuck": ["gap_mm"], "cause": "curve"}})
        result = run(load_capture(self.NAME), motion)
        self.assertEqual(list(marked(result)), ["gap_mm"])
        self.assertEqual(self.origin(result), [10.0, 10.0, 10.0])

    def test_a_point_that_was_not_measured_marks_the_sizes_that_act_on_its_component(self):
        motion = motion_with(self.NAME, {}, {"3.positions.0": "its place could not be brought into the part's coordinates"})
        self.assertEqual(sorted(marked(run(load_capture(self.NAME), motion))), ["ear_mm", "gap_mm"])

    def on_a_face(self, edit=None):
        def change(capture):
            data = capture["items"][3]["data"]
            data.pop("position_refs", None)
            data.update(foreign=True, position_refs=[ref("BRepFace", "positions.0", point=[10, 10, 10], normal=[0, 0, 1],
                                                          face_point=[10, 10, 10])])
            if edit:
                edit(data)
        return with_users("hole_through", change)

    def test_a_hole_on_a_flat_face_of_another_component_moves_along_the_face_normal(self):
        motion = motion_with(self.NAME, {"3/r/positions.0/offset": MOVES}, {"3.positions.0": ""})
        result = run(self.on_a_face(), motion)
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), {})
        origin = self.origin(result)
        self.assertEqual([value_at(origin[2], gap) for gap in (10, 13)], [10, 13])
        self.assertEqual(origin[:2], [10.0, 10.0])

    def test_a_hole_placed_on_an_edge_of_another_component_is_refused_with_that_reason(self):
        def edit(data):
            data["position_refs"] = [ref("BRepEdge", "positions.0", point=[10, 10, 10])]
        result = run(self.on_a_face(edit), motion_with(self.NAME))
        self.assertEqual(left_out(result)["index"], 3)
        self.assertIn("edge", left_out(result)["reason"])

    def test_a_hole_on_a_face_whose_place_was_not_brought_in_is_refused(self):
        def edit(data):
            data["position_refs"] = [ref("BRepFace", "positions.0")]
        result = run(self.on_a_face(edit), motion_with(self.NAME))
        self.assertIn("could not be read", left_out(result)["reason"])


class PlaneShiftTest(unittest.TestCase):
    """`plane_shift` writes the plane's move only along its normal; along a slanted line it marks the sizes."""

    def shift(self, direction):
        marks = []
        sized = Quantity(5.0, "gap_mm - 10", ["gap_mm"])
        record = {"ref": {"slot": "plane"}, "normal": [0, 0, 1]}
        with mock.patch.object(ref_motion, "moves", return_value=[sized]), \
                mock.patch.object(refs, "mark_all", side_effect=lambda *a: marks.append(a)):
            return ref_motion.plane_shift(None, {}, record, direction, "a step"), marks

    def test_a_line_along_the_normal_gets_the_move_and_a_slanted_one_marks_the_sizes(self):
        written, marks = self.shift([0, 0, -1])
        self.assertEqual((written.sized, marks), (True, []))
        written, marks = self.shift([0, 0.6, 0.8])
        self.assertEqual((written.sized, len(marks)), (False, 1))


class AuditTest(unittest.TestCase):
    def test_a_size_that_reaches_a_step_only_through_a_reference_is_not_dropped_as_unused(self):
        capture = load_capture("component_ref_reach")
        for motion in (None, motion_with("component_ref_reach"), motion_with("component_ref_reach", {}, {})):
            result = run(copy.deepcopy(capture), motion, ["ear_mm", "lid_mm"])
            reasons = {d["name"]: d["reason"] for d in result.dropped + result.loose}
            with self.subTest(motion=motion is not None):
                self.assertNotIn("not used by any copied step", reasons.get("ear_mm", ""))
                self.assertIn("lid_mm", reasons)


if __name__ == "__main__":
    unittest.main()
