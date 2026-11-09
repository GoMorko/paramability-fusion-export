import unittest

from tests import context  # noqa: F401
from tests import fakes
from lib.export_plan.result_rows import result_view
from lib.params import size_table

fakes.install_adsk_core()
from lib.fusion_ui import result_dialog  # noqa: E402


def length(name):
    return dict(name=name, expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length")


def view(manifest=None, plain=False, **sizes):
    params = [length(n) for n in ("wall", "gap", "pipe", "spare")]
    table = size_table.build(params, ["wall", "gap", "pipe"])
    report = {"sizes": {"free": ["wall"], "fixed": [], "checks": [], "unchecked": [], "dropped": [], **sizes}}
    if plain:
        report["check_sizes"] = False
    manifest = manifest or {"kind": "recipe", "notes": ["12 steps copied."], "parameters": [{}, {}, {}, {}]}
    return result_view("box.paramability", manifest, report, table, ["wall", "gap", "pipe"])


class ResultViewTest(unittest.TestCase):
    def test_a_checked_size_shows_its_range_and_that_it_matches(self):
        shown = view()
        self.assertEqual(shown["rows"][0], {"name": "wall", "range": "1 to 4 mm", "check": "matches Fusion"})
        self.assertEqual(shown["size_title"], "1 size ready for the form")
        self.assertEqual(shown["saved"], "Saved box.paramability. 12 steps copied.")
        self.assertEqual(shown["variables"], "All 4 parameters come along as variables, with their formulas and comments.")

    def test_unchecked_fixed_and_unused_ticks_each_get_a_row_and_a_reason(self):
        shown = view(unchecked=["wall"], fixed=[{"name": "gap", "reason": "gap stays fixed: no build."}],
                     dropped=["pipe"])
        self.assertEqual([(r["name"], r["check"]) for r in shown["rows"]],
                         [("wall", "not checked"), ("gap", "kept fixed"), ("pipe", "not used")])
        self.assertEqual(shown["fixed"], ["gap: gap stays fixed: no build."])

    def test_a_loose_size_is_marked_and_listed_with_its_reason(self):
        shown = view(loose=[{"name": "wall", "reason": "wall may give unexpected results: it moves a joint."}])
        self.assertEqual(shown["rows"][0]["check"], "may be unexpected")
        self.assertEqual(shown["loose"], ["wall: wall may give unexpected results: it moves a joint."])

    def test_a_plain_export_says_size_or_may_be_unexpected_instead_of_a_check_result(self):
        shown = view(plain=True, free=["wall", "gap"],
                     loose=[{"name": "gap", "reason": "gap may give unexpected results: it moves a joint."}])
        self.assertEqual([(r["name"], r["check"]) for r in shown["rows"][:2]],
                         [("wall", "size"), ("gap", "may be unexpected")])
        self.assertEqual(shown["check_header"], "In Paramability")
        self.assertEqual(view()["check_header"], "Check")

    def test_a_raised_smallest_value_shows_in_the_range(self):
        shown = view(raised=[{"name": "wall", "min": 1.5, "reason": "wall starts at 1.5: ..."}])
        self.assertEqual(shown["rows"][0]["range"], "1.5 to 4 mm")

    def test_a_long_fixed_list_is_cut_and_points_to_the_report(self):
        fixed = [{"name": "p%d" % i, "reason": "r"} for i in range(8)]
        self.assertEqual(view(fixed=fixed)["fixed"][-1], "and 3 more (see report.json).")

    def test_a_part_without_a_recipe_has_no_result_dialog(self):
        self.assertIsNone(view({"kind": "stepOnly", "notes": ["x"]}))


class ResultDialogTest(unittest.TestCase):
    def test_the_dialog_lists_the_rows_and_has_only_a_close_button(self):
        command = fakes.FakeCommand()
        shown = view(fixed=[{"name": "gap", "reason": "why"}], dropped=["pipe"])
        result_dialog.build(command, shown)
        inputs = command.commandInputs
        self.assertFalse(command.isOKButtonVisible)
        self.assertEqual(command.cancelButtonText, "Close")
        self.assertEqual(inputs.itemById("pm_result_table").rowCount, 1 + len(shown["rows"]))
        self.assertIn("gap: why", inputs.itemById("pm_result_fixed_text").formattedText)
        loose = view(loose=[{"name": "wall", "reason": "doubt"}])
        result_dialog.build(fakes.FakeCommand(), loose)
        command = fakes.FakeCommand()
        result_dialog.build(command, loose)
        self.assertIn("wall: doubt", command.commandInputs.itemById("pm_result_loose_text").formattedText)
        self.assertIn("4 parameters", inputs.itemById("pm_result_variables").formattedText)


if __name__ == "__main__":
    unittest.main()
