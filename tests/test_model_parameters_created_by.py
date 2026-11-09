"""Who made a model parameter: a sketch dimension is recognised even when `createdBy` does not say so by name."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj

from lib.fusion_reader.parameters import list_model_parameters


def param(name, created_by=None, role="Linear Dimension-2"):
    return Obj(name=name, expression="1 mm", value=0.1, unit="mm", role=role, createdBy=created_by,
               comment="", isFavorite=False, valueType="x", dependencyParameters=Coll([]))


def component(params, sketches=()):
    return Obj(entityToken="c", modelParameters=Coll(params), sketches=Coll(sketches))


def sketch_with(dimension_param_name):
    sketch = Obj("fusion::Sketch", name="Sketch4", parentComponent=Obj(entityToken="c"))
    dimension = Obj("fusion::SketchLinearDimension", entityToken="dim4", name="", parentSketch=sketch,
                    parameter=Obj(name=dimension_param_name))
    sketch.sketchDimensions = Coll([dimension])
    return sketch


class CreatedByTest(unittest.TestCase):
    def made(self, parameter, sketches=()):
        return list_model_parameters(component([parameter], sketches))[0]["created_by"]

    def test_a_dimension_known_by_its_type_name(self):
        sketch = Obj(name="Sketch1", parentComponent=Obj(entityToken="c"))
        dimension = Obj("fusion::SketchRadialDimension", entityToken="d1", name="d1", parentSketch=sketch)
        made = self.made(param("d1", dimension))
        self.assertEqual((made["kind"], made["sketch"], made["token"]), ("sketchDimension", "Sketch1", "d1"))

    def test_a_dimension_known_only_by_its_members(self):
        sketch = Obj(name="Sketch2", parentComponent=Obj(entityToken="c"))
        dimension = Obj("fusion::Base", entityToken="d2", parentSketch=sketch, parameter=Obj(name="d2"))
        made = self.made(param("d2", dimension))
        self.assertEqual((made["kind"], made["sketch"]), ("sketchDimension", "Sketch2"))

    def test_a_parameter_without_a_maker_is_found_through_the_dimensions_of_the_sketches(self):
        made = self.made(param("d4"), [sketch_with("d4")])
        self.assertEqual((made["kind"], made["sketch"], made["token"], made["component"]),
                         ("sketchDimension", "Sketch4", "dim4", "c"))

    def test_a_feature_stays_a_feature_and_an_unknown_maker_stays_other(self):
        extrude = Obj("fusion::ExtrudeFeature", entityToken="e1", name="Extrude1")
        self.assertEqual(self.made(param("d5", extrude, role="Distance"))["kind"], "feature")
        self.assertEqual(self.made(param("d6", None, role="Distance"), [sketch_with("d4")])["kind"], "other")
