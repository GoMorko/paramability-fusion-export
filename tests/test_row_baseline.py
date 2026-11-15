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


def scripted(answers=(True,), errors=(), expressions=None):
    """A store whose recompute answers come from `answers` (the last one repeats; an exception is raised) and whose
    steps in error are the `(index, name)` pairs in `errors`."""
    return FakeStore(expressions or {"w": "5 mm"}, answers=answers, errors=errors)


def apply(store, baseline, value=7.0):
    return apply_row_values(store, UNITS, {"w": value}, baseline)


class BaselineRowTest(unittest.TestCase):
    def test_a_design_that_recomputes_cleanly_fails_a_row_whose_recompute_fails(self):
        store = scripted([True, False])
        baseline = measure_baseline(store)
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.detail["reason"], "recompute_failed")

    def test_a_baseline_that_already_fails_lets_a_row_pass_when_nothing_new_is_in_error(self):
        store = scripted([False], errors=[(3, "Fillet1")])
        baseline = measure_baseline(store)
        self.assertFalse(baseline.recompute_ok)
        self.assertEqual(apply(store, baseline), {"w": 7.0})

    def test_a_new_error_item_fails_the_row_and_is_named(self):
        store = scripted([False], errors=[(3, "Fillet1")])
        baseline = measure_baseline(store)
        store.errors.append((9, "Extrude5"))
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.items, ["Extrude5"])
        self.assertIn("Extrude5", str(ctx.exception))

    def test_items_are_told_apart_by_position_when_names_repeat(self):
        store = scripted([True], errors=[(3, "Extrude")])
        baseline = measure_baseline(store)
        store.errors.append((8, "Extrude"))
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.items, ["Extrude"])

    def test_a_recompute_that_raises_fails_the_row_even_when_the_baseline_failed(self):
        store = scripted([False, RuntimeError("boom")])
        baseline = measure_baseline(store)
        with self.assertRaises(RowBuildError) as ctx:
            apply(store, baseline)
        self.assertEqual(ctx.exception.detail["reason"], "recompute_raised")

    def test_a_baseline_recompute_that_raises_counts_as_failed_and_does_not_stop_the_run(self):
        store = scripted([RuntimeError("boom"), False])
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
        store = scripted([False], errors=[(2, "Other")])
        self.assertEqual(self.run_rows(store)[0]["values"], {"w": 7.0})
        self.assertEqual(store.exprs, {"w": "5 mm"})

    def test_a_failed_row_carries_its_detail_and_the_run_goes_on(self):
        store = scripted([True], errors=[])
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
        store = scripted(expressions={name: "1.8"})
        values = apply_row_values(store, {name: ""}, {name: 3.6}, measure_baseline(store))
        self.assertEqual(store.sets, [(name, "3.6")])
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


class FormulaOfNumbersTest(unittest.TestCase):
    def test_a_row_writes_a_number_into_a_formula_of_numbers_and_the_restore_puts_the_text_back(self):
        store = FakeStore({"w": "5 mm", "wall": "3 * 0.4 mm"})
        saved = store.saved_expressions()
        apply_row_values(store, {"wall": "mm"}, {"wall": 1.5})
        self.assertEqual(store.exprs["wall"], "1.5 mm")
        self.assertEqual(restore_parameters(store, saved), [])
        self.assertEqual(store.exprs, saved)


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

    def test_a_value_the_one_change_did_not_take_is_put_back_on_its_own(self):
        class Skipping(BatchDesign):
            def modifyParameters(self, parameters, values):
                kept = [(p, v) for p, v in zip(parameters, values) if p.name != "h"]
                return super().modifyParameters([p for p, _ in kept], [v for _, v in kept])

        design = Skipping()
        store = self.store(design)
        saved = store.saved_expressions()
        apply_row_values(store, self.UNITS, {"w": 6.0})
        store.set_expression("h", "9 mm")
        self.assertEqual(restore_parameters(store, saved), [])
        self.assertEqual(store.current_expressions(), saved)

    def test_a_change_fusion_refuses_as_a_whole_is_set_one_value_at_a_time(self):
        design = BatchDesign(refuse="9 mm")
        store = self.store(design)
        self.assertEqual(apply_row_values(store, self.UNITS, {"w": 6.0, "h": 9.0}), {"w": 6.0, "h": 9.0})
        self.assertEqual((design.batches, design.computed), ([], 1))


class BatchStore(FakeStore):
    """A store that takes a row in one change (`set_expressions`). `errors` are the steps in error after a change;
    with `cleared_by_recompute` a full recompute clears them, as when only a partial rebuild left them."""

    def __init__(self, errors=(), cleared_by_recompute=False, bad="9 mm"):
        super().__init__({"w": "5 mm"})
        self.bad, self.cleared = bad, cleared_by_recompute
        self.failing, self.stale = list(errors), False

    def set_expressions(self, expressions):
        self.exprs.update(expressions)
        self.stale = self.stale or self.bad in expressions.values()
        return True

    def recompute(self):
        self.recomputes += 1
        if self.cleared:
            self.stale = False
        return True

    def error_items(self):
        return list(self.failing) if self.stale else []


class IncrementalStore(BatchStore):
    """A store whose one change leaves the design rebuilt only in part until a full recompute; `answers` are what
    the recomputes report, in turn (the last one repeats)."""

    def __init__(self, answers=(True,)):
        super().__init__()
        self.answers, self.complete = list(answers), True

    def set_expressions(self, expressions):
        self.complete = False
        return super().set_expressions(expressions)

    def recompute(self):
        super().recompute()
        self.complete = True
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class OneChangeRowTest(unittest.TestCase):
    def export(self, store):
        written = []
        job = RowExport(store, UNITS, lambda path: written.append(store.complete) or open(path, "wb").close())
        with tempfile.TemporaryDirectory() as tmp:
            job.run([{"name": "wide", "values": {"w": 6.0}}], tmp, lambda *a: True)
        return written

    def test_a_row_with_a_step_file_is_recomputed_in_full_before_the_file_is_written(self):
        self.assertEqual(self.export(IncrementalStore()), [True])

    def test_a_row_whose_full_recompute_fails_is_not_written(self):
        with self.assertRaises(RowBuildError) as raised:
            self.export(IncrementalStore(answers=(True, False)))
        self.assertEqual(raised.exception.detail["reason"], "recompute_failed")


class StopCheckTest(unittest.TestCase):
    def run_rows(self, store):
        starts = []
        job = RowExport(store, UNITS, lambda path: None, before_row=lambda row: starts.append(row["name"]))
        rows = [{"name": n, "values": {"w": v}, "step": False} for n, v in (("bad", 9.0), ("next", 6.0))]
        with tempfile.TemporaryDirectory() as tmp:
            results = job.run(rows, tmp, lambda *a: True, tolerate_build_errors=True)
        return job, results, starts

    def test_a_row_judged_after_one_change_says_its_rebuild_is_not_known(self):
        with self.assertRaises(RowBuildError) as raised:
            apply_row_values(BatchStore(errors=["Fillet1"]), UNITS, {"w": 9.0})
        self.assertIsNone(raised.exception.detail["recompute_ok"])

    def test_an_error_a_full_recompute_clears_does_not_stop_the_rows(self):
        job, results, _ = self.run_rows(BatchStore(errors=["Fillet1"], cleared_by_recompute=True))
        self.assertIsNone(job.not_back)
        self.assertEqual([r["name"] for r in results], ["bad", "next"])

    def test_a_stop_comes_before_the_next_row_reads_the_design(self):
        job, results, starts = self.run_rows(BatchStore(errors=["Fillet1"]))
        self.assertEqual(job.not_back["items"], ["Fillet1"])
        self.assertEqual((len(results), starts), (1, ["bad"]))


if __name__ == "__main__":
    unittest.main()
