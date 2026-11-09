"""The `params` map of feature data and the parameter lists of the capture envelope."""
import unittest

from tests import context  # noqa: F401
from tests.test_capture_reader import Coll, FakeDesign, Obj, body, extrude, feature, rect_profile, sketch_entry
from tests.test_capture_reader_finish import face, read_data

from lib.fusion_reader import param_refs
from lib.fusion_reader.capture import read_capture


def model_param(name, expression, value):
    return Obj("fusion::ModelParameter", name=name, expression=expression, value=value)


def capture_of(extrude_kwargs=None, **design_members):
    target = body()
    design = FakeDesign([sketch_entry(), extrude(rect_profile(), target=target, **(extrude_kwargs or {}))], target)
    design.__dict__.update(design_members)
    return read_capture(design, target, fusion="", name="", up_axis="z")


class RefTest(unittest.TestCase):
    def test_value_in_mm_degrees_or_as_is(self):
        self.assertEqual(param_refs.ref(model_param("d1", "wall", 0.2)),
                         {"name": "d1", "expression": "wall", "value": 2.0})
        self.assertEqual(param_refs.ref(model_param("d2", "turn", 1.5707963267948966), "angle")["value"], 90.0)
        self.assertEqual(param_refs.ref(model_param("d3", "count", 3), "scalar")["value"], 3.0)

    def test_a_member_that_is_not_a_model_parameter_gives_none(self):
        self.assertIsNone(param_refs.ref(Obj(value=0.2)))
        self.assertIsNone(param_refs.ref(0.2))
        self.assertIsNone(param_refs.ref(model_param("d1", "", 0.2)))


class FeatureParamsTest(unittest.TestCase):
    def test_extrude_distance_and_start_offset(self):
        data = capture_of({
            "extentOne": Obj("fusion::DistanceExtentDefinition", distance=model_param("d3", "height", 1.0)),
            "startExtent": Obj("fusion::OffsetStartDefinition", offset=model_param("d4", "gap", 0.5)),
        })["items"][1]["data"]
        self.assertEqual(data["params"], {
            "side_one.distance": {"name": "d3", "expression": "height", "value": 10.0},
            "start.offset": {"name": "d4", "expression": "gap", "value": 5.0}})

    def test_values_without_a_model_parameter_leave_params_out(self):
        self.assertNotIn("params", capture_of()["items"][1]["data"])

    def test_shell_thickness(self):
        data = read_data(feature("ShellFeature", "Shell1", inputEntities=Coll([face("f1")]),
                                 insideThickness=model_param("d5", "wall", 0.2)))
        self.assertEqual(data["params"], {"inside": {"name": "d5", "expression": "wall", "value": 2.0}})


class EnvelopeTest(unittest.TestCase):
    def test_default_length_unit_and_user_parameters_are_read(self):
        user = Obj(name="wall", expression="2 mm", value=0.2, unit="mm", comment="", isFavorite=True)
        capture = capture_of(fusionUnitsManager=Obj(defaultLengthUnits="in"), userParameters=Coll([user]))
        self.assertEqual(capture["design_units"], "in")
        self.assertEqual([p["name"] for p in capture["parameters"]["user"]], ["wall"])


if __name__ == "__main__":
    unittest.main()
