"""Capture of a body inside a component: native target, placement, component items, target changes, foreign inputs."""
import json
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakeOccurrence, FakeSolid, apply_matrix, turn_z
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, entry, extrude, feature, rect_profile
from tests.test_capture_reader_finish import edge, face, with_edges
from tests.test_capture_reader_params import model_param

from lib.fusion_reader.capture import read_capture
from lib.fusion_reader.read_geometry import ReadContext, foreign
from lib.fusion_reader.read_geometry import edge_record as geo_edge_record

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

    def test_occurrences_and_construction_geometry_name_the_component_they_sit_in(self):
        tray = Tray()
        child = Obj(entityToken="lid", name="Lid")
        inside = Obj("fusion::Occurrence", name="Lid:1", component=child, sourceComponent=tray.component)
        through = Obj("fusion::Occurrence", name="Lid:1", component=child,
                      assemblyContext=Obj(component=tray.component), nativeObject=Obj("fusion::Occurrence"))
        unknown = Obj("fusion::Occurrence", name="Box:1", component=tray.component)
        plane = Obj("fusion::ConstructionPlane", component=tray.component)
        lost_plane = Obj("fusion::ConstructionPlane")
        lost_feature = Obj("fusion::ExtrudeFeature", bodies=Coll([]))
        entries = [(e, "X", {}) for e in (inside, through, unknown, plane, lost_plane, lost_feature)]
        items = read(tray.design(entries), tray.proxy)["items"]
        self.assertEqual([(i["component"], i["in_target_component"]) for i in items],
                         [("tray", True), ("tray", True), ("", False), ("tray", True), ("", False), ("", True)])
        self.assertEqual([i["bodies_after"] for i in items[:5]], [[]] * 5)
        self.assertFalse(any("read_error" in i for i in items[:5]))

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
                              tray.feature("Sketch", "S2"), tray.feature("ThickenFeature", "Cut")])
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
        # The target seen through its own occurrence is the target itself.
        self.assertEqual(data["participants"], [{"token": "t1", "name": "Body1"}] * 2)

    def test_a_sketch_of_another_component_is_read_native_and_brought_into_the_target(self):
        lid = Obj(entityToken="lid", name="Lid")
        place = turn_z(90, (110, 50, 32))
        occurrence = FakeOccurrence("Lid:1", place, component=lid)
        points = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
        sketch_points = [Obj(worldGeometry=P(*p), createForAssemblyContext=lambda occ, p=p: Obj(
            worldGeometry=P(*apply_matrix(place, p)))) for p in points]
        width = Obj(name="wall_mm", dependencyParameters=Coll([]))
        dimension = Obj(parameter=Obj(name="d7", expression="wall_mm * 2", dependencyParameters=Coll([width])))
        native = rect_profile(w=10, h=10)
        native.parentSketch = Obj("fusion::Sketch", name="Rim", parentComponent=lid,
                                  transform=native.parentSketch.transform, sketchPoints=Coll(sketch_points),
                                  sketchDimensions=Coll([dimension]))
        proxy = Obj("fusion::Profile", assemblyContext=occurrence, nativeObject=native,
                    parentSketch=Obj(parentComponent=lid))
        ext = self.tray.extrude()
        ext[0].profile = proxy
        profile = self.read_data(ext)["profiles"][0]
        self.assertEqual((profile["foreign"], profile["sketch"], profile["component"]),
                         (True, "Rim", {"token": "lid", "name": "Lid"}))
        self.assertEqual(profile["frame"], {"origin": [0, -10, 32], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]})
        self.assertEqual(profile["native_frame"]["origin"], [0, 0, 0])
        self.assertEqual((profile["placement"]["frame"]["origin"], profile["placement"]["checked_points"]),
                         ([110, 50, 32], 3))
        self.assertEqual(profile["sketch_params"], [{"name": "d7", "expression": "wall_mm * 2", "reads": ["wall_mm"]}])

    def test_a_mirror_plane_of_the_root_is_brought_into_the_target(self):
        plane = Obj("fusion::ConstructionPlane", parentComponent=Obj(entityToken="root"),
                    geometry=Obj("core::Plane", origin=P(0, 0, 0), normal=Obj(x=1, y=0, z=0)))
        mirror = self.tray.feature("MirrorFeature", "Mirror1", inputEntities=Coll([]), mirrorPlane=plane)
        record = self.read_data(mirror)["plane"]
        self.assertEqual({k: record[k] for k in ("point", "normal", "assembly")},
                         {"point": [-50, 100, 0], "normal": [0, -1, 0], "assembly": True})
        self.assertEqual((record["ref"]["slot"], record["ref"]["component"]["token"], record["ref"]["path"]),
                         ("plane", "root", ""))

    def test_a_root_plane_read_before_a_later_step_makes_the_target_is_brought_in(self):
        plane = Obj("fusion::ConstructionPlane", parentComponent=Obj(entityToken="root"),
                    geometry=Obj("core::Plane", origin=P(0, 0, 0), normal=Obj(x=1, y=0, z=0)))
        mirror = self.tray.feature("MirrorFeature", "Mirror1", inputEntities=Coll([]), mirrorPlane=plane)
        design = self.tray.design([mirror, self.tray.extrude()], appears_at=2)
        shown = self.tray.proxy.vertices
        # The picked body has no points before the step that makes it.
        self.tray.proxy.vertices = BodiesWhen(
            lambda: [shown.item(i) for i in range(shown.count)] if design.timeline.markerPosition >= 2 else [])
        record = read(design, self.tray.proxy)["items"][0]["data"]["plane"]
        self.assertEqual((record["normal"], record.get("assembly")), ([0, -1, 0], True))

    def lid(self):
        """The Lid component and an occurrence of it turned and moved in the assembly."""
        lid = Obj(entityToken="lid", name="Lid")
        place = turn_z(90, (110, 50, 32))
        occurrence = FakeOccurrence("Lid:1", place, component=lid)
        return lid, occurrence, place

    def lid_plane(self, native_point=(0, 0, 4), normal=(1, 0, 0)):
        lid, occurrence, place = self.lid()
        native = Obj("fusion::ConstructionPlane", entityToken="cp1", parentComponent=lid,
                     geometry=Obj("core::Plane", origin=P(*native_point), normal=Obj(x=normal[0], y=normal[1], z=normal[2])))
        # Seen through its occurrence the plane is in the assembly's coordinates.
        shown = apply_matrix(place, native_point)
        turned = tuple(apply_matrix(place, normal)[i] - place[0][i] for i in range(3))
        proxy = Obj("fusion::ConstructionPlane", entityToken="cp1:path", assemblyContext=occurrence, nativeObject=native,
                    geometry=Obj("core::Plane", origin=P(*shown), normal=Obj(x=turned[0], y=turned[1], z=turned[2])))
        return lid, native, proxy

    def mirror_plane(self, plane):
        mirror = self.tray.feature("MirrorFeature", "Mirror1", inputEntities=Coll([]), mirrorPlane=plane)
        return self.read_data(mirror)["plane"]

    def test_a_mirror_plane_of_another_component_is_brought_in_and_named(self):
        lid, native, proxy = self.lid_plane()
        record = self.mirror_plane(proxy)
        self.assertNotIn("foreign", record)
        self.assertTrue(record["assembly"])
        # The tray sits at the assembly origin turned 90 degrees at (100, 50, 0): its frame is the lid's own, shifted.
        self.assertEqual(record["normal"], record["ref"]["normal"])
        self.assertEqual(record["point"], record["ref"]["point"])
        self.assertEqual({k: record["ref"][k] for k in ("slot", "type", "token", "component", "path")},
                         {"slot": "plane", "type": "ConstructionPlane", "token": "cp1",
                          "component": {"token": "lid", "name": "Lid"}, "path": "Lid:1"})
        self.assertNotIn("origin", record["ref"])

    def test_an_origin_plane_of_another_component_is_marked_as_one(self):
        lid, native, proxy = self.lid_plane()
        lid.xYConstructionPlane = native
        self.assertTrue(self.mirror_plane(proxy)["ref"]["origin"])

    def test_an_axis_of_another_component_is_brought_in_without_sketch_tokens(self):
        lid, occurrence, place = self.lid()
        native = Obj("fusion::SketchLine", entityToken="ln1", parentSketch=Obj(entityToken="sk1", name="Axis sketch",
                     parentComponent=lid), worldGeometry=Obj("core::Line3D", startPoint=P(0, 0, 0), endPoint=P(0, 0, 3)))
        shown = [apply_matrix(place, p) for p in ((0, 0, 0), (0, 0, 3))]
        proxy = Obj("fusion::SketchLine", entityToken="ln1:path", assemblyContext=occurrence, nativeObject=native,
                    parentSketch=Obj(entityToken="sk1:path", name="Axis sketch", parentComponent=lid),
                    worldGeometry=Obj("core::Line3D", startPoint=P(*shown[0]), endPoint=P(*shown[1])))
        circular = self.tray.feature("CircularPatternFeature", "Pattern1", inputEntities=Coll([]), axis=proxy,
                                     quantity=param_value(3), totalAngle=param_value(6.283185307179586),
                                     isSymmetric=False, patternElements=Coll([]))
        data = self.read_data(circular)
        axis = data["axis"]
        self.assertTrue(axis["assembly"])
        for key in ("entity", "sketch_token", "sketch", "foreign"):
            self.assertNotIn(key, axis)
        self.assertEqual((axis["ref"]["slot"], axis["ref"]["type"], axis["ref"]["component"]["token"],
                          axis["ref"]["sketch"]["token"]), ("axis", "SketchLine", "lid", "sk1"))
        self.assertEqual(axis["ref"]["dir"], axis["dir"])

    def test_a_face_another_component_owns_gives_an_extrude_extent_its_reference_and_stays_foreign(self):
        lid, occurrence, place = self.lid()
        body = Obj("fusion::BRepBody", entityToken="lb", name="LidBody", parentComponent=lid)
        native = Obj("fusion::BRepFace", entityToken="lf", body=body, pointOnFace=P(1, 2, 4), parentComponent=lid)
        proxy = Obj("fusion::BRepFace", entityToken="lf:path", assemblyContext=occurrence, nativeObject=native,
                    pointOnFace=P(*apply_matrix(place, (1, 2, 4))), body=body,
                    geometry=Obj("core::Plane", origin=P(*apply_matrix(place, (1, 2, 4))),
                                 normal=Obj(x=0, y=0, z=1)))
        extent = Obj("fusion::ToEntityExtentDefinition", entity=proxy, offset=param_value(0.0))
        start = Obj("fusion::FromEntityStartDefinition", entity=proxy)
        ext = self.tray.extrude(extentType="OneSideFeatureExtentType", extentOne=extent, startExtent=start)
        data = self.read_data(ext)
        for side in (data["side_one"], data["start"]):
            self.assertTrue(side["foreign"])
        ref = data["side_one"]["ref"]
        self.assertEqual((ref["slot"], data["start"]["ref"]["slot"]), ("side_one", "start"))
        self.assertEqual((ref["type"], ref["token"], ref["component"]["token"], ref["body"]["token"]),
                         ("BRepFace", "lf", "lid", "lb"))
        # The face is brought into the tray's own coordinates.
        self.assertEqual(ref["normal"], [0.0, 0.0, 1.0])
        self.assertEqual((ref["point"][2], ref["face_point"]), (36.0, [1, -8, 36]))

    def test_a_chained_face_of_another_component_keeps_its_outline_in_the_target_frame(self):
        lid, occurrence, place = self.lid()
        body = Obj("fusion::BRepBody", entityToken="lb", name="LidBody", parentComponent=lid)
        native = Obj("fusion::BRepFace", entityToken="lf", body=body, pointOnFace=P(1, 2, 4), parentComponent=lid)
        corner = apply_matrix(place, (1, 2, 4))
        proxy = Obj("fusion::BRepFace", entityToken="lf:path", assemblyContext=occurrence, nativeObject=native,
                    pointOnFace=P(*corner), body=body,
                    geometry=Obj("core::Plane", origin=P(*corner), normal=Obj(x=0, y=0, z=1)))
        loops = [{"outer": True, "curves": []}]
        # The outline as `face_loops` reads it through the occurrence: its frame in root coordinates.
        seen = {"frame": {"origin": list(corner), "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0],
                          "z": [0.0, 0.0, 1.0]}, "loops": loops}
        extent = Obj("fusion::ToEntityExtentDefinition", entity=proxy, offset=param_value(0.0), isChained=True)
        with mock.patch("lib.fusion_reader.read_solid.face_loops", lambda face, ctx: seen):
            data = self.read_data(self.tray.extrude(extentType="OneSideFeatureExtentType", extentOne=extent))
        side = data["side_one"]
        self.assertNotIn("face_outline", side)
        outline = side["ref"]["face_outline"]
        self.assertEqual((outline["frame"]["origin"], outline["frame"]["z"], outline["loops"]),
                         (side["ref"]["face_point"], [0.0, 0.0, 1.0], loops))

    def test_a_hole_on_points_of_another_components_sketch_is_read_in_the_target_frame(self):
        lid, occurrence, place = self.lid()
        sketch = Obj("fusion::Sketch", entityToken="sk9", name="Holes", parentComponent=lid)
        points = []
        for n, at in enumerate(((0, 0, 0), (10, 0, 0))):
            native = Obj("fusion::SketchPoint", entityToken="pt%d" % n, parentSketch=sketch,
                         worldGeometry=P(*at))
            points.append(Obj("fusion::SketchPoint", entityToken="pt%d:path" % n, assemblyContext=occurrence,
                              nativeObject=native, parentSketch=sketch, worldGeometry=P(*apply_matrix(place, at))))
        data = self.read_data(self.hole(Obj("fusion::SketchPointsHolePositionDefinition", sketchPoints=Coll(points))))
        self.assertNotIn("foreign", data)
        # The lid sits at (110, 50, 32) and the tray at (100, 50, 0), both turned 90 degrees about Z.
        self.assertEqual(data["positions"], [[0, -10, 32], [10, -10, 32]])
        self.assertEqual(data["positions"], [r["point"] for r in data["position_refs"]])
        for key in ("sketch_token", "sketch", "point_tokens"):
            self.assertNotIn(key, data)
        self.assertEqual([r["slot"] for r in data["position_refs"]], ["positions.0", "positions.1"])
        self.assertEqual(data["position_refs"][0]["component"]["token"], "lid")

    def hole(self, definition, **kw):
        base = dict(holeType="SimpleHoleType", holeTapType="SimpleHoleTapType", holeDiameter=param_value(0.5),
                    tipAngle=param_value(2.0), direction=Obj(x=0.0, y=0.0, z=-1.0), position=P(0, 0, 0),
                    holePositionDefinition=definition, extentDefinition=Obj("fusion::ThroughAllExtentDefinition"),
                    sideFaces=Coll([]), endFaces=Coll([]))
        base.update(kw)
        return self.tray.feature("HoleFeature", "Hole1", **base)

    def test_a_hole_whose_points_cannot_be_brought_in_is_marked_foreign(self):
        sketch = Obj("fusion::Sketch", entityToken="sk9", name="Holes", parentComponent=self.other)
        point = Obj("fusion::SketchPoint", entityToken="pt0", parentSketch=sketch, worldGeometry=P(1, 2, 3))
        data = self.read_data(self.hole(Obj("fusion::SketchPointsHolePositionDefinition", sketchPoints=Coll([point]))))
        self.assertTrue(data["foreign"])
        self.assertNotIn("sketch_token", data)

    def test_a_hole_placed_on_a_face_of_another_component_is_marked_foreign_with_its_reference(self):
        lid, occurrence, place = self.lid()
        face = Obj("fusion::BRepFace", entityToken="lf:path", assemblyContext=occurrence,
                   nativeObject=Obj("fusion::BRepFace", entityToken="lf", parentComponent=lid),
                   pointOnFace=P(*apply_matrix(place, (1, 2, 4))))
        data = self.read_data(self.hole(Obj("fusion::PointHolePositionDefinition", planarEntity=face)))
        self.assertTrue(data["foreign"])
        self.assertEqual((data["position_refs"][0]["type"], data["position_refs"][0]["token"]), ("BRepFace", "lf"))

    def test_a_hole_placed_by_offsets_from_an_edge_of_another_component_is_marked_foreign(self):
        lid, occurrence, place = self.lid()
        own = Obj("fusion::BRepFace", entityToken="tf", parentComponent=self.tray.component)
        edge_one = Obj("fusion::BRepEdge", entityToken="le:path", assemblyContext=occurrence,
                       nativeObject=Obj("fusion::BRepEdge", entityToken="le", parentComponent=lid))
        definition = Obj("fusion::PlaneAndOffsetsHolePositionDefinition", planarEntity=own, edgeOne=edge_one)
        data = self.read_data(self.hole(definition))
        self.assertTrue(data["foreign"])
        self.assertEqual([r["token"] for r in data["position_refs"]], ["le"])

    def test_a_hole_on_an_own_face_stays_a_plain_hole(self):
        own = Obj("fusion::BRepFace", entityToken="tf", parentComponent=self.tray.component)
        data = self.read_data(self.hole(Obj("fusion::PointHolePositionDefinition", planarEntity=own)))
        self.assertNotIn("foreign", data)
        self.assertNotIn("position_refs", data)

    def test_own_inputs_seen_through_the_occurrence_are_read_native(self):
        moved = rect_profile(w=90)
        moved.assemblyContext = self.tray.occurrence
        moved.nativeObject = rect_profile()
        moved.nativeObject.parentSketch.parentComponent = self.tray.component
        stray = edge("e1", 7)
        stray.assemblyContext = self.tray.occurrence
        stray.nativeObject = edge("e1", 1)
        stray.nativeObject.body = Obj(parentComponent=self.tray.component)
        ext = self.tray.extrude()
        ext[0].profile = moved
        data = self.read_data(ext)
        self.assertNotIn("foreign", data["profiles"][0])
        self.assertEqual(max(c["end"][0] for c in data["profiles"][0]["loops"][0]["curves"]), 40)
        edge_set = with_edges("ConstantRadiusFilletEdgeSet", [stray], radius=model_param("d", "r", 0.2),
                              isTangentChain=False, continuity="TangentSurfaceContinuityType")
        record = self.read_data(self.tray.feature("FilletFeature", "F", edgeSets=Coll([edge_set])))["sets"][0]["edges"][0]
        self.assertEqual(record, geo_edge_record(stray.nativeObject))

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


def param_value(value):
    return Obj(value=value)


if __name__ == "__main__":
    unittest.main()
