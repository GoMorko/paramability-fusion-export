import unittest

from tests import context  # noqa: F401
from lib.export_plan.size_checks import PLACEMENT_KEY, frame_numbers, plan_checks, read_checks

SIZES = [{"param": "gap", "size": "gap", "unit": "mm", "value": 2.0, "min": 1.0, "max": 4.0, "favorite": False}]
FRAME = {"origin": [100, 50, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


class PlaceMovedTest(unittest.TestCase):
    def read(self, after_frame, part="Tray"):
        checks, _ = plan_checks(SIZES)
        baseline = {"c/S": [1.0], PLACEMENT_KEY: frame_numbers(FRAME)}
        snapshot = {"c/S": [1.0]}
        if after_frame is not None:
            snapshot[PLACEMENT_KEY] = frame_numbers(after_frame)
        results = [{"name": "gap", "step_file": "a.step"}]
        return read_checks(checks, results, baseline, {checks[0]["row"]["key"]: snapshot}, {"gap": "gap_mm"}, part)

    def test_a_size_that_moves_the_part_is_fixed_with_the_reason(self):
        kept, fixed, _ = self.read({**FRAME, "origin": [100, 52, 0]})
        self.assertEqual(kept, [])
        self.assertEqual(fixed[0]["reason"], "gap_mm stays fixed: it moves Tray in the assembly, and parts that "
                         "move with sizes come in a later version.")

    def test_noise_and_an_unread_place_are_not_a_move(self):
        self.assertEqual(len(self.read({**FRAME, "origin": [100, 50 + 1e-6, 0]})[0]), 1)
        self.assertEqual(len(self.read(None)[0]), 1)

    def test_the_place_is_not_counted_as_a_sketch(self):
        kept, fixed, _ = self.read(FRAME)
        self.assertEqual((len(kept), fixed), (1, []))


if __name__ == "__main__":
    unittest.main()
