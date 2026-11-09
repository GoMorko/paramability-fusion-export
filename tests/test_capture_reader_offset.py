"""Reader of offset faces: the moved faces as outlines on their planes, their side walls, and where they landed."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import CM, Coll, FakeDesign, Obj, P, body, entry, feature, line

from lib.fusion_reader.capture import read_capture


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


def plane_face(z_mm, normal=(0, 0, 1), token="top"):
    geometry = Obj("core::Plane", origin=P(0, 0, z_mm), normal=vector(*normal), uDirection=vector(1, 0, 0))
    return Obj("fusion::BRepFace", entityToken=token, geometry=geometry, pointOnFace=P(5, 5, z_mm),
               evaluator=Obj(getNormalAtPoint=lambda p: (True, vector(*normal))))


def side(normal):
    return Obj("fusion::BRepFace", geometry=Obj("core::Plane", normal=vector(*normal)))


def with_outline(face, sides):
    """Gives `face` the 40 x 20 outline at its height; edge i borders sides[i]."""
    z = face.geometry.origin.z / CM
    corners = [(0, 0, z), (40, 0, z), (40, 20, z), (0, 20, z)]
    edges = [Obj("fusion::BRepEdge", geometry=line(corners[i], corners[(i + 1) % 4]), faces=Coll([face, sides[i]]))
             for i in range(4)]
    face.loops = Coll([Obj(isOuter=True, edges=Coll(edges))])
    return face


def read(face, moved, more=()):
    target = body()
    offset = entry(feature("OffsetFacesFeature", "OffsetFaces1", bodies=[target], inputFaces=Coll([face, *more]),
                           distance=Obj(value=0.2, name="d5", expression="2 mm"), faces=Coll([moved])))
    return read_capture(FakeDesign([offset], target), target, fusion="", name="", up_axis="z")["items"][0]["data"]


class OffsetFacesReaderTest(unittest.TestCase):
    def test_a_top_face_with_square_walls(self):
        walls = [side((0, -1, 0)), side((1, 0, 0)), side((0, 1, 0)), side((-1, 0, 0))]
        data = read(with_outline(plane_face(10), walls), plane_face(12))
        face = data["faces"][0]
        self.assertEqual((data["distance"], data["params"]["distance"]["expression"]), (2.0, "2 mm"))
        self.assertEqual(face["frame"], {"origin": [0, 0, 10], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]})
        self.assertEqual(face["loops"][0]["curves"][1], {"kind": "line", "start": [40, 0], "end": [40, 20]})
        self.assertEqual((face["sides"], face["meets_offset"]), ("square", False))
        self.assertEqual(data["faces_after"], [{"point": [5, 5, 12], "normal": [0, 0, 1]}])

    def test_two_moved_faces_that_share_an_edge(self):
        wall = with_outline(plane_face(0, (1, 0, 0), "wall"), [side((0, 0, 1))] * 4)
        walls = [side((0, -1, 0)), wall, side((0, 1, 0)), side((-1, 0, 0))]
        self.assertTrue(read(with_outline(plane_face(10), walls), plane_face(12), [wall])["faces"][0]["meets_offset"])

    def test_a_leaning_wall_and_a_curved_face(self):
        walls = [side((0, -1, 0)), side((1, 0, 1)), side((0, 1, 0)), side((-1, 0, 0))]
        self.assertEqual(read(with_outline(plane_face(10), walls), plane_face(12))["faces"][0]["sides"], "other")
        curved = Obj("fusion::BRepFace", geometry=Obj("core::Cylinder"))
        self.assertEqual(read(curved, plane_face(12))["faces"][0], {"kind": "other", "type": "Cylinder"})


if __name__ == "__main__":
    unittest.main()
