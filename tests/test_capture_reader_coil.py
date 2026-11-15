"""Reader of coil features: the parameters the coil made, the bodies around it, its flat end faces and sampled edges."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry

from lib.fusion_reader.capture import read_capture


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


def circle_edge(token, centre, radius):
    return Obj("fusion::BRepEdge", entityToken=token, geometry=Obj("core::Circle3D", center=P(*centre), radius=radius / 10.0))


def end_face(token, origin, normal, radius, area_mm2):
    """A flat round end face: its plane, outward normal and one circle edge."""
    geometry = Obj("core::Plane", origin=P(*origin), normal=vector(*normal), uDirection=vector(1, 0, 0))
    face = Obj("fusion::BRepFace", entityToken=token, geometry=geometry, pointOnFace=P(*origin),
               area=area_mm2 / 100.0, evaluator=Obj(getNormalAtPoint=lambda p: (True, vector(*normal))))
    face.loops = Coll([Obj(isOuter=True, edges=Coll([circle_edge("c_" + token, origin, radius)]))])
    return face


def helix_edge(token="seam"):
    def trace(t):
        a = 2 * math.pi * 3 * t
        return 5 * math.cos(a), 5 * math.sin(a), 12 * t
    evaluator = Obj(getParameterExtents=lambda: (True, 0.0, 1.0), getPointAtParameter=lambda t: (True, P(*trace(t))))
    return Obj("fusion::BRepEdge", entityToken=token, evaluator=evaluator)


def curved_face(edges):
    face = Obj("fusion::BRepFace", entityToken="wire", geometry=Obj("core::NurbsSurface"))
    face.loops = Coll([Obj(isOuter=True, edges=Coll(edges))])
    return face


def parameter(feature, name, role, expression, value):
    return Obj("fusion::ModelParameter", name=name, role=role, expression=expression, value=value, createdBy=feature)


def read(faces=None, parameters=True, volume_after=8.5):
    target = body()
    feature = Obj("fusion::CoilFeature", entityToken="coil1", bodies=Coll([target]), faces=Coll(faces or []))
    root = Obj(entityToken="root", bRepBodies=Coll([target]))
    other = Obj("fusion::ModelParameter", name="d1", role="Distance", expression="1 mm", value=0.1,
                createdBy=Obj(entityToken="extrude1"))
    feature.parentComponent = root
    root.modelParameters = Coll([other] + ([
        parameter(feature, "d5", "Diameter", "coil_d", 1.0), parameter(feature, "d6", "Section Size", "2 mm", 0.2),
        parameter(feature, "d7", "TaperAngle", "0 deg", 0.0), parameter(feature, "d8", "Revolutions", "3", 3.0),
        parameter(feature, "d9", "Height", "12 mm", 1.2), parameter(feature, "d10", "Something", "1", 1.0)]
        if parameters else []))
    design = FakeDesign([entry((feature, "Coil1"))], target, appears_at=0)
    design.rootComponent = root
    target.volume = volume_after
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]


class CoilReaderTest(unittest.TestCase):
    def test_the_parameters_the_coil_made_are_read_by_role_and_the_rest_are_left(self):
        data = read()
        self.assertEqual(sorted(data["params"]), ["diameter", "height", "revolutions", "section_size", "taper_deg"])
        self.assertEqual(data["params"]["diameter"], {"name": "d5", "expression": "coil_d", "value": 10.0})
        self.assertEqual(data["params"]["taper_deg"]["value"], 0.0)
        self.assertEqual(data["params"]["revolutions"]["value"], 3.0)
        self.assertEqual(data["roles"], ["Diameter", "Section Size", "TaperAngle", "Revolutions", "Height", "Something"])

    def test_the_bodies_before_and_after_carry_their_volumes(self):
        data = read(volume_after=8.5)
        self.assertEqual(data["volumes_before"], [{"token": "b1", "name": "Body1", "volume": 8500.0}])
        self.assertEqual(data["made"], [{"token": "b1", "name": "Body1", "volume": 8500.0}])

    def test_flat_end_faces_give_their_outline_and_curved_faces_give_sampled_edges(self):
        data = read([end_face("a", (5, 0, 0), (0, -1, 0), 1.0, 3.14159), end_face("b", (5, 0, 12), (0, 1, 0), 1.0, 3.14159),
                     curved_face([helix_edge()])])
        faces = data["faces"]
        self.assertEqual([f["area"] for f in faces["flat"]], [3.14159, 3.14159])
        self.assertEqual(faces["flat"][0]["frame"]["z"], [0.0, -1.0, 0.0])
        self.assertEqual(faces["flat"][0]["loops"][0]["curves"][0]["radius"], 1.0)
        self.assertEqual(faces["curved"], 1)
        self.assertEqual(len(faces["edges"]), 1)
        self.assertEqual(len(faces["edges"][0]), 17)
        self.assertEqual(faces["edges"][0][-1], [5.0, 0.0, 12.0])

    def test_a_coil_with_too_many_faces_or_a_face_that_does_not_read_has_no_faces(self):
        many = [end_face("f%d" % n, (0, 0, n), (0, 0, 1), 1.0, 3.0) for n in range(3)]
        self.assertIsNone(read(many)["faces"])
        broken = end_face("a", (5, 0, 0), (0, -1, 0), 1.0, 3.0)
        del broken.loops
        self.assertIsNone(read([broken])["faces"])

    def test_a_coil_without_readable_parameters_has_none(self):
        data = read(parameters=False)
        self.assertNotIn("params", data)
        self.assertEqual(data["roles"], [])


if __name__ == "__main__":
    unittest.main()
