"""Reader of thin extrudes: the wall location and thickness of side one, its parameter, and what an open line comes
back as."""
import json
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, body, extrude, rect_profile, sketch_entry

from lib.fusion_reader.capture import read_capture


class WithoutThickness(Obj):
    """A thin extrude whose wall thickness cannot be read."""

    @property
    def thinExtrudeWallThicknessOne(self):
        raise RuntimeError("not available")


def thickness(cm=0.2, name="d3", expression="wall"):
    return Obj(value=cm, name=name, expression=expression)


def read(profile=None, thin=True, location="Side1ThinExtrudeWallLocation", broken=False):
    target = body()
    extra = {}
    if thin:
        extra = dict(isThinExtrude=True, thinExtrudeWallLocationOne=location, thinExtrudeWallThicknessOne=thickness(),
                     thinExtrudeWallLocationTwo="CenterThinExtrudeWallLocation",
                     thinExtrudeWallThicknessTwo=Obj(value=0.1))
    step = extrude(profile or rect_profile(), target=target, **extra)
    if broken:
        step[0].__class__ = WithoutThickness
    design = FakeDesign([sketch_entry(), step], target)
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


if __name__ == "__main__":
    unittest.main()
