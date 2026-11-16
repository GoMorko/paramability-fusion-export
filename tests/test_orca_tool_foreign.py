"""A Combine's tool body of another component in the Orca copy (`orca_translate/tools.py`, with the facts of
`design_model/tool_chains.py`).

The fixture `component_tool_foreign`: a box in the root cut by a tool of two joined cylinders made in the component
Rod, which sits at (30, 10, 0) turned a quarter about z. box_h is read by the box, tool_len by both tool steps, and
rod_x acts on Rod without a step reading it.
"""
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.geometry import vec
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, translate
from lib.orca_translate.context import Body, Context
from lib.orca_translate.place import Placement
from lib.orca_translate.tools import build
from scripts.orca_live_check import table_for

NAME = "component_tool_foreign"
COMBINE = 7


def run(edit=None, sized=False):
    capture = fixture(NAME)
    if edit is not None:
        edit(capture)
    return translate(capture, table_for(capture) if sized else None)


def tool_of(capture):
    return capture["items"][COMBINE]["data"]["tools"][0]


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def transformed(f, p):
    """Where the Orca Transform `f` puts the point `p` (Orca coordinates): a turn about the pivot, then the shift."""
    turned = vec.rotate(list(p), list(f.xf_axis), f.xf_angle_deg, list(f.xf_pivot)) if f.xf_angle_deg else list(p)
    return vec.add(turned, list(f.xf_translate))


def combine_gap(result, index=COMBINE):
    return next(g for g in result.left_out if g["index"] == index)


class CopiedTest(unittest.TestCase):
    def test_the_tool_is_built_in_its_component_then_carried_to_its_place_and_cut(self):
        result = run()
        (move,) = of_type(result, FeatureType.TRANSFORM)
        (boolean,) = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual((boolean.mode, boolean.target_body, boolean.bool_tool_body), (BooleanMode.CUT, 0, 1))
        self.assertEqual(move.target_body, 1)
        # Rod's point (0, 10, 0) sits at (20, 10, 0) of the part.
        place = result.place
        self.assertTrue(vec.close(transformed(move, place.point([0, 10, 0])), list(place.point([20, 10, 0])), 1e-9))
        self.assertEqual([verdict_of(result, i)["verdict"] for i in (4, 6, COMBINE)], ["copied"] * 3)

    def test_a_tool_turned_out_of_the_bed_plane_is_carried_the_same_way(self):
        def edit(capture):
            tool_of(capture)["place"]["frame"] = {"origin": [30, 30, 5], "x": [1, 0, 0], "y": [0, 0, 1],
                                                  "z": [0, -1, 0]}
        result = run(edit)
        (move,) = of_type(result, FeatureType.TRANSFORM)
        place = result.place
        # The rod's end 20 mm up its own z lies 20 mm along -y of the part.
        self.assertTrue(vec.close(transformed(move, place.point([0, 0, 20])), list(place.point([30, 10, 5])), 1e-9))

    def test_the_sizes_that_act_on_the_tools_component_do_not_show_as_following_only(self):
        outcomes = {p["name"]: p["outcome"] for p in run(sized=True).parameters}
        self.assertEqual(outcomes, {"box_h": "variable", "tool_len": "partly", "rod_x": "fixed"})

    def test_a_tool_of_the_root_needs_no_move_and_marks_no_place(self):
        def edit(capture):
            tool_of(capture)["place"] = {"frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0],
                                                   "z": [0, 0, 1]}, "source": "root", "target_frame": None}
        result = run(edit, sized=True)
        self.assertEqual(of_type(result, FeatureType.TRANSFORM), [])
        self.assertEqual({p["name"]: p["outcome"] for p in result.parameters}["tool_len"], "variable")


class LeftOutTest(unittest.TestCase):
    def cause(self, edit):
        result = run(edit)
        self.assertEqual(of_type(result, FeatureType.BOOLEAN), [])
        return combine_gap(result)["cause"]

    def test_a_place_that_was_not_read(self):
        self.assertEqual(self.cause(lambda c: tool_of(c).update(place={"error": "Not found."})),
                         gap_hints.OTHER_COMPONENT)

    def test_a_tool_of_another_component_that_the_export_could_not_name(self):
        self.assertEqual(self.cause(lambda c: tool_of(c).pop("component")), gap_hints.OTHER_COMPONENT)

    def test_a_step_of_the_tool_that_was_not_read_in_its_component(self):
        self.assertEqual(self.cause(lambda c: c["items"][6].pop("helper_of")), gap_hints.REFUSED)

    def test_a_step_whose_sketch_is_named_only_by_name(self):
        self.assertEqual(self.cause(lambda c: c["items"][6]["data"]["profiles"][0].pop("sketch_token")),
                         gap_hints.REFUSED)

    def test_a_split_inside_the_tool(self):
        def edit(capture):
            capture["items"][6].update(type="SplitBodyFeature", data={"tool": {"kind": "plane"}})
        self.assertEqual(self.cause(edit), gap_hints.OTHER_COMPONENT)

    def test_a_step_of_a_third_component_that_changes_the_tool(self):
        def edit(capture):
            capture["items"][5].update(type="MoveFeature", component="cOther", bodies_after=[{"token": "t2"}])
        self.assertEqual(self.cause(edit), gap_hints.CHANGED_FROM_OTHER_COMPONENT)

    def test_a_tool_step_left_out_leaves_the_combine_out_with_its_cause(self):
        result = translate(fixture("combine_tool_foreign_fillet"))
        self.assertEqual(combine_gap(result, 8)["cause"], causes.EDGES_UNKNOWN)

    def test_a_tool_that_a_split_made(self):
        capture = fixture("combine_cut")
        parent = {"token": "t0", "name": "Body0"}
        capture["items"][3].update(bodies_after=[parent], bodies_before=[])
        split = {"index": 5, "name": "Split1", "type": "SplitBodyFeature", "in_target_component": True,
                 "bodies_before": [parent], "bodies_after": [parent, {"token": "t2", "name": "Body2"}],
                 "data": {"bodies": [parent], "pieces": [parent, {"token": "t2", "name": "Body2"}]}}
        capture["items"][4]["index"] = 6
        capture["items"].insert(4, split)
        self.assertEqual(combine_gap(translate(capture), 6)["cause"], gap_hints.UNSUPPORTED)

    def test_a_tool_of_another_component_inside_one_is_left_out(self):
        capture = fixture(NAME)
        ctx = Context(capture, None, Placement(capture))
        ctx.push(Body(tool_of(capture), "outer"))
        found = build(ctx, tool_of(capture), capture["items"][COMBINE])
        self.assertEqual(found.cause, gap_hints.OTHER_COMPONENT)


class FrameTest(unittest.TestCase):
    def test_inside_a_tool_of_another_component_the_walk_reads_that_components_frame(self):
        capture = fixture(NAME)
        ctx = Context(capture, None, Placement(capture))
        self.assertIsNone(ctx.component_frame())
        ctx.push(Body(tool_of(capture), "tool"))
        self.assertEqual(ctx.component_frame(), tool_of(capture)["place"]["frame"])


if __name__ == "__main__":
    unittest.main()
