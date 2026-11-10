"""Derived values for hole points and revolve axis lines (world coordinates through the frame of their sketch)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.derived_fixtures import box_capture, dimension
from tests.probe_helpers import IDENT, state, table
from tests.sketch_solve_helpers import L, P, Sketch

from lib.probe import build, derived

HOLE_KEY, AXIS_KEY = "5/positions/0/0", "7/axis/point/0"


def sketch_record(name, token, build_it):
    s = Sketch()
    build_it(s)
    record = s.record()
    record.update(sketch=name, token=token)
    return record


def hole_sketch(s):
    """The hole point of `sketch_rect_centred`'s Sketch2, `pipe_offset_mm` left of the origin on the x axis."""
    point = s.point(-20.0, 0.0)
    s.con("horizontal_points", P(0), P(point))
    dimension(s, "linear", [P(point), P(0)], 20.0, "d10", "pipe_offset_mm", "horizontal")
    s.points[point]["token"] = "pt1"


def axis_sketch(s):
    """A vertical line `pipe_offset_mm` to the right of the origin and `depth_mm` long."""
    start, end = s.point(20.0, 0.0), s.point(20.0, 60.0)
    line = s.line(start, end)
    s.curves[line]["token"] = "ln1"
    s.con("vertical", L(line))
    s.con("horizontal_points", P(0), P(start))
    dimension(s, "linear", [P(0), P(start)], 20.0, "d11", "pipe_offset_mm", "horizontal")
    dimension(s, "linear", [L(line)], 60.0, "d12", "depth_mm", "vertical")


def capture():
    out = box_capture()
    out["sketch_graphs"] += [sketch_record("Sketch2", "s2", hole_sketch), sketch_record("Sketch3", "s3", axis_sketch)]
    revolve = {"index": 7, "name": "Revolve1", "type": "RevolveFeature",
               "data": {"axis": {"entity": "ln1", "sketch_token": "s3", "sketch": "Sketch3", "point": [20, 0, 0],
                                 "dir": [0, 1, 0]}}}
    out["items"].append(revolve)
    return out


def read_at(base, offset, depth):
    """The probe read with the hole point and the axis line where those sizes put them."""
    sketches = copy.deepcopy(base["sketches"])
    sketches["s2"] = sketches["s3"] = {"frame": IDENT, "profiles": []}
    return {"sketches": sketches, "points": {"pt1": [-offset, 0.0, 0.0]},
            "lines": {"ln1": {"point": [offset, 0.0, 0.0], "dir": [0.0, 1.0, 0.0]}}, "params": {}}


def sketch_of(found, name):
    return next(s for s in found["sketches"] if s["sketch"] == name)


class PointsTest(unittest.TestCase):
    def setUp(self):
        self.capture = capture()
        first = {"sketches": {"s1": {"frame": IDENT, "profiles": [{"loops": self.capture["items"][1]["data"][
            "profiles"][0]["loops"]}]}}}
        params = self.capture["parameters"]
        self.table = table(params["user"], ["pipe_offset_mm", "depth_mm"], params["model"])
        self.states = [state({}, read_at(first, 20.0, 60.0), e0=True),
                       state({"pipe_offset_mm": 30.0}, read_at(first, 30.0, 60.0)),
                       state({"pipe_offset_mm": 15.0, "depth_mm": 45.0}, read_at(first, 15.0, 45.0))]

    def block(self, states=None):
        states = self.states if states is None else states
        return derived.shadow(self.capture, self.table, states, build.build(self.capture, self.table, states))

    def test_a_hole_point_is_the_solver_point_in_the_frame_of_its_sketch(self):
        sketch = sketch_of(self.block(), "Sketch2")
        self.assertEqual(sketch["outcome"], "derived")
        self.assertEqual(sketch["keys"][HOLE_KEY]["formula"], "-pipe_offset_mm")
        self.assertEqual(sketch["keys"]["5/positions/0/2"]["formula"], "0")
        self.assertEqual((sketch["compare"]["agree"], sketch["compare"]["disagree"]), (3, 0))

    def test_the_start_of_a_revolve_axis_line_follows_its_sketch_sizes(self):
        sketch = sketch_of(self.block(), "Sketch3")
        self.assertEqual(sketch["keys"][AXIS_KEY]["formula"], "pipe_offset_mm")
        self.assertEqual((sketch["compare"]["agree"], sketch["compare"]["disagree"]), (3, 0))

    def test_a_hole_point_that_moved_another_way_than_derived_is_recorded(self):
        wrong = copy.deepcopy(self.states)
        wrong[1]["read"]["points"]["pt1"] = [-31.0, 0.0, 0.0]
        compare = sketch_of(self.block(wrong), "Sketch2")["compare"]
        self.assertEqual(compare["disagree"], 1)
        self.assertEqual((compare["listed"][0]["derived"], compare["listed"][0]["read"]), (-30.0, -31.0))

    def test_a_sketch_whose_frame_was_not_read_has_no_hole_values(self):
        states = copy.deepcopy(self.states)
        del states[0]["read"]["sketches"]["s2"]
        sketch = sketch_of(self.block(states), "Sketch2")
        self.assertEqual(sketch["outcome"], "not_derived")
        self.assertEqual(set(sketch["reasons"]), {"no_frame"})


if __name__ == "__main__":
    unittest.main()
