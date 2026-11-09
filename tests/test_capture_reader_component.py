"""Capture of a body inside a component: native target, placement, component items, target changes, foreign inputs."""
import json
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeOccurrence, FakeSolid, apply_matrix, turn_z
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, entry, extrude, feature, rect_profile
from tests.test_capture_reader_finish import edge, face, with_edges
from tests.test_capture_reader_params import model_param

from lib.fusion_reader.capture import read_capture
from lib.fusion_reader.read_geometry import ReadContext, foreign
from lib.fusion_reader.sketches import read_sketches, sketch_key

PLACE = turn_z(90, (100, 50, 0))
CORNERS = [(0, 0, 0), (40, 0, 0), (0, 20, 0), (0, 0, 10)]


class Tray:
    """The Tray component with one native body and its proxy in the root."""

    def __init__(self):
        self.component = Obj(entityToken="tray", name="Tray", bRepBodies=Coll([]), modelParameters=Coll([]),
                             sketches=Coll([]))
        self.native = FakeSolid(CORNERS, component=self.component, token="t1", name="Body1")
        self.native.volume = 8.0
        self.native.boundingBox = Obj(minPoint=P(0, 0, 0), maxPoint=P(40, 20, 10))
        self.component.bRepBodies = Coll([self.native])
        self.occurrence = FakeOccurrence("Tray:1", PLACE, component=self.component)
        self.proxy = FakeSolid([apply_matrix(PLACE, p) for p in CORNERS], context=self.occurrence,
                               native=self.native, component=self.component, token="t1:path", name="Body1")

    def design(self, entries, appears_at=1):
        design = FakeDesign(entries, self.native, appears_at=appears_at)
        design.rootComponent = Obj(entityToken="root", name="Assembly", bRepBodies=Coll([]),
                                   allOccurrencesByComponent=lambda c: Coll([self.occurrence]),
                                   modelParameters=Coll([]))
        return design

    def feature(self, type_name, name, **kw):
        kw.setdefault("parentComponent", self.component)
        return entry(feature(type_name, name, **kw))

    def extrude(self, **kw):
        entity, name, extra = extrude(rect_profile(), target=self.native, **kw)
        entity.parentComponent = self.component
        return entity, name, extra


class BodiesWhen:
    """A bodies collection whose content follows the timeline marker."""

    def __init__(self, bodies):
        self._bodies = bodies

    @property
    def count(self):
        return len(self._bodies())

    def item(self, i):
        return self._bodies()[i]


def read(design, picked):
    return read_capture(design, picked, fusion="", name="", up_axis="z")


class ComponentEnvelopeTest(unittest.TestCase):
    def setUp(self):
        self.tray = Tray()
        self.capture = read(self.tray.design([self.tray.feature("Sketch", "Sketch1"), self.tray.extrude()]),
                            self.tray.proxy)

    def test_target_is_native_with_its_component_and_placement(self):
        target = self.capture["target"]
        self.assertEqual((target["token"], target["box"]["max"], target["volume_mm3"]), ("t1", [40, 20, 10], 8000.0))
        self.assertEqual(target["component"], {"token": "tray", "name": "Tray", "root": False})
        self.assertEqual(target["placement"]["frame"]["origin"], [100, 50, 0])
        self.assertEqual(self.capture["targets"], [target])
        json.dumps(self.capture)

    def test_items_name_their_component_and_list_its_bodies(self):
        sketch, ext = self.capture["items"]
        self.assertEqual((ext["component"], ext["in_target_component"]), ("tray", True))
        self.assertEqual(ext["bodies_before"], [{"token": "t1", "name": "Body1"}])
        self.assertEqual(ext["data"]["operation"], "newBody")
        self.assertEqual(sketch["data"], {})


class ComponentItemsTest(unittest.TestCase):
    def test_items_of_other_components_are_listed_without_their_data(self):
        tray = Tray()
        elsewhere = Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="root"),
                        bodies=Coll([Obj(entityToken="x1", name="Other")]))
        design = tray.design([tray.feature("Sketch", "Sketch1"), tray.extrude(), (elsewhere, "Extrude9", {})])
        item = read(design, tray.proxy)["items"][2]
        self.assertEqual((item["component"], item["in_target_component"], item["data"]), ("root", False, {}))
        self.assertEqual(item["bodies_after"], [{"token": "x1", "name": "Other"}])

    def test_a_proxy_entity_is_turned_native_and_marked(self):
        tray = Tray()
        native = Obj("fusion::ExtrudeFeature", parentComponent=tray.component, bodies=Coll([]))
        proxy = Obj("fusion::ExtrudeFeature", parentComponent=Obj(entityToken="root"), bodies=Coll([]),
                    assemblyContext=tray.occurrence, nativeObject=native)
        item = read(tray.design([(proxy, "Extrude1", {})]), tray.proxy)["items"][0]
        self.assertEqual((item["entity_context"], item["component"], item["in_target_component"]),
                         ("proxy", "tray", True))

    def test_target_changed_follows_the_box_and_volume_at_each_position(self):
        tray = Tray()
        design = tray.design([tray.feature("Sketch", "S"), tray.extrude(),
                              tray.feature("Sketch", "S2"), tray.feature("EmbossFeature", "Cut")])
        timeline = design.timeline
        # The body exists from marker 2 on and loses volume from marker 4 on.
        tray.component.bRepBodies = BodiesWhen(lambda: [tray.native] if timeline.markerPosition >= 2 else [])

        def find(token):
            tray.native.volume = 8.0 if timeline.markerPosition < 4 else 7.0
            return [tray.native] if token == "t1" and timeline.markerPosition >= 2 else []

        design.findEntityByToken = find
        items = read(design, tray.proxy)["items"]
        self.assertEqual([i["target_changed"] for i in items], [None, True, False, True])

    def test_target_changed_is_null_when_the_target_cannot_be_measured(self):
        tray = Tray()
        design = tray.design([tray.feature("Sketch", "S"), tray.extrude()])
        timeline = design.timeline
        box = tray.native.boundingBox

        def find(token):
            tray.native.boundingBox = None if timeline.markerPosition < 2 else box
            return [tray.native]

        design.findEntityByToken = find
        self.assertEqual([i["target_changed"] for i in read(design, tray.proxy)["items"]], [None, None])


class ComponentParametersTest(unittest.TestCase):
    def test_model_parameters_merge_along_the_path_and_name_their_component(self):
        tray = Tray()
        box = Obj(entityToken="box", name="Box")
        dimension = Obj("fusion::SketchLinearDimension", entityToken="d", name="d",
                        parentSketch=Obj(name="Sketch1", parentComponent=tray.component))

        def param(name, created_by=None):
            return Obj(name=name, expression="1 mm", value=0.1, unit="mm", role="x", createdBy=created_by,
                       comment="", isFavorite=False, valueType="x")

        tray.component.modelParameters = Coll([param("d1", dimension)])
        box.modelParameters = Coll([param("d2"), param("d1")])
        design = tray.design([])
        design.rootComponent.modelParameters = Coll([param("d3")])
        inner = FakeOccurrence("Tray:2", PLACE, parent=FakeOccurrence("Box:1", PLACE, component=box),
                               component=tray.component)
        tray.proxy.assemblyContext = inner
        model = read(design, tray.proxy)["parameters"]["model"]
        self.assertEqual([p["name"] for p in model], ["d1", "d2", "d3"])
        by_name = {p["name"]: p["created_by"]["component"] for p in model}
        self.assertEqual(by_name, {"d1": "tray", "d2": "box", "d3": "root"})


class ForeignTest(unittest.TestCase):
    def setUp(self):
        self.tray = Tray()
        self.other = Obj(entityToken="box", name="Box")

    def ctx(self):
        return ReadContext(self.tray.design([]), self.tray.proxy)

    def test_foreign_by_component_or_by_occurrence(self):
        ctx = self.ctx()
        mine = Obj(parentComponent=self.tray.component)
        self.assertFalse(foreign(mine, ctx))
        self.assertTrue(foreign(Obj(parentComponent=self.other), ctx))
        self.assertTrue(foreign(Obj(parentComponent=self.tray.component, assemblyContext=object()), ctx))
        self.assertTrue(foreign(Obj(body=Obj(parentComponent=self.other)), ctx))
        self.assertTrue(foreign(Obj(parentSketch=Obj(parentComponent=self.other)), ctx))
        self.assertFalse(foreign(Obj(), ctx))
        self.assertFalse(foreign(mine, None))

    def read_data(self, entity_entry):
        return read(self.tray.design([self.tray.feature("Sketch", "S"), entity_entry]), self.tray.proxy)["items"][1]["data"]

    def test_extrude_inputs_from_another_component_are_flagged(self):
        sketch = Obj("fusion::Sketch", name="Sketch1", parentComponent=self.other, transform=rect_profile().parentSketch.transform)
        profile = rect_profile()
        profile.parentSketch = sketch
        end_face = Obj("fusion::BRepFace", body=Obj(parentComponent=self.other), pointOnFace=P(0, 0, 5),
                       geometry=Obj("core::Plane", origin=P(0, 0, 5), normal=Obj(x=0, y=0, z=1)))
        extent = Obj("fusion::ToEntityExtentDefinition", entity=end_face, offset=param_value(0.0))
        ext = self.tray.extrude(extentType="OneSideFeatureExtentType", extentOne=extent,
                                participantBodies=Coll([self.tray.proxy, self.tray.native]))
        ext[0].profile = profile
        data = self.read_data(ext)
        self.assertTrue(data["profiles"][0]["foreign"])
        self.assertTrue(data["side_one"]["foreign"])
        self.assertEqual([p.get("foreign") for p in data["participants"]], [True, None])

    def test_native_inputs_carry_no_flag(self):
        data = self.read_data(self.tray.extrude())
        self.assertNotIn("foreign", data["profiles"][0])
        self.assertNotIn("foreign", json.dumps(data["participants"]))

    def test_fillet_edges_and_shell_inputs_from_another_body_are_flagged(self):
        stray = edge("e1", 1)
        stray.body = Obj(parentComponent=self.other)
        own = edge("e2", 2)
        own.body = Obj(parentComponent=self.tray.component)
        edge_set = with_edges("ConstantRadiusFilletEdgeSet", [stray, own], radius=model_param("d", "r", 0.2),
                              isTangentChain=False, continuity="TangentSurfaceContinuityType")
        data = self.read_data(self.tray.feature("FilletFeature", "Fillet1", edgeSets=Coll([edge_set])))
        self.assertEqual([e.get("foreign") for e in data["sets"][0]["edges"]], [True, None])
        shell_face = face("f1")
        shell_face.body = Obj(parentComponent=self.other)
        shell = self.tray.feature("ShellFeature", "Shell1", inputEntities=Coll([shell_face]), insideThickness=Obj(value=0.2))
        self.assertTrue(self.read_data(shell)["faces"][0]["foreign"])

    def test_combine_target_and_tools_are_flagged(self):
        tool = Obj("fusion::BRepBody", entityToken="x9", name="Tool", parentComponent=self.other)
        combine = self.tray.feature("CombineFeature", "Combine1", targetBody=self.tray.native, toolBodies=Coll([tool]),
                                    operation="CutFeatureOperation")
        data = self.read_data(combine)
        self.assertNotIn("foreign", data["target"])
        self.assertTrue(data["tools"][0]["foreign"])


class SketchKeyTest(unittest.TestCase):
    def test_sketches_are_keyed_by_component_so_equal_names_do_not_meet(self):
        def component(token):
            point = Obj(worldGeometry=Obj(x=1.0, y=2.0, z=3.0))
            sketch = Obj(name="Sketch1", sketchPoints=Coll([point]), sketchCurves=Coll([]))
            return Obj(entityToken=token, sketches=Coll([sketch]))

        self.assertEqual(list(read_sketches(component("tray"))), ["tray/Sketch1"])
        self.assertEqual(list(read_sketches(component("box"))), ["box/Sketch1"])
        self.assertEqual(read_sketches(component("tray"), skip={"Sketch1"}), {})
        self.assertEqual(read_sketches(component("tray"), skip={sketch_key("tray", "Sketch1")}), {})
        self.assertEqual(list(read_sketches(component("tray"), skip={sketch_key("box", "Sketch1")})), ["tray/Sketch1"])


def param_value(value):
    return Obj(value=value)


if __name__ == "__main__":
    unittest.main()
