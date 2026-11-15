import unittest

from tests import context  # noqa: F401
from tests.test_recipe_export import coil_then_plate
from tests.translator_helpers import load_capture

from lib.dialog_model.stop_warning import saved_message, status_text, summarize, summarize_many


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
    def test_a_stop_with_a_hint_shows_the_tip_before_the_fixed_shape_line(self):
        summary = summarize(load_capture("component_cross_cut"))
        self.assertTrue(summary["stops"])
        self.assertTrue(summary["lines"][-2].startswith("Tip: "))
        self.assertIn("export both parts together", summary["lines"][-2])

    def test_a_part_that_copies_cleanly_or_is_not_picked_has_nothing_to_warn_about(self):
        self.assertIsNone(summarize(load_capture("extrude_plate")))
        self.assertIsNone(summarize(None))

    def test_the_stopping_step_is_named_and_the_variables_promise_follows_the_parameters(self):
        summary = summarize(coil_then_plate())
        self.assertTrue(summary["stops"])
        self.assertEqual(summary["label"], "Coil1 (coil)")
        self.assertEqual(summary["index"], 2)
        self.assertIn("Coil1", summary["lines"][0])
        self.assertIn("variables", summary["lines"][-1])
        self.assertIn("Steps of type coil", summary["tooltip"])
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
        capture["items"].append({"index": 99, "name": "Coil1", "type": "CoilFeature", "suppressed": False,
                                 "health": "error", "message": "", "in_target_component": True,
                                 "bodies_after": capture["items"][-1]["bodies_after"], "data": {}})
        lines = summarize(capture)["lines"]
        self.assertIn("Coil1", lines[0])
        self.assertTrue(lines[-1].startswith("Copied with a note: "))


def tray_with_gaps(count=1):
    """The tray whose shell is a coil, and a fillet after it that picks edges of the shell. `count` more steps
    that cannot be copied are added before the fillet."""
    capture = load_capture("filter_tray_sized")
    capture["items"][2]["type"] = "CoilFeature"
    for n in range(count - 1):
        extra = {**capture["items"][2], "index": 50 + n, "name": "Coil%d" % (n + 2)}
        capture["items"].insert(3, extra)
    return capture


class LeftOutTest(unittest.TestCase):
    def test_a_step_the_copy_will_leave_out_is_named_with_its_reason_and_the_picking_step_after_it_is_not(self):
        summary = summarize(tray_with_gaps())
        self.assertFalse(summary["stops"])
        self.assertEqual(summary["lines"][0], "Likely left out of the copy:")
        self.assertTrue(summary["lines"][1].startswith("Shell1 (coil): "), summary["lines"])
        self.assertEqual(len(summary["lines"]), 2)
        self.assertEqual([label for label, _ in summary["left_out"]], ["Shell1 (coil)"])
        self.assertIn("Shell1 (coil): ", summary["tooltip"])

    def test_a_long_list_shows_a_few_steps_and_counts_the_rest(self):
        summary = summarize(tray_with_gaps(5))
        self.assertEqual(len(summary["left_out"]), 5)
        self.assertEqual(len(summary["lines"]), 5)
        self.assertEqual(summary["lines"][-1], "and 2 more.")

    def test_a_copy_that_stops_lists_no_left_out_steps(self):
        self.assertEqual(summarize(coil_then_plate())["left_out"], [])

    def test_a_part_with_nothing_left_out_has_no_such_lines(self):
        self.assertEqual(summarize(load_capture("fillet_setback"))["left_out"], [])

    def test_with_several_bodies_the_steps_are_listed_under_the_name_of_their_body(self):
        summary = summarize_many([("Tray", tray_with_gaps()), ("Plate", load_capture("extrude_plate"))])
        self.assertFalse(summary["stops"])
        self.assertEqual(summary["lines"][0], "Tray: likely left out of the copy:")
        self.assertTrue(summary["lines"][1].startswith("Shell1 (coil): "))
        self.assertFalse(any("Plate" in line for line in summary["lines"]))


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
