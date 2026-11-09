import unittest

from tests import context  # noqa: F401
from tests import fakes
from lib.dialog_model.result_rows import result_view
from lib.params import size_table

fakes.install_adsk_core()
from lib.fusion_ui import result_dialog  # noqa: E402


def length(name):
    return dict(name=name, expression="2 mm", value=0.2, unit="mm", comment="", is_favorite=True, kind="length")


def unused(name):
    return {"name": name, "reason": "%s is not used by any copied step, so it is not a size." % name, "used": False}


def not_followed(name):
    return {"name": name, "reason": "%s is not a size: Extrude1 reads it, and the copy does not follow it." % name,
            "used": True}


def view(manifest=None, health=None, **sizes):
    params = [length(n) for n in ("wall", "gap", "pipe", "spare")]
    table = size_table.build(params, ["wall", "gap", "pipe"])
    report = {"sizes": {"free": ["wall"], "fixed": [], "dropped": [], **sizes}}
    if health:
        report["health"] = health
    manifest = manifest or {"kind": "recipe", "notes": ["12 steps copied."], "parameters": [{}, {}, {}, {}]}
    return result_view("box.paramability", manifest, report, table, ["wall", "gap", "pipe"])


class ResultViewTest(unittest.TestCase):
    def test_a_size_shows_its_range_and_what_it_becomes(self):
        shown = view()
        self.assertEqual(shown["rows"][0], {"name": "wall", "range": "1 to 4 mm", "check": "size"})
        self.assertEqual(shown["size_title"], "1 size ready for the form")
        self.assertEqual(shown["saved"], "Saved box.paramability. 12 steps copied.")

    def test_fixed_and_unused_ticks_each_get_a_row_and_a_reason(self):
        shown = view(fixed=[{"name": "gap", "reason": "gap stays fixed: no build."}], dropped=[unused("pipe")])
        self.assertEqual([(r["name"], r["check"]) for r in shown["rows"]],
                         [("wall", "size"), ("gap", "kept fixed"), ("pipe", "not used")])
        self.assertEqual(shown["fixed"], ["gap stays fixed: no build."])
        self.assertEqual(shown["dropped"], [])

    def test_a_loose_size_is_marked_and_listed_with_its_reason(self):
        shown = view(loose=[{"name": "wall", "reason": "wall may give unexpected results: it moves a joint."}])
        self.assertEqual(shown["rows"][0]["check"], "may be unexpected")
        self.assertEqual(shown["loose"], ["wall may give unexpected results: it moves a joint."])

    def test_a_size_a_step_reads_but_the_copy_cannot_follow_is_not_called_unused(self):
        shown = view(dropped=[not_followed("gap"), unused("pipe")])
        self.assertEqual([(r["name"], r["check"]) for r in shown["rows"][1:]],
                         [("gap", "not followed"), ("pipe", "not used")])
        self.assertEqual(shown["dropped"], ["gap is not a size: Extrude1 reads it, and the copy does not follow it."])
        self.assertIn(shown["dropped"][0], shown["message"])

    def test_a_reason_that_does_not_start_with_the_name_gets_the_name_in_front(self):
        self.assertEqual(view(fixed=[{"name": "gap", "reason": "no build."}])["fixed"], ["gap: no build."])

    def test_a_design_that_did_not_come_back_is_said_in_the_warnings_and_the_message(self):
        health = {"unrestored": ["wall"], "sketch_gap_mm": 0.5, "sketch_drift": True, "probe": "measured"}
        shown = view(health=health)
        self.assertEqual(len(shown["warnings"]), 2)
        self.assertIn("Undo", shown["warnings"][0])
        self.assertIn(shown["warnings"][1], shown["message"])

    def test_sketches_that_could_not_be_measured_get_a_row_and_a_warning(self):
        shown = view(health={"unrestored": [], "sketch_gap_mm": None, "probe": "failed"})
        self.assertEqual(shown["rows"][-1]["check"], "not measured")
        self.assertEqual(len(shown["warnings"]), 1)
        self.assertEqual(view()["warnings"], [])

    def test_a_long_fixed_list_is_cut_and_points_to_the_report(self):
        fixed = [{"name": "p%d" % i, "reason": "r"} for i in range(8)]
        self.assertEqual(view(fixed=fixed)["fixed"][-1], "and 3 more (see report.json).")

    def test_a_part_without_a_recipe_has_no_result_dialog(self):
        self.assertIsNone(view({"kind": "stepOnly", "notes": ["x"]}))


class ResultDialogTest(unittest.TestCase):
    def test_the_dialog_lists_the_rows_and_has_only_a_close_button(self):
        command = fakes.FakeCommand()
        shown = view(fixed=[{"name": "gap", "reason": "why"}], dropped=[unused("pipe")])
        result_dialog.build(command, shown)
        inputs = command.commandInputs
        self.assertFalse(command.isOKButtonVisible)
        self.assertEqual(command.cancelButtonText, "Close")
        self.assertEqual(inputs.itemById("pm_result_table").rowCount, 1 + len(shown["rows"]))
        self.assertIn("gap: why", inputs.itemById("pm_result_fixed_text").formattedText)
        loose = view(loose=[{"name": "wall", "reason": "doubt"}])
        self.assertIn("4 parameters", inputs.itemById("pm_result_variables").formattedText)
        command = fakes.FakeCommand()
        result_dialog.build(command, loose)
        self.assertIn("wall: doubt", command.commandInputs.itemById("pm_result_loose_text").formattedText)

    def test_warnings_show_under_the_saved_text_only_when_there_are_some(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, dict(view(), warnings=["The sketch could not be tried."]))
        self.assertIn("could not be tried", command.commandInputs.itemById("pm_result_warnings_text").formattedText)
        quiet = fakes.FakeCommand()
        result_dialog.build(quiet, dict(view(), warnings=[]))
        self.assertIsNone(quiet.commandInputs.itemById("pm_result_warnings"))


if __name__ == "__main__":
    unittest.main()
