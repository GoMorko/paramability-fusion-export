"""Reader of thin extrudes: the wall location and thickness of side one, its parameter, and an open line read as its
path with the faces the wall made."""
import json
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, extrude, matrix, rect_profile, sketch_entry
from tests.test_capture_reader_sweep import line3, path, sketch, sketch_curve, step

from lib.fusion_reader import read_solid

from lib.fusion_reader.capture import read_capture


class WithoutThickness(Obj):
    """A thin extrude whose wall thickness cannot be read."""

    @property
    def thinExtrudeWallThicknessOne(self):
        raise RuntimeError("not available")


def thickness(cm=0.2, name="d3", expression="wall"):
    return Obj(value=cm, name=name, expression=expression)


def read(profile=None, thin=True, location="Side1ThinExtrudeWallLocation", broken=False, target_faces=(), **members):
    target = body()
    target.faces = Coll(target_faces)
    extra = dict(members)
    if thin:
        extra.update(isThinExtrude=True, thinExtrudeWallLocationOne=location,
                     thinExtrudeWallThicknessOne=thickness(),
                     thinExtrudeWallLocationTwo="CenterThinExtrudeWallLocation",
                     thinExtrudeWallThicknessTwo=Obj(value=0.1))
    item = extrude(profile or rect_profile(), target=target, **extra)
    if broken:
        item[0].__class__ = WithoutThickness
    design = FakeDesign([sketch_entry(), item], target)
    item = read_capture(design, target, fusion="", name="", up_axis="z")["items"][1]
    json.dumps(item)
    return item["data"]


class ThinReaderTest(unittest.TestCase):
    def test_the_wall_of_side_one_and_side_two(self):
        data = read()
        self.assertTrue(data["thin"])
        self.assertEqual(data["thin_wall"], {"location": "side1", "thickness": 2.0, "location_two": "center",
                                             "thickness_two": 1.0, "profile_type": "Profile"})

    def test_each_location_reads_by_its_name(self):
        found = {name: read(location=name)["thin_wall"]["location"]
                 for name in ("Side1ThinExtrudeWallLocation", "Side2ThinExtrudeWallLocation",
                              "CenterThinExtrudeWallLocation", "SomethingElse")}
        self.assertEqual(list(found.values()), ["side1", "side2", "center", "other"])

    def test_the_wall_thickness_names_its_parameter(self):
        self.assertEqual(read()["params"]["thin.thickness"], {"name": "d3", "expression": "wall", "value": 2.0})

    def test_a_thickness_that_cannot_be_read_is_null_and_names_no_parameter(self):
        data = read(broken=True)
        self.assertIsNone(data["thin_wall"]["thickness"])
        self.assertNotIn("thin.thickness", data.get("params", {}))

    def test_an_extrude_that_is_not_thin_has_no_wall(self):
        data = read(thin=False)
        self.assertFalse(data["thin"])
        self.assertNotIn("thin_wall", data)
        self.assertNotIn("thin.thickness", data.get("params", {}))

    def test_an_open_line_is_recorded_by_its_type(self):
        line = Obj("fusion::SketchLine")
        data = read(profile=Coll([line]))
        self.assertEqual(data["profiles"], [{"kind": "other", "type": "SketchLine"}])
        self.assertEqual(data["thin_wall"]["profile_type"], "none")


def flat_face(point, normal):
    return Obj("fusion::BRepFace", geometry=Obj("core::Plane"), pointOnFace=P(*point),
               evaluator=Obj(getNormalAtPoint=lambda at: (True, Obj(x=normal[0], y=normal[1], z=normal[2]))))


def open_line():
    """The path of two sketch lines (0, 0) to (30, 0) to (30, 20) on the XY plane."""
    plane = sketch(name="Sketch1", token="sk1", transform=matrix())
    first = sketch_curve(line3((0, 0, 0), (30, 0, 0)), plane, token="ln0")
    second = sketch_curve(line3((30, 0, 0), (30, 20, 0)), plane, token="ln1")
    return path(step(first), step(second))


class OpenLineReaderTest(unittest.TestCase):
    def test_an_open_line_is_one_outline_with_its_path_and_the_faces_the_wall_made(self):
        faces = [flat_face((15, 0, 7.5), (0, -1, 0)), flat_face((15, 1, 15), (0, 0, 1))]
        data = read(profile=open_line(), endFaces=Coll([]), faces=Coll(faces))
        self.assertEqual(data["profiles"], [{"kind": "other", "type": "Path"}])
        path = data["path"]
        self.assertEqual((path["kind"], path["closed"], path["sketch_token"]), ("sketch", False, "sk1"))
        self.assertEqual([(c["flat"]["start"], c["flat"]["end"], c["opposed"]) for c in path["curves"]],
                         [([0, 0], [30, 0], False), ([30, 0], [30, 20], False)])
        self.assertEqual(data["wall_faces"], [{"surface": "Plane", "point": [15, 0, 7.5], "normal": [0, -1, 0]},
                                              {"surface": "Plane", "point": [15, 1, 15], "normal": [0, 0, 1]}])

    def test_a_join_reads_the_faces_of_the_part_before_it(self):
        plate = [flat_face((0, 20, 1.5), (-1, 0, 0))]
        data = read(profile=open_line(), endFaces=Coll([]), faces=Coll([]), target_faces=plate,
                    operation="JoinFeatureOperation")
        self.assertEqual(data["target_faces_before"], [{"surface": "Plane", "point": [0, 20, 1.5],
                                                         "normal": [-1, 0, 0]}])
        self.assertNotIn("target_faces_before", read(profile=open_line(), endFaces=Coll([]), faces=Coll([])))

    def test_too_many_faces_to_read_give_no_wall_faces(self):
        faces = [flat_face((15, 0, 7.5), (0, -1, 0))] * (read_solid.MAX_WALL_FACES + 1)
        self.assertIsNone(read(profile=open_line(), endFaces=Coll([]), faces=Coll(faces))["wall_faces"])


if __name__ == "__main__":
    unittest.main()
