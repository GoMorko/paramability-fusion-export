import unittest

from tests import context  # noqa: F401
from tests.test_recipe_export import coil_then_plate
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.capture_model.gap_hints import hint as gap_hint
from lib.dialog_model.left_out_preview import MORE_MAY_SHOW
from lib.dialog_model.stop_warning import saved_message, status_text, summarize, summarize_many
from lib.export_plan.messages import left_out_line, left_out_lines
from lib.export_plan.recipe_export import translate_capture


class SummarizeManyTest(unittest.TestCase):
    def test_only_the_bodies_that_stop_are_named_and_one_line_says_what_happens_to_them(self):
        summary = summarize_many([("Tray", load_capture("extrude_plate")), ("Cover", coil_then_plate())])
        self.assertTrue(summary["stops"])
        self.assertEqual(summary["index"], 2)
        self.assertTrue(summary["lines"][0].startswith("Cover: "))
        self.assertIn("Coil1", summary["lines"][0])
        self.assertFalse(any(line.startswith("Tray") for line in summary["lines"]))
        self.assertIn("fixed shapes", summary["lines"][-1])
        self.assertIn("Cover: ", summary["tooltip"])

    def test_bodies_that_copy_cleanly_have_nothing_to_warn_about(self):
        clean = load_capture("extrude_plate")
        self.assertIsNone(summarize_many([("A", clean), ("B", clean)]))

    def test_a_body_that_could_not_be_read_stops_the_copy_of_that_body_only(self):
        summary = summarize_many([("A", RuntimeError("boom")), ("B", load_capture("extrude_plate"))])
        self.assertTrue(summary["stops"])
        self.assertIsNone(summary["index"])
        self.assertTrue(summary["lines"][0].startswith("A: "))


class SummarizeTest(unittest.TestCase):
    def test_a_part_that_copies_cleanly_or_is_not_picked_has_nothing_to_warn_about(self):
        self.assertIsNone(summarize(load_capture("extrude_plate")))
        self.assertIsNone(summarize(None))

    def test_the_stopping_step_is_named_and_the_variables_promise_follows_the_parameters(self):
        summary = summarize(coil_then_plate())
        self.assertTrue(summary["stops"])
        self.assertEqual(summary["label"], "Coil1 (thicken)")
        self.assertEqual(summary["index"], 2)
        self.assertIn("Coil1", summary["lines"][0])
        self.assertIn("variables", summary["lines"][-1])
        self.assertIn("Steps of type thicken", summary["tooltip"])
        self.assertNotIn("variables", summarize(coil_then_plate(), has_parameters=False)["lines"][-1])

    def test_a_stop_without_a_step_has_nothing_to_point_at(self):
        linked = load_capture("component_moved")
        linked["target"]["placement"]["linked"] = True
        for name, capture in (("read failed", RuntimeError("boom")), ("linked part", linked)):
            with self.subTest(name):
                summary = summarize(capture)
                self.assertTrue(summary["stops"])
                self.assertIsNone(summary["index"])

    def test_steps_copied_with_a_note_are_listed_in_one_line(self):
        summary = summarize(load_capture("fillet_setback"))
        self.assertFalse(summary["stops"])
        self.assertEqual(len(summary["lines"]), 1)
        self.assertTrue(summary["lines"][0].startswith("Copied with a note: "))
        self.assertTrue(summary["tooltip"])

    def test_notes_are_listed_after_a_stop_too(self):
        capture = load_capture("fillet_setback")
        capture["items"].append({"index": 99, "name": "Coil1", "type": "ThickenFeature", "suppressed": False,
                                 "health": "error", "message": "", "in_target_component": True,
                                 "bodies_after": capture["items"][-1]["bodies_after"], "data": {}})
        lines = summarize(capture)["lines"]
        self.assertIn("Coil1", lines[0])
        self.assertTrue(lines[-1].startswith("Copied with a note: "))


def tray_with_gaps(count=1):
    """The tray whose shell is a thicken, and a fillet after it that picks edges of the shell. `count` more steps
    that cannot be copied are added before the fillet."""
    capture = load_capture("filter_tray_sized")
    capture["items"][2]["type"] = "ThickenFeature"
    for n in range(count - 1):
        extra = {**capture["items"][2], "index": 50 + n, "name": "Coil%d" % (n + 2)}
        capture["items"].insert(3, extra)
    return capture


class LeftOutTest(unittest.TestCase):
    def test_a_left_out_step_is_named_with_reason_and_hint_and_the_step_picking_its_faces_is_not(self):
        summary = summarize(tray_with_gaps())
        self.assertFalse(summary["stops"])
        self.assertEqual(summary["lines"][0], "Likely left out of the copy:")
        self.assertEqual(summary["lines"][1], left_out_line("Shell1", "Steps of type thicken are not copied yet.",
                                                            gap_hint(gap_hints.SURFACE)))
        self.assertEqual([step["name"] for step in summary["left_out"]], ["Shell1"])
        self.assertIn(summary["lines"][1], summary["tooltip"])

    def test_the_line_of_a_step_reads_the_same_as_in_the_result_window_after_the_export(self):
        capture = load_capture("fillet_variable")
        record = translate_capture(capture, "z").gaps[0]
        self.assertEqual(summarize(capture)["lines"][1], left_out_lines([(None, record)])[0])

    def test_a_step_without_a_hint_has_no_tip(self):
        self.assertNotIn("Tip", summarize(load_capture("fillet_g2"))["lines"][1])

    def test_the_export_may_find_more_steps_only_when_a_later_step_waits_for_the_face_read(self):
        self.assertTrue(summarize(tray_with_gaps())["more_may_show"])
        self.assertEqual(summarize(tray_with_gaps())["lines"][-1], MORE_MAY_SHOW)
        alone = summarize(load_capture("fillet_g2"))
        self.assertFalse(alone["more_may_show"])
        self.assertNotIn(MORE_MAY_SHOW, alone["lines"])

    def test_a_long_list_shows_a_few_steps_counts_the_rest_and_says_more_may_show_once(self):
        summary = summarize(tray_with_gaps(5))
        self.assertEqual(len(summary["left_out"]), 5)
        self.assertEqual(summary["lines"][-2:], ["and 2 more.", MORE_MAY_SHOW])
        self.assertEqual(len(summary["lines"]), 6)

    def test_a_copy_that_stops_lists_no_left_out_steps_and_gives_the_hint_of_the_stop(self):
        stopped = summarize(coil_then_plate())
        self.assertEqual(stopped["left_out"], [])
        self.assertFalse(stopped["more_may_show"])
        self.assertEqual(stopped["hint"], gap_hint(gap_hints.SURFACE))
        self.assertIn("Tip: " + stopped["hint"], stopped["lines"])
        self.assertLess(stopped["lines"].index("Tip: " + stopped["hint"]), len(stopped["lines"]) - 1)
        self.assertIn("Tip: " + stopped["hint"], stopped["tooltip"])

    def test_a_stop_without_a_hint_has_no_tip_line(self):
        stopped = summarize(load_capture("revolve_two_sides"))
        self.assertEqual(stopped["hint"], "")
        self.assertFalse(any(line.startswith("Tip") for line in stopped["lines"]))

    def test_a_part_with_nothing_left_out_has_no_such_lines(self):
        self.assertEqual(summarize(load_capture("fillet_setback"))["left_out"], [])

    def test_a_step_that_reaches_into_another_component_is_listed_with_the_hint_for_it(self):
        summary = summarize(load_capture("component_foreign_extent"))
        self.assertEqual(summary["left_out"][0]["hint"], gap_hint(gap_hints.OTHER_COMPONENT))
        self.assertIn("Tip: " + gap_hint(gap_hints.OTHER_COMPONENT), summary["lines"][1])

    def test_with_several_bodies_the_steps_are_listed_under_the_name_of_their_body(self):
        summary = summarize_many([("Tray", tray_with_gaps()), ("Plate", load_capture("extrude_plate"))])
        self.assertFalse(summary["stops"])
        self.assertEqual(summary["lines"][0], "Tray: likely left out of the copy:")
        self.assertTrue(summary["lines"][1].startswith("Shell1: "))
        self.assertFalse(any("Plate" in line for line in summary["lines"]))

    def test_with_several_bodies_more_may_show_is_said_once_and_a_stop_keeps_its_hint(self):
        summary = summarize_many([("Tray", tray_with_gaps()), ("Lid", tray_with_gaps()), ("Cover", coil_then_plate())])
        self.assertEqual(summary["lines"].count(MORE_MAY_SHOW), 1)
        self.assertIn("Tip: " + gap_hint(gap_hints.SURFACE), summary["lines"])
        self.assertIn("fixed shapes", summary["lines"][-1])


class AfterExportTest(unittest.TestCase):
    refusal = {"index": 9, "name": "Extrude9", "type": "ExtrudeFeature", "reason": "Thin extrudes are not copied yet."}
    manifest = {"kind": "stepOnly", "notes": ["x"], "parameters": [{}]}

    def test_a_fixed_shape_message_names_the_stopping_step_and_the_status_line_follows(self):
        text = saved_message(self.manifest, {"refusal": self.refusal}, "box.paramability")
        self.assertIn("Extrude9 (extrude)", text.split("\n")[0])
        self.assertIn("Thin extrudes are not copied yet.", text)
        self.assertIn("parameters still come along", text)
        self.assertIn("Extrude9 (extrude)", status_text({"outcome": "stepOnly", "refusal": self.refusal}))

    def test_a_recipe_keeps_the_usual_message_and_no_status_line(self):
        manifest = {"kind": "recipe", "notes": ["3 steps copied from Fusion."]}
        self.assertIn("3 steps copied from Fusion.", saved_message(manifest, {}, "a.paramability"))
        self.assertEqual(status_text({"outcome": "recipe"}), "")


if __name__ == "__main__":
    unittest.main()
