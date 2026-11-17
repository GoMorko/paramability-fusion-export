"""The values the walk back sets after a try left a sketch on its other solution (`design_edit.walk_back.settings`)."""
import unittest

from ParamabilityExport.lib.design_edit.walk_back import settings


class SettingsTest(unittest.TestCase):
    def test_a_ratio_without_a_unit_steps_by_fractions(self):
        self.assertAlmostEqual(settings({"Ratio": 3.6}, {"Ratio": 1.8}, {"Ratio": ""}, 0)[0]["Ratio"], 1.62)
        walk = [step["Ratio"] for step in settings({"Ratio": 3.6}, {"Ratio": 1.8}, {"Ratio": ""}, 1)]
        self.assertEqual([round(v, 3) for v in walk], [3.15, 2.7, 2.25])

    def test_a_count_steps_by_whole_numbers(self):
        self.assertEqual(settings({"Count": 8.0}, {"Count": 4.0}, {"Count": ""}, 0), [{"Count": 3.0}])
        self.assertEqual([s["Count"] for s in settings({"Count": 8.0}, {"Count": 4.0}, {"Count": ""}, 1)],
                         [7.0, 6.0, 5.0])

    def test_a_length_steps_past_its_start_by_a_share_of_the_try(self):
        self.assertAlmostEqual(settings({"W": 50.0}, {"W": 40.0}, {"W": "mm"}, 0)[0]["W"], 39.0)


if __name__ == "__main__":
    unittest.main()
