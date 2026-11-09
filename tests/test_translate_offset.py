"""Offset faces (press pull): a flat face with square side walls moves like an extrude of its outline."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TRAY, run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.translator import translate

TOP = {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def rect(w, h):
    corners = [(0, 0), (w, 0), (w, h), (0, h)]
    return [{"kind": "line", "start": list(corners[i]), "end": list(corners[(i + 1) % 4])} for i in range(4)]


def top_face(**fields):
    face = {"token": "f1", "frame": TOP, "space": "sketch", "loops": [{"outer": True, "curves": rect(40, 20)}],
            "sides": "square", "meets_offset": False}
    face.update(fields)
    return face


def plate_with_offset(distance, face=None, moved_to=None, params=None):
    """The 40 x 20 x 10 plate, then its top face offset by `distance`; Fusion's moved face sits at `moved_to`."""
    capture = load_capture("extrude_plate")
    data = {"distance": distance, "faces": [face or top_face()],
            "faces_after": [{"point": [5, 5, 10 + (distance if moved_to is None else moved_to)], "normal": [0, 0, 1]}]}
    if params:
        data["params"] = params
    capture["items"].append({"index": 2, "name": "OffsetFaces1", "type": "OffsetFacesFeature", "suppressed": False,
                             "health": "ok", "message": "", "component_root": True,
                             "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data})
    return capture


class OffsetFacesTest(unittest.TestCase):
    def test_outwards_adds_a_slab_on_the_face(self):
        result = translate(plate_with_offset(2.0))
        assert_schema_ok(self, result.recipe)
        slab = steps_of(result.recipe, "extrude")[1]
        self.assertEqual((slab["combine"], slab["distance"], slab["sketch"]["on"]["origin"]), ("add", 2.0, [0, 0, 10]))
        self.assertEqual(slab["sketch"]["on"]["normal"], [0, 0, 1])

    def test_inwards_cuts_a_slab_from_the_face(self):
        slab = steps_of(translate(plate_with_offset(-3.0)).recipe, "extrude")[1]
        self.assertEqual((slab["combine"], slab["distance"], slab["sketch"]["on"]["normal"]), ("cut", 3.0, [0, 0, -1]))

    def test_the_distance_follows_its_size(self):
        capture = plate_with_offset(2.0, params={"distance": {"name": "d9", "expression": "wall_mm", "value": 2.0}})
        capture["capture"] = 2
        capture["parameters"] = load_capture(TRAY)["parameters"]
        result, _ = run(capture)
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["distance"], {"expr": "wall_mm"})

    def test_faces_the_recipe_cannot_move_refuse(self):
        cases = {
            "Offsets of curved faces are not copied yet.": (top_face(kind="other", type="Cylinder"), None),
            "Offsets of faces whose side walls lean or curve are not copied yet.": (top_face(sides="other"), None),
            "Offsets of faces that touch each other are not copied yet.": (top_face(meets_offset=True), None),
            "The offset of this step could not be measured, so it is not copied.": (top_face(), -2.0),
        }
        for reason, (face, moved_to) in cases.items():
            refusal = translate(plate_with_offset(2.0, face, moved_to)).refusal
            self.assertEqual((refusal["index"], refusal["reason"]), (2, reason))


if __name__ == "__main__":
    unittest.main()
