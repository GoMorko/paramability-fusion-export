"""A revolve or a circular pattern turned about a face of the part: a cylinder, a cone or a torus face has an axis of its
own and is copied; a face with no axis (a sphere) is left out. The sizes that may move the face are marked."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture, steps_of

from lib.params import size_table
from lib.translator import translate


def face_axis(surface, point, direction):
    """The axis record of a face of the part, as the reader writes it."""
    return {"point": list(point), "dir": list(direction), "entity_type": "BRepFace", "surface": surface,
            "face_point": [point[0] + 5.0, point[1], point[2]], "body": {"token": "t1", "name": "Body1"}}


def other_face(surface):
    """What the reader writes for a face with no axis."""
    return {"kind": "other", "type": "BRepFace", "geometry": surface}


def marks(result):
    """{ size: reason } of the sizes the translation could not keep as sizes."""
    return {d["name"]: d["reason"] for d in result.dropped + result.loose + result.fixed}


def with_size(name, item, axis):
    """The fixture `name` with the axis of its item `item` replaced, and a size `Height` that the first item reads."""
    capture = copy.deepcopy(load_capture(name))
    capture["parameters"] = copy.deepcopy(load_capture("component_ref_reach")["parameters"])
    capture["items"][item]["data"]["axis"] = axis
    capture["items"][0]["data"]["params"] = {"x": {"name": "gap_mm", "expression": "gap_mm"}}
    params = capture["parameters"]
    table = size_table.build(params["user"], ["gap_mm"], params["model"], capture.get("design_units", "mm"))
    return translate(capture, size_table=table)


class RevolveFaceAxisTest(unittest.TestCase):
    def test_a_cone_and_a_torus_face_turn_the_revolve_about_their_axis(self):
        for surface in ("Cone", "Torus"):
            with self.subTest(surface=surface):
                result = with_size("revolve_full", 1, face_axis(surface, (0, 0, 0), (0, 1, 0)))
                self.assertIsNone(result.refusal)
                step = steps_of(result.recipe, "revolve")[0]
                self.assertEqual((step["axis"]["point"], step["axis"]["dir"]), ([0.0, 0.0], [0.0, 1.0]))
                self.assertEqual([i["verdict"] for i in result.items], ["skipped", "translated"])

    def test_the_sizes_that_may_move_the_face_are_marked_as_for_a_cylinder_face(self):
        found = {surface: marks(with_size("revolve_full", 1, face_axis(surface, (0, 0, 0), (0, 1, 0))))
                 for surface in ("Cylinder", "Cone", "Torus")}
        self.assertEqual(list(found["Cylinder"]), ["gap_mm"])
        self.assertIn("turns about a face", found["Cylinder"]["gap_mm"])
        self.assertEqual(found["Cone"], found["Cylinder"])
        self.assertEqual(found["Torus"], found["Cylinder"])

    def test_a_face_with_no_axis_leaves_the_revolve_out_as_not_round(self):
        for surface in ("Sphere", "other"):
            with self.subTest(surface=surface):
                result = with_size("revolve_full", 1, other_face(surface))
                self.assertIsNone(result.recipe)
                self.assertIn("face that is not round", result.refusal["reason"])


class PatternFaceAxisTest(unittest.TestCase):
    def test_a_cone_and_a_torus_face_turn_the_copies_of_a_circular_pattern(self):
        for surface in ("Cone", "Torus"):
            with self.subTest(surface=surface):
                result = with_size("cpattern_full", 4, face_axis(surface, (20, 10, 0), (0, 0, 1)))
                self.assertIsNone(result.refusal)
                polar = steps_of(result.recipe, "pattern")[0]["polar"]
                self.assertEqual((polar["axisPoint"], polar["axis"]), ([20.0, 10.0, 0.0], [0.0, 0.0, 1.0]))

    def test_the_sizes_that_may_move_the_face_are_marked_as_for_a_cylinder_face(self):
        found = {surface: marks(with_size("cpattern_full", 4, face_axis(surface, (20, 10, 0), (0, 0, 1))))
                 for surface in ("Cylinder", "Cone", "Torus")}
        self.assertEqual(list(found["Cylinder"]), ["gap_mm"])
        self.assertEqual(found["Cone"], found["Cylinder"])
        self.assertEqual(found["Torus"], found["Cylinder"])

    def test_a_face_with_no_axis_leaves_the_pattern_out(self):
        result = with_size("cpattern_full", 4, other_face("Sphere"))
        self.assertEqual(steps_of(result.recipe, "pattern"), [])
        self.assertEqual(result.items[-1]["verdict"], "leftOut")
        self.assertIn("face that is not round", result.items[-1]["note"])


if __name__ == "__main__":
    unittest.main()
