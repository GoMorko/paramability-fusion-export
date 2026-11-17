"""The undo of an export that did not put the design back: which exports ask Fusion to abort, what the first execute
event holds, and what the result window of an undone export carries."""
import dataclasses
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakePartsPort, FakePort
from tests.test_parts_pipeline import BASE, second_body, request as parts_request
from tests.test_pipeline import TICKED, request as single_request
from tests.test_put_back_order import OrderStore, order_parts_port, order_port

from lib.design_edit.errors import StepExportError
from lib.design_edit.runner import ExportCancelled
from lib.dialog_model.orca_result import orca_view
from lib.dialog_model.result_rows import parts_result_view, result_view, section_lines
from lib.export_plan import rollback, undo_steps
from lib.export_plan.health import HealthInputs, health_lines, make_health
from lib.export_plan.pipeline import run_parts_pipeline, run_pipeline
from lib.export_plan.rollback import ExecuteGate, ExportOutcome, Rollback, decide


class Args:
    """The `CommandEventArgs` of an execute event: the two members the gate sets."""

    executeFailed = False
    executeFailedMessage = ""


def run(port, parts=False, light_undo=False, **request_options):
    """`(outcome, error)` of one export through the pipeline: the outcome it filled in, and what it raised."""
    outcome = ExportOutcome()
    if light_undo:
        undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
    ask, pipeline = (parts_request(), run_parts_pipeline) if parts else (single_request(), run_pipeline)
    ask = dataclasses.replace(ask, faster_tries=True, outcome=outcome, **request_options)
    error = None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            pipeline(port, ask, tmp)
        except (ExportCancelled, StepExportError) as exc:
            error = exc
    return outcome, error


CLEAN = make_health(HealthInputs())


def aborts(outcome):
    return decide(outcome).abort


class DecideTest(unittest.TestCase):
    def test_a_design_that_is_back_is_not_aborted(self):
        self.assertEqual(decide(ExportOutcome(CLEAN, touched=True)), Rollback())

    def test_a_design_with_a_change_is_aborted_even_when_no_try_ran(self):
        self.assertEqual(decide(ExportOutcome({"unrestored": ["wall_mm"]})), Rollback(True, False, True))

    def test_tries_with_no_confirmed_health_are_aborted_but_no_tries_are_not(self):
        self.assertEqual(decide(ExportOutcome(None, touched=True)), Rollback(True, False, False))
        self.assertEqual(decide(ExportOutcome(None, touched=False)), Rollback())
        self.assertEqual(decide(None), Rollback())

    def test_a_health_that_cannot_confirm_the_design_is_aborted_without_any_warning_line(self):
        health = dict(CLEAN, steps_unread=True)
        undone = decide(ExportOutcome(health, touched=True))
        self.assertTrue(undone.abort)
        self.assertEqual(health_lines(health), [])
        self.assertTrue(rollback.check_lines(health, undone))

    def test_a_change_after_forgotten_undo_data_is_a_partial_undo(self):
        undone = decide(ExportOutcome({"unrestored": ["wall_mm"], "undo_dropped": True}, touched=True))
        self.assertTrue(undone.abort and undone.partial)


class ExportOutcomeTest(unittest.TestCase):
    def test_a_clean_export_is_not_aborted(self):
        outcome, error = run(order_port(OrderStore()))
        self.assertIsNone(error)
        self.assertTrue(outcome.touched)
        self.assertFalse(aborts(outcome))

    def test_a_step_that_stays_changed_is_aborted(self):
        outcome, _ = run(order_port(OrderStore(changed="Fillet1", heals=False)))
        self.assertTrue(aborts(outcome))
        self.assertFalse(decide(outcome).partial)

    def test_a_parameter_that_will_not_go_back_is_aborted(self):
        outcome, _ = run(order_port(OrderStore(stuck_param="box_count")))
        self.assertTrue(aborts(outcome))

    def test_tries_that_stopped_on_a_broken_design_are_aborted(self):
        outcome, _ = run(order_port(OrderStore(broken_above=70)))
        self.assertTrue(aborts(outcome))

    def test_a_cancel_that_put_the_design_back_is_not_aborted(self):
        outcome, error = run(order_port(OrderStore(), cancel_at=4))
        self.assertIsInstance(error, ExportCancelled)
        self.assertTrue(outcome.touched)
        self.assertFalse(aborts(outcome))

    def test_a_cancel_that_left_a_step_changed_is_aborted(self):
        outcome, error = run(order_port(OrderStore(changed="Fillet1", heals=False), cancel_at=4))
        self.assertIsInstance(error, ExportCancelled)
        self.assertTrue(aborts(outcome))

    def test_an_export_that_stops_before_the_tries_changes_nothing_and_is_not_aborted(self):
        outcome, error = run(order_port(OrderStore(), fail_step_at=1))
        self.assertIsInstance(error, StepExportError)
        self.assertFalse(outcome.touched)
        self.assertFalse(aborts(outcome))

    def test_several_bodies_follow_the_same_rule(self):
        clean, _ = run(order_parts_port(OrderStore()), parts=True)
        self.assertTrue(clean.touched)
        self.assertFalse(aborts(clean))
        changed, _ = run(order_parts_port(OrderStore(changed="Fillet1", heals=False)), parts=True)
        self.assertTrue(aborts(changed))

    def test_forgotten_undo_data_makes_the_undo_partial(self):
        outcome, _ = run(order_port(OrderStore(changed="Fillet1", heals=False)), light_undo=True)
        verdict = decide(outcome)
        self.assertTrue(verdict.abort and verdict.partial)
        clean, _ = run(order_port(OrderStore()), light_undo=True)
        self.assertFalse(aborts(clean))

    def test_the_orca_output_keeps_its_outcome_too_and_is_not_aborted_when_clean(self):
        from lib.export_plan.orca_export import ORCA
        clean, _ = run(FakePort(), output=ORCA)
        self.assertFalse(clean.touched)
        self.assertFalse(aborts(clean))


class ExecuteGateTest(unittest.TestCase):
    def test_a_change_sets_the_abort_with_a_message(self):
        args = Args()
        ExecuteGate().run(args, lambda outcome: setattr(outcome, "health", {"broken": ["Fillet1"]}))
        self.assertTrue(args.executeFailed)
        self.assertTrue(args.executeFailedMessage)

    def test_a_clean_export_leaves_the_abort_off(self):
        args = Args()
        ExecuteGate().run(args, lambda outcome: (setattr(outcome, "health", CLEAN), setattr(outcome, "touched", True)))
        self.assertFalse(args.executeFailed)

    def test_a_second_event_does_not_run_or_abort_again(self):
        gate, runs = ExecuteGate(), []

        def export(outcome):
            runs.append(1)
            outcome.health = {"broken": ["Fillet1"]}

        first, nested, later = Args(), Args(), Args()
        gate.run(first, export)
        gate.run(nested, export)
        gate.run(later, export)
        self.assertEqual(len(runs), 1)
        self.assertTrue(first.executeFailed)
        self.assertFalse(nested.executeFailed or later.executeFailed)

    def test_an_event_fired_while_the_export_runs_does_nothing(self):
        gate, runs, args, nested = ExecuteGate(), [], Args(), Args()

        def export(outcome):
            runs.append(1)
            gate.run(nested, export)  # the event of a step the export starts
            outcome.health = {"unrestored": ["wall_mm"]}

        gate.run(args, export)
        self.assertEqual(len(runs), 1)
        self.assertTrue(args.executeFailed)
        self.assertFalse(nested.executeFailed)

    def test_an_export_that_raises_still_sets_the_abort_and_the_error_goes_on(self):
        args = Args()

        def export(outcome):
            outcome.touched = True
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            ExecuteGate().run(args, export)
        self.assertTrue(args.executeFailed)

    def test_a_failing_set_is_logged_and_not_raised(self):
        class Locked:
            @property
            def executeFailed(self):
                return False

            @executeFailed.setter
            def executeFailed(self, value):
                raise RuntimeError("read only")

        logged = []
        ExecuteGate(logged.append).run(Locked(), lambda outcome: setattr(outcome, "health", {"broken": ["x"]}))
        self.assertEqual(len(logged), 1)


class ResultViewTest(unittest.TestCase):
    def _result(self, port=None):
        with tempfile.TemporaryDirectory() as tmp:
            return run_pipeline(port or FakePort(), single_request(), tmp)

    def test_the_keys_of_a_view_say_whether_the_export_was_undone(self):
        result = self._result()
        args = (result.manifest, result.report, result.table, TICKED)
        plain = result_view("box.paramability", *args)
        self.assertEqual((plain["rolled_back"], plain["partial"]), (False, False))
        full = result_view("box.paramability", *args, rollback=Rollback(True, False, True))
        self.assertEqual((full["rolled_back"], full["partial"]), (True, False))
        partial = result_view("box.paramability", *args, rollback=Rollback(True, True, True))
        self.assertEqual((partial["rolled_back"], partial["partial"]), (True, True))

    def test_a_full_undo_replaces_the_advice_to_use_undo_and_a_partial_one_keeps_what_changed(self):
        health = {"broken": ["Fillet1"], "undo_dropped": True}
        result = self._result()
        report = dict(result.report, health=health)
        args = (result.manifest, report, result.table, TICKED)
        full = section_lines(result_view("box.paramability", *args, rollback=Rollback(True, False, True)), "check")
        partial = section_lines(result_view("box.paramability", *args, rollback=Rollback(True, True, True)), "check")
        shown = section_lines(result_view("box.paramability", *args), "check")
        self.assertTrue(full)
        self.assertFalse([line for line in full if "Fillet1" in line])
        self.assertTrue([line for line in partial if "Fillet1" in line])
        self.assertGreater(len(partial), len(full))
        self.assertTrue([line for line in shown if "Fillet1" in line])

    def test_the_parts_and_orca_views_carry_the_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            parts = run_parts_pipeline(FakePartsPort([BASE, second_body()]), parts_request(), tmp)
        undone = Rollback(True, False, True)
        view = parts_result_view("parts.paramability", parts.manifest, parts.report, parts.table, TICKED, undone)
        self.assertTrue(view["rolled_back"])
        self.assertFalse(view["partial"])
        orca = orca_view("box.3mf", {"health": {"broken": ["Fillet1"]}}, TICKED, undone)
        self.assertTrue(orca["rolled_back"])
        self.assertTrue(section_lines(orca, "check"))
        self.assertFalse(orca_view("box.3mf", {})["rolled_back"])

    def test_the_window_says_so_when_the_health_has_no_warning(self):
        result = self._result()
        report = dict(result.report, health=dict(CLEAN, steps_unread=True))
        view = result_view("box.paramability", result.manifest, report, result.table, TICKED,
                           rollback=decide(ExportOutcome(report["health"], touched=True)))
        self.assertTrue(view["rolled_back"])
        self.assertTrue(section_lines(view, "check"))

    def test_no_lines_without_an_abort(self):
        self.assertEqual(rollback.lines(Rollback()), [])


if __name__ == "__main__":
    unittest.main()
