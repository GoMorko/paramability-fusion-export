"""The model parameters of a sketch text (its height) are tied to the sketch the text is in."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, Obj

from lib.fusion_reader.parameters import list_model_parameters


def param(name, created_by=None):
    return Obj(name=name, expression="5 mm", value=0.5, unit="mm", role="", createdBy=created_by,
               comment="", isFavorite=False, valueType="x", dependencyParameters=Coll([]))


def sketch_with_text(height_name):
    sketch = Obj("fusion::Sketch", name="Sketch3", parentComponent=Obj(entityToken="c"),
                 sketchDimensions=Coll([]))
    text = Obj("fusion::SketchText", entityToken="txt3", parentSketch=sketch, heightParameter=Obj(name=height_name))
    sketch.sketchTexts = Coll([text])
    return sketch, text


def made(parameter, sketches=()):
    component = Obj(entityToken="c", modelParameters=Coll([parameter]), sketches=Coll(sketches))
    return list_model_parameters(component)[0]["created_by"]


class TextParameterTest(unittest.TestCase):
    def test_a_height_found_through_the_texts_of_the_sketches(self):
        sketch, _ = sketch_with_text("d9")
        got = made(param("d9", Obj("fusion::Sketch", entityToken="skx")), [sketch])
        self.assertEqual((got["kind"], got["sketch"], got["token"], got["component"]), ("sketchText", "Sketch3", "txt3", "c"))

    def test_a_height_whose_maker_is_the_text_itself(self):
        _, text = sketch_with_text("d9")
        got = made(param("d9", text))
        self.assertEqual((got["kind"], got["sketch"]), ("sketchText", "Sketch3"))

    def test_a_parameter_that_is_not_a_text_height_stays_other(self):
        sketch, _ = sketch_with_text("d9")
        self.assertEqual(made(param("d10", None), [sketch])["kind"], "other")
