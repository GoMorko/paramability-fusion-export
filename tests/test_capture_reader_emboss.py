"""Reader of emboss features: outlines, input faces, depth, shift and turn, and the measured result."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, entry, feature, line

from lib.fusion_reader.capture import read_capture


def vector(x, y, z):
    return Obj(x=x, y=y, z=z)


def identity():
    return Obj(getAsCoordinateSystem=lambda: (P(0, 0, 0), vector(1, 0, 0), vector(0, 1, 0), vector(0, 0, 1)))


class LidBody(Obj):
    """The target: 8000 mm3 before the emboss, `after` mm3 once the marker is past it."""
    after = 8000.0

    @property
    def volume(self):
        return (8000.0 if self.timeline.markerPosition == 0 else self.after) / 1000.0


def lid(after):
    body = LidBody("fusion::BRepBody", entityToken="b1", name="Body1",
                   boundingBox=Obj(minPoint=P(0, 0, 0), maxPoint=P(40, 20, 10)))
    body.after = after
    return body


def face_of(geometry_type, z, body, normal=(0, 0, 1), area=0.0):
    geometry = Obj("core::" + geometry_type, origin=P(0, 0, z), normal=vector(*normal), uDirection=vector(1, 0, 0))
    return Obj("fusion::BRepFace", entityToken="f%s" % z, geometry=geometry, pointOnFace=P(5, 5, z), body=body,
               area=area, evaluator=Obj(getNormalAtPoint=lambda p: (True, vector(*normal))))


def ring_profile(sketch):
    """A 30 x 10 outline with a 3.04 cm2 (304 mm2) area."""
    curves = [line((0, 0), (30, 0)), line((30, 0), (30, 10)), line((30, 10), (0, 10)), line((0, 10), (0, 0))]
    loop = Obj(isOuter=True, profileCurves=Coll([Obj(geometry=g) for g in curves]))
    return Obj("fusion::Profile", parentSketch=sketch, profileLoops=Coll([loop]),
               areaProperties=lambda: Obj(area=3.04))


def parameter(value, name="d5", expression="1 mm"):
    return Obj(value=value, name=name, expression=expression)


class EmbossFeatureStub(Obj):
    """An emboss whose horizontal distance cannot be read."""

    @property
    def horizontalDistance(self):
        raise RuntimeError("not available")


def read(depth_cm=0.1, after=8304.0, made_z=11, face_z=10, surface="Plane", text=False, broken=False):
    target = lid(after)
    sketch = Obj("fusion::Sketch", name="Sketch1", transform=identity(), entityToken="sk1")
    outlines = [ring_profile(sketch)]
    if text:
        outlines.append(Obj("fusion::SketchText", parentSketch=sketch, text="Hi"))
    made = face_of("Plane", made_z, target, area=3.04)
    kind = EmbossFeatureStub if broken else Obj
    emboss = kind("fusion::EmbossFeature", parentComponent=Obj(entityToken="root"), bodies=Coll([target]),
                  profiles=Coll(outlines), inputFaces=Coll([face_of(surface, face_z, target)]), faces=Coll([made]),
                  isTangentChain=True, depth=parameter(depth_cm), horizontalDistance=parameter(0, "d6", "0 mm"),
                  verticalDistance=parameter(0, "d7", "0 mm"), rotationAngle=parameter(0, "d8", "0 deg"))
    design = FakeDesign([entry((emboss, "Emboss1"))], target, appears_at=0)
    target.timeline = design.timeline
    return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]


class EmbossReaderTest(unittest.TestCase):
    def test_a_raised_outline_on_a_flat_face(self):
        data = read()
        self.assertEqual(data["profiles"][0]["frame"]["origin"], [0, 0, 0])
        self.assertEqual(data["areas"], [304.0])
        self.assertEqual(data["faces"][0], {
            "entity_type": "BRepFace", "surface": "Plane", "plane": {"point": [0, 0, 10], "normal": [0, 0, 1]},
            "outward": [0, 0, 1], "face_point": [5, 5, 10]})
        self.assertEqual((data["depth"], data["offset_x"], data["offset_y"], data["rotation_deg"]), (1.0, 0, 0, 0))
        self.assertEqual(data["params"]["depth"], {"name": "d5", "expression": "1 mm", "value": 1.0})
        self.assertEqual(data["participants"], [{"token": "b1", "name": "Body1"}])
        self.assertEqual((data["volume_before"], data["volume_after"]), (8000.0, 8304.0))
        self.assertEqual((data["end_offset"], data["end_area"]), (11.0, 304.0))

    def test_a_sunk_outline_has_a_negative_depth_and_its_floor_below_the_face(self):
        # The sketch plane is z = 0, the face z = 10 and the floor z = 9: end_offset runs from the sketch plane.
        data = read(depth_cm=-0.1, after=7696.0, made_z=9)
        self.assertEqual((data["depth"], data["end_offset"], data["volume_after"]), (-1.0, 9.0, 7696.0))

    def test_a_curved_input_face_is_named_by_its_surface_without_a_plane(self):
        face = read(surface="Cylinder")["faces"][0]
        self.assertEqual((face["surface"], face["plane"]), ("Cylinder", None))

    def test_a_setting_that_cannot_be_read_is_null_and_the_rest_is_still_read(self):
        data = read(broken=True)
        self.assertNotIn("read_error", data)
        self.assertEqual((data["offset_x"], data["depth"]), (None, 1.0))
        self.assertNotIn("offset_x", data["params"])

    def test_sketch_text_is_marked_as_text_and_has_no_area(self):
        data = read(text=True)
        self.assertEqual(data["profiles"][1], {"text": True, "sketch": "Sketch1", "sketch_token": "sk1"})
        self.assertEqual(data["areas"], [304.0, None])

    def test_input_faces_that_cannot_be_listed_give_a_read_error(self):
        target = lid(8000.0)
        emboss = Obj("fusion::EmbossFeature", parentComponent=Obj(entityToken="root"), bodies=Coll([target]))
        design = FakeDesign([entry((emboss, "Emboss1"))], target, appears_at=0)
        target.timeline = design.timeline
        data = read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]
        self.assertIn("read_error", data)


if __name__ == "__main__":
    unittest.main()
