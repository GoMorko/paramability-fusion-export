"""A size row is judged against how the design recomputed before any change, so trouble elsewhere in a large design
does not fail every size."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign, FakeStore

from lib.design_edit.apply import RowBuildError, apply_row_values, measure_baseline
from lib.design_edit.restore import restore_parameters
from lib.design_edit.runner import RowExport
from lib.fusion_reader.rows import DesignParameterStore
from tests.row_helpers import apply_row

UNITS = {"w": "mm"}


class ScriptedStore(FakeStore):
    """recompute() answers come from `answers` (the last one repeats); an answer that is an exception is raised.
    error_entries() gives the pairs the test sets in `errors`."""

    def __init__(self, answers=(True,), errors=(), expressions=None):
        super().__init__(expressions or {"w": "5 mm"})
        self.answers = list(answers)
        self.errors = list(errors)
        self.calls = []

    def recompute(self):
        self.recomputes += 1
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def error_entries(self):
        return list(self.errors)

    def error_items(self):
        return [name for _, name in self.errors]

    def set_expression(self, name, expression):
        self.calls.append((name, expression))
        super().set_expression(name, expression)


def apply(store, baseline, value=7.0):
    return apply_row_values(store, UNITS, {"w": value}, baseline)


class BaselineRowTest(unittest.TestCase):
    def test_a_design_that_recomputes_cleanly_fails_a_row_whose_recompute_fails(self):
        store = ScriptedStore([True, False])
        baseline = measure_baseline(store)
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.detail["reason"], "recompute_failed")

    def test_a_baseline_that_already_fails_lets_a_row_pass_when_nothing_new_is_in_error(self):
        store = ScriptedStore([False], errors=[(3, "Fillet1")])
        baseline = measure_baseline(store)
        self.assertFalse(baseline.recompute_ok)
        self.assertEqual(apply(store, baseline), {"w": 7.0})

    def test_a_new_error_item_fails_the_row_and_is_named(self):
        store = ScriptedStore([False], errors=[(3, "Fillet1")])
        baseline = measure_baseline(store)
        store.errors.append((9, "Extrude5"))
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.items, ["Extrude5"])
        self.assertIn("Extrude5", str(ctx.exception))

    def test_items_are_told_apart_by_position_when_names_repeat(self):
        store = ScriptedStore([True], errors=[(3, "Extrude")])
        baseline = measure_baseline(store)
        store.errors.append((8, "Extrude"))
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.items, ["Extrude"])

    def test_a_recompute_that_raises_fails_the_row_even_when_the_baseline_failed(self):
        store = ScriptedStore([False, RuntimeError("boom")])
        baseline = measure_baseline(store)
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.detail["reason"], "recompute_raised")

    def test_a_baseline_recompute_that_raises_counts_as_failed_and_does_not_stop_the_run(self):
        store = ScriptedStore([RuntimeError("boom"), False])
        baseline = measure_baseline(store)
        self.assertFalse(baseline.recompute_ok)
        self.assertEqual(apply(store, baseline), {"w": 7.0})

    def test_a_refused_expression_says_which_one(self):
        store = FakeStore({"w": "5 mm"}, reject=["7 mm"])
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, None)
        self.assertEqual(ctx.exception.detail["expression"], "7 mm")


class RunnerBaselineTest(unittest.TestCase):
    def run_rows(self, store, tolerate=False):
        job = RowExport(store, UNITS, lambda path: None)
        return job.run([{"name": "A", "values": {"w": 7.0}, "step": False}], "", lambda *a: True,
                       tolerate_build_errors=tolerate)

    def test_a_design_with_trouble_elsewhere_still_gets_its_rows_built(self):
        store = ScriptedStore([False], errors=[(2, "Other")])
        self.assertEqual(self.run_rows(store)[0]["values"], {"w": 7.0})
        self.assertEqual(store.exprs, {"w": "5 mm"})

    def test_a_failed_row_carries_its_detail_and_the_run_goes_on(self):
        store = ScriptedStore([True], errors=[])
        store.errors = []
        result = self.run_rows_with_new_error(store)
        self.assertEqual(result["detail"]["items"], ["Extrude5"])
        self.assertIsNone(result["values"])

    def run_rows_with_new_error(self, store):
        original = store.set_expression

        def set_expression(name, expression):
            original(name, expression)
            store.errors = [(4, "Extrude5")]
        store.set_expression = set_expression
        return self.run_rows(store, tolerate=True)[0]


class ParameterNameTest(unittest.TestCase):
    def test_a_parameter_name_with_a_dollar_sign_is_passed_as_it_is_and_not_into_the_expression(self):
        name = "FilterBox_$_width__contains_CeramicMedium"
        store = ScriptedStore(expressions={name: "1.8"})
        values = apply_row_values(store, {name: ""}, {name: 3.6}, measure_baseline(store))
        self.assertEqual(store.calls, [(name, "3.6")])
        self.assertEqual(values, {name: 0.36})


class FusionDesignBaselineTest(unittest.TestCase):
    PARAMS = [dict(name="width", expression="20 mm", value=2.0, unit="mm")]

    def test_error_entries_keep_the_position_of_items_that_share_a_name(self):
        timeline = [dict(name="Extrude1", isSuppressed=False, healthState=2),
                    dict(name="Sketch1", isSuppressed=False, healthState=0),
                    dict(name="Extrude1", isSuppressed=False, healthState=2)]
        self.assertEqual(DesignParameterStore(FakeDesign(self.PARAMS, timeline)).error_entries(),
                         [(0, "Extrude1"), (2, "Extrude1")])

    def test_computeall_false_with_nothing_new_in_error_passes_through_the_design_wrapper(self):
        class Warned(FakeDesign):
            def computeAll(self):
                return False

        design = Warned(self.PARAMS, [dict(name="Extrude1", isSuppressed=False, healthState=2)])
        baseline = measure_baseline(DesignParameterStore(design))
        self.assertEqual(apply_row(design, {"width": 40.0}, {"width": "mm"}, baseline), {"width": 40.0})


if __name__ == "__main__":
    unittest.main()


class BatchDesign(FakeDesign):
    """A design with Fusion's `modifyParameters`: it sets every expression in one change, or none when `refuse` is
    one of them, and records each call."""

    def __init__(self, refuse=None):
        super().__init__([dict(name="w", expression="5 mm", value=0.5, unit="mm"),
                          dict(name="h", expression="8 mm", value=0.8, unit="mm")])
        self.refuse = refuse
        self.batches = []

    def modifyParameters(self, parameters, values):
        if self.refuse in values:
            return False
        self.batches.append({p.name: v for p, v in zip(parameters, values)})
        for parameter, value in zip(parameters, values):
            parameter.expression = value
        return True


class BatchedParametersTest(unittest.TestCase):
    UNITS = {"w": "mm", "h": "mm"}

    def store(self, design):
        return DesignParameterStore(design, value_input=lambda text: text)

    def test_a_row_and_its_restore_set_all_values_in_one_change_without_a_full_recompute(self):
        design = BatchDesign()
        store = self.store(design)
        saved = store.saved_expressions()
        self.assertEqual(apply_row_values(store, self.UNITS, {"w": 6.0, "h": 9.0}), {"w": 6.0, "h": 9.0})
        self.assertEqual(restore_parameters(store, saved), [])
        self.assertEqual(design.batches, [{"w": "6 mm", "h": "9 mm"}, {"w": "5 mm", "h": "8 mm"}])
        self.assertEqual(design.computed, 0)

    def test_a_change_fusion_refuses_as_a_whole_is_set_one_value_at_a_time(self):
        design = BatchDesign(refuse="9 mm")
        store = self.store(design)
        self.assertEqual(apply_row_values(store, self.UNITS, {"w": 6.0, "h": 9.0}), {"w": 6.0, "h": 9.0})
        self.assertEqual((design.batches, design.computed), ([], 1))
