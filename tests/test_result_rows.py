import unittest

from tests import context  # noqa: F401
from tests import fakes
from lib.dialog_model.result_rows import result_view, section, section_lines
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


def view(manifest=None, health=None, extra=None, **sizes):
    params = [length(n) for n in ("wall", "gap", "pipe", "spare")]
    table = size_table.build(params, ["wall", "gap", "pipe"])
    report = {"sizes": {"free": ["wall"], "fixed": [], "dropped": [], **sizes}}
    if health:
        report["health"] = health
    report.update(extra or {})
    manifest = manifest or {"kind": "recipe", "notes": ["12 steps copied."], "parameters": [{}, {}, {}, {}]}
    return result_view("box.paramability", manifest, report, table, ["wall", "gap", "pipe", "spare"])


def keys(shown):
    return [s["key"] for s in shown["sections"]]


class ResultViewTest(unittest.TestCase):
    def test_a_plain_recipe_has_a_result_and_a_sizes_section_and_nothing_empty(self):
        shown = view()
        self.assertEqual(keys(shown), ["result", "sizes"])
        self.assertEqual(section_lines(shown, "sizes"), ["wall: 1 to 4 mm"])
        self.assertTrue(all(s["lines"] for s in shown["sections"]))

    def test_the_result_leads_with_the_file_and_what_to_do_next(self):
        lines = section_lines(view(), "result")
        self.assertIn("box.paramability", lines[0])
        self.assertIn("1 size", lines[0])
        self.assertEqual(len(lines), 3)

    def test_without_sizes_the_result_says_the_form_is_empty(self):
        shown = view(free=[])
        self.assertIn("empty", section_lines(shown, "result")[0])

    def test_every_size_is_one_line_with_its_state_and_reason_and_the_name_once(self):
        shown = view(
            free=["wall", "gap"],
            loose=[{"name": "wall", "reason": "wall may give unexpected results past 3: it moves a joint."}],
            fixed=[{"name": "pipe", "reason": "pipe stays fixed: no build."}],
            dropped=[unused("spare")])
        self.assertEqual(section_lines(shown, "sizes")[:3], [
            "gap: 1 to 4 mm",
            "wall: 1 to 4 mm, may be unexpected past 3 (it moves a joint)",
            "pipe: kept fixed (no build)"])
        names = [line.split(":")[0] for line in section_lines(shown, "sizes")]
        self.assertEqual(len(names), len(set(names)))

    def test_a_size_a_step_reads_but_the_copy_cannot_follow_is_not_called_unused(self):
        shown = view(dropped=[not_followed("gap"), unused("pipe")], free=[])
        rows = {r["name"]: r["check"] for r in section(shown, "sizes")["rows"]}
        self.assertEqual(rows, {"gap": "not followed", "pipe": "not used"})
        self.assertIn("Extrude1 reads it", section_lines(shown, "sizes")[0])
        self.assertIn(section_lines(shown, "sizes")[0], shown["message"])

    def test_a_reason_that_does_not_start_with_the_name_is_still_one_line_for_that_size(self):
        shown = view(free=[], fixed=[{"name": "gap", "reason": "no build."}])
        self.assertEqual(section_lines(shown, "sizes"), ["gap: kept fixed (no build)"])

    def test_a_part_tag_in_front_of_a_reason_stays_with_the_reason(self):
        shown = view(loose=[{"name": "wall", "reason": "Lid: wall may give unexpected results: it moves a joint."}])
        self.assertEqual(section_lines(shown, "sizes"), ["wall: 1 to 4 mm, may be unexpected (Lid: it moves a joint)"])

    def test_a_design_that_did_not_come_back_is_a_check_section_and_in_the_message(self):
        health = {"unrestored": ["wall"], "sketch_gap_mm": 0.5, "sketch_drift": True, "probe": "measured"}
        shown = view(health=health)
        self.assertEqual(keys(shown)[0], "check")
        lines = section_lines(shown, "check")
        self.assertEqual(len(lines), 2)
        self.assertIn("Undo", lines[0])
        self.assertIn(lines[1], shown["message"])

    def test_sketches_that_could_not_be_measured_get_a_row_and_a_warning(self):
        shown = view(health={"unrestored": [], "sketch_gap_mm": None, "probe": "failed"})
        self.assertEqual(section_lines(shown, "sizes")[-1], "Sketches: not measured")
        self.assertEqual(len(section_lines(shown, "check")), 1)
        self.assertNotIn("check", keys(view()))

    def test_steps_left_out_get_their_own_section_and_show_in_the_result_kind(self):
        shown = view(extra={"gaps": [{"name": "Extrude5", "reason": "No."}, {"name": "Draft1", "reason": "Steep.",
                                                                              "hint": "Use less."}]})
        self.assertEqual(section_lines(shown, "left_out")[:2], ["Extrude5: No.", "Draft1: Steep. Tip: Use less."])
        self.assertIn("left out", section_lines(shown, "result")[1])

    def test_a_formula_kept_as_a_number_gets_a_line_after_the_sizes(self):
        listed = [{"name": "odd", "label": "odd", "value": 5, "unit": "mm", "expression": "wall + 30 deg",
                   "untranslated": "It adds a length and an angle."}, {"name": "wall", "value": 2, "unit": "mm"}]
        manifest = {"kind": "recipe", "notes": [], "parameters": listed}
        self.assertEqual(section_lines(view(manifest), "sizes"), [
            "wall: 1 to 4 mm", "kept as a number: odd = wall + 30 deg (It adds a length and an angle)"])

    def test_parameters_that_also_change_the_part_are_in_a_more_sizes_section(self):
        shown = view(extra={"also_changes": ["spare"]})
        self.assertEqual(len(section_lines(shown, "more")), 1)
        self.assertIn("spare", section_lines(shown, "more")[0])

    def test_a_part_without_a_recipe_has_no_result_dialog(self):
        self.assertIsNone(view({"kind": "stepOnly", "notes": ["x"]}))


class ResultDialogTest(unittest.TestCase):
    def test_every_section_is_a_group_with_its_title_and_the_dialog_has_only_a_close_button(self):
        command = fakes.FakeCommand()
        shown = view(fixed=[{"name": "gap", "reason": "why"}], dropped=[unused("pipe")])
        result_dialog.build(command, shown)
        inputs = command.commandInputs
        self.assertFalse(command.isOKButtonVisible)
        self.assertEqual(command.cancelButtonText, "Close")
        for found in shown["sections"]:
            self.assertEqual(inputs.itemById("pm_group_" + found["key"]).name, found["title"])
            self.assertIsNotNone(inputs.itemById("pm_result_" + found["key"]))
        self.assertIn("gap: kept fixed (why)", inputs.itemById("pm_result_sizes").formattedText)

    def test_a_section_the_view_does_not_have_is_not_added(self):
        command = fakes.FakeCommand()
        result_dialog.build(command, view())
        self.assertIsNone(command.commandInputs.itemById("pm_result_check"))
        self.assertIsNone(command.commandInputs.itemById("pm_result_left_out"))


if __name__ == "__main__":
    unittest.main()
