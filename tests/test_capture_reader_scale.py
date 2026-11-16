"""Reader of Scale features: the bodies with their measures around the step, the point and the factors."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, P, body, entry, feature

from lib.fusion_reader.capture import read_capture

ORIGIN = Obj("fusion::ConstructionPoint", entityToken="origin", geometry=P(0, 0, 0))


def factor(value, name="d2", expression="grow"):
    return Obj(value=value, name=name, expression=expression)


def read(inputs=None, point=ORIGIN, **kw):
    """The data of one Scale of the target, read by the capture reader."""
    target = body()
    kw.setdefault("isUniform", True)
    kw.setdefault("scaleFactor", factor(1.5))
    scale = entry(feature("ScaleFeature", "Scale1", bodies=[target], point=point,
                          inputEntities=Coll([target] if inputs is None else inputs), **kw))
    design = FakeDesign([scale], target, appears_at=0)
    design.rootComponent.originConstructionPoint = ORIGIN
    type(target).volume = property(lambda self: 8.0 if design.timeline.markerPosition == 0 else 27.0)
    try:
        return read_capture(design, target, fusion="", name="", up_axis="z")["items"][0]["data"]
    finally:
        del type(target).volume


class ScaleReaderTest(unittest.TestCase):
    def test_a_uniform_scale_about_the_origin(self):
        data = read()
        self.assertEqual((data["input_kind"], data["uniform"], data["factor"]), ("bodies", True, 1.5))
        self.assertEqual(data["point"], {"origin": True, "point": [0.0, 0.0, 0.0]})
        self.assertEqual(data["params"]["factor"], {"name": "d2", "expression": "grow", "value": 1.5})
        self.assertEqual((data["bodies"][0]["volume_before"], data["after"][0]["volume"]), (8000.0, 27000.0))
        self.assertEqual(data["bodies"][0]["box_before"], {"min": [0, 0, 0], "max": [40, 20, 10]})

    def test_a_scale_per_axis_about_a_corner(self):
        corner = Obj("fusion::BRepVertex", geometry=P(40, 20, 10), body=body())
        data = read(point=corner, isUniform=False, xScale=factor(1.0, "d3", "1"), yScale=factor(2.0, "d4", "2"),
                    zScale=factor(0.5, "d5", "0.5"))
        self.assertEqual((data["uniform"], data["factors"]), (False, [1.0, 2.0, 0.5]))
        self.assertEqual(sorted(data["params"]), ["factors.0", "factors.1", "factors.2"])
        self.assertEqual(data["point"], {"entity_type": "BRepVertex", "point": [40, 20, 10],
                                         "body": {"token": "b1", "name": "Body1"}})

    def test_a_sketch_among_the_inputs_and_an_unreadable_point(self):
        data = read(inputs=[body(), Obj("fusion::Sketch", name="Sketch1")], point=Obj("fusion::BRepFace"))
        self.assertEqual(data["input_kind"], "sketches")
        self.assertEqual(data["point"], {"kind": "other", "type": "BRepFace"})

    def test_a_factor_fusion_does_not_give_is_null(self):
        self.assertEqual(read(isUniform=True, scaleFactor=None)["factor"], None)


if __name__ == "__main__":
    unittest.main()
