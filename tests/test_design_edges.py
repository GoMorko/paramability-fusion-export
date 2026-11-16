"""Edges and faces of the part matched to the straight extrudes that made them (`design_model/edges.py`): which sizes
may turn a pattern direction taken from one, which may change the angle between two faces, and which may change the
thickness a hole goes through."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import placed_hole_pattern, second_extrude, table_of
from tests.probe_helpers import model
from tests.test_orca_holes import BOX_TICKED

from lib.design_model import edges, reach

# The centred box of `placed_hole_pattern`: 80 by 60 mm on the XY plane, 32 mm high (`height_mm`).
EVERY = ["box_count", "cube_mm", "depth_mm", "height_mm", "pipe_offset_mm"]


def edge(point):
    return {"own": True, "entity_type": "BRepEdge", "edge_points": [list(point)]}


def face(point):
    return {"own": True, "entity_type": "BRepFace", "surface": "Plane", "face_point": list(point)}


def step(name, kind, **more):
    return dict({"index": 2, "name": name, "type": kind, "suppressed": False, "in_target_component": True,
                 "data": {}}, **more)


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
            capture["items"].insert(2, step("Move1", "MoveFeature"))
        cases = (("no outline there", edge((10, 0, 5)), (0, 1, 0), None),
                 ("a line that may turn", edge((0, -30, 32)), (1, 0, 0), unsolved),
                 ("a move between", edge((40, -30, 10)), (0, 0, 1), moved),
                 ("no point", {"own": True, "entity_type": "BRepEdge"}, (0, 0, 1), None))
        for name, place, direction, edit in cases:
            self.assertEqual(self.sizes(place, direction, edit), EVERY, name)

    def test_a_place_another_step_may_have_made_keeps_the_general_sizes(self):
        # A step other than a straight extrude or a simple hole through all, before the pattern, may make an edge or
        # face where the box's would lie.
        def before(item):
            return lambda capture: capture["items"].insert(2, item)

        def tapered(capture):
            second_extrude(capture, (0, -10, 20, 10), 32, 42)["items"][2]["data"]["side_one"]["taper_deg"] = 5.0

        def counterbored(capture):
            next(i for i in capture["items"] if i["type"] == "HoleFeature")["data"]["hole_type"] = "counterbore"
        side = (edge((40, -30, 10)), (0, 0, 1))
        cases = (("a revolve", before(step("Revolve1", "RevolveFeature"))), ("a tapered extrude", tapered),
                 ("a counterbored hole", counterbored),
                 ("a combine of another component",
                  before(step("Combine1", "CombineFeature", in_target_component=False))))
        for name, edit in cases:
            self.assertEqual(self.sizes(*side, edit), EVERY, name)

    def test_a_place_off_the_end_caps_keeps_the_general_sizes(self):
        cases = (("edge over a line between the caps", edge((40, 0, 10)), (0, 1, 0)),
                 ("face across the axis between the caps", face((0, 0, 10)), (0, 0, 1)),
                 ("side edge past the top cap", edge((40, -30, 50)), (0, 0, 1)),
                 ("side face past the top cap", face((40, 0, 50)), (1, 0, 0)))
        for name, place, direction in cases:
            self.assertEqual(self.sizes(place, direction), EVERY, name)

    def test_an_edge_of_one_extrude_turns_with_the_planes_of_every_extrude(self):
        # Where two extrudes meet, an edge turns with both sketch planes.
        def boss(capture):
            reference = {"kind": "constructionPlane", "token": "p1", "definition": "Offset",
                         "built_on": [{"origin": True}]}
            second_extrude(capture, (0, -10, 20, 10), 32, 42, reference=reference)
            capture["parameters"]["model"].append(model("d21", "cube_mm", 1.0, kind="constructionPlane",
                                                        token="p1"))
        self.assertEqual(self.sizes(edge((40, -30, 10)), (0, 0, 1), boss), ["cube_mm"])


def side(point, normal):
    return {"face_point": list(point), "surface": "Plane", "normal": list(normal)}


class AngleTest(unittest.TestCase):
    def sizes(self, faces, edit=None):
        capture = placed_hole_pattern()
        if edit:
            edit(capture)
        return edges.angle_sizes(table_of(capture, BOX_TICKED), capture, capture["items"][-1], faces)

    def test_the_top_and_a_side_of_a_plain_box_keep_their_angle(self):
        self.assertEqual(self.sizes([side((0, 0, 32), (0, 0, 1)), side((40, 0, 10), (1, 0, 0))]), [])

    def test_a_face_that_may_turn_or_is_not_described_keeps_the_general_sizes(self):
        def unsolved(capture):
            graph = capture["sketch_graphs"][0]
            graph["constraints"] = [c for c in graph["constraints"] if c["id"] != 0]
        top = side((0, 0, 32), (0, 0, 1))
        cases = (("a side over a line that may turn", [top, side((0, -30, 10), (0, -1, 0))], unsolved),
                 ("a face with no normal", [top, {"face_point": [40, 0, 10], "surface": "Plane"}], None),
                 ("no faces", [], None))
        for name, faces, edit in cases:
            self.assertEqual(self.sizes(faces, edit), EVERY, name)


class ThroughTest(unittest.TestCase):
    def sizes(self, end, edit=None):
        capture = placed_hole_pattern()
        if edit:
            edit(capture)
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

    def test_a_stepped_part_marks_what_places_the_hole(self):
        # A boss on top over x 0..20: the hole at x = -20 goes through 32 mm now, but `pipe_offset_mm` can move it
        # under the boss.
        found, general = self.sizes((-20, 0, 0), lambda c: second_extrude(c, (0, -10, 20, 10), 32, 42))
        self.assertEqual(found, general)
        self.assertIn("pipe_offset_mm", found)

    def test_extrudes_that_span_the_same_planes_give_the_lengths_of_all(self):
        found, _ = self.sizes((-20, 0, 0), lambda c: second_extrude(c, (-40, -30, 40, 30), 0, 32, reads="depth_mm"))
        self.assertEqual(found, ["depth_mm", "height_mm"])


if __name__ == "__main__":
    unittest.main()
