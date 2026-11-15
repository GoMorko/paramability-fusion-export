"""Reader of Split Body: what it splits with, the bodies it splits and the pieces, with their boxes and volumes."""
import types
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import fake_brep_tools, install_adsk_core
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry, feature

from lib.fusion_reader.capture import read_capture


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


def face(at, normal):
    return Obj("fusion::BRepFace", pointOnFace=P(*at), evaluator=Obj(getNormalAtPoint=lambda p: (True, vector(*normal))))


def read(tool, pieces, split=None):
    target = pieces[-1]
    split = split or [body("b1", "Body1", hi=(40, 20, 10), volume=8.0)]
    item = entry(feature("SplitBodyFeature", "Split1", bodies=pieces, splittingTool=tool, splitBodies=Coll(split),
                         isSplittingToolExtended=True))
    return read_capture(FakeDesign([item], target), target, fusion="", name="", up_axis="z")["items"][0]["data"]


def inner_and_outer():
    """A block inside a plate, each with one face, for the reader's point-containment path."""
    core = install_adsk_core()
    core.Point3D = types.SimpleNamespace(create=lambda x, y, z: Obj(x=x, y=y, z=z))
    inner = body("b2", "Body2", lo=(15, 5, 0), hi=(25, 15, 10), volume=0.8)
    inner.faces = Coll([face((20, 10, 10), (0, 0, 1))])
    outer = body("b1", "Body1", hi=(40, 20, 10), volume=7.2)
    outer.faces = Coll([face((0, 10, 5), (-1, 0, 0))])
    return inner, outer


class SplitReaderTest(unittest.TestCase):
    def test_a_construction_plane_with_the_bodies_and_pieces(self):
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1",
                    geometry=Obj("core::Plane", origin=P(10, 0, 0), normal=vector(1, 0, 0)))
        left = body("b1", "Body1", hi=(10, 20, 10), volume=2.0)
        right = body("b2", "Body2", lo=(10, 0, 0), hi=(40, 20, 10), volume=6.0)
        data = read(plane, [left, right])
        self.assertEqual(data["tool"]["kind"], "plane")
        self.assertEqual((data["tool"]["plane"]["point"], data["tool"]["plane"]["normal"]), ([10, 0, 0], [1, 0, 0]))
        self.assertEqual(data["bodies"][0]["volume"], 8000.0)
        self.assertEqual([(p["name"], p["box"]["min"][0], p["volume"]) for p in data["pieces"]],
                         [("Body1", 0, 2000.0), ("Body2", 10, 6000.0)])

    def test_a_solid_tool_body_says_which_pieces_lie_inside_it(self):
        inner, outer = inner_and_outer()

        def holds(p):
            return "PointInsidePointContainment" if 1.5 < p.x < 2.5 and 0.5 < p.y < 1.5 else "PointOutsidePointContainment"

        tool = Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, pointContainment=holds,
                   volume=1.1, boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))
        data = read(tool, [outer, inner])
        self.assertEqual((data["tool"]["kind"], data["tool"]["body"]["name"]), ("body", "Body3"))
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, True])

    def test_inside_is_read_once_fusion_no_longer_gives_the_tool(self):
        inner, outer = inner_and_outer()
        tool = Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, volume=1.1,
                   pointContainment=lambda p: "PointInsidePointContainment" if 1.5 < p.x < 2.5 and 0.5 < p.y < 1.5
                   else "PointOutsidePointContainment",
                   boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))

        class Split(Obj):
            # Fusion gives the splitting tool only while the marker sits before the feature.
            @property
            def splittingTool(self):
                return tool if design.timeline.markerPosition == 0 else None

        split, _ = feature("SplitBodyFeature", "Split1", bodies=[outer, inner],
                           splitBodies=Coll([body("b1", "Body1", hi=(40, 20, 10), volume=8.0)]),
                           isSplittingToolExtended=False)
        split.__class__ = Split
        design = FakeDesign([entry((split, "Split1"))], inner)
        design.findEntityByToken = lambda token: {"b3": [tool], "b2": [inner]}.get(token, [])
        data = read_capture(design, inner, fusion="", name="", up_axis="z")["items"][0]["data"]
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, True])

    def test_a_tool_body_of_a_moved_component_is_seen_where_its_occurrence_puts_it(self):
        inner, outer = inner_and_outer()
        occurrence = Obj("fusion::Occurrence", entityToken="occ1")

        def tool_body(shift, context):
            # Holds the points of a 1 cm square that starts `shift` cm along x.
            return Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, volume=1.1,
                       assemblyContext=context, parentComponent=Obj(entityToken="other"),
                       pointContainment=lambda p: "PointInsidePointContainment"
                       if shift < p.x < shift + 1 and 0.5 < p.y < 1.5 else "PointOutsidePointContainment",
                       boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))

        native = tool_body(0.5, None)
        proxy = tool_body(1.5, occurrence)
        proxy.nativeObject = native
        native.createForAssemblyContext = lambda context: proxy if context is occurrence else None

        class Split(Obj):
            @property
            def splittingTool(self):
                return proxy if design.timeline.markerPosition == 0 else None

        split, _ = feature("SplitBodyFeature", "Split1", bodies=[outer, inner],
                           splitBodies=Coll([body("b1", "Body1", hi=(40, 20, 10), volume=8.0)]),
                           isSplittingToolExtended=False)
        split.__class__ = Split
        design = FakeDesign([entry((split, "Split1"))], inner)
        design.findEntityByToken = lambda token: {"b3": [native], "b2": [inner]}.get(token, [])
        data = read_capture(design, inner, fusion="", name="", up_axis="z")["items"][0]["data"]
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, True])

    def test_a_temporary_intersect_decides_when_no_face_of_a_piece_tells(self):
        inner, outer = inner_and_outer()
        inner.faces = outer.faces = Coll([])
        # Each body is a set of one cm3 cells for the fake temporary booleans.
        inner.volume, inner.cells = 2.0, {1, 2}
        outer.volume, outer.cells = 4.0, {3, 4, 5, 6}
        tool = Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, volume=3.0, cells={1, 2, 9},
                   pointContainment=lambda p: "PointOnPointContainment",
                   boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))
        with mock.patch("lib.fusion_reader.read_intersect.brep_tools", return_value=fake_brep_tools()):
            data = read(tool, [outer, inner])
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, True])

    def test_a_piece_the_intersect_only_partly_keeps_has_no_answer(self):
        inner, outer = inner_and_outer()
        inner.faces = outer.faces = Coll([])
        inner.volume, inner.cells = 4.0, {1, 2, 3, 4}
        outer.volume, outer.cells = 2.0, {7, 8}
        tool = Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, volume=3.0, cells={1, 2, 9},
                   pointContainment=lambda p: "PointOnPointContainment",
                   boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))
        with mock.patch("lib.fusion_reader.read_intersect.brep_tools", return_value=fake_brep_tools()):
            data = read(tool, [outer, inner])
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, None])

    def test_a_curved_face_is_a_surface(self):
        curved = Obj("fusion::BRepFace", geometry=Obj("core::Cylinder"))
        self.assertEqual(read(curved, [body()])["tool"], {"kind": "surface", "type": "Cylinder"})


class LineageStatesTest(unittest.TestCase):
    def test_the_body_a_split_made_the_target_from_is_measured_on_the_steps_before_the_split(self):
        plate = body("b1", "Body1", hi=(40, 20, 10), volume=8.0)
        right = body("b2", "Body2", lo=(10, 0, 0), hi=(40, 20, 10), volume=6.0)
        plane = Obj("fusion::ConstructionPlane", entityToken="cp1",
                    geometry=Obj("core::Plane", origin=P(10, 0, 0), normal=vector(1, 0, 0)))
        made = entry(feature("ThickenFeature", "Coil1", bodies=[plate]))
        split = entry(feature("SplitBodyFeature", "Split1", bodies=[plate, right], splittingTool=plane,
                              splitBodies=Coll([plate]), isSplittingToolExtended=True))
        design = FakeDesign([made, split], right, appears_at=2)
        design.findEntityByToken = lambda token: {"b1": [plate], "b2": [right]}.get(token, [])
        items = read_capture(design, right, fusion="", name="", up_axis="z")["items"]
        self.assertEqual(items[0]["body_states"]["b1"]["volume_after"], 8000.0)
        self.assertIn("b1", items[1]["body_states"])


if __name__ == "__main__":
    unittest.main()
