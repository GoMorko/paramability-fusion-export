"""A revolve about a line of another sketch than its outline's: the sizes that may move that sketch's plane are
followed when the probe tried them with the line read, and marked otherwise."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture, steps_of

from lib.capture_model import gap_hints
from lib.params import size_table
from lib.probe.plane_sizes import plane_driven
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate

XZ = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, 1], "z": [0, -1, 0]}
TOP_FACE = {"kind": "face", "token": "f1"}


def sketch(index, name):
    return {"index": index, "name": name, "type": "Sketch", "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [], "data": {}}


def ring_on_plate():
    """The plate of 10 mm (`plate_mm`) of the sketch_offset_plane fixture, then a 10 by 3 outline on the XZ origin
    plane turned a quarter about a line along x at z = 10, drawn in a sketch on the plate's top face."""
    base = load_capture("sketch_offset_plane")
    outline = [[0, 12], [10, 12], [10, 15], [0, 15]]
    profile = {"sketch": "Outline", "sketch_token": "s3", "frame": XZ, "space": "sketch",
               "reference": {"kind": "constructionPlane", "origin": True},
               "loops": [{"outer": True, "curves": [
                   {"kind": "line", "start": a, "end": b, "entity": "o%d" % n}
                   for n, (a, b) in enumerate(zip(outline, outline[1:] + outline[:1]))]}]}
    axis = {"point": [0, 0, 10], "dir": [1, 0, 0], "entity": "a0", "entity_type": "SketchLine", "sketch_token": "s2",
            "sketch": "AxisSketch", "sketch_reference": TOP_FACE, "sketch_projected": False}
    revolve = dict(sketch(4, "Revolve1"), type="RevolveFeature", bodies_after=[{"token": "t1", "name": "Body1"}],
                   data={"operation": "join", "profiles": [profile], "axis": axis, "project_axis": False,
                         "extent": {"kind": "angle", "angle_deg": 90, "symmetric": False},
                         "participants": [{"token": "t1", "name": "Body1"}], "start_face_normal": [0, 1, 0]})
    base["items"] = base["items"][:2] + [sketch(2, "AxisSketch"), sketch(3, "Outline"), revolve]
    return base


def table_of(capture):
    params = capture["parameters"]
    return size_table.build(params["user"], ["plate_mm"], params["model"], capture.get("design_units", "mm"))


def run(capture, motion, ranges=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], ["plate_mm"], params["model"], capture.get("design_units", "mm"),
                             ranges=ranges) if ranges else table_of(capture)
    return translate(capture, size_table=table, motion=motion)


def marked(result):
    return {f["name"]: f["reason"] for f in result.loose}


def axis_point(result):
    return steps_of(result.recipe, "revolve")[0]["axis"]["point"]


class AxisInAnotherSketchTest(unittest.TestCase):
    def test_the_probe_tries_a_size_that_moves_the_axis_sketch(self):
        capture = ring_on_plate()
        self.assertEqual(plane_driven(capture, table_of(capture)), ["plate_mm"])

    def test_a_size_that_moves_the_axis_sketch_and_was_not_followed_is_marked(self):
        untried = Motion(states=[{"values": {"lift_mm": 0.9}, "built": True}], untried=["plate_mm"])
        unmeasured = Motion(states=[{"values": {"plate_mm": 1.2}, "built": True}],
                            unmeasured={"AxisSketch": "it could not be read"})
        for label, motion in (("no probe", None), ("not tried", untried), ("sketch not measured", unmeasured)):
            with self.subTest(label):
                result = run(ring_on_plate(), motion)
                self.assertIsNone(result.refusal)
                self.assertIn("sketch line", marked(result).get("plate_mm", ""))
                self.assertEqual(axis_point(result), [0.0, 10.0])

    def test_a_size_the_probe_tried_with_the_line_read_is_followed(self):
        values = {"4/axis/point/2": Affine(0.0, {"plate_mm": 1.0}, "AxisSketch")}
        motion = Motion(values=values, states=[{"values": {"plate_mm": 1.2}, "built": True}])
        result = run(ring_on_plate(), motion)
        self.assertNotIn("plate_mm", marked(result))
        self.assertEqual(axis_point(result)[1]["expr"], "plate_mm")

    def test_a_line_in_the_outline_sketch_is_left_to_the_outline(self):
        capture = ring_on_plate()
        data = capture["items"][4]["data"]
        data["axis"].update(sketch="Outline", sketch_token="s3", sketch_reference=copy.deepcopy(
            data["profiles"][0]["reference"]))
        self.assertNotIn("plate_mm", marked(run(capture, None)))


def axis_follows_plate(rate=1.0, at=10.0):
    """The probe saw the axis line move `rate` mm per mm of plate_mm, through z = `at` at plate_mm 10."""
    values = {"4/axis/point/2": Affine(at - 10.0 * rate, {"plate_mm": rate}, "AxisSketch")}
    return Motion(values=values, states=[{"values": {"plate_mm": 12.0}, "built": True}])


def outline_from(capture, bottom):
    """The outline of the revolve drawn from z = `bottom` to 15."""
    loop = capture["items"][4]["data"]["profiles"][0]["loops"][0]
    for curve in loop["curves"]:
        for end in ("start", "end"):
            if curve[end][1] == 12:
                curve[end] = [curve[end][0], bottom]
    return capture


def arc_bottom(capture):
    """The outline closed below by an arc from (0, 13) to (8, 15) about (3, 18): its lowest point, z = 18 - sqrt(34)
    (about 12.169), lies between its ends and below its middle point (about 12.343)."""
    r = math.sqrt(34.0)
    mid = [3 + r * math.cos(math.radians(-75.9638)), 18 + r * math.sin(math.radians(-75.9638))]
    loop = capture["items"][4]["data"]["profiles"][0]["loops"][0]
    loop["curves"] = [
        {"kind": "arc", "start": [0, 13], "end": [8, 15], "mid": mid, "center": [3, 18], "radius": r, "entity": "o0"},
        {"kind": "line", "start": [8, 15], "end": [0, 15], "entity": "o1"},
        {"kind": "line", "start": [0, 15], "end": [0, 13], "entity": "o2"}]
    return capture


class AxisSideTest(unittest.TestCase):
    """Fusion turns toward one side of the sketch plane, so the turn about the axis reverses once the axis passes the
    outline: the range stops before the outline reaches the axis."""

    def test_the_range_stops_before_a_moving_axis_reaches_the_outline(self):
        result = run(ring_on_plate(), axis_follows_plate())
        self.assertIsNone(result.refusal)
        size = result.recipe["sizes"]["plate_mm"]
        self.assertEqual((size["min"], size["max"]), (5.0, 11.99))
        self.assertEqual([c["name"] for c in result.cuts], ["plate_mm"])

    def test_the_range_stops_where_a_curved_outline_comes_closest(self):
        result = run(arc_bottom(ring_on_plate()), axis_follows_plate())
        size = result.recipe["sizes"]["plate_mm"]
        self.assertEqual(size["max"], 12.16)

    def test_an_axis_that_stays_off_the_outline_keeps_the_range(self):
        result = run(ring_on_plate(), axis_follows_plate(rate=0.1))
        size = result.recipe["sizes"]["plate_mm"]
        self.assertEqual((size["min"], size["max"]), (5.0, 20.0))

    def test_an_outline_on_the_axis_may_stay_on_it_but_not_cross_it(self):
        result = run(outline_from(ring_on_plate(), 10), axis_follows_plate())
        self.assertIsNone(result.refusal)
        self.assertEqual({v["name"]: v["verdict"] for v in result.items}["Revolve1"], "translated")
        size = result.recipe["sizes"]["plate_mm"]
        self.assertEqual((size["min"], size["max"]), (5.0, 10.0))

    def test_a_typed_range_that_lets_the_axis_reach_the_outline_leaves_the_revolve_out(self):
        result = run(ring_on_plate(), axis_follows_plate(), ranges={"plate_mm": (4.0, 20.0)})
        self.assertEqual({v["name"]: v["verdict"] for v in result.items}["Revolve1"], "leftOut")
        self.assertEqual(result.gaps[0]["hint"], gap_hints.hint(gap_hints.REVOLVE_AXIS_SIDE))


if __name__ == "__main__":
    unittest.main()
