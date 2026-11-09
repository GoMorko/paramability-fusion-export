"""The keys the probe writes are the keys the translator asks for, and the three answers about a sketch."""
import glob
import os
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import capture, table
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, at, states
from tests.translator_helpers import FIXTURES, load_capture

from lib.params import size_table
from lib.probe import coverage, match, plan
from lib.probe.motion import Affine, Motion, Stuck, build
from lib.translator import translate
from lib.translator.sizes import sketch_answer


class Recorder(Motion):
    """A motion file that remembers every key the translator asks for."""

    def __init__(self, curves):
        super().__init__(curves=curves)
        self.asked = set()

    def get(self, key):
        self.asked.add(key)
        return super().get(key)


class KeyAgreementTest(unittest.TestCase):
    def test_every_key_the_translator_asks_for_is_a_key_the_probe_plan_reads(self):
        checked = 0
        for path in sorted(glob.glob(os.path.join(FIXTURES, "*.json"))):
            name = os.path.basename(path)[:-5]
            cap = load_capture(name)
            params = cap.get("parameters") or {}
            if not params.get("user"):
                continue
            found = plan.scan(cap)
            if not found.targets:
                continue
            read = set()
            for target in found.targets:
                read.update(match.captured_values(target))
            motion = Recorder({match.prefix(t) for t in found.targets if t["kind"] == "profile"})
            size = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                                    cap.get("design_units", "mm"))
            translate(cap, size_table=size, motion=motion)
            with self.subTest(fixture=name):
                checked += 1
                self.assertTrue(motion.asked)
                self.assertEqual(sorted(motion.asked - read), [])
        self.assertGreater(checked, 1)


class AnswerTest(unittest.TestCase):
    """Sketch1 of the probe tests is drawn by `d1` (the filter width, from count and cube) and `d3` (off);
    Sketch2 sits on a construction plane and has no dimension."""

    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)

    def test_a_measured_sketch_is_answered_moved_for_a_size_that_moved_it_and_still_for_one_that_did_not(self):
        motion = build(CAPTURE, self.table, states())
        self.assertEqual(motion.unmeasured, {})
        moved = sketch_answer(self.table, motion, "Sketch1", "count")
        self.assertEqual(moved.kind, coverage.MOVED)
        self.assertIn("4/p0/l0/width", moved.keys)
        self.assertEqual(sketch_answer(self.table, motion, "Sketch1", "height").kind, coverage.STILL)

    def test_a_sketch_whose_first_read_does_not_match_is_not_measured_for_every_size_behind_it(self):
        e0 = at(off=4)
        e0["e0"], e0["values"] = True, {}
        motion = build(CAPTURE, self.table, [e0] + states()[1:])
        self.assertEqual(list(motion.unmeasured), ["Sketch1"])
        for size in ("count", "cube", "off"):
            answer = sketch_answer(self.table, motion, "Sketch1", size)
            self.assertEqual((answer.kind, answer.reason), (coverage.NOT_MEASURED, coverage.NOT_MATCHED), size)

    def test_a_size_the_sketch_does_not_read_is_never_not_measured(self):
        e0 = at(off=4)
        e0["e0"], e0["values"] = True, {}
        motion = build(CAPTURE, self.table, [e0] + states()[1:])
        self.assertEqual(sketch_answer(self.table, motion, "Sketch1", "height").kind, coverage.STILL)

    def test_a_sketch_a_step_uses_in_a_way_the_probe_cannot_follow_is_not_measured(self):
        stray = {"index": 7, "type": "RectangularPatternFeature", "data": {"direction_one": {"sketch_token": "sk1"}}}
        motion = build(capture(*CAPTURE["items"], stray), self.table, states())
        self.assertEqual(motion.unmeasured, {"Sketch1": coverage.NOT_FOLLOWABLE})
        self.assertEqual(sketch_answer(self.table, motion, "Sketch1", "cube").kind, coverage.NOT_MEASURED)

    def test_without_a_read_at_the_current_sizes_every_covered_sketch_is_not_measured(self):
        motion = build(CAPTURE, self.table, states()[1:])
        self.assertEqual(motion.unmeasured, {"Sketch1": coverage.NOT_READ, "Sketch2": coverage.NOT_READ})

    def test_the_answers_survive_the_json_file(self):
        e0 = at(off=4)
        e0["e0"], e0["values"] = True, {}
        motion = build(CAPTURE, self.table, [e0] + states()[1:])
        again = Motion.from_json(motion.json())
        self.assertEqual(again.unmeasured, motion.unmeasured)
        self.assertEqual(sketch_answer(self.table, again, "Sketch1", "cube").kind, coverage.NOT_MEASURED)

    def test_a_stuck_value_counts_as_moved_by_the_sizes_that_block_it(self):
        motion = Motion({"4/p0/l0/width": Stuck(["count"], "curve", "Sketch1"),
                         "4/p0/l0/height": Affine(0, {"height": 1.0}, "Sketch1")})
        self.assertEqual(sketch_answer(self.table, motion, "Sketch1", "count").kind, coverage.MOVED)


if __name__ == "__main__":
    unittest.main()
