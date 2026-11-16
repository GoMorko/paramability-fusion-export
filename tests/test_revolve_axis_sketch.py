"""A revolve about a line of another sketch than its outline's: the sizes that may move that sketch's plane are
followed when the probe tried them with the line read, and marked otherwise."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture, steps_of

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


def run(capture, motion):
    return translate(capture, size_table=table_of(capture), motion=motion)


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


if __name__ == "__main__":
    unittest.main()
