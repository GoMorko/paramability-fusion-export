"""Which left out step made the geometry a later step picks, read with the marker before each picking step."""
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakeEdge, FakeFace, FakeMadeFeature, FakeMarkerTimeline, FakeReachDesign, FakeSolidBody

from lib.fusion_reader import read_gap_reach
from lib.fusion_reader.capture import MarkerError
from lib.fusion_reader.read_gap_reach import read_reach


def edge_pick(token):
    return {"sets": [{"kind": "constant", "radius": 1.0, "edges": [{"token": token, "closed": False, "points": []}]}]}


def face_pick(token, point=(0, 0, 0)):
    return {"faces": [{"token": token, "point": list(point)}]}


def item(index, type_name="ExtrudeFeature", data=None):
    return {"index": index, "type": type_name, "data": data or {}}


class World:
    """Faces by maker: a left out extrude (1) made `top` and `wall`, an extrude (2) made `floor` and `rim`."""

    def __init__(self):
        self.top, self.wall, self.floor = FakeFace("top"), FakeFace("wall"), FakeFace("floor")
        self.rim = FakeFace("rim")
        self.edges = [FakeEdge("top_wall", [self.top, self.wall]), FakeEdge("floor_rim", [self.floor, self.rim])]
        self.features = [FakeMadeFeature([]), FakeMadeFeature([self.top, self.wall]),
                         FakeMadeFeature([self.floor, self.rim]), FakeMadeFeature([])]

    def design(self, marker=None, **timeline):
        entities = self.edges + [self.top, self.wall, self.floor, self.rim]
        return FakeReachDesign(FakeMarkerTimeline(self.features, marker, **timeline), entities)


class ReachTest(unittest.TestCase):
    def setUp(self):
        self.world = World()

    def read(self, items, gaps=(1,), **timeline):
        design = self.world.design(**timeline)
        return design, read_reach(design, {"items": items}, set(gaps))

    def test_a_pick_on_a_face_of_a_left_out_step_is_reported_and_another_is_not(self):
        design, reach = self.read([item(1), item(2), item(3, "FilletFeature", edge_pick("top_wall"))])
        self.assertEqual(reach, {"read": True, "gaps": [1], "makers": {"3": [1]}})
        _, reach = self.read([item(1), item(2), item(3, "FilletFeature", edge_pick("floor_rim"))])
        self.assertEqual(reach, {"read": True, "gaps": [1], "makers": {"3": []}})

    def test_a_face_pick_is_tested_by_the_face_itself(self):
        _, reach = self.read([item(1), item(3, "ShellFeature", face_pick("wall"))])
        self.assertEqual(reach["makers"], {"3": [1]})

    def test_a_step_that_picks_after_the_gap_is_a_candidate_for_later_picks(self):
        # Step 2 rounds an edge of the left out step; step 3 picks a face step 2 made.
        items = [item(1), item(2, "FilletFeature", edge_pick("top_wall")),
                 item(3, "ShellFeature", face_pick("rim"))]
        _, reach = self.read(items)
        self.assertEqual(reach["makers"], {"2": [1], "3": [2]})

    def test_steps_before_the_first_gap_and_the_gaps_themselves_are_not_tested(self):
        items = [item(0, "FilletFeature", edge_pick("top_wall")), item(1, "FilletFeature", edge_pick("top_wall")),
                 item(2, "FilletFeature", edge_pick("floor_rim"))]
        design, reach = self.read(items)
        self.assertEqual(reach["makers"], {"2": []})
        self.assertNotIn(0, design.timeline.visited)

    def test_a_face_whose_token_is_gone_is_found_by_its_point_on_the_body(self):
        body = FakeSolidBody("b1", {(1, 2, 3): [self.world.top]})
        data = {"faces": [{"token": "gone", "point": [1, 2, 3]}]}
        design = self.world.design()
        design._entities["b1"] = body
        with mock.patch.object(read_gap_reach.geo, "point3d", lambda p: tuple(p)):
            reach = read_reach(design, {"items": [item(1), item(3, "ShellFeature", data)], "target": {"token": "b1"}},
                               {1})
        self.assertEqual(reach["makers"], {"3": [1]})

    def test_a_point_on_a_face_or_a_face_outline_is_not_a_pick(self):
        data = {"start": {"kind": "fromEntity", "face_point": [1, 2, 3]},
                "profiles": [{"face": True, "loops": [], "face_point": [1, 2, 3]}]}
        design, reach = self.read([item(1), item(3, "ExtrudeFeature", data)])
        self.assertEqual(reach["makers"], {})

    def test_a_candidate_whose_faces_are_no_longer_all_listed_counts_as_reached(self):
        # Right after step 1 it listed top and wall; a later step took wall out of the list.
        self.world.features[1] = FakeMadeFeature([self.world.top], complete=[self.world.top, self.world.wall])
        _, reach = self.read([item(1), item(3, "FilletFeature", edge_pick("floor_rim"))])
        self.assertEqual(reach["makers"], {"3": [1]})

    def test_a_candidate_that_lists_no_faces_counts_as_reached(self):
        self.world.features[1] = FakeMadeFeature([])
        _, reach = self.read([item(1, "MoveFeature"), item(3, "FilletFeature", edge_pick("floor_rim"))])
        self.assertEqual(reach["makers"], {"3": [1]})

    def test_a_pick_on_a_face_of_a_left_out_combines_tool_is_reported_under_the_combine(self):
        # Step 1 made the tool body; the Combine at step 2 joined it and is left out.
        tool = {"token": "tool", "name": "Tool"}
        self.world.features[2] = FakeMadeFeature([FakeFace("seam")])
        items = [dict(item(1), bodies_after=[tool]), item(2, "CombineFeature", {"tools": [tool]}),
                 item(3, "FilletFeature", edge_pick("top_wall"))]
        _, reach = self.read(items, gaps=(2,))
        self.assertIn(2, reach["makers"]["3"])
        _, reach = self.read([items[0], items[1], item(3, "FilletFeature", edge_pick("floor_rim"))], gaps=(2,))
        self.assertNotIn(2, reach["makers"]["3"])

    def test_a_pick_that_cannot_be_found_counts_as_reached_by_every_earlier_candidate(self):
        _, reach = self.read([item(1), item(2), item(3, "FilletFeature", edge_pick("gone"))], gaps=(1, 2))
        self.assertEqual(reach["makers"], {"3": [1, 2]})

    def test_a_candidate_whose_faces_cannot_be_read_counts_as_reached_unless_it_makes_no_faces(self):
        self.world.features[1] = FakeMadeFeature(None)
        items = [item(1), item(3, "FilletFeature", edge_pick("floor_rim"))]
        self.assertEqual(self.read(items)[1]["makers"], {"3": [1]})
        items[0] = item(1, "Sketch")
        self.assertEqual(self.read(items)[1]["makers"], {"3": []})

    def test_without_gaps_nothing_is_read_and_the_marker_does_not_move(self):
        design, reach = self.read([item(3, "FilletFeature", edge_pick("top_wall"))], gaps=())
        self.assertEqual((reach, design.timeline.visited), ({"read": True, "gaps": [], "makers": {}}, []))


class MarkerTest(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.items = [item(1), item(2, "FilletFeature", edge_pick("top_wall")),
                      item(3, "FilletFeature", edge_pick("top_wall"))]

    def test_the_marker_is_after_each_candidate_then_before_each_picking_step_and_back_where_it_was_after(self):
        design = self.world.design(marker=2)
        read_reach(design, {"items": self.items}, {1})
        self.assertEqual(design.timeline.visited, [2, 3, 4, 2, 3, 2])
        self.assertEqual(design.timeline.markerPosition, 2)

    def test_a_marker_at_the_end_goes_to_the_end(self):
        design = self.world.design()
        read_reach(design, {"items": self.items}, {1})
        self.assertEqual(design.timeline.markerPosition, design.timeline.count)

    def test_a_read_that_raises_gives_an_unread_answer_and_the_marker_is_back(self):
        design = self.world.design(marker=2, refuse=3)
        reach = read_reach(design, {"items": self.items}, {1})
        self.assertFalse(reach["read"])
        self.assertTrue(reach["error"])
        self.assertEqual(design.timeline.markerPosition, 2)

    def test_a_marker_that_cannot_be_put_back_is_an_error(self):
        design = self.world.design(marker=2, moves_allowed=2)
        with self.assertRaises(MarkerError):
            read_reach(design, {"items": self.items}, {1})

    def test_a_timeline_that_cannot_be_read_gives_an_unread_answer(self):
        design = FakeReachDesign(object())
        self.assertFalse(read_reach(design, {"items": self.items}, {1})["read"])

    def test_too_many_picking_steps_give_an_unread_answer_without_moving_the_marker(self):
        design = self.world.design(marker=2)
        with mock.patch.object(read_gap_reach, "MAX_PICKING_ITEMS", 1):
            reach = read_reach(design, {"items": self.items}, {1})
        self.assertFalse(reach["read"])
        self.assertEqual(design.timeline.visited, [])


if __name__ == "__main__":
    unittest.main()
