"""Edges and faces of the part matched to the straight extrude that made them (`design_model/edges.py`): which sizes
may turn a pattern direction taken from one, and which may change the thickness a hole goes through."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import placed_hole_pattern, table_of
from tests.test_orca_holes import BOX_TICKED

from lib.design_model import edges, reach

# The centred box of `placed_hole_pattern`: 80 by 60 mm on the XY plane, 32 mm high (`height_mm`).
EVERY = ["box_count", "cube_mm", "depth_mm", "height_mm", "pipe_offset_mm"]


def edge(point):
    return {"own": True, "entity_type": "BRepEdge", "edge_points": [list(point)]}


def face(point):
    return {"own": True, "entity_type": "BRepFace", "surface": "Plane", "face_point": list(point)}


class DirectionTest(unittest.TestCase):
    def sizes(self, place, direction, edit=None):
        capture = placed_hole_pattern()
        if edit:
            edit(capture)
        pattern = capture["items"][-1]
        pattern["data"].update(direction_one_place=place, direction_one=list(direction))
        return edges.direction_sizes(table_of(capture, BOX_TICKED), capture, pattern, "one")

    def test_edges_and_faces_of_a_plain_box_turn_with_no_size(self):
        cases = (("side edge", edge((40, -30, 10)), (0, 0, 1)),
                 ("edge over a fixed line", edge((40, 0, 32)), (0, 1, 0)),
                 ("end face", face((0, 0, 32)), (0, 0, 1)),
                 ("side face", face((40, 0, 10)), (1, 0, 0)))
        for name, place, direction in cases:
            self.assertEqual(self.sizes(place, direction), [], name)

    def test_a_sketch_plane_that_moves_gives_its_sizes(self):
        def on_plane(capture):
            capture["items"][1]["data"]["profiles"][0]["reference"] = {
                "kind": "constructionPlane", "token": "p1", "definition": "Offset", "built_on": [{"origin": True}]}
            capture["parameters"]["model"].append(
                {"name": "d20", "expression": "cube_mm", "value": 1.0, "unit": "mm", "kind": "derived", "role": "",
                 "dependency_parameters": ["cube_mm"], "created_by": {"kind": "constructionPlane", "token": "p1"}})
        self.assertEqual(self.sizes(edge((40, -30, 10)), (0, 0, 1), on_plane), ["cube_mm"])

    def test_without_a_match_every_size_read_before_stays(self):
        def unsolved(capture):
            graph = capture["sketch_graphs"][0]
            graph["constraints"] = [c for c in graph["constraints"] if c["id"] != 0]

        def moved(capture):
            capture["items"].insert(2, {"index": 2, "name": "Move1", "type": "MoveFeature", "suppressed": False,
                                        "in_target_component": True, "data": {}})
        cases = (("no outline there", edge((10, 0, 5)), (0, 1, 0), None),
                 ("a line that may turn", edge((0, -30, 32)), (1, 0, 0), unsolved),
                 ("a move between", edge((40, -30, 10)), (0, 0, 1), moved),
                 ("no point", {"own": True, "entity_type": "BRepEdge"}, (0, 0, 1), None))
        for name, place, direction, edit in cases:
            self.assertEqual(self.sizes(place, direction, edit), EVERY, name)


class ThroughTest(unittest.TestCase):
    def sizes(self, end):
        capture = placed_hole_pattern()
        hole = next(i for i in capture["items"] if i["type"] == "HoleFeature")
        data = dict(hole["data"], positions=[[-20, 0, 32]], end_points=[list(end)], direction=[0, 0, -1])
        return edges.through_sizes(table_of(capture, BOX_TICKED), capture["items"], hole, data), \
            reach.hole_end_sizes(table_of(capture, BOX_TICKED), capture["items"], hole, data)

    def test_a_hole_from_one_end_face_to_the_other_changes_only_with_the_length(self):
        self.assertEqual(self.sizes((-20, 0, 0))[0], ["height_mm"])

    def test_a_hole_that_comes_out_elsewhere_keeps_the_general_sizes(self):
        found, general = self.sizes((-20, 0, 10))
        self.assertEqual(found, general)
        self.assertIn("box_count", found)


if __name__ == "__main__":
    unittest.main()
