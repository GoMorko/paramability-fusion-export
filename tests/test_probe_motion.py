import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import (
    IDENT, capture, circle, extrude, loop, model, profile, read, rect_curves, sketch_state, state, table, user)

from lib.probe import build as probe_build
from lib.probe.motion import OPTIMISTIC, Affine, Motion, Stuck, build

W = "FilterBox_width_mm"
PARAMS = [user("count", "3", 3, ""), user("cube", "10 mm", 10), user(W, "count * cube + 2 mm", 32),
          user("off", "5 mm", 5), user("height", "20 mm", 20)]
MODEL = [model("d1", W, 32, sketch="Sketch1"),
         model("d2", "height", 20, kind="constructionPlane", token="cp1"),
         model("d3", "off", 5, sketch="Sketch1")]
TICKED = ["count", "cube", "off", "height"]


def base_profile(w=32, off=5):
    """Sketch1: a rectangle from the origin (width the filter width) with a hole off the right edge."""
    return profile("Sketch1", "sk1", [loop(rect_curves("r", 0, 0, w, 20)), loop([circle((w - off, 10), 2, "c")], False)])


def lid_profile(h=20, frame_z=(0, 0, 1)):
    frame = {"origin": [0, 0, h], "x": [1, 0, 0], "y": [0, 1, 0], "z": list(frame_z)}
    return profile("Sketch2", "sk2", [loop([circle((0, 0), 3, "c2")])], frame=frame,
                   reference={"kind": "constructionPlane", "token": "cp1"})


CAPTURE = capture(extrude(4, base_profile()), extrude(6, lid_profile()))


def read_at(count=3, cube=10, off=5, height=20, with_hole=True, turned=False):
    w = count * cube + 2
    profiles = [base_profile(w, off)["loops"]]
    if not with_hole:
        profiles = [base_profile(w, off)["loops"][:1]]
    sketches = sketch_state("sk1", [{"loops": profiles[0]}])
    sketches.update(sketch_state("sk2", [{"loops": lid_profile(height)["loops"]}],
                                 frame=lid_profile(height, (1, 0, 0) if turned else (0, 0, 1))["frame"]))
    params = {W: w / 10, "d1": w / 10, "d2": height / 10, "d3": off / 10, "height": height / 10, "off": off / 10}
    return read(sketches, params=params, box={"min": [0, 0, 0], "max": [w, 20, height]})


def at(**sizes):
    return state(sizes, read_at(**sizes))


def states(extra=()):
    return [state({}, read_at(), e0=True), at(count=6), at(cube=20), at(off=10), at(height=40),
            at(count=1), at(cube=5), at(off=2.5), at(height=10),
            at(count=1, cube=5, off=2.5, height=10), at(count=6, cube=20, off=10, height=40)] + list(extra)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)

    def motion(self, state_list=None):
        return build(CAPTURE, self.table, states() if state_list is None else state_list)

    def terms(self, motion, key):
        value = motion.get(key)
        self.assertIsInstance(value, Affine, key)
        return value.terms

    def test_filter_box_follows_the_derived_width_with_count_and_cube_ticked(self):
        motion = self.motion()
        self.assertEqual(self.terms(motion, "4/p0/l0/width"), {W: 1.0})
        self.assertEqual(self.terms(motion, "4/p0/l0/center.0"), {W: 0.5})
        self.assertEqual(self.terms(motion, "4/p0/l1/center.0"), {W: 1.0, "off": -1.0})
        self.assertEqual(self.terms(motion, "6/p0/plane"), {"height": 1.0})

    def test_values_that_never_move_are_absent(self):
        motion = self.motion()
        for key in ("4/p0/l0/height", "4/p0/l0/center.1", "4/p0/l1/radius", "6/p0/l0/radius"):
            self.assertIsNone(motion.get(key), key)

    def test_the_user_parameter_is_written_instead_of_a_dimension_that_equals_it(self):
        motion = self.motion()
        used = {name for v in motion.values.values() for name in getattr(v, "terms", {})}
        self.assertNotIn("d1", used)
        self.assertNotIn("d2", used)

    def test_formula_over_the_sizes_and_the_number_it_stands_for(self):
        quantity = self.motion().get("4/p0/l1/center.0").render(self.table)
        self.assertEqual(quantity.text, "FilterBox_width_mm - off")
        self.assertAlmostEqual(quantity.n, 27)
        self.assertEqual(set(quantity.reads), {"count", "cube", "off"})

    def test_half_the_width_and_a_constant(self):
        text = Affine(2, {W: 0.5}).render(self.table).text
        self.assertEqual(text, "0.5 * FilterBox_width_mm + 2")

    def test_a_term_that_is_a_fixed_number_joins_the_constant(self):
        fixed = self.table.with_fixed({"off": "fixed"})
        quantity = Affine(1, {"off": 2.0}).render(fixed)
        self.assertEqual((quantity.sized, quantity.n), (False, 11.0))

    def test_a_term_that_cannot_be_written_is_stuck(self):
        stuck = Affine(0, {"missing": 1.0}, "Sketch1").render(self.table)
        self.assertEqual((stuck.cause, stuck.sketch), ("unread", "Sketch1"))

    def test_union_of_the_boxes_over_all_states(self):
        self.assertEqual(self.motion().box_max, {"min": [0, 0, 0], "max": [122, 20, 40]})

    def test_a_state_fusion_could_not_build_is_dropped_and_listed(self):
        broken = state({"count": 5}, read_at(count=5, off=99), built=False)
        motion = self.motion(states([broken]))
        self.assertEqual(self.terms(motion, "4/p0/l1/center.0"), {W: 1.0, "off": -1.0})
        self.assertEqual(motion.states[-1], {"values": {"count": 5}, "built": False})

    def test_json_round_trip(self):
        motion = self.motion()
        again = Motion.from_json(motion.json())
        self.assertEqual(again.json(), motion.json())
        self.assertIsInstance(again.get("4/p0/l0/width"), Affine)

    def test_the_sketch_curves_of_each_profile_are_measured_too(self):
        motion = self.motion()
        self.assertEqual(self.terms(motion, "4/p0/c0.1/offset"), {W: -1.0})  # the right edge of the rectangle
        self.assertIsNone(motion.get("4/p0/c0.1/turn"))
        self.assertEqual(Motion.from_json(motion.json()).curves, {"4/p0", "6/p0"})

    def test_stuck_json_matches_the_motion_format(self):
        data = {"values": {"1/p0/l0/points.2.1": {"stuck": ["angle"], "cause": "curve", "sketch": "Sketch5"}}}
        self.assertEqual(Motion.from_json(data).get("1/p0/l0/points.2.1"), Stuck(["angle"], "curve", "Sketch5"))

    def test_a_sketch_that_differs_from_the_capture_at_the_start_is_left_to_the_measured_check(self):
        e0 = state({}, read_at(off=4), e0=True)
        motion = self.motion([e0] + states()[1:])
        self.assertEqual([k for k in motion.values if k.startswith("4/")], [])
        self.assertIsNotNone(motion.get("6/p0/plane"))

    def test_without_a_start_read_nothing_is_written(self):
        self.assertEqual(self.motion(states()[1:]).values, {})

    def test_optimistic_motion_writes_numbers_only(self):
        self.assertTrue(OPTIMISTIC.optimistic)
        self.assertIsNone(OPTIMISTIC.get("4/p0/l0/width"))
        self.assertFalse(Motion().optimistic)


class ProblemStateTests(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)

    def motion(self, **changed):
        state_list = states()
        for number, replacement in changed.items():
            state_list[int(number[1:])] = replacement
        return build(CAPTURE, self.table, state_list)

    def test_an_outline_that_changes_shape_fixes_the_size_that_did_it(self):
        motion = self.motion(s5=state({"count": 1}, read_at(count=1, with_hole=False)))
        width = motion.get("4/p0/l0/width")
        self.assertEqual((width.movers, width.cause, width.rest.terms), (("count",), "shape", {W: 1.0}))
        self.assertEqual(motion.get("4/p0/l1/radius"), Stuck(["count"], "shape", "Sketch1"))
        self.assertIsInstance(motion.get("6/p0/plane"), Affine)

    def test_a_plane_that_turns_fixes_the_size_that_did_it(self):
        motion = self.motion(s8=state({"height": 10}, read_at(height=10, turned=True)))
        plane = motion.get("6/p0/plane")
        self.assertEqual((plane.movers, plane.cause), (("height",), "turns"))
        self.assertIsInstance(motion.get("4/p0/l0/width"), Affine)

    def test_a_state_without_the_sketch_is_unread(self):
        motion = self.motion(s2=state({"cube": 20}, read({}, params={})))
        width = motion.get("4/p0/l0/width")
        self.assertEqual((width.movers, width.cause, width.rest.terms), (("cube",), "unread", {W: 1.0}))

    def test_a_point_moved_along_a_curve_gives_up(self):
        import math
        angle = user("ang", "60 deg", 60, "deg")
        tbl = table([angle], ["ang"])
        tri = lambda a: [  # noqa: E731
            loop([{"kind": "line", "start": s, "end": e, "entity": t} for s, e, t in (
                ([0, 0], [10, 0], "a"), ([10, 0], [10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))], "b"),
                ([10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))], [0, 0], "c"))])]
        cap = capture(extrude(1, profile("S", "s", tri(60))))
        mk = lambda a: read(sketch_state("s", [{"loops": tri(a)}]))  # noqa: E731
        got = build(cap, tbl, [state({}, mk(60), e0=True), state({"ang": 105}, mk(105)),
                               state({"ang": 15}, mk(15))])
        self.assertEqual(got.get("1/p0/l0/points.2.0"), Stuck(["ang"], "curve", "S"))
        self.assertEqual(got.get("1/p0/l0/points.1.0"), None)
        self.assertIsNotNone(got.get("1/p0/c0.1/turn"))  # the line that turns


class HoleAndAxisTests(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        hole = {"index": 8, "type": "HoleFeature", "data": {
            "sketch_token": "sk3", "positions": [[16, 5, 0]], "point_tokens": ["pt1"]}}
        axis = {"index": 9, "type": "RevolveFeature", "data": {"profiles": [], "axis": {
            "point": [5, 0, 0], "dir": [0, 1, 0], "entity": "ln1", "sketch_token": "sk4"}}}
        self.cap = capture(hole, axis)

    def snapshot(self, count=3, off=5, axis_dir=(0, 1, 0), hole_normal=(0, 0, 1)):
        frame = dict(IDENT, z=list(hole_normal))
        return read(sketch_state("sk3", [], frame), points={"pt1": [(count * 10 + 2) / 2, off, 0]},
                    lines={"ln1": {"point": [off, 0, 0], "dir": list(axis_dir)}})

    def states(self, **last):
        return [state({}, self.snapshot(), e0=True), state({"count": 6}, self.snapshot(count=6)),
                state({"count": 1}, self.snapshot(count=1)), state({"off": 10}, self.snapshot(off=10)),
                state({"off": 2.5}, self.snapshot(off=2.5))] + [state(v, r) for v, r in last.items()]

    def test_hole_point_and_axis_line_follow_the_sizes(self):
        motion = build(self.cap, self.table, self.states())
        self.assertEqual(motion.get("8/positions/0/0").terms, {W: 0.5})
        self.assertEqual(motion.get("8/positions/0/1").terms, {"off": 1.0})
        self.assertEqual(motion.get("9/axis/point/0").terms, {"off": 1.0})
        self.assertIsNone(motion.get("9/axis/point/1"))

    def test_an_axis_that_turns_is_stuck(self):
        motion = build(self.cap, self.table, self.states() + [state({"cube": 20}, self.snapshot(axis_dir=(1, 0, 0)))])
        point = motion.get("9/axis/point/0")
        self.assertEqual((point.movers, point.cause, point.rest.terms), (("cube",), "turns", {"off": 1.0}))

    def test_a_hole_sketch_that_turns_is_stuck(self):
        motion = build(self.cap, self.table, self.states() + [state({"cube": 20}, self.snapshot(hole_normal=(1, 0, 0)))])
        self.assertEqual(motion.get("8/positions/0/0").cause, "turns")


class MovedSizesTests(unittest.TestCase):
    def test_only_sizes_whose_own_state_moved_a_value(self):
        current = {"count": 3, "cube": 10, "off": 5, "height": 20}
        quiet = state({"count": 6}, read_at(count=3))  # a size that moves nothing
        found = probe_build.moved_sizes(CAPTURE, [state({}, read_at(), e0=True), quiet, at(off=10), at(height=40),
                                                  at(count=1, cube=5)], current)
        self.assertEqual(found, ["off", "height"])


if __name__ == "__main__":
    unittest.main()
