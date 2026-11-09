"""A size that Fusion cannot build at the end of its range is tried again at smaller steps and keeps a shorter range."""
import os
import re
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.params_fixtures import CUBE, reader_dicts

from lib.export_plan import recipe_export
from lib.export_plan.messages import narrowed_notes
from lib.export_plan.recipe_export import plan_single_export
from lib.export_plan.result_rows import result_view
from lib.export_plan.runner import ExportCancelled, RowExport
from lib.export_plan.size_checks import build_failures, check_at, plan_checks, read_checks
from lib.export_plan.size_narrowing import narrow_failed, retry_values
from lib.export_plan.size_offers import sizes_for_checks
from lib.params import size_table
from lib.probe import plan
from lib.translator.result import TranslateResult
from tests.translator_helpers import load_capture

UNITS = {"wall": "mm", "gap": "mm"}
START = {"wall": "1.25 mm", "gap": "4 mm"}
LABELS = {"wall": "Wall thickness", "gap": "Gap"}


def sizes(**changes):
    wall = {"param": "wall", "size": "wall", "unit": "mm", "kind": "length", "value": 1.25, "min": 0.625, "max": 2.5,
            "typed_min": False, "typed_max": False, "favorite": True}
    gap = {"param": "gap", "size": "gap", "unit": "mm", "kind": "length", "value": 4.0, "min": 2.0, "max": 8.0,
           "typed_min": False, "typed_max": False, "favorite": False}
    return [dict(wall, **changes), gap]


def number(text):
    return float(re.match(r"\s*([-0-9.eE+]+)", text).group(1))


class Fusion:
    """A design that builds while `wall` is between `low` and `limit` and `gap` is at most `gap_limit`."""

    def __init__(self, limit, gap_limit=100.0, low=0.0):
        self.store = FakeStore(START, bad_when=lambda e: not low <= number(e["wall"]) <= limit
                               or number(e["gap"]) > gap_limit)
        self.exports, self.calls = [], []
        self.tmp = tempfile.mkdtemp()
        self.job = RowExport(self.store, UNITS, self._export)
        self.sizes = []

    def _export(self, path):
        if path is not None:
            self.exports.append(number(self.store.exprs["wall"]))
            open(path, "wb").close()

    def run(self, size, values, step, description, progress=lambda *a: True):
        self.calls.append((size["param"], list(values), step, description))
        rows = [dict(check_at(size, v, self.sizes)["row"], step=step) for v in values]
        return self.job.run(rows, self.tmp, progress, tolerate_build_errors=True, until_built=True)

    def first_pass(self, size_list):
        self.sizes = size_list
        checks, _ = plan_checks(size_list)
        return checks, self.job.run([c["row"] for c in checks], self.tmp, lambda *a: True, tolerate_build_errors=True)


class RetryValuesTest(unittest.TestCase):
    def test_values_run_from_near_the_failed_end_toward_the_current_value(self):
        self.assertEqual(retry_values(sizes()[0], 2.5), [1.87, 1.56, 1.4])

    def test_the_min_side_goes_up_toward_the_current_value(self):
        self.assertEqual(retry_values(sizes()[0], 0.625), [0.94, 1.1, 1.172])

    def test_a_count_tries_whole_numbers_only_and_none_equal_to_the_current_one(self):
        count = dict(sizes()[0], kind="count", value=3.0, min=1.0, max=7.0, unit="")
        self.assertEqual(retry_values(count, 7.0), [5.0, 4.0])


class NarrowFailedTest(unittest.TestCase):
    def narrow(self, fusion, size_list=None, labels=LABELS):
        size_list = size_list or sizes()
        checks, results = fusion.first_pass(size_list)
        return checks, results, narrow_failed(checks, results, size_list, fusion.run, labels)

    def test_a_size_that_builds_at_the_first_smaller_step_ends_its_range_there(self):
        fusion = Fusion(limit=2.0)
        checks, results, out = self.narrow(fusion)
        self.assertEqual(results[0]["error"][:12], "This size do")
        wall = out.narrowed[0]
        self.assertEqual((wall["side"], wall["to"], wall["min"], wall["max"]), ("max", 1.87, 0.625, 1.87))
        self.assertEqual(out.checks[0]["value"], 1.87)
        self.assertTrue(out.results[0]["step_file"])
        self.assertEqual([s["max"] for s in out.sizes], [1.87, 8.0])
        self.assertEqual(out.tries["wall"], [{"value": 1.87, "built": True}, {"value": 0.625, "built": True}])
        self.assertEqual(fusion.exports[-1:], [1.87])
        self.assertEqual(fusion.store.exprs, START)

    def test_the_other_end_is_tried_without_a_step_and_narrowed_the_same_way(self):
        fusion = Fusion(limit=100, low=0.9)
        _, _, out = self.narrow(fusion)
        wall = out.narrowed[0]
        self.assertEqual((wall["side"], wall["to"], wall["min"], wall["max"]), ("min", 0.94, 0.94, 2.5))
        self.assertEqual(out.checks[0]["value"], 2.5)
        self.assertEqual([c[2] for c in fusion.calls], [False, False])
        self.assertEqual(fusion.calls[0][1], [0.625, 0.94, 1.1, 1.172])

    def test_a_size_that_builds_only_at_the_second_step_is_narrowed_after_two_tries(self):
        fusion = Fusion(limit=1.6)
        _, _, out = self.narrow(fusion)
        self.assertEqual(out.narrowed[0]["to"], 1.56)
        self.assertEqual([t["built"] for t in out.tries["wall"]], [False, True, True])
        self.assertEqual(out.ranges(), {"wall": (0.625, 1.56)})

    def test_a_size_that_cannot_grow_keeps_the_lower_half_of_its_range_with_the_check_there(self):
        fusion = Fusion(limit=1.3)
        _, _, out = self.narrow(fusion)
        self.assertEqual(out.ranges(), {"wall": (0.625, 1.25)})
        self.assertEqual((out.checks[0]["value"], out.failed_ends), (0.625, {}))
        self.assertIn("the range ends at 1.25 mm", out.narrowed[0]["note"])
        self.assertEqual(fusion.exports[-1:], [0.625])

    def test_a_size_that_builds_at_no_other_value_stays_a_failure_for_the_fixed_list(self):
        fusion = Fusion(limit=1.25, low=1.25)
        checks, results, out = self.narrow(fusion)
        self.assertEqual((out.narrowed, out.failed_ends), ([], {"wall": [2.5, 0.625]}))
        self.assertEqual(len(out.tries["wall"]), 7)
        self.assertTrue(out.results[0].get("error"))
        _, fixed, _ = read_checks(out.checks, out.results, {}, {}, {"wall": "Wall thickness"},
                                  failed_ends=out.failed_ends)
        self.assertEqual(fixed[0]["reason"], "Wall thickness stays fixed: Fusion cannot build the part when it is 2.5 "
                                             "or 0.625, or any value closer to the current one: Fillet1 fails.")
        self.assertEqual(build_failures(checks, results, out.tries)[0]["tries"][0], {"value": 1.87, "built": False})
        self.assertEqual(fusion.store.exprs, START)

    def test_only_the_moved_end_reaches_the_table(self):
        _, _, out = self.narrow(Fusion(limit=2.0))
        table = size_table.build([dict(name="wall", expression="1.25 mm", value=0.125, unit="mm", comment="",
                                       is_favorite=True, kind="length")], ["wall"])
        planned = table.with_minimums({"wall": 0.8})
        self.assertEqual(out.moved_ends(planned), {"wall": (0.8, 1.87)})
        self.assertEqual(out.moved_ends(table), {"wall": (0.625, 1.87)})

    def test_a_check_that_went_to_the_bottom_narrows_the_min(self):
        size_list = sizes(min=0.1, max=1.25)
        _, _, out = self.narrow(Fusion(limit=100, low=0.5), size_list)
        wall = out.narrowed[0]
        self.assertEqual((wall["side"], wall["to"], wall["min"], wall["max"]), ("min", 0.68, 0.68, 1.25))

    def test_a_refused_expression_is_not_tried_again_and_the_other_end_takes_the_check(self):
        fusion = Fusion(limit=100)
        checks, results, out = self.narrow(fusion)
        self.assertEqual(out.narrowed, [])
        refused = [dict(results[0], error="no", detail={"reason": "expression_refused"}), results[1]]
        fusion.calls = []
        out = narrow_failed(checks, refused, sizes(), fusion.run, LABELS)
        self.assertEqual((fusion.calls[0][0], fusion.calls[0][1][0], fusion.calls[0][2]), ("wall", 0.625, True))
        self.assertEqual((out.checks[0]["value"], out.ranges()["wall"]), (0.625, (0.625, 1.25)))

    def test_two_failing_sizes_are_narrowed_each_and_the_progress_names_the_try(self):
        fusion = Fusion(limit=2.0, gap_limit=6.0)
        _, _, out = self.narrow(fusion)
        self.assertEqual([(n["size"], n["to"]) for n in out.narrowed], [("wall", 1.87), ("gap", 6.0)])
        self.assertEqual(fusion.calls[0][3], "Wall thickness at 1.87 mm")

    def test_a_cancel_during_a_try_stops_the_run_and_puts_the_parameters_back(self):
        fusion = Fusion(limit=2.0)
        checks, results = fusion.first_pass(sizes())

        def run(size, values, step, description):
            return fusion.run(size, values, step, description, progress=lambda *a: False)

        with self.assertRaises(ExportCancelled):
            narrow_failed(checks, results, sizes(), run, LABELS)
        self.assertEqual(fusion.store.exprs, START)

    def test_the_note_says_what_happened_and_names_a_typed_max(self):
        fusion = Fusion(limit=2.0)
        note = self.narrow(fusion)[2].narrowed[0]["note"]
        self.assertEqual(note, "Wall thickness: the range ends at 1.87 mm, since Fusion cannot build the part at "
                               "2.5 mm (Fillet1 fails).")
        typed = self.narrow(Fusion(limit=2.0), sizes(typed_max=True))[2].narrowed[0]["note"]
        self.assertEqual(typed, "Wall thickness: you typed a Max of 2.5 mm, but Fusion cannot build the part there "
                                "(Fillet1 fails), so the range ends at 1.87 mm.")

    def test_a_third_and_later_note_become_one_count(self):
        self.assertEqual(narrowed_notes(["a", "b"]), ["a", "b"])
        self.assertEqual(narrowed_notes(["a", "b", "c", "d"]), ["a", "3 more ranges were shortened the same way (see report.json)."])


class NarrowedTableTest(unittest.TestCase):
    def setUp(self):
        self.params = reader_dicts()

    def test_the_narrowed_range_reaches_the_sizes_the_checks_and_the_probe_rows(self):
        table = size_table.build(self.params, [CUBE])
        name = table.size_name(CUBE)
        narrowed = table.with_narrowed({CUBE: (9.0, 27.0)})
        self.assertEqual((narrowed.sizes[name]["min"], narrowed.sizes[name]["max"]), (9.0, 27.0))
        self.assertFalse(narrowed.typed_range(CUBE))
        self.assertEqual(narrowed.with_fixed({}).sizes[name]["max"], 27.0)
        kept = sizes_for_checks(narrowed, self.params)[0]
        self.assertEqual((kept["min"], kept["max"], kept["typed_max"]), (9.0, 27.0, False))
        rows, _ = plan.probe_rows([dict(kept, value=18.0)], {CUBE: 27.0}, {CUBE})
        self.assertEqual([r["name"] for r in rows], ["%s (min)" % name])

    def test_a_typed_range_counts_as_typed_and_the_default_does_not(self):
        table = size_table.build(self.params, [CUBE], ranges={CUBE: (9.0, 40.0)})
        kept = sizes_for_checks(table, self.params)[0]
        self.assertEqual((kept["typed_min"], kept["typed_max"]), (False, True))


class NarrowedPackageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.part = os.path.join(tmp.name, "part.step")
        with open(self.part, "wb") as f:
            f.write(b"ISO-10303-21;")
        original = recipe_export.translate
        recipe_export.translate = lambda capture, size_table=None: TranslateResult(recipe={
            "schema": "paramability.recipe", "version": 13, "sizesAsWritten": True,
            "sizes": {"wall": {"value": 1.25, "min": 0.625, "max": 1.87}},
            "features": [{"id": "extrude_1", "kind": "extrude"}]})
        self.addCleanup(setattr, recipe_export, "translate", original)
        self.table = size_table.build([dict(name="wall", expression="1.25 mm", value=0.125, unit="mm", comment="",
                                            is_favorite=True, kind="length")], ["wall"])

    def plan(self, narrowed):
        checks = [{"size": "wall", "value": 1.87, "step_file": self.part}]
        return plan_single_export(load_capture("extrude_plate"), self.part, "Box", "w", "z", size_table=self.table,
                                  checks=checks, narrowed=narrowed)

    def test_the_note_and_the_report_name_a_narrowed_size_the_recipe_keeps(self):
        narrowed = [{"size": "wall", "side": "max", "from": 2.5, "to": 1.87, "note": "Wall: the range ends at 1.87."}]
        manifest, _, report = self.plan(narrowed)
        self.assertIn("Wall: the range ends at 1.87.", manifest["notes"])
        self.assertEqual(report["sizes"]["narrowed"], narrowed)
        view = result_view("box.paramability", manifest, report, self.table, ["wall"])
        self.assertEqual(view["narrowed"], ["Wall: the range ends at 1.87."])

    def test_a_narrowed_size_the_recipe_does_not_keep_is_not_mentioned(self):
        manifest, _, report = self.plan([{"size": "gone", "note": "Gone: the range ends."}])
        self.assertNotIn("narrowed", report["sizes"])
        self.assertFalse([n for n in manifest["notes"] if n.startswith("Gone")])

    def test_notes_stay_within_the_manifest_limit(self):
        narrowed = [{"size": "wall", "note": "n%d" % i} for i in range(3)]
        manifest, _, _ = plan_single_export(
            load_capture("extrude_plate"), self.part, "Box", "w", "z", size_table=self.table, narrowed=narrowed,
            unchecked=["a"], fixed=[{"name": "b", "reason": "x"}])
        self.assertLessEqual(len(manifest["notes"]), 5)


if __name__ == "__main__":
    unittest.main()
