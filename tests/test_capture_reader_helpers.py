"""The second reading pass: steps of a tool body that lives in another component (lib/fusion_reader/helper_pass.py)."""
import json
import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401
from tests.fakes import FakeOccurrence, FakeSolid, Vec, apply_matrix, turn_z
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, entry, extrude, feature, rect_profile, sketch_entry, body

from lib.fusion_reader import helper_pass
from lib.fusion_reader.capture import read_capture
from lib.translator import tool_items

PLACE = turn_z(90, (100, 50, 0))
AXES = {"xy": (0, 0, 1), "xz": (0, 1, 0), "yz": (1, 0, 0)}
MEMBERS = {"xy": "xYConstructionPlane", "xz": "xZConstructionPlane", "yz": "yZConstructionPlane"}


def turned(v):
    o, x, y, z = PLACE
    return tuple(v[0] * x[i] + v[1] * y[i] + v[2] * z[i] for i in range(3))


class Rod:
    """A component Rod with a tool body, placed once at PLACE, with its three origin planes."""

    def __init__(self):
        self.component = Obj(entityToken="rod", name="Rod", bRepBodies=Coll([]), sketches=Coll([]),
                             modelParameters=Coll([Obj("fusion::ModelParameter", name="d7", expression="tool_len",
                                                       value=2.0, unit="mm")]))
        self.native = FakeSolid(component=self.component, token="b2", name="Body2")
        self.native.volume = 1.0
        self.native.boundingBox = Obj(minPoint=P(0, 0, 0), maxPoint=P(10, 10, 10))
        self.component.bRepBodies = Coll([self.native])
        self.occurrence = FakeOccurrence("Rod:1", PLACE, component=self.component)
        self.proxy = Obj("fusion::BRepBody", entityToken="b2:path", name="Body2", assemblyContext=self.occurrence,
                         nativeObject=self.native, parentComponent=self.component)
        for slot, axis in AXES.items():
            native = Obj("fusion::ConstructionPlane", entityToken="pl_" + slot, parentComponent=self.component,
                         geometry=Obj("core::Plane", origin=P(0, 0, 0), normal=Obj(x=axis[0], y=axis[1], z=axis[2])))
            setattr(self.component, MEMBERS[slot], native)
            self._proxy_of(native, axis)

    def _proxy_of(self, native, axis):
        rotated = turned(axis)
        proxy = Obj("fusion::ConstructionPlane", entityToken=native.entityToken + ":path",
                    assemblyContext=self.occurrence, nativeObject=native,
                    geometry=Obj("core::Plane", origin=P(*PLACE[0]), normal=Obj(x=rotated[0], y=rotated[1], z=rotated[2])))
        native.createForAssemblyContext = lambda occurrence: proxy


class Design(FakeDesign):
    """A design whose bodies appear at a marker position."""

    def __init__(self, entries, target, rod, tool_at=3):
        super().__init__(entries, target)
        self.rod, self.tool_at = rod, tool_at
        self.rootComponent = Obj(entityToken="root", name="Assembly", bRepBodies=Coll([]), modelParameters=Coll([]),
                                 allOccurrencesByComponent=lambda c: Coll([rod.occurrence]))

    def findEntityByToken(self, token):
        if token == "b2" and self.timeline.markerPosition >= self.tool_at:
            return [self.rod.native]
        return super().findEntityByToken(token)


def tool_entries(rod, target, tool_extrude=True, operation="CutFeatureOperation"):
    steps = [sketch_entry(), extrude(rect_profile(), target=target)]
    if tool_extrude:
        entity, name, extra = extrude(rect_profile(), name="Extrude2", target=rod.native)
        entity.parentComponent = rod.component
        steps.append((entity, name, extra))
    combine = entry(feature("CombineFeature", "Combine1", bodies=[target], targetBody=target,
                            toolBodies=Coll([rod.proxy]), operation=operation, isKeepToolBodies=False))
    steps.append(combine)
    return steps


def read(design, target):
    return read_capture(design, target, fusion="", name="", up_axis="z")


class HelperPassTest(unittest.TestCase):
    def setUp(self):
        self.rod, self.target = Rod(), body()
        self.design = Design(tool_entries(self.rod, self.target), self.target, self.rod)
        self.capture = read(self.design, self.target)
        self.items = {i["name"]: i for i in self.capture["items"]}
        self.tool = self.items["Combine1"]["data"]["tools"][0]

    def test_the_tool_names_its_component_and_where_that_component_sits(self):
        self.assertEqual((self.tool["foreign"], self.tool["token"], self.tool["component"]),
                         (True, "b2", {"token": "rod", "name": "Rod"}))
        place = self.tool["place"]
        self.assertEqual(place["frame"]["origin"], [100, 50, 0])
        self.assertEqual((place["frame"]["x"], place["target_frame"], place["checked_points"]), ([0, 1, 0], None, 3))
        json.dumps(self.capture)

    def test_the_origin_planes_are_measured_references_in_the_parts_coordinates(self):
        place = self.tool["place"]
        self.assertEqual([place[s]["ref"]["slot"] for s in ("xy", "xz", "yz")], ["tool0.xy", "tool0.xz", "tool0.yz"])
        yz = place["yz"]["ref"]
        self.assertEqual((yz["origin"], yz["component"]["name"], yz["normal"], yz["point"]),
                         (True, "Rod", [0, 1, 0], [100, 50, 0]))

    def test_the_steps_that_made_the_tool_are_read_in_its_own_frame(self):
        step = self.items["Extrude2"]
        self.assertEqual((step["helper_of"], step["in_target_component"], step["data"]["operation"]),
                         ("b2", False, "newBody"))
        self.assertEqual(step["bodies_before"], [{"token": "b2", "name": "Body2"}])
        self.assertNotIn("foreign", step["data"]["profiles"][0])

    def test_steps_of_the_target_are_not_read_a_second_time(self):
        self.assertNotIn("helper_of", self.items["Extrude1"])

    def test_the_model_parameters_of_the_tool_component_join_the_capture(self):
        self.assertIn("d7", [p["name"] for p in self.capture["parameters"]["model"]])

    def test_only_the_steps_before_the_combine_are_rolled_to(self):
        history = self.design.timeline.history
        self.assertEqual(history[:5], [0, 1, 2, 3, 4])
        self.assertEqual(history[5:8], [3, 2, 3])
        self.assertEqual(self.design.timeline.markerPosition, 4)

    def test_a_design_without_a_foreign_tool_is_read_once(self):
        target = body()
        design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=target)], target)
        read(design, target)
        self.assertEqual(design.timeline.history, [0, 1, 2])


class HelperFailureTest(unittest.TestCase):
    def capture_with(self, edit):
        rod, target = Rod(), body()
        design = Design(tool_entries(rod, target), target, rod)
        edit(rod, design)
        capture = read(design, target)
        items = {i["name"]: i for i in capture["items"]}
        return items, items["Combine1"]["data"]["tools"][0]["place"]

    def test_a_tool_body_that_cannot_be_found_has_no_place_and_its_steps_stay_unread(self):
        items, place = self.capture_with(lambda rod, design: setattr(design, "tool_at", 99))
        self.assertIn("error", place)
        self.assertEqual((items["Extrude2"]["data"], items["Extrude2"].get("helper_of")), ({}, None))
        self.assertIn("helper_unread", items["Extrude2"])

    def test_an_occurrence_that_cannot_be_found_gives_a_place_with_an_error(self):
        def edit(rod, design):
            design.rootComponent.allOccurrencesByComponent = lambda c: Coll([])
        _, place = self.capture_with(edit)
        self.assertNotIn("frame", place)
        self.assertIn("error", place)

    def test_a_plane_that_cannot_be_shown_through_the_occurrence_gives_a_place_with_an_error(self):
        def edit(rod, design):
            rod.component.xZConstructionPlane.createForAssemblyContext = lambda occurrence: 1 / 0
        _, place = self.capture_with(edit)
        self.assertIn("error", place)

    def test_a_frame_that_does_not_land_the_planes_is_not_used(self):
        def edit(rod, design):
            rod.occurrence.transform2.matrix = turn_z(10, (100, 50, 0))
        _, place = self.capture_with(edit)
        self.assertNotIn("frame", place)

    def test_a_step_whose_reader_throws_keeps_a_read_error_and_the_pass_goes_on(self):
        def edit(rod, design):
            del design.timeline.entries[2][0].__dict__["profile"]
        items, place = self.capture_with(edit)
        self.assertIn("frame", place)
        self.assertIn("read_error", items["Extrude2"]["data"])

    def test_a_tool_in_the_targets_own_component_is_not_read_a_second_time(self):
        rod, target = Rod(), body()
        rod.proxy = Obj("fusion::BRepBody", entityToken="b2", name="Body2", parentComponent=Obj(entityToken="root"))
        design = Design(tool_entries(rod, target), target, rod)
        items = read(design, target)["items"]
        self.assertNotIn("place", items[-1]["data"]["tools"][0])
        self.assertNotIn("helper_of", items[2])


def ref(token, **kw):
    return dict({"token": token, "name": "Body" + token}, **kw)


def step(index, bodies, component="root", data=None, type_="ExtrudeFeature", **kw):
    return dict({"index": index, "name": "S%d" % index, "type": type_, "component": component,
                 "bodies_after": [ref(t) for t in bodies], "data": data or {}}, **kw)


def combine(index, tools, target="t", **kw):
    return step(index, [target], data={"target": ref(target), "tools": [ref(t) for t in tools]},
                type_="CombineFeature", **kw)


def paste(index, result, source, **kw):
    return step(index, [result], data={"sources": [ref(source)], "result_bodies": [ref(result)]},
                type_="CopyPasteBody", **kw)


def indices(pairs):
    return [pair[0]["index"] for pair in pairs]


class PlanTest(unittest.TestCase):
    def items(self, count, tool_component="rod"):
        tool = {"token": "b2", "name": "Body2", "foreign": True, "component": {"token": tool_component, "name": "Rod"}}
        out = [{"index": i, "name": "E%d" % i, "type": "ExtrudeFeature", "component": "rod", "bodies_after":
                [{"token": "b2", "name": "Body2"}], "data": {}} for i in range(count)]
        out.append({"index": count, "name": "Combine1", "type": "CombineFeature", "component": "root",
                    "in_target_component": True, "bodies_after": [{"token": "b1", "name": "Body1"}],
                    "data": {"tools": [tool]}})
        return out

    def test_an_exported_body_that_is_a_copy_follows_its_source(self):
        items = [step(0, ["s"]), paste(1, "t", "s")]
        self.assertEqual(indices(tool_items.plan(items, ref("t")).wanted), [0])

    def test_the_steps_before_the_combine_that_touch_the_tool_are_planned_in_order(self):
        plan = tool_items.plan(self.items(3))
        self.assertEqual((indices(plan.wanted), plan.left), ([0, 1, 2], []))

    def test_steps_past_the_cap_are_left(self):
        plan = tool_items.plan(self.items(5), max_items=3)
        self.assertEqual((len(plan.wanted), [(i["index"], r) for i, r in plan.left]),
                         (3, [(3, tool_items.TOO_MANY), (4, tool_items.TOO_MANY)]))

    def test_a_step_of_another_component_with_the_same_body_name_is_not_planned(self):
        items = self.items(2)
        items[0]["component"] = "elsewhere"
        self.assertEqual(indices(tool_items.plan(items).wanted), [1])

    def test_a_tool_of_the_same_component_is_planned_from_the_steps_of_that_component(self):
        items = [step(0, ["b2"]), step(1, ["b2"], component="elsewhere"), step(2, ["b1"]), combine(3, ["b2"])]
        self.assertEqual(indices(tool_items.plan(items, ref("t")).wanted), [0])

    def test_only_combines_of_the_exported_body_give_tools(self):
        items = [step(0, ["b2"]), combine(1, ["b2"], target="other")]
        self.assertEqual(tool_items.plan(items, ref("t")).sources, [])
        self.assertEqual(indices(tool_items.plan(items).wanted), [0])

    def test_the_source_of_a_paste_is_followed_with_its_depth(self):
        items = [step(0, ["b2"]), step(1, ["b2"]), paste(2, "b3", "b2"), combine(3, ["b3"])]
        plan = tool_items.plan(items, ref("t"))
        self.assertEqual((indices(plan.wanted), [(s.record["token"], s.depth) for s in plan.sources]),
                         ([2, 0, 1], [("b3", 1), ("b2", 2)]))
        self.assertEqual([r["token"] for r in plan.wanted[1][1]], ["b2"])

    def test_the_exported_body_is_never_a_source(self):
        items = [step(0, ["t"]), paste(1, "b3", "t"), combine(2, ["b3"])]
        plan = tool_items.plan(items, ref("t"))
        self.assertEqual(([s.record["token"] for s in plan.sources], indices(plan.wanted)), (["b3"], [1]))

    def test_the_tools_of_a_combine_that_changed_a_tool_are_followed(self):
        items = [step(0, ["b2"]), step(1, ["b4"]), combine(2, ["b4"], target="b2"), combine(3, ["b2"])]
        self.assertEqual(sorted(indices(tool_items.plan(items, ref("t")).wanted)), [0, 1, 2])

    def test_a_kept_tool_used_again_is_followed_up_to_the_later_combine(self):
        kept = combine(1, ["b2"])
        kept["data"]["keep_tools"] = True
        items = [step(0, ["b2"]), kept, step(2, ["b2"]), combine(3, ["b2"])]
        self.assertEqual(sorted(indices(tool_items.plan(items, ref("t")).wanted)), [0, 2])

    def test_a_kept_tool_pasted_later_is_followed_up_to_the_paste(self):
        items = [step(0, ["b2"]), combine(1, ["b2"]), step(2, ["b2"]), paste(3, "b3", "b2"), combine(4, ["b3"])]
        self.assertEqual(sorted(indices(tool_items.plan(items, ref("t")).wanted)), [0, 2, 3])

    def test_copies_of_one_source_count_as_one_body(self):
        copies = ["c%d" % n for n in range(5)]
        pattern = step(1, copies, data={"source_bodies": [ref("b2")], "result_bodies": [ref(c) for c in copies]},
                       type_="RectangularPatternFeature")
        items = [step(0, ["b2"]), pattern, combine(2, copies)]
        plan = tool_items.plan(items, ref("t"), max_tools=1)
        self.assertEqual((plan.refused, indices(plan.wanted)), ([], [1, 0]))

    def test_bodies_past_the_tool_limit_are_refused_with_their_steps_left(self):
        items = [step(0, ["b2"]), step(1, ["b3"]), combine(2, ["b2", "b3"])]
        plan = tool_items.plan(items, ref("t"), max_tools=1)
        self.assertEqual(([(r["token"], why) for r, why in plan.refused], [(i["index"], why) for i, why in plan.left]),
                         ([("b3", tool_items.TOO_MANY_TOOLS)], [(1, tool_items.TOO_MANY_TOOLS)]))
        self.assertEqual(indices(plan.wanted), [0])

    def test_sources_deeper_than_the_limit_are_left_with_their_steps(self):
        items = [step(0, ["b4"]), paste(1, "b3", "b4"), paste(2, "b2", "b3"), combine(3, ["b2"])]
        plan = tool_items.plan(items, ref("t"), max_depth=2)
        self.assertEqual(([s.record["token"] for s in plan.sources], [(i["index"], why) for i, why in plan.left]),
                         (["b2", "b3"], [(0, tool_items.TOO_DEEP)]))



class BuiltByTest(unittest.TestCase):
    def test_the_steps_behind_a_pasted_or_patterned_body_are_those_of_its_source_in_its_component(self):
        copies = step(6, ["c0"], data={"source_bodies": [ref("b3")], "result_bodies": [ref("c0")]},
                      type_="RectangularPatternFeature")
        items = [step(0, ["b4"]), step(1, ["b4"], component="elsewhere"), step(2, ["b2"]),
                 combine(3, ["b4"], target="b2"), paste(4, "b3", "b2"), combine(5, ["b3"]), copies, combine(7, ["c0"])]
        self.assertEqual(tool_items.built_by(items, ref("b3"), items[5]), {0, 2, 3, 4})
        self.assertEqual(tool_items.built_by(items, ref("c0"), items[7]), {6, 4, 3, 2})


class HelperRoundsTest(unittest.TestCase):
    def test_a_step_with_no_read_context_in_one_round_is_read_in_a_later_one(self):
        timeline = SimpleNamespace(markerPosition=0, item=lambda index: index)
        run = helper_pass._Pass(None, None, timeline, {}, {}, lambda entity: [entity], lambda hctx: [])
        item = step(2, [], in_target_component=False)
        first, second = {"name": "Body2"}, {"name": "Body5"}
        self.assertEqual(run.job(item, [first]), (False, []))
        run.contexts[id(second)] = SimpleNamespace(target_ref={"token": "b5"})
        hctx, tokens = run.job(item, [first, second])
        run.read({2: (item, hctx, tokens)})
        self.assertEqual(item["helper_of"], "b5")
        self.assertNotIn("helper_unread", item)


if __name__ == "__main__":
    unittest.main()
