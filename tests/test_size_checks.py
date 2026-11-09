import unittest

from tests import context  # noqa: F401
from lib.export_plan.size_checks import check_value, plan_checks, read_checks
from lib.fusion_reader.sketches import moved_sketches, read_sketches

SIZES = [
    {"param": "wall", "size": "wall", "unit": "mm", "value": 2.0, "min": 1.0, "max": 4.0, "favorite": False},
    {"param": "count", "size": "count", "unit": "", "value": 3.0, "min": 1.0, "max": 6.0, "favorite": True},
    {"param": "turn", "size": "turn", "unit": "deg", "value": 90.0, "min": 45.0, "max": 90.0, "favorite": True},
    {"param": "flat", "size": "flat", "unit": "mm", "value": 5.0, "min": 5.0, "max": 5.0, "favorite": True},
]


class PlanChecksTest(unittest.TestCase):
    def test_checks_the_top_of_the_range_or_the_bottom_when_the_top_is_current(self):
        self.assertEqual(check_value(SIZES[0]), 4.0)
        self.assertEqual(check_value(SIZES[2]), 45.0)
        self.assertIsNone(check_value(SIZES[3]))

    def test_each_row_changes_one_size_and_keeps_the_others(self):
        checks, unchecked = plan_checks(SIZES)
        self.assertEqual([c["size"] for c in checks], ["count", "turn", "wall"])
        self.assertEqual([s["size"] for s in unchecked], ["flat"])
        wall_row = checks[2]["row"]
        self.assertEqual(wall_row["values"]["wall"], 4.0)
        self.assertEqual(wall_row["values"]["count"], 3.0)
        self.assertAlmostEqual(wall_row["values"]["turn"], 90.0)

    def test_values_are_written_in_the_parameter_unit(self):
        inches = [{"param": "w", "size": "w", "unit": "in", "value": 25.4, "min": 12.7, "max": 50.8,
                   "favorite": False}]
        checks, _ = plan_checks(inches)
        self.assertAlmostEqual(checks[0]["row"]["values"]["w"], 2.0)
        self.assertEqual(checks[0]["value"], 50.8)

    def test_limit_leaves_the_rest_unchecked(self):
        checks, unchecked = plan_checks(SIZES, limit=2)
        self.assertEqual([c["size"] for c in checks], ["count", "turn"])
        self.assertEqual([s["size"] for s in unchecked], ["flat", "wall"])


class ReadChecksTest(unittest.TestCase):
    def setUp(self):
        self.checks, _ = plan_checks(SIZES[:2] + SIZES[2:3])
        self.baseline = {"Sketch1": [1.0, 2.0], "Sketch2": [3.0]}

    def test_sorts_by_what_each_check_showed(self):
        results = [
            {"name": "count", "step_file": "a.step"},
            {"name": "turn", "step_file": None, "error": "Fusion could not rebuild the design for this size."},
            {"name": "wall", "step_file": "c.step"},
        ]
        snapshots = {"count": dict(self.baseline), "wall": {"Sketch1": [1.0, 2.5], "Sketch2": [3.0]}}
        kept, fixed = read_checks(self.checks, results, self.baseline, snapshots, {"wall": "Wall"})
        self.assertEqual([c["size"] for c in kept], ["count"])
        self.assertEqual(kept[0]["step_file"], "a.step")
        by_param = {f["param"]: f["reason"] for f in fixed}
        self.assertIn("cannot build the part", by_param["turn"])
        self.assertIn("Wall stays fixed for now: it changes Sketch1.", by_param["wall"])


    def test_a_moved_sketch_of_a_component_is_named_with_the_component_and_never_a_token(self):
        results = [{"name": "wall", "step_file": "c.step"}]
        wall = [c for c in self.checks if c["size"] == "wall"]
        snapshots = {"wall": {"Sketch1": [1.0, 2.5], "Sketch2": [3.0]}}
        _, fixed = read_checks(wall, results, self.baseline, snapshots, {}, scope="Tray")
        self.assertEqual(fixed[0]["reason"], "wall stays fixed for now: it changes Tray / Sketch1. "
                                             "A sketch like this cannot follow sizes yet.")


class SketchStateTest(unittest.TestCase):
    def test_noise_is_not_a_move_but_a_new_or_resized_sketch_is(self):
        before = {"A": [1.0, 2.0], "B": [1.0], "C": [1.0]}
        after = {"A": [1.0, 2.0 + 1e-7], "B": [1.0, 2.0], "D": [0.0]}
        self.assertEqual(moved_sketches(before, after), ["B", "D", "C"])

    def test_reads_numbers_from_points_and_curves_and_skips_what_it_cannot_read(self):
        class P:
            x, y, z = 1.0, 2.0, 3.0

        class Geo:
            radius = 4.0
            center = P()

        class Curve:
            worldGeometry = Geo()

        class Coll:
            def __init__(self, items):
                self._items, self.count = items, len(items)

            def item(self, i):
                return self._items[i]

        class Sketch:
            name = "S"
            sketchPoints = Coll([type("Pt", (), {"worldGeometry": P()})()])
            sketchCurves = Coll([Curve()])

        root = type("Root", (), {"sketches": Coll([Sketch()])})()
        self.assertEqual(read_sketches(root), {"S": [1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0]})
        self.assertEqual(read_sketches(root, skip={"S"}), {})
        self.assertEqual(read_sketches(object()), {})


if __name__ == "__main__":
    unittest.main()
