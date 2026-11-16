"""Offset faces (press pull): each flat face becomes one pick point and the item one `offsetFaces` step."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TRAY, run
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of

from lib.capture_model import gap_hints
from lib.geometry.footprint import Footprint
from lib.translator import translate
from lib.translator.finishes import offset

TOP = {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def polygon(points):
    return [{"kind": "line", "start": list(points[i]), "end": list(points[(i + 1) % len(points)])}
            for i in range(len(points))]


def rect(w, h):
    return polygon([(0, 0), (w, 0), (w, h), (0, h)])


def top_face(**fields):
    face = {"token": "f1", "frame": TOP, "space": "sketch", "loops": [{"outer": True, "curves": rect(40, 20)}],
            "sides": "square", "meets_offset": False}
    face.update(fields)
    return face


def plate_with_offset(distance, faces=None, moved=None, params=None):
    """The 40 x 20 x 10 plate, then `faces` offset by `distance`. `moved` lists the faces Fusion left after the step
    (default: the top face moved by `distance`)."""
    capture = load_capture("extrude_plate")
    data = {"distance": distance, "faces": faces or [top_face()],
            "faces_after": moved or [{"point": [5, 5, 10 + distance], "normal": [0, 0, 1]}]}
    if params:
        data["params"] = params
    capture["items"].append({"index": 2, "name": "OffsetFaces1", "type": "OffsetFacesFeature", "suppressed": False,
                             "health": "ok", "message": "", "in_target_component": True,
                             "bodies_after": [{"token": "t1", "name": "Body1"}], "data": data})
    return capture


def on_plane(face, distance):
    """The face Fusion reports after the step: a point of the face moved by `distance` along its normal."""
    frame = face["frame"]
    point = [frame["origin"][i] + 8 * frame["x"][i] + 7 * frame["y"][i] + distance * frame["z"][i] for i in range(3)]
    return {"point": point, "normal": frame["z"]}


class OffsetFacesTest(unittest.TestCase):
    def test_a_face_becomes_one_step_with_a_point_inside_it_and_keeps_the_sign_of_the_distance(self):
        result = translate(plate_with_offset(2.0))
        assert_schema_ok(self, result.recipe)
        step = steps_of(result.recipe, "offsetFaces")[0]
        self.assertEqual((step["faces"], step["distance"]), ({"near": [[20.0, 10.0, 10.0]]}, 2.0))
        self.assertEqual(result.recipe["version"], 13)
        pulled = steps_of(translate(plate_with_offset(-3.0)).recipe, "offsetFaces")[0]
        self.assertEqual(pulled["distance"], -3.0)

    def test_a_recipe_without_the_step_keeps_version_12(self):
        self.assertEqual(translate(load_capture("extrude_plate")).recipe["version"], 12)

    def test_a_face_with_leaning_sides_is_copied(self):
        face = top_face(sides="other")
        result = translate(plate_with_offset(-0.04, [face], [on_plane(face, -0.04)]))
        assert_schema_ok(self, result.recipe)
        self.assertEqual(steps_of(result.recipe, "offsetFaces")[0]["faces"], {"near": [[20.0, 10.0, 10.0]]})

    def test_a_tilted_face_gets_a_point_on_its_plane_inside_its_outline(self):
        face = {"token": "r", "frame": {"origin": [13.76, -14.868394, 1.548148016], "x": [1, 0, 0],
                                        "y": [0, 0.866025404, -0.5], "z": [0, 0.5, 0.866025404]},
                "space": "sketch", "loops": [{"outer": True, "curves": polygon([(-5.25, -1.1), (0.25, -1.1),
                                                                                (0.25, -0.01), (-5.25, -0.01)])}],
                "sides": "other", "meets_offset": False}
        moved = {"point": [11.26, -15.372258, 1.792865], "normal": [0, 0.5, 0.866025404]}
        result = translate(plate_with_offset(-0.04, [face], [moved]))
        point = steps_of(result.recipe, "offsetFaces")[0]["faces"]["near"][0]
        rel = [point[i] - face["frame"]["origin"][i] for i in range(3)]
        u = sum(a * b for a, b in zip(rel, face["frame"]["x"]))
        v = sum(a * b for a, b in zip(rel, face["frame"]["y"]))
        along = sum(a * b for a, b in zip(rel, face["frame"]["z"]))
        self.assertAlmostEqual(along, 0.0, places=6)
        self.assertTrue(-5.25 < u < 0.25 and -1.1 < v < -0.01, (u, v))

    def test_faces_that_meet_are_one_step_with_two_points(self):
        side = {"token": "f2", "frame": {"origin": [40, 0, 0], "x": [0, 1, 0], "y": [0, 0, 1], "z": [1, 0, 0]},
                "space": "sketch", "loops": [{"outer": True, "curves": rect(20, 10)}], "sides": "other",
                "meets_offset": True}
        moved = [{"point": [5, 5, 12], "normal": [0, 0, 1]}, {"point": [42, 5, 5], "normal": [1, 0, 0]}]
        result = translate(plate_with_offset(2.0, [top_face(meets_offset=True), side], moved))
        assert_schema_ok(self, result.recipe)
        steps = steps_of(result.recipe, "offsetFaces")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["faces"], {"near": [[20.0, 10.0, 10.0], [40.0, 10.0, 5.0]]})

    def test_the_point_stays_out_of_a_hole_and_inside_a_bent_outline(self):
        ring = top_face(loops=[{"outer": True, "curves": rect(40, 20)},
                               {"outer": False, "curves": polygon([(10, 5), (30, 5), (30, 15), (10, 15)])}])
        elbow = top_face(loops=[{"outer": True, "curves": polygon([(0, 0), (40, 0), (40, 4), (4, 4), (4, 20), (0, 20)])}])
        for face in (ring, elbow):
            footprint = Footprint(face)
            uv = offset.inside_point(face)
            self.assertTrue(footprint.covers(uv))
            self.assertGreater(min(footprint.gaps(uv)), 1.0)

    def test_the_point_is_turned_with_a_y_up_design(self):
        capture = plate_with_offset(2.0)
        capture["up_axis"] = "y"
        near = steps_of(translate(capture).recipe, "offsetFaces")[0]["faces"]["near"][0]
        self.assertEqual(near, [20.0, -10.0, 10.0])

    def test_the_distance_follows_its_size(self):
        capture = plate_with_offset(2.0, params={"distance": {"name": "d9", "expression": "wall_mm", "value": 2.0}})
        capture["capture"] = 3
        capture["parameters"] = load_capture(TRAY)["parameters"]
        result, _ = run(capture)
        step = steps_of(result.recipe, "offsetFaces")[0]
        self.assertEqual(step["distance"], {"expr": "wall_mm"})
        self.assertIn("wall_mm", result.recipe["sizes"])

    def test_the_pick_names_the_extrude_whose_end_face_moves_with_a_size(self):
        capture = plate_with_offset(2.0)
        capture["capture"] = 3
        capture["parameters"] = load_capture(TRAY)["parameters"]
        capture["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d1", "expression": "wall_mm * 5", "value": 10.0}}
        result, _ = run(capture)
        assert_schema_ok(self, result.recipe)
        self.assertEqual(steps_of(result.recipe, "offsetFaces")[0]["faces"], {"featureFace": "extrude_1", "which": "end"})

    def test_a_curved_face_beside_a_flat_one_leaves_the_step_out_with_its_hint(self):
        result = translate(plate_with_offset(2.0, [top_face(), {"kind": "other", "type": "Cylinder"}]))
        self.assertEqual(steps_of(result.recipe, "offsetFaces"), [])
        self.assertEqual(result.gaps[0]["hint"], gap_hints.HINTS[gap_hints.OFFSET_CURVED])

    def test_the_faces_the_recipe_cannot_move_refuse(self):
        cases = {
            "Offsets of curved faces are not copied yet.": (top_face(kind="other", type="Cylinder"), None),
            "The offset of this step could not be measured, so it is not copied.":
                (top_face(), [{"point": [5, 5, 8], "normal": [0, 0, 1]}]),
        }
        for reason, (face, moved) in cases.items():
            refusal = left_out(translate(plate_with_offset(2.0, [face], moved)))
            self.assertEqual((refusal["index"], refusal["reason"]), (2, reason))


if __name__ == "__main__":
    unittest.main()
