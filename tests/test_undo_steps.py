"""The tries leave their undo data out of Fusion (the "lighter on memory" box): when the step calls are made, and an
export that goes on as before when the call is missing or fails."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.test_pipeline import START, FakePort, request

from lib.export_plan import undo_steps
from lib.export_plan.pipeline import run_pipeline
from lib.timing.export_timing import ExportTiming


class FakeCommand:
    """`Command.beginStep` that notes the parameter values at each call; `fail` raises from the n-th call on."""

    def __init__(self, store, fail=None, answer=True):
        self.store, self.fail, self.answer = store, fail, answer
        self.calls = []

    def beginStep(self, makeExistingStepNonUndoable=False):
        self.calls.append((makeExistingStepNonUndoable, dict(self.store.exprs)))
        if self.fail is not None and len(self.calls) >= self.fail:
            raise RuntimeError("beginStep is not supported here")
        return self.answer


def export(command=None, on=True):
    port = FakePort()
    port.timing = ExportTiming()
    steps = undo_steps.command_steps(command(port.store) if command else None, port.log) if on else None
    undo_steps.attach(port, steps)
    with tempfile.TemporaryDirectory() as tmp:
        result = run_pipeline(port, request(), tmp)
    return port, steps, result


class UndoStepsTest(unittest.TestCase):
    def test_with_the_box_off_the_report_says_so(self):
        _, _, result = export(on=False)
        self.assertEqual(result.report["timing"]["undo"], {"on": False})

    def test_with_the_box_on_each_call_drops_a_step_with_every_value_back(self):
        made = []
        port, steps, result = export(lambda store: made.append(FakeCommand(store)) or made[-1])
        calls = made[0].calls
        self.assertGreater(len(calls), 2)
        self.assertTrue(all(non_undoable and values == START for non_undoable, values in calls))
        self.assertEqual(result.report["timing"]["undo"],
                         {"on": True, "applied": True, "steps": len(calls), "error": ""})
        self.assertEqual(port.store.exprs, START)

    def test_a_missing_or_failing_call_leaves_the_export_as_without_the_box(self):
        plain = export(on=False)[2]
        made = []
        cases = (("missing", lambda store: object(), 0),
                 ("raises", lambda store: made.append(FakeCommand(store, fail=1)) or made[-1], 1),
                 ("refused", lambda store: made.append(FakeCommand(store, answer=False)) or made[-1], 1))
        for name, command, count in cases:
            with self.subTest(name):
                made.clear()
                port, steps, result = export(command)
                self.assertEqual(sum(len(c.calls) for c in made), count)
                undo = result.report["timing"]["undo"]
                self.assertEqual((undo["on"], undo["applied"], undo["steps"]), (True, False, 0))
                self.assertTrue(undo["error"])
                self.assertEqual(result.manifest, plain.manifest)
                self.assertEqual(result.health, plain.health)
                self.assertEqual(port.store.exprs, START)

    def test_the_last_part_of_the_export_is_dropped_only_when_the_design_is_back(self):
        for name, health, applied, expected in (("back", {}, True, 1), ("changed", {"unrestored": ["Width"]}, True, 0),
                                                ("never applied", {}, False, 0)):
            with self.subTest(name):
                calls = []
                steps = undo_steps.UndoSteps(lambda flag: calls.append(flag) or True, lambda text: None)
                steps.record["applied"] = applied
                undo_steps.drop_after(steps, health)
                self.assertEqual(calls, [True] * expected)


if __name__ == "__main__":
    unittest.main()
