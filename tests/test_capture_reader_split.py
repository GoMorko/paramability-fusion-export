"""Reader of Split Body: what it splits with, the bodies it splits and the pieces, with their boxes and volumes."""
import types
import unittest

from tests import context  # noqa: F401
from tests.fakes import install_adsk_core
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
        core = install_adsk_core()
        core.Point3D = types.SimpleNamespace(create=lambda x, y, z: Obj(x=x, y=y, z=z))
        inner = body("b2", "Body2", lo=(15, 5, 0), hi=(25, 15, 10), volume=0.8)
        inner.faces = Coll([face((20, 10, 10), (0, 0, 1))])
        outer = body("b1", "Body1", hi=(40, 20, 10), volume=7.2)
        outer.faces = Coll([face((0, 10, 5), (-1, 0, 0))])

        def holds(p):
            return "PointInsidePointContainment" if 1.5 < p.x < 2.5 and 0.5 < p.y < 1.5 else "PointOutsidePointContainment"

        tool = Obj("fusion::BRepBody", entityToken="b3", name="Body3", isSolid=True, pointContainment=holds,
                   volume=1.1, boundingBox=Obj(minPoint=P(15, 5, -2), maxPoint=P(25, 15, 12)))
        data = read(tool, [outer, inner])
        self.assertEqual((data["tool"]["kind"], data["tool"]["body"]["name"]), ("body", "Body3"))
        self.assertEqual([p["inside"] for p in data["pieces"]], [False, True])

    def test_a_curved_face_is_a_surface(self):
        curved = Obj("fusion::BRepFace", geometry=Obj("core::Cylinder"))
        self.assertEqual(read(curved, [body()])["tool"], {"kind": "surface", "type": "Cylinder"})


if __name__ == "__main__":
    unittest.main()
