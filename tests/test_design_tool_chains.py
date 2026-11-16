"""Tool bodies in the shared layer (`design_model/tool_chains.py`): which items build a tool, through splits and in
another component, where a tool of another component sits, and the frame a walk builds in."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.design_model import tool_chains
from lib.design_model.problem import is_problem

PARENT = {"token": "t0", "name": "Body0"}
TOOL = {"token": "t2", "name": "Body2"}
ROD = {"token": "cRod", "name": "Rod"}
TURNED = {"origin": [30, 10, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}


def item(index, kind="ExtrudeFeature", after=(TOOL,), **more):
    found = {"index": index, "name": "Step%d" % index, "type": kind, "suppressed": False,
             "in_target_component": True, "bodies_after": list(after), "data": {}}
    found.update(more)
    return found


def foreign_tool(place=None):
    return dict(TOOL, foreign=True, component=ROD, place=place if place is not None else {"frame": TURNED})


def moved(move, point):
    return [sum(move.rows[i][k] * point[k] for k in range(3)) + move.offset[i] for i in range(3)]


class ChainTest(unittest.TestCase):
    def test_a_tool_of_another_component_is_built_by_the_steps_of_that_component(self):
        capture = load_capture("component_tool_foreign")
        found = tool_chains.read(capture["items"], capture["items"][7]["data"]["tools"][0], 7)
        self.assertEqual(([i["index"] for i in found.items], found.owner, found.foreign, found.unseen),
                         ([4, 6], "cRod", True, None))
        # Each item reads as one of the walk's own component.
        self.assertTrue(all(i["in_target_component"] for i in found.items))

    def test_a_tool_made_by_a_split_is_built_by_the_steps_of_the_body_it_was_split_from(self):
        split = item(3, "SplitBodyFeature", after=(PARENT, TOOL), bodies_before=[PARENT],
                     data={"bodies": [PARENT], "pieces": [PARENT, TOOL]})
        timeline = [item(1, after=(PARENT,)), item(2, after=(PARENT,)), split, item(4)]
        found = tool_chains.read(timeline, TOOL, 9)
        self.assertEqual((found.links, [i["index"] for i in found.items]), (((3, PARENT),), [1, 2, 3, 4]))

    def test_a_step_of_another_component_that_lists_the_tool_is_an_unseen_change(self):
        timeline = [item(1), item(2, in_target_component=False, component="cRod")]
        found = tool_chains.read(timeline, TOOL, 5)
        self.assertEqual((found.unseen[0]["index"], found.unseen[1]), (2, tool_chains.CHANGED_ELSEWHERE))

    def test_an_outline_named_only_by_its_sketch_name(self):
        named = item(1, data={"profiles": [{"sketch": "Sketch1", "sketch_token": "sk1"}]})
        bare = item(2, data={"profiles": [{"sketch": "Sketch1"}]})
        self.assertEqual([tool_chains.sketch_by_name_only(i) for i in (named, bare)], [False, True])


class PlaceTest(unittest.TestCase):
    def test_the_place_carries_the_tool_into_the_part_component(self):
        place = tool_chains.place_of(foreign_tool())
        self.assertIsNone(place.problem)
        self.assertEqual(moved(place.move, [0, 10, 0]), [20, 10, 0])
        self.assertEqual(place.moves_with, {"component": ROD, "type": tool_chains.PLACE})

    def test_the_part_own_place_at_the_combine_is_taken_out(self):
        place = tool_chains.place_of(foreign_tool({"frame": TURNED, "target_frame": dict(TURNED)}))
        self.assertTrue(place.stays)

    def test_a_tool_of_the_root_moves_only_with_the_place_of_the_part(self):
        frame = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        place = tool_chains.place_of(foreign_tool({"frame": frame, "source": "root", "target_frame": TURNED}))
        self.assertEqual((place.problem, place.planes, place.stays), (None, (), False))
        self.assertTrue(place.moves_with["root"])

    def test_a_place_that_cannot_be_used_is_a_problem(self):
        mirrored = dict(TURNED, z=[0, 0, -1])
        for record in ({"error": "The component could not be read."}, {"frame": mirrored},
                       {"frame": TURNED, "target_error": "No place."}, None):
            place = tool_chains.place_of(dict(foreign_tool(), place=record))
            self.assertIsNone(place.move, record)
            self.assertTrue(is_problem(place.problem), record)
            self.assertEqual(place.problem.cause, gap_hints.OTHER_COMPONENT)

    def test_the_origin_planes_of_a_tool_place_are_place_slots(self):
        self.assertEqual([tool_chains.is_place_slot(s) for s in ("tool0.xy", "tool12.yz", "start", "toolbar")],
                         [True, True, False, False])


class FrameTest(unittest.TestCase):
    def test_the_innermost_tool_of_another_component_gives_the_frame(self):
        part = {"origin": [5, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
        capture = {"target": {"placement": {"frame": part}}}
        self.assertEqual(tool_chains.component_frame(capture), part)
        self.assertEqual(tool_chains.component_frame(capture, [PARENT]), part)
        self.assertEqual(tool_chains.component_frame(capture, [foreign_tool(), PARENT]), TURNED)


if __name__ == "__main__":
    unittest.main()
