"""Readers for steps that make or move bodies (Paste, Move, body patterns), the tool volume and intersect model of a
Combine, and the states of the bodies behind a Combine's tools (lib/fusion_reader/helper_pass.py)."""
import json
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakeSolid, fake_brep_tools
from tests.test_capture_reader import (Coll, FakeDesign, Obj, P, body, entry, extrude, feature, matrix, rect_profile,
                                       sketch_entry)
from tests.test_capture_reader_helpers import Design, Rod, read

from lib.fusion_reader import read_intersect
from lib.translator import tool_items

SQUARE = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
BRICK = "lib.fusion_reader.read_intersect._brep_tools"


class Brick(FakeSolid):
    objectType = "adsk::fusion::BRepBody"


def named(value, name="d1", expression="gap"):
    """A model parameter (Fusion cm or radians)."""
    return Obj(name=name, expression=expression, value=value)


def item_of(design, target, name):
    return next(i for i in read(design, target)["items"] if i["name"] == name)


def with_feature(entity_and_name, bodies=None):
    target = body()
    design = FakeDesign([sketch_entry(), entry(entity_and_name)], target)
    return design, target


class PasteTest(unittest.TestCase):
    def read(self, **kw):
        source = kw.pop("source", Brick(vertices=SQUARE, token="b2", name="Body2"))
        result = Brick(vertices=[(p[0] + 20, p[1], p[2]) for p in SQUARE], token="b3", name="Body3")
        members = dict(sourceBody=Coll([source]))
        members.update(kw)
        design, target = with_feature(feature("CopyPasteBody", "Paste1", bodies=[result], **members))
        data = item_of(design, target, "Paste1")["data"]
        json.dumps(data)
        return data

    def test_the_source_and_the_result_come_with_their_points(self):
        data = self.read()
        self.assertEqual(data["sources"], [{"token": "b2", "name": "Body2", "points": [list(map(float, p)) for p in SQUARE]}])
        self.assertEqual([(b["token"], b["points"][0]) for b in data["result_bodies"]], [("b3", [20, 0, 0])])

    def test_every_body_of_the_collection_is_a_source(self):
        other = Brick(vertices=SQUARE, token="b4", name="Body4")
        data = self.read(sourceBody=Coll([Brick(vertices=SQUARE, token="b2", name="Body2"), other]))
        self.assertEqual([s["token"] for s in data["sources"]], ["b2", "b4"])

    def test_a_single_body_is_taken_as_the_source(self):
        data = self.read(sourceBody=Brick(vertices=SQUARE, token="b2", name="Body2"))
        self.assertEqual([s["token"] for s in data["sources"]], ["b2"])

    def test_a_source_that_cannot_be_read_leaves_the_sources_empty(self):
        data = self.read(source=Obj())
        self.assertEqual(data["sources"][0]["points"], [])
        self.assertEqual(self.read(sourceBody=None)["sources"], [])

    def test_a_vertex_that_cannot_be_read_leaves_no_points(self):
        source = Brick(vertices=SQUARE, token="b2")
        source.vertices._items[1].geometry = None
        self.assertEqual(self.read(source=source)["sources"][0]["points"], [])

    def test_results_that_cannot_be_read_are_null(self):
        target = body()
        paste = Obj("fusion::CopyPasteBody", parentComponent=Obj(entityToken="root"),
                    sourceBody=Coll([Brick(vertices=SQUARE)]))
        design = FakeDesign([sketch_entry(), entry((paste, "Paste1"))], target)
        self.assertIsNone(item_of(design, target, "Paste1")["data"]["result_bodies"])


class MoveTest(unittest.TestCase):
    """The moved body's vertices are read by token, so the fake design hands out a body that moved at the item."""

    class Design(FakeDesign):
        def __init__(self, entries, target, moved):
            super().__init__(entries, target)
            self.moved = moved

        def findEntityByToken(self, token):
            if token == "b2":
                points = self.moved if self.timeline.markerPosition >= 2 else SQUARE
                return [Brick(vertices=points, token="b2", name="Body2")]
            return super().findEntityByToken(token)

    def read(self, definition, entities=None, **kw):
        entities = [Brick(vertices=SQUARE, token="b2", name="Body2")] if entities is None else entities
        moved = [(p[0] + 5, p[1], p[2]) for p in SQUARE]
        target = body()
        move = feature("MoveFeature", "Move1", inputEntities=Coll(entities), definition=definition, **kw)
        design = self.Design([sketch_entry(), entry(move)], target, moved)
        data = item_of(design, target, "Move1")["data"]
        json.dumps(data)
        return data

    def test_a_move_along_the_axes_has_its_distances_and_the_points_before_and_after(self):
        definition = Obj("fusion::MoveFeatureTranslateXYZDefinition", xDistance=named(0.5, "d1", "gap"),
                         yDistance=Obj(value=0.0), zDistance=Obj(value=0.0), isDesignSpace=True)
        data = self.read(definition)
        self.assertEqual((data["input_kind"], data["move_type"], data["translate"], data["is_design_space"]),
                         ("bodies", "translateXYZ", [5.0, 0.0, 0.0], True))
        self.assertEqual(data["bodies"], [{"token": "b2", "name": "Body2"}])
        self.assertEqual((data["points_before"][0][0], data["points_after"][0][0]), ([0, 0, 0], [5, 0, 0]))
        self.assertEqual(data["params"], {"translate.0": {"name": "d1", "expression": "gap", "value": 5.0}})

    def test_a_distance_that_cannot_be_read_is_null(self):
        definition = Obj("fusion::MoveFeatureTranslateXYZDefinition", xDistance=Obj(value=0.5))
        data = self.read(definition)
        self.assertEqual((data["translate"], data["is_design_space"]), ([5.0, None, None], None))

    def test_a_rotation_has_its_angle_and_axis(self):
        axis = Obj("fusion::ConstructionAxis", geometry=Obj(origin=P(5, 5, 0), direction=Obj(x=0.0, y=0.0, z=1.0)))
        data = self.read(Obj("fusion::MoveFeatureRotateDefinition", angle=named(1.5707963267948966, "d2", "tilt"),
                             axisEntity=axis))
        self.assertEqual((data["move_type"], data["angle_deg"], data["axis"]["dir"]), ("rotate", 90.0, [0.0, 0.0, 1.0]))
        self.assertEqual(data["params"]["angle_deg"]["expression"], "tilt")

    def test_a_rotation_whose_members_cannot_be_read_gives_null_and_other(self):
        data = self.read(Obj("fusion::MoveFeatureRotateDefinition"))
        self.assertEqual((data["angle_deg"], data["axis"]), (None, {"kind": "other"}))

    def test_a_free_move_has_its_transform_when_it_can_be_read(self):
        free = Obj("fusion::MoveFeatureFreeMoveDefinition", transform=matrix(origin=(10, 0, 0)))
        data = self.read(free)
        self.assertEqual((data["move_type"], data["transform"]["origin"]), ("free", [10, 0, 0]))
        self.assertIsNone(self.read(Obj("fusion::MoveFeatureFreeMoveDefinition"))["transform"])

    def test_a_move_along_an_entity_lists_the_parameter_of_its_distance(self):
        data = self.read(Obj("fusion::MoveFeatureTranslateAlongEntityDefinition", distance=named(0.5)))
        self.assertEqual(data["params"], {"distance": {"name": "d1", "expression": "gap", "value": 5.0}})

    def test_a_move_to_a_position_lists_the_parameters_of_its_distances(self):
        data = self.read(Obj("fusion::MoveFeaturePointToPositionDefinition", xDistance=named(0.5),
                             yDistance=named(0.2, "d2", "lift"), zDistance=Obj(value=0.0)))
        self.assertEqual({path: ref["expression"] for path, ref in data["params"].items()},
                         {"translate.0": "gap", "translate.1": "lift"})

    def test_the_other_kinds_of_move_are_named_and_a_definition_that_cannot_be_read_is_other(self):
        for name, expected in (("PointToPoint", "pointToPoint"), ("PointToPosition", "pointToPosition"),
                               ("TranslateAlongEntity", "alongEntity")):
            self.assertEqual(self.read(Obj("fusion::MoveFeature%sDefinition" % name))["move_type"], expected)
        self.assertEqual(self.read(None)["move_type"], "other")

    def test_a_move_of_faces_names_no_bodies(self):
        data = self.read(Obj("fusion::MoveFeatureFreeMoveDefinition"), entities=[Obj("fusion::BRepFace")])
        self.assertEqual((data["input_kind"], data["bodies"], data["points_before"]), ("faces", [], []))

    def test_inputs_that_cannot_be_read_are_other(self):
        target = body()
        move = Obj("fusion::MoveFeature", parentComponent=Obj(entityToken="root"), bodies=Coll([]))
        design = FakeDesign([sketch_entry(), entry((move, "Move1"))], target)
        data = item_of(design, target, "Move1")["data"]
        self.assertEqual((data["input_kind"], data["bodies"], data["move_type"]), ("other", [], "other"))

    def test_a_body_that_cannot_be_found_after_the_move_has_no_points_after(self):
        data = self.read(Obj("fusion::MoveFeatureFreeMoveDefinition"),
                         entities=[Brick(vertices=SQUARE, token="gone", name="Body9")])
        self.assertEqual(data["points_after"], [[]])


class BodyPatternTest(unittest.TestCase):
    def read(self, type_name, entities, **kw):
        copies = [Brick(vertices=[(p[0] + 20, p[1], p[2]) for p in SQUARE], token="b4", name="Body4")]
        members = dict(inputEntities=Coll(entities), patternEntityType="BodiesPatternEntityType", patternElements=Coll([]),
                       quantityOne=Obj(value=2), distanceOne=Obj(value=2.0), mirrorPlane=None, isCombine=False)
        members.update(kw)
        design, target = with_feature(feature(type_name, "Pattern1", bodies=copies, **members))
        data = item_of(design, target, "Pattern1")["data"]
        json.dumps(data)
        return data

    def test_a_pattern_of_bodies_has_the_points_of_its_sources_and_copies(self):
        source = Brick(vertices=SQUARE, token="b2", name="Body2")
        for type_name in ("RectangularPatternFeature", "MirrorFeature"):
            with self.subTest(type_name):
                data = self.read(type_name, [source])
                self.assertEqual(data["source_bodies"][0]["points"][1], [10, 0, 0])
                self.assertEqual([(b["token"], b["points"][0]) for b in data["result_bodies"]], [("b4", [20, 0, 0])])

    def test_a_pattern_of_features_has_no_bodies(self):
        data = self.read("RectangularPatternFeature", [Obj("fusion::ExtrudeFeature", timelineObject=Obj(index=1))],
                         patternEntityType="FeaturesPatternEntityType")
        self.assertNotIn("source_bodies", data)
        self.assertNotIn("result_bodies", data)

    def test_copies_that_cannot_be_read_are_null(self):
        target = body()
        pattern = Obj("fusion::MirrorFeature", parentComponent=Obj(entityToken="root"),
                      inputEntities=Coll([Brick(vertices=SQUARE, token="b2")]),
                      patternEntityType="BodiesPatternEntityType", isCombine=False, mirrorPlane=None)
        design = FakeDesign([sketch_entry(), entry((pattern, "Mirror1"))], target)
        self.assertIsNone(item_of(design, target, "Mirror1")["data"]["result_bodies"])


class Live(Obj):
    """A body whose volume (cm3) and top (mm) change with the timeline marker: `stages` maps the first marker position
    of each stage to `(volume, top)`. `clock` is the timeline, set once the design exists."""

    def __init__(self, stages, broken=False, **kw):
        super().__init__("fusion::BRepBody", **kw)
        self.stages, self.broken, self.clock = stages, broken, None

    def _stage(self):
        marker = self.clock.markerPosition
        return self.stages[max(k for k in self.stages if k <= marker)]

    @property
    def volume(self):
        if self.broken:
            raise RuntimeError("no volume")
        return self._stage()[0]

    @property
    def boundingBox(self):
        return Obj(minPoint=P(0, 0, 0), maxPoint=P(10, 10, self._stage()[1]))


class CombineToolTest(unittest.TestCase):
    """Combines of the target with tools of known volume, in the target's own component."""

    def combine(self, tools, operation="CutFeatureOperation"):
        target = Live({0: (6.0, 10), 1: (6.0, 10)}, entityToken="b1", name="Body1", cells={1, 2, 3, 4, 5, 6})
        entity = feature("CombineFeature", "Combine1", bodies=[target], targetBody=target, toolBodies=Coll(tools),
                         operation=operation, isKeepToolBodies=False)
        design = FakeDesign([entry(entity)], target, appears_at=0)
        target.clock = design.timeline
        return design, target

    def cell_tool(self, token, cells):
        return Obj("fusion::BRepBody", entityToken=token, name="Body" + token, volume=float(len(cells)), cells=set(cells))

    def test_each_tool_has_its_volume_and_an_unreadable_one_is_null(self):
        sound = self.cell_tool("b2", {1, 2})
        broken = Live({0: (1.0, 1)}, broken=True, entityToken="b3", name="Body3")
        design, target = self.combine([sound, broken])
        tools = item_of(design, target, "Combine1")["data"]["tools"]
        self.assertEqual([t["volume"] for t in tools], [2000.0, None])

    def read_intersect(self, tools, after, **patches):
        design, target = self.combine(tools, "IntersectFeatureOperation")
        target.stages[1] = (after, 10)
        with mock.patch(BRICK, return_value=fake_brep_tools(**patches)):
            data = item_of(design, target, "Combine1")["data"]
        json.dumps(data)
        return data, target

    def tools(self):
        return [self.cell_tool("b2", {1, 2, 3, 4}), self.cell_tool("b3", {3, 4, 5, 9})]

    def test_a_result_the_part_shares_with_every_tool_is_every(self):
        data, target = self.read_intersect(self.tools(), 2.0)
        self.assertEqual((data["intersect_volumes"], data["intersect_model"]), ({"every": 2000.0, "any": 5000.0}, "every"))
        self.assertEqual(target.cells, {1, 2, 3, 4, 5, 6})

    def test_a_result_the_part_shares_with_any_tool_is_any(self):
        self.assertEqual(self.read_intersect(self.tools(), 5.0)[0]["intersect_model"], "any")

    def test_a_result_that_fits_neither_is_unknown(self):
        self.assertEqual(self.read_intersect(self.tools(), 3.0)[0]["intersect_model"], "unknown")

    def test_when_both_candidates_are_equal_the_model_is_every(self):
        same = [self.cell_tool("b2", {1, 2}), self.cell_tool("b3", {1, 2})]
        self.assertEqual(self.read_intersect(same, 2.0)[0]["intersect_model"], "every")

    def test_a_failed_temporary_boolean_is_unknown(self):
        self.assertEqual(self.read_intersect(self.tools(), 2.0, failing=True)[0]["intersect_model"], "unknown")

    def test_tools_that_share_nothing_still_measure_what_any_tool_holds(self):
        apart = [self.cell_tool("b2", {1, 2}), self.cell_tool("b3", {3, 4})]
        data, _ = self.read_intersect(apart, 4.0, empty_fails=True)
        self.assertEqual((data["intersect_volumes"], data["intersect_model"]), ({"every": 0.0, "any": 4000.0}, "any"))

    def test_without_the_temporary_body_manager_it_is_unknown(self):
        design, target = self.combine(self.tools(), "IntersectFeatureOperation")
        data = item_of(design, target, "Combine1")["data"]
        self.assertEqual(data["intersect_model"], "unknown")

    def test_a_result_volume_that_cannot_be_read_is_unknown(self):
        self.assertEqual(read_intersect.model({"every": 1.0, "any": 2.0}, None), "unknown")

    def test_a_tool_of_another_component_is_not_measured(self):
        self.assertIsNone(read_intersect.volumes(Obj(), [{"foreign": True}, {}]))

    def test_only_an_intersect_of_several_tools_is_measured(self):
        for tools, operation in ((self.tools(), "CutFeatureOperation"), (self.tools()[:1], "IntersectFeatureOperation")):
            design, target = self.combine(tools, operation)
            data = item_of(design, target, "Combine1")["data"]
            self.assertNotIn("intersect_model", data)
            self.assertNotIn("intersect_volumes", data)


class OwnToolStatesTest(unittest.TestCase):
    """A tool made in the target's own component: its steps are read already, the pass adds the body's states."""

    class Design(FakeDesign):
        def __init__(self, entries, target, tool, appears_at):
            super().__init__(entries, target)
            self.tool, self.tool_at = tool, appears_at

        def findEntityByToken(self, token):
            if token == "b2":
                return [self.tool] if self.timeline.markerPosition >= self.tool_at else []
            return super().findEntityByToken(token)

    def design(self, broken=False):
        target = body()
        tool = Live({3: (4.0, 10), 4: (3.0, 8)}, broken=broken, entityToken="b2", name="Body2")
        entries = [sketch_entry(), extrude(rect_profile(), target=target),
                   extrude(rect_profile(), name="Tool", target=tool),
                   extrude(rect_profile(), name="Cut2", target=tool, operation="CutFeatureOperation"),
                   entry(feature("CombineFeature", "Combine1", bodies=[target], targetBody=target,
                                 toolBodies=Coll([tool]), operation="CutFeatureOperation", isKeepToolBodies=False))]
        design = self.Design(entries, target, tool, appears_at=3)
        tool.clock = design.timeline
        return design, target

    def items(self, **kw):
        design, target = self.design(**kw)
        return {i["name"]: i for i in read(design, target)["items"]}

    def test_each_step_that_made_the_tool_records_the_body_before_and_after_it(self):
        items = self.items()
        self.assertEqual(items["Tool"]["body_states"],
                         {"b2": {"box_before": None, "volume_before": None, "volume_after": 4000.0}})
        self.assertEqual(items["Cut2"]["body_states"], {"b2": {
            "box_before": {"min": [0, 0, 0], "max": [10, 10, 10]}, "volume_before": 4000.0, "volume_after": 3000.0}})
        json.dumps(items["Cut2"])

    def test_steps_of_other_bodies_and_the_tools_own_feature_data_are_left_alone(self):
        items = self.items()
        self.assertNotIn("body_states", items["Extrude1"])
        self.assertNotIn("helper_of", items["Tool"])
        self.assertEqual(items["Tool"]["data"]["operation"], "newBody")

    def test_a_body_whose_volume_cannot_be_read_has_null_volumes(self):
        state = self.items(broken=True)["Cut2"]["body_states"]["b2"]
        self.assertEqual((state["volume_before"], state["volume_after"]), (None, None))
        self.assertIsNotNone(state["box_before"])

    def test_steps_past_the_limit_are_not_read_and_say_why(self):
        design, target = self.design()
        original = tool_items.plan
        with mock.patch.object(tool_items, "plan", lambda items, target=None: original(items, target, max_items=1)):
            items = {i["name"]: i for i in read(design, target)["items"]}
        self.assertIn("body_states", items["Tool"])
        self.assertEqual((items["Cut2"].get("body_states"), items["Cut2"]["helper_unread"]), (None, tool_items.TOO_MANY))


class PastedFromAnotherComponentTest(unittest.TestCase):
    """A Paste in the target's component of a body that lives in another component."""

    class PasteDesign(Design):
        def __init__(self, entries, target, rod, pasted):
            super().__init__(entries, target, rod)
            self.pasted = pasted

        def findEntityByToken(self, token):
            if token == "b3":
                return [self.pasted] if self.timeline.markerPosition >= 4 else []
            return super().findEntityByToken(token)

    def design(self):
        rod, target = Rod(), body()
        pasted = Live({4: (4.0, 10)}, entityToken="b3", name="Body3")
        tool_step, name, extra = extrude(rect_profile(), name="Extrude2", target=rod.native)
        tool_step.parentComponent = rod.component
        entries = [sketch_entry(), extrude(rect_profile(), target=target), (tool_step, name, extra),
                   entry(feature("CopyPasteBody", "Paste1", bodies=[pasted], sourceBody=Coll([rod.proxy]))),
                   entry(feature("CombineFeature", "Combine1", bodies=[target], targetBody=target,
                                 toolBodies=Coll([pasted]), operation="CutFeatureOperation", isKeepToolBodies=False))]
        design = self.PasteDesign(entries, target, rod, pasted)
        pasted.clock = design.timeline
        return design, target

    def capture(self):
        design, target = self.design()
        capture = read(design, target)
        return capture, {i["name"]: i for i in capture["items"]}

    def test_the_source_has_its_place_and_its_steps_are_read_in_its_own_component(self):
        _, items = self.capture()
        source = items["Paste1"]["data"]["sources"][0]
        self.assertEqual((source["foreign"], source["token"], source["place"]["frame"]["origin"]),
                         (True, "b2", [100, 50, 0]))
        step = items["Extrude2"]
        self.assertEqual((step["helper_of"], step["in_target_component"], list(step["body_states"])), ("b2", False, ["b2"]))

    def test_the_paste_records_the_pasted_body_and_the_copy_follows_the_tool(self):
        capture, items = self.capture()
        self.assertEqual(list(items["Paste1"]["body_states"]), ["b3"])
        self.assertEqual(items["Paste1"]["body_states"]["b3"]["volume_after"], 4000.0)
        self.assertNotIn("helper_of", items["Paste1"])
        json.dumps(capture)

    def test_a_source_past_the_tool_limit_has_a_place_with_the_reason(self):
        design, target = self.design()
        original = tool_items.plan
        with mock.patch.object(tool_items, "plan", lambda items, target=None: original(items, target, max_tools=0)):
            items = {i["name"]: i for i in read(design, target)["items"]}
        self.assertEqual(items["Paste1"]["data"]["sources"][0]["place"], {"error": tool_items.TOO_MANY_TOOLS})
        self.assertEqual(items["Extrude2"]["helper_unread"], tool_items.TOO_MANY_TOOLS)


if __name__ == "__main__":
    unittest.main()
