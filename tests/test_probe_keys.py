"""The keys the probe writes are the keys the translator asks for, and the three answers about a sketch."""
import glob
import os
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import capture, circle, loop, model, profile, read, state, table, user
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, at, states
from tests.translator_helpers import FIXTURES, load_capture

from lib.export_plan.probe_flow import probe_view
from lib.params import size_table
from lib.probe import match, plan
from lib.sketch_values import coverage
from lib.probe.build import build
from lib.sketch_values.motion import Affine, Motion, Stuck
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
            found = plan.scan(probe_view(cap))
            if not found.targets:
                continue
            read = set()
            for target in found.targets:
                read.update(match.captured_values(target))
            motion = Recorder({match.prefix(t) for t in found.targets if t["kind"] in ("profile", "path")})
            size = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                                    cap.get("design_units", "mm"))
            translate(cap, size_table=size, motion=motion)
            with self.subTest(fixture=name):
                checked += 1
                self.assertTrue(motion.asked)
                self.assertEqual(sorted(motion.asked - read), [])
        self.assertGreater(checked, 1)


PATH_PARAMS = [user("run", "20 mm", 20), user("bend", "5 mm", 5)]
PATH_MODEL = [model("d1", "run", 20, sketch="Path"), model("d2", "bend", 5, sketch="Path")]


def path_item():
    """A sweep along a line of `run` mm that ends in a quarter arc of radius `bend` (sketch plane = XY)."""
    flat = [{"kind": "line", "start": [0, 0], "end": [0, 20]},
            {"kind": "arc", "start": [0, 20], "end": [5, 25], "mid": [1.464466, 23.535534], "center": [5, 20],
             "radius": 5.0}]
    curves = [dict(f, entity="e%d" % n, flat=f) for n, f in enumerate(flat)]
    wire = profile("Wire", "skW", [loop([circle((0, 0), 1, "w")])])
    return {"index": 3, "name": "Sweep1", "type": "SweepFeature", "data": {"profiles": [wire], "path": {
        "closed": False, "kind": "sketch", "sketch": "Path", "sketch_token": "skP", "frame": IDENT_FRAME,
        "curves": curves, "edges": []}}}


IDENT_FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def path_read(run=20, bend=5, frame=IDENT_FRAME):
    k = 0.707106781
    curves = {"e0": {"kind": "line", "start": [0, 0], "end": [0, run]},
              "e1": {"kind": "arc", "start": [0, run], "end": [bend, run + bend], "center": [bend, run],
                     "mid": [bend - bend * k, run + bend * k], "radius": bend}}
    sketches = {"skP": {"frame": frame, "profiles": [], "curves": curves},
                "skW": {"frame": IDENT_FRAME, "profiles": [{"loops": [loop([circle((0, 0), 1, "w")])]}]}}
    return read(sketches, params={"run": run / 10, "bend": bend / 10, "d1": run / 10, "d2": bend / 10})


class PathMotionTest(unittest.TestCase):
    """A sweep path is measured like an outline: its curves under `<item>/path/c<n>/...`."""

    def build(self, *states):
        tbl = table(PATH_PARAMS, ["run", "bend"], PATH_MODEL)
        cap = capture(path_item())
        return build(cap, tbl, [state({}, path_read(), e0=True)] + list(states))

    def test_a_curve_that_moves_with_a_size_is_fitted_and_one_that_does_not_has_no_key(self):
        motion = self.build(state({"run": 30}, path_read(run=30)), state({"run": 15}, path_read(run=15)),
                            state({"bend": 8}, path_read(bend=8)), state({"bend": 3}, path_read(bend=3)))
        self.assertEqual(motion.curves, {"3/path", "3/p0"})
        self.assertEqual(motion.get("3/path/c0/end.1").terms, {"run": 1.0})
        self.assertEqual(motion.get("3/path/c1/center.0").terms, {"bend": 1.0})
        self.assertEqual(motion.get("3/path/c1/radius").terms, {"bend": 1.0})
        self.assertIsNone(motion.get("3/path/c0/start.0"))
        self.assertIsNone(motion.get("3/path/c1/turn"))

    def test_a_sketch_plane_that_turns_is_a_problem_with_a_cause_for_the_sizes_that_did_it(self):
        turned = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 0, 1], "z": [0, -1, 0]}
        motion = self.build(state({"run": 30}, path_read(run=30, frame=turned)),
                            state({"run": 15}, path_read(run=15)), state({"run": 25}, path_read(run=25)))
        stuck = motion.get("3/path/c0/end.1")
        self.assertIsInstance(stuck, Stuck)
        self.assertEqual((stuck.cause, stuck.movers), ("turns", ("run",)))

    def test_a_path_the_first_read_does_not_return_is_left_unfollowed_and_nothing_else_is_unmeasured(self):
        tbl = table(PATH_PARAMS, ["run", "bend"], PATH_MODEL)
        wrong = path_read(run=21)
        motion = build(capture(path_item()), tbl, [state({}, wrong, e0=True), state({"run": 30}, path_read(run=30))])
        self.assertEqual((motion.curves, motion.unmeasured), ({"3/p0"}, {}))


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

    def test_a_size_no_try_set_is_not_measured_rather_than_still(self):
        motion = build(CAPTURE, self.table, [s for s in states() if "off" not in s["values"]])
        answer = sketch_answer(self.table, motion, "Sketch1", "off")
        self.assertEqual((answer.kind, answer.reason), (coverage.NOT_MEASURED, coverage.NOT_TRIED))

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
