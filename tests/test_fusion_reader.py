import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign
from lib.design_edit.apply import RowBuildError
from lib.fusion_reader.parameters import list_user_parameters
from lib.fusion_reader.rows import DesignParameterStore
from tests.row_helpers import apply_row, restore, saved_expressions

PARAMS = [
    dict(name="width", expression="20 mm", value=2.0, unit="mm", comment="Clip width", isFavorite=True),
    dict(name="depth", expression="width / 2", value=1.0, unit="mm", comment=None, isFavorite=False),
    dict(name="speed", expression="5 kg", value=5.0, unit="kg", comment="", isFavorite=True),
    dict(name="angle", expression="30 deg", value=0.5235987755982988, unit="deg", comment="", isFavorite=True),
]


class ReaderTest(unittest.TestCase):
    def test_lists_parameters_as_plain_dicts(self):
        listed = list_user_parameters(FakeDesign(PARAMS))
        self.assertEqual([p["kind"] for p in listed], ["length", "derived", "unsupported", "angle"])
        self.assertAlmostEqual(listed[0]["display_value"], 20.0)
        self.assertAlmostEqual(listed[3]["display_value"], 30.0)
        self.assertEqual(listed[1]["comment"], "")
        self.assertTrue(listed[0]["is_favorite"])

    def test_a_formula_of_numbers_has_the_kind_of_its_unit_and_one_that_reads_a_parameter_is_derived(self):
        design = FakeDesign([
            dict(name="wall", expression="3 * 0.4 mm", value=0.12, unit="mm", comment="", isFavorite=False),
            dict(name="turn", expression="2 * 45 deg", value=1.5707963267948966, unit="deg", comment="",
                 isFavorite=False),
            dict(name="ratio", expression="2 * PI", value=6.283185307179586, unit="", comment="", isFavorite=False),
            dict(name="plate", expression="wall * 2", value=0.24, unit="mm", comment="", isFavorite=False),
            dict(name="jitter", expression="random() * 2 mm", value=0.1, unit="mm", comment="", isFavorite=False),
        ])
        self.assertEqual([p["kind"] for p in list_user_parameters(design)],
                         ["length", "angle", "count", "derived", "derived"])

    def test_apply_then_restore_round_trip(self):
        design = FakeDesign(PARAMS)
        saved = saved_expressions(design)
        values = apply_row(design, {"width": 40.0}, {"width": "mm"})
        self.assertEqual(values, {"width": 40.0})
        self.assertEqual(design.userParameters.itemByName("width").expression, "40 mm")
        self.assertEqual(restore(design, saved), [])
        self.assertEqual(saved_expressions(design), saved)

    def test_timeline_error_item_fails_the_row(self):
        design = FakeDesign(PARAMS, timeline=[dict(name="Extrude1", isSuppressed=False, healthState=2)])
        self.assertEqual(DesignParameterStore(design).error_items(), ["Extrude1"])
        with self.assertRaises(RowBuildError):
            apply_row(design, {"width": 40.0}, {"width": "mm"})

    def test_suppressed_error_item_is_ignored(self):
        design = FakeDesign(PARAMS, timeline=[dict(name="Extrude1", isSuppressed=True, healthState=2)])
        self.assertEqual(DesignParameterStore(design).error_items(), [])


if __name__ == "__main__":
    unittest.main()
