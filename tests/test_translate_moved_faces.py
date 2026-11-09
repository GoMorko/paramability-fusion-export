"""Picks on a face that an offsetFaces step moved follow the extrude and the offset distance (offset_faces.py)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_offset import plate_with_offset
from tests.test_translate_sized import TRAY, run
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of

from lib.translator import follow
from lib.translator.translate import HANDLERS, _walk

CHAMFER = load_capture("chamfer_equal")["items"][2]


def plate_moved_then_chamfered(z, points=None):
    """The plate (length wall_mm * 5), its top moved up by wall_mm, then a chamfer on two edges (points of the moved
    top at height `z`, or `points`)."""
    capture = plate_with_offset(2.0, params={"distance": {"name": "d9", "expression": "wall_mm", "value": 2.0}})
    capture["capture"] = 3
    capture["parameters"] = load_capture(TRAY)["parameters"]
    capture["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d1", "expression": "wall_mm * 5",
                                                                   "value": 10.0}}
    chamfer = copy.deepcopy(CHAMFER)
    chamfer["index"] = 3
    chamfer["data"]["sets"][0]["edges"] = [{"token": "e%d" % n, "closed": False, "points": [p]} for n, p in
                                           enumerate(points or [[20, 0, z], [40, 10, z]])]
    capture["items"].append(chamfer)
    return capture


class MovedFacesTest(unittest.TestCase):
    def test_an_edge_of_a_moved_face_follows_the_length_and_the_distance(self):
        result, _ = run(plate_moved_then_chamfered(12.0))
        self.assertEqual(result.fixed, [])
        assert_schema_ok(self, result.recipe)
        near = steps_of(result.recipe, "bevel")[0]["edges"]["near"]
        self.assertEqual(near[0][:2], [20.0, 0.0])
        self.assertEqual(near[0][2], {"expr": "wall_mm * 5 + wall_mm"})

    def test_a_point_off_the_moved_face_is_not_placed_on_it(self):
        result, _ = run(plate_moved_then_chamfered(11.0))
        self.assertIn("wall_mm", [f["name"] for f in result.loose])

    def test_a_corner_on_the_wall_the_move_grew_follows_a_share_of_the_distance(self):
        result, _ = run(plate_moved_then_chamfered(0, [[0, 0, 11]]))
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "bevel")[0]["edges"]["near"]
        self.assertEqual(near[0][:2], [0.0, 0.0])
        self.assertEqual(near[0][2], {"expr": "wall_mm * 5 + (0.5 * wall_mm)"})

    def test_a_point_on_the_wall_the_move_shrank_follows_the_distance_too(self):
        capture = plate_moved_then_chamfered(0, [[0, 0, 9]])
        data = capture["items"][2]["data"]
        data["params"]["distance"].update({"expression": "-wall_mm", "value": -2.0})
        data.update({"distance": -2.0, "faces_after": [{"point": [5, 5, 8], "normal": [0, 0, 1]}]})
        result, _ = run(capture)
        self.assertEqual(result.fixed, [])
        near = steps_of(result.recipe, "bevel")[0]["edges"]["near"]
        self.assertEqual(near[0][2], {"expr": "wall_mm * 5 + (0.5 * (-wall_mm))"})

    def test_material_the_move_added_or_removed_counts_for_the_part(self):
        for distance, point, held in ((2.0, [20, 10, 11], True), (-3.0, [20, 10, 8], False), (-3.0, [20, 10, 6], True)):
            with self.subTest(distance=distance, z=point[2]):
                _, ctx = _walk(plate_with_offset(distance), dict(HANDLERS), None)
                self.assertEqual(follow.inside(ctx, point), held)


if __name__ == "__main__":
    unittest.main()
