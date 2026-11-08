import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign
from lib.export_plan.apply import RowBuildError
from lib.fusion_reader.parameters import list_user_parameters
from lib.fusion_reader.rows import DesignParameterStore, apply_row, restore, saved_expressions

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
