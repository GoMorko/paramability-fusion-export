"""A Combine written as a step that builds its tool on its own (lib/translator/combine/step.py, faces/tool_placer.py)."""
import copy
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.schema_check import check_recipe
from tests.translator_helpers import left_out
from tests.translator_helpers import load_capture, steps_of, verdict_of

from lib.capture_model import gap_hints
from lib.fusion_reader import read_geometry as geo
from lib.geometry.combine_volume import exceeds_tools
from lib.geometry.rigid import Move
from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Motion
from lib.translator import translate
from lib.design_model import roles
from lib.translator.combine import tool_walk
from lib.translator.context import Context
from lib.translator.faces import follow
from lib.translator.faces.placer import ADD, CUT, Placer
from lib.translator.faces.slabs import Motion as CopyMotion, Slab
from lib.translator.faces.tool_placer import ToolPlacer
from lib.translator.place import place
from lib.translator.step_walk import all_steps
from lib.translator.translate import _over_caps as over_caps

translate_module = importlib.import_module("lib.translator.translate")
from lib.design_model.values import Quantity

PLATE = {"token": "t1", "name": "Body1"}
TOOL = {"token": "t2", "name": "Body2"}
FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def sized(capture, motion=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                             capture.get("design_units", "mm"))
    return translate(capture, size_table=table, motion=motion)


def marked(result):
    return sorted({d["name"] for d in result.loose + result.fixed + [d for d in result.dropped if d.get("used")]})


def tool_of(result, n=0):
    return steps_of(result.recipe, "toolBody")[n]


def reach(z, body=None, x=20):
    side = {"kind": "toEntity", "plane": {"point": [x, 10, z], "normal": [0, 0, 1]}, "offset": 0.0, "taper_deg": 0.0,
            "entity_type": "BRepFace", "face_point": [x, 10, z]}
    return dict(side, body=body) if body else side


def reaching(z, body=None):
    """The chamfered peg, its extrude reaching from its sketch 3 mm up to a face at height `z`."""
    capture = load_capture("combine_tool_chamfer")
    data = capture["items"][3]["data"]
    data.update(side_one=reach(z, body), end_offset=z - 3.0, params={})
    capture["items"][4]["data"]["sets"][0]["edges"][0]["points"] = [[25, 10, z]]
    return capture


class WrittenToolTest(unittest.TestCase):
    def test_each_tool_is_written_with_its_own_steps(self):
        cases = {"combine_tool_filleted": ["extrude", "round"], "combine_tool_chamfer": ["extrude", "bevel"],
                 "combine_tool_cut_inside": ["extrude", "extrude"], "combine_tool_foreign_fillet": ["extrude", "extrude", "round"]}
        for name, kinds in cases.items():
            with self.subTest(name):
                result = translate(load_capture(name))
                self.assertIsNone(result.refusal)
                self.assertEqual(result.recipe["version"], 15)
                self.assertEqual([s["kind"] for s in tool_of(result)["features"]], kinds)
                self.assertEqual(tool_of(result)["combine"], "cut")
                self.assertEqual(check_recipe(result.recipe), [])

    def test_a_tool_of_two_steps_that_cuts_itself_is_copied(self):
        capture = load_capture("combine_tool_two_steps")
        capture["items"][5]["data"]["operation"] = "cut"
        capture["items"][-1]["data"]["operation"] = "cut"
        result = translate(capture)
        self.assertEqual([s["combine"] for s in tool_of(result)["features"]], ["new", "cut"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_an_intersect_of_a_tool_of_two_steps_is_one_tool_step(self):
        capture = load_capture("combine_tool_two_steps")
        capture["items"][-1]["data"]["operation"] = "intersect"
        result = translate(capture)
        self.assertEqual(tool_of(result)["combine"], "intersect")
        self.assertEqual([s["combine"] for s in tool_of(result)["features"]], ["new", "add"])

    def test_flat_tools_keep_their_recipe_and_version(self):
        for name in ("combine_cut", "combine_join", "combine_intersect", "combine_keep_tools", "component_tool_foreign"):
            with self.subTest(name):
                recipe = translate(load_capture(name)).recipe
                self.assertEqual(recipe["version"], 12)
                self.assertEqual(steps_of(recipe, "toolBody"), [])

    def test_a_tool_inside_a_tool_is_nested(self):
        result = translate(load_capture("combine_in_tool"))
        outer = tool_of(result)
        self.assertEqual([s["kind"] for s in outer["features"]], ["extrude", "toolBody"])
        self.assertEqual([s["kind"] for s in outer["features"][1]["features"]], ["extrude", "round"])
        ids = [s["id"] for s in all_steps(result.recipe["features"])]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_the_verdict_of_the_combine_holds_the_verdicts_inside(self):
        verdict = verdict_of(translate(load_capture("combine_tool_chamfer")), 5)
        self.assertEqual([(v["name"], v["verdict"]) for v in verdict["tool_steps"]],
                         [("Extrude3", "translated"), ("Chamfer1", "translated")])

    def test_a_cut_through_all_inside_a_tool_clears_the_tool_and_not_the_part(self):
        capture = load_capture("combine_tool_cut_inside")
        data = capture["items"][5]["data"]
        data.update(side_one={"kind": "throughAll", "positive": True, "taper_deg": 0.0}, params={}, end_offset=None,
                    target_box_before={"min": [0, 0, 0], "max": [400, 400, 400]})
        inner = tool_of(translate(capture))["features"][1]
        self.assertAlmostEqual(inner["distance"], 14 + (100 + 100 + 196) ** 0.5 + 1, places=6)

    def test_a_cut_through_all_without_measures_of_the_tool_refuses(self):
        capture = load_capture("combine_tool_cut_inside")
        item = capture["items"][5]
        del item["body_states"]
        item["data"].update(side_one={"kind": "throughAll", "positive": True, "taper_deg": 0.0}, params={}, end_offset=None,
                            target_box_before={"min": [0, 0, 0], "max": [400, 400, 400]})
        self.assertEqual(left_out(translate(capture))["name"], "Extrude5")

    def test_a_tool_step_that_cannot_be_copied_gives_the_combine_its_hint(self):
        capture = load_capture("combine_tool_chamfer")
        capture["items"][3]["type"] = "ThickenFeature"
        result = translate(capture)
        self.assertIn("Extrude3 (thicken)", left_out(result)["reason"])
        self.assertEqual([gap["hint"] for gap in result.gaps], [gap_hints.HINTS[gap_hints.SURFACE]])

    def test_a_step_of_the_tool_from_another_component_leaves_the_combine_out(self):
        capture = load_capture("combine_tool_cut_inside")
        capture["items"][5]["in_target_component"] = False
        self.assertIn("Extrude5", left_out(translate(capture))["reason"])

    def test_a_tool_listed_under_another_token_leaves_the_combine_out(self):
        capture = load_capture("combine_tool_cut_inside")
        capture["items"][5]["bodies_after"] = [{"token": "t9", "name": "Body2"}]
        self.assertIn("Extrude5", left_out(translate(capture))["reason"])

    def test_a_name_used_by_another_body_before_the_tool_existed_does_not_stop_the_copy(self):
        capture = load_capture("combine_tool_cut_inside")
        capture["items"][1]["bodies_after"] = [{"token": "t1", "name": "Body1"}, {"token": "t9", "name": "Body2"}]
        capture["items"][1]["bodies_before"] = [{"token": "t9", "name": "Body2"}]
        self.assertIsNone(translate(capture).refusal)

    def test_a_kept_tool_with_the_name_of_a_body_of_another_component_is_not_lost(self):
        capture = load_capture("combine_kept_tool_grows")
        twin = {"token": "x2", "name": "Body2", "foreign": True, "component": {"token": "rod", "name": "Rod"},
                "place": {"frame": FRAME}, "volume": None}
        capture["items"][4]["data"]["tools"].append(twin)
        capture["items"][4]["bodies_after"].append({"token": "p2", "name": "Body2"})
        self.assertIsNone(tool_walk.unseen_change(Context(capture), TOOL, 8))

    def test_a_combine_of_another_component_that_keeps_the_tool_does_not_change_it(self):
        capture = load_capture("combine_kept_tool_grows")
        capture["items"][4].update(in_target_component=False, component="rod")
        self.assertIsNone(tool_walk.unseen_change(Context(capture), TOOL, 8))

    def test_a_split_face_inside_a_tool_is_skipped(self):
        capture = load_capture("combine_tool_chamfer")
        chamfer = next(i for i in capture["items"] if i["type"] == "ChamferFeature")
        chamfer.update(type="SplitFaceFeature", name="Split1", data={},
                       body_states={"t2": {"box_before": None, "volume_before": 5.0, "volume_after": 5.0}})
        capture["items"][-1]["data"].update(volume_before=None, volume_after=None)
        copied = translate(capture)
        self.assertEqual((copied.refusal, copied.gaps), (None, []))
        chamfer["body_states"]["t2"]["volume_after"] = 4.0
        self.assertEqual(left_out(translate(capture))["name"], "Split1")

    def test_a_tool_of_another_component_is_carried_into_place(self):
        result = translate(load_capture("combine_tool_foreign_fillet"))
        first = tool_of(result)["features"][0]
        self.assertEqual(first["sketch"]["on"]["origin"], [30.0, 10.0, 0.0])
        self.assertEqual(tool_of(result)["features"][2]["edges"]["near"][0], [30.0, 14.0, 20.0])

    def test_a_placed_recipe_moves_nested_steps(self):
        recipe = {"features": [{"kind": "toolBody", "features": [{"kind": "hole", "origin": [1, 0, 0]}]}]}
        moved = place(recipe, Move(((1, 0, 0), (0, 1, 0), (0, 0, 1)), (5, 0, 0)))
        self.assertEqual(moved["features"][0]["features"][0]["origin"], [6.0, 0.0, 0.0])


class IntersectOfSeveralToolsTest(unittest.TestCase):
    def test_equal_candidates_mark_the_sizes_the_tools_read(self):
        capture = load_capture("intersect_every")
        capture["items"][-1]["data"]["intersect_volumes"]["any"] = 2000.0
        self.assertEqual(marked(sized(capture)), ["tool_a_mm"])

    def test_the_model_of_a_combine_inside_a_tool_comes_from_the_tool_volume(self):
        item = {"data": {"intersect_volumes": {"every": 2.0, "any": 5.0}, "intersect_model": "unknown"},
                "body_states": {"t2": {"volume_before": 9.0, "volume_after": 5.0}}}
        self.assertEqual(roles.seen_on(item, TOOL, False)["data"]["intersect_model"], "any")

    def test_a_part_kept_where_every_tool_reaches_is_a_tool_step_per_tool(self):
        result = sized(load_capture("intersect_every"))
        self.assertEqual([(s["kind"], s.get("combine")) for s in result.recipe["features"][1:]],
                         [("toolBody", "intersect"), ("toolBody", "intersect")])
        self.assertEqual(marked(result), [])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_part_kept_where_any_tool_reaches_is_one_tool_step_that_holds_the_tools(self):
        result = sized(load_capture("intersect_any"))
        (outer,) = steps_of(result.recipe, "toolBody")
        self.assertEqual(outer["combine"], "intersect")
        self.assertEqual([(s["kind"], s["combine"]) for s in outer["features"]], [("toolBody", "new"), ("toolBody", "add")])
        self.assertEqual(marked(result), [])
        ids = [s["id"] for s in all_steps(result.recipe["features"])]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_model_that_is_unknown_or_missing_refuses(self):
        for model in ("unknown", None):
            with self.subTest(model):
                capture = load_capture("intersect_every")
                capture["items"][-1]["data"]["intersect_model"] = model
                self.assertEqual(left_out(translate(capture))["name"], "Combine1")


class RefusedToolTest(unittest.TestCase):

    def test_a_change_bigger_than_the_tools_refuses(self):
        capture = load_capture("combine_tool_chamfer")
        capture["items"][-1]["data"]["volume_after"] = 5000.0
        self.assertEqual(left_out(translate(capture))["index"], 5)

    def test_measured_tool_volumes_bound_the_change(self):
        tools = [{"volume": 100.0}, {"volume": 50.0}]
        cases = (("cut", 1000.0, 860.0, False), ("cut", 1000.0, 800.0, True), ("add", 1000.0, 1200.0, True),
                 ("intersect", 1000.0, 40.0, False), ("intersect", 1000.0, 80.0, True))
        for combine, before, after, expected in cases:
            with self.subTest((combine, after)):
                self.assertEqual(exceeds_tools(combine, {"volume_before": before, "volume_after": after, "tools": tools}),
                                 expected)

    def test_an_intersect_that_keeps_what_any_tool_holds_ends_below_their_sum(self):
        data = {"volume_after": 120.0, "intersect_model": "any", "tools": [{"volume": 100.0}, {"volume": 50.0}]}
        self.assertFalse(exceeds_tools("intersect", data))

    def test_tool_volumes_that_were_not_read_skip_the_check(self):
        self.assertFalse(exceeds_tools("cut", {"volume_before": 9.0, "volume_after": 1.0, "tools": [{"volume": None}]}))


class SizesInsideTheToolTest(unittest.TestCase):
    def test_sizes_of_inner_steps_are_followed(self):
        result = sized(load_capture("combine_tool_chamfer"), Motion.from_json({"values": {}, "refs": {}}))
        self.assertEqual(marked(result), [])
        extrude, bevel = tool_of(result)["features"]
        self.assertEqual(extrude["distance"], {"expr": "peg_len_mm"})
        self.assertEqual(bevel["size"], {"expr": "bevel_mm"})

    def test_a_forgotten_inner_value_is_loose(self):
        capture = load_capture("combine_tool_chamfer")
        capture["items"][4]["data"]["params"]["sets.0.other"] = {"name": "d4", "expression": "bevel_mm", "value": 1.0}
        self.assertEqual(marked(sized(capture)), ["bevel_mm"])

    def test_sizes_of_a_nested_tool_are_followed(self):
        result = sized(load_capture("combine_in_tool"))
        self.assertEqual(marked(result), [])
        self.assertIn("round_mm", result.recipe["sizes"])


class ReachOutOfTheToolTest(unittest.TestCase):
    def test_a_face_of_the_part_is_followed(self):
        result = sized(reaching(10, PLATE))
        self.assertEqual(tool_of(result)["features"][0]["distance"], {"expr": "plate_h_mm - 3"})
        self.assertNotIn("plate_h_mm", marked(result))

    def test_without_a_body_on_record_a_point_off_the_tool_is_on_the_part(self):
        self.assertEqual(tool_of(sized(reaching(10)))["features"][0]["distance"], {"expr": "plate_h_mm - 3"})

    def test_a_face_of_the_part_no_step_places_marks_the_sizes_of_the_part(self):
        result = sized(reaching(30, PLATE))
        self.assertEqual(tool_of(result)["features"][0]["distance"], 27)
        self.assertIn("plate_h_mm", marked(result))

    def test_a_face_of_a_body_the_copy_does_not_hold_marks_every_size(self):
        result = sized(reaching(30, {"token": "t9", "name": "Body9"}))
        self.assertEqual(sorted(marked(result)), ["bevel_mm", "peg_len_mm", "plate_h_mm"])

    def coincident(self, body):
        """A tool of two steps. The first ends at the height of the plate's top, where the second reaches."""
        capture = load_capture("combine_cut_tool_two_steps_sized")
        first, second = capture["items"][3], capture["items"][5]
        first["data"].update(end_offset=7.0, side_one=dict(first["data"]["side_one"], distance=7.0))
        first["data"]["params"] = {"side_one.distance": {"name": "d3", "expression": "peg_len_mm", "value": 7.0}}
        capture["parameters"]["user"][1].update(expression="7 mm", value=0.7, display_value=7.0)
        model = next(p for p in capture["parameters"]["model"] if p["name"] == "d3")
        model.update(value=0.7, display_value=7.0)
        frame = second["data"]["profiles"][0]["frame"]
        second["data"].update(side_one=reach(10, body, x=12), end_offset=10.0 - frame["origin"][2], params={})
        capture["items"][-1]["data"]["operation"] = "cut"
        return capture

    def inner_length(self, result):
        return tool_of(result)["features"][1]["distance"]

    def test_the_body_on_record_tells_a_face_of_the_part_from_one_of_the_tool(self):
        on_part = sized(self.coincident(PLATE))
        self.assertIn("plate_h_mm", self.inner_length(on_part)["expr"])
        on_tool = sized(self.coincident(TOOL))
        self.assertIn("peg_len_mm", self.inner_length(on_tool)["expr"])

    def test_without_a_body_on_record_a_face_shared_with_the_part_marks_the_part(self):
        self.assertIn("plate_h_mm", marked(sized(self.coincident(None))))

    def walks(self):
        """A walk with a plate whose height follows `h`, and a tool walk inside it."""
        outer = Context({"target": PLATE, "items": []})
        on = {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]}
        profile = {"frame": FRAME, "loops": [{"outer": True, "curves": [{"kind": "circle", "center": [0, 0], "radius": 50}]}]}
        outer.enter({"index": 1})
        outer.add_slab(Slab("plate", on, "oneSide", Quantity(10.0, "h", ("h",)), profile))
        outer.written_reads = ("h",)
        outer.enter({"index": 2})
        return outer, outer.child(TOOL, "t_", depth=1)

    def test_a_mirror_plane_on_a_face_of_the_part_or_built_on_one_follows_it(self):
        _, child = self.walks()
        face = {"entity_type": "BRepFace", "surface": "Plane", "face_point": [0, 0, 10], "body": PLATE}
        built = {"entity_type": "ConstructionPlane", "definition": "ConstructionPlaneOffsetDefinition", "built_on": [face]}
        for label, ref in (("face", face), ("built on a face", built)):
            with self.subTest(label):
                shift = follow.place_plane(child, {"index": 2, "name": "Mirror1"}, ref, [0, 0, 1])
                self.assertEqual(evaluate(shift.text, {"h": 15}), 5.0)

    def test_a_reach_sees_the_part_as_it_stood_at_that_step(self):
        outer, child = self.walks()
        target = reach(10, PLATE)
        self.assertFalse(follow.target_shift(child, {"index": 1, "name": "E"}, target, [0, 0, 1]).sized)
        self.assertTrue(follow.target_shift(child, {"index": 2, "name": "E"}, target, [0, 0, 1]).sized)


def plate_then(capture, item):
    capture["items"].append(item)
    return capture


class AfterTheToolTest(unittest.TestCase):
    def later_reach(self, name, z, point):
        """`name` followed by an extrude on the part that reaches to the face at `point`."""
        capture = load_capture(name)
        step = copy.deepcopy(capture["items"][1])
        step.update(index=capture["items"][-1]["index"] + 1, name="Later")
        step["data"].update(operation="join", end_offset=float(z), params={}, side_one={
            "kind": "toEntity", "plane": {"point": point, "normal": [0, 0, 1]}, "offset": 0.0, "taper_deg": 0.0,
            "entity_type": "BRepFace", "face_point": point})
        return plate_then(capture, step)

    def test_a_reach_to_a_face_the_tool_left_follows_the_tool(self):
        result = sized(self.later_reach("combine_tool_chamfer", 7, [20, 10, 7]))
        later = result.recipe["features"][-1]
        self.assertEqual(evaluate(later["distance"]["expr"], {"peg_len_mm": 5}), 8.0)

    def test_a_reach_to_a_step_carried_from_another_component_follows_it(self):
        capture = self.later_reach("component_tool_foreign", 20, [30, 10, 20])
        later = sized(capture, Motion.from_json({"values": {}, "refs": {"7.tool0.xy": "", "7.tool0.xz": "", "7.tool0.yz": ""}}))
        self.assertEqual(evaluate(later.recipe["features"][-1]["distance"]["expr"], {"tool_len": 25}), 25.0)

    def proud_tool(self, point):
        """The chamfered peg stands on the plate and is joined; a later fillet picks `point`."""
        capture = load_capture("combine_tool_chamfer")
        capture["items"][3]["data"]["profiles"][0]["frame"]["origin"][2] = 10
        capture["items"][4]["data"]["sets"][0]["edges"][0]["points"] = [[25, 10, 14]]
        data = capture["items"][-1]["data"]
        data.update(operation="join", volume_before=None, volume_after=None)
        step = {"index": 6, "name": "Fillet1", "type": "FilletFeature", "suppressed": False, "health": "ok", "message": "",
                "in_target_component": True, "bodies_after": [PLATE], "data": {"rolling_ball": True, "sets": [
                    {"kind": "constant", "radius": 0.2, "continuity": "tangent", "input_kinds": ["edge"],
                     "edges": [{"token": "e9", "closed": False, "points": [point]}]}]}}
        return plate_then(capture, step)

    def test_a_pick_only_on_the_tool_marks_only_what_can_move_the_tool(self):
        self.assertEqual(marked(sized(self.proud_tool([24.5, 10.5, 13.5]))), ["bevel_mm", "peg_len_mm"])

    def test_a_pick_that_may_also_lie_on_the_part_marks_every_size(self):
        class Opaque(Placer):
            opaque = True

            def place(self, p, edge):
                return None

            def material_at(self, p):
                return None

        on = {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]}
        profile = {"frame": FRAME, "loops": [{"outer": True, "curves": [{"kind": "circle", "center": [0, 0], "radius": 5}]}]}
        slab = Slab("inner", on, "oneSide", Quantity(4.0), profile).copied("tool", CopyMotion())
        ctx = Context({"target": PLATE, "items": []})
        ctx.add_placer(Opaque())
        ctx.add_placer(ToolPlacer("tool", [slab], "add", {"plate"}))
        ctx.written_reads = ("plate", "peg")
        follow.follow_points(ctx, {"name": "Fillet1"}, [[1, 1, 2]], False)
        self.assertEqual(ctx.doubts[0].names, ("plate", "peg"))


class NestingCapTest(unittest.TestCase):
    def test_tools_nested_past_the_limit_refuse(self):
        def nested(depth):
            return {"kind": "toolBody", "features": [nested(depth - 1)] if depth > 1 else [{"kind": "extrude"}]}
        ctx = Context({"target": PLATE, "items": []})
        self.assertIsNone(over_caps({"features": [nested(3)]}, ctx))
        self.assertIsNotNone(over_caps({"features": [nested(4)]}, ctx))


    def test_a_tool_level_that_holding_or_gathering_tools_adds_leaves_the_combine_out(self):
        # Tools kept where any of them reaches sit inside one more tool step, and a pattern of the whole body after a
        # round gathers the body into one. With the limit one level lower, each of them passes it.
        for name, limit in (("intersect_any", 1), ("pattern_target_finish", 0)):
            with self.subTest(name), mock.patch.object(tool_walk, "MAX_DEPTH", limit), \
                    mock.patch.object(translate_module, "MAX_TOOL_DEPTH", limit):
                result = translate(load_capture(name))
                self.assertIsNotNone(result.recipe)
                self.assertEqual(left_out(result)["name"], "Combine1")


class KeptToolTest(unittest.TestCase):
    def test_a_kept_tool_grows_before_the_next_combine(self):
        result = translate(load_capture("combine_kept_tool_grows"))
        self.assertEqual([s["kind"] for s in tool_of(result)["features"]], ["extrude", "round", "extrude"])
        self.assertEqual([s["kind"] for s in result.recipe["features"]], ["extrude", "extrude", "toolBody"])
        self.assertEqual(check_recipe(result.recipe), [])

    def test_a_tool_written_twice_has_distinct_ids(self):
        capture = load_capture("combine_tool_chamfer")
        capture["items"][-1]["data"]["keep_tools"] = True
        again = copy.deepcopy(capture["items"][-1])
        again.update(index=6, name="Combine2")
        result = translate(plate_then(capture, again))
        ids = [s["id"] for s in all_steps(result.recipe["features"])]
        self.assertEqual((len(ids), len(set(ids))), (7, 7))

    def exported_as_kept_tool(self, changed):
        capture = load_capture("combine_keep_tools")
        capture["target"] = dict(capture["target"], token="t2", name="Body2")
        combine = capture["items"][-1]
        combine.update(bodies_after=[PLATE, TOOL], target_changed=changed)
        return capture

    def test_a_combine_that_keeps_the_exported_body_as_a_tool_is_skipped(self):
        result = translate(self.exported_as_kept_tool(False))
        self.assertIsNone(result.refusal)
        self.assertEqual(verdict_of(result, 4)["verdict"], "skipped")
        self.assertEqual(len(result.recipe["features"]), 1)

    def test_a_combine_that_changes_the_exported_body_as_a_tool_refuses(self):
        self.assertEqual(left_out(translate(self.exported_as_kept_tool(True)))["index"], 4)


class OwnerBodyTest(unittest.TestCase):
    def test_a_face_names_the_body_it_lies_on_and_none_when_it_cannot_be_read(self):
        body = SimpleNamespace(entityToken="t2", name="Body2")
        self.assertEqual(geo.owner_body(SimpleNamespace(body=body), None), TOOL)
        self.assertIsNone(geo.owner_body(SimpleNamespace(), None))


class ToolPlacerTest(unittest.TestCase):
    def tool(self, combine):
        on = {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]}
        profile = {"frame": FRAME, "loops": [{"outer": True, "curves": [{"kind": "circle", "center": [0, 0], "radius": 5}]}]}
        slab = Slab("inner", on, "oneSide", Quantity(4.0, "h", ("h",)), profile).copied("tool", CopyMotion())
        return ToolPlacer("tool", [slab], combine, set())

    def test_material_follows_how_the_tool_meets_the_part(self):
        inside, outside = [0, 0, 2], [20, 0, 2]
        for combine, at_inside, at_outside in (("add", ADD, None), ("cut", CUT, None), ("intersect", ADD, CUT)):
            with self.subTest(combine):
                tool = self.tool(combine)
                self.assertEqual((tool.material_at(inside), tool.material_at(outside)), (at_inside, at_outside))

    def test_a_place_on_the_tool_never_names_a_step_inside_it(self):
        found = self.tool("cut").place([0, 0, 4], False)
        self.assertTrue(found.moves)
        self.assertTrue(found.slab.is_copy)

    def test_a_size_that_moves_the_copy_is_no_longer_unrelated(self):
        tool = ToolPlacer("tool", self.tool("cut").placers, "cut", {"gap", "plate"})
        copied = tool.copied("move", CopyMotion(shift=(Quantity(30.0, "gap", ("gap",)), 0, 0)))
        self.assertEqual(set(copied.not_moved_by([30, 0, 2])), {"plate"})

    def test_a_copy_of_the_tool_is_placed_where_the_copy_is(self):
        copied = self.tool("cut").copied("ring", CopyMotion(shift=(30, 0, 0)))
        self.assertEqual(copied.material_at([30, 0, 2]), CUT)
        self.assertIsNone(copied.material_at([0, 0, 2]))


if __name__ == "__main__":
    unittest.main()
