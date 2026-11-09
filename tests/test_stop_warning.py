import unittest

from tests import context  # noqa: F401
from tests.test_recipe_export import plate_then_emboss
from tests.translator_helpers import load_capture

from lib.export_plan.stop_warning import saved_message, status_text, summarize


class SummarizeTest(unittest.TestCase):
    def test_a_part_that_copies_cleanly_has_nothing_to_warn_about(self):
        self.assertIsNone(summarize(load_capture("extrude_plate")))

    def test_nothing_picked_gives_no_warning(self):
        self.assertIsNone(summarize(None))

    def test_the_stopping_step_is_named_with_its_type_in_plain_words(self):
        summary = summarize(plate_then_emboss())
        self.assertTrue(summary["stops"])
        self.assertEqual(summary["label"], "Emboss1 (emboss)")
        self.assertEqual(summary["index"], 2)
        self.assertEqual(summary["lines"][0], "Copy stops at Emboss1 (emboss).")
        self.assertEqual(summary["lines"][-1],
                         "The part will be saved as a fixed shape; your parameters still come along as variables.")
        self.assertIn("Emboss steps", summary["tooltip"])

    def test_a_design_without_parameters_does_not_promise_variables(self):
        summary = summarize(plate_then_emboss(), has_parameters=False)
        self.assertEqual(summary["lines"][-1], "The part will be saved as a fixed shape.")

    def test_a_read_that_failed_says_the_steps_could_not_be_read(self):
        summary = summarize(RuntimeError("boom"))
        self.assertEqual(summary["lines"][0], "The steps could not be read.")
        self.assertIsNone(summary["index"])

    def test_a_stop_without_a_step_has_nothing_to_point_at(self):
        capture = load_capture("component_moved")
        capture["target"]["placement"]["linked"] = True
        summary = summarize(capture)
        self.assertTrue(summary["stops"])
        self.assertIsNone(summary["index"])
        self.assertEqual(summary["lines"][0], "The part cannot be copied.")

    def test_steps_copied_with_a_note_are_listed_in_one_line(self):
        summary = summarize(load_capture("fillet_setback"))
        self.assertFalse(summary["stops"])
        self.assertEqual(len(summary["lines"]), 1)
        self.assertTrue(summary["lines"][0].startswith("Copied with a note: "))
        self.assertTrue(summary["tooltip"])

    def test_notes_are_listed_after_a_stop_too(self):
        capture = load_capture("fillet_setback")
        capture["items"].append({"index": 99, "name": "Emboss1", "type": "EmbossFeature", "suppressed": False,
                                 "health": "ok", "message": "", "in_target_component": True,
                                 "bodies_after": capture["items"][-1]["bodies_after"], "data": {}})
        lines = summarize(capture)["lines"]
        self.assertEqual(lines[0], "Copy stops at Emboss1 (emboss).")
        self.assertTrue(lines[-1].startswith("Copied with a note: "))


class AfterExportTest(unittest.TestCase):
    refusal = {"index": 9, "name": "Extrude9", "type": "ExtrudeFeature", "reason": "Thin extrudes are not copied yet."}
    manifest = {"kind": "stepOnly", "notes": ["x"], "parameters": [{}]}

    def test_the_message_starts_with_the_stopping_step(self):
        text = saved_message(self.manifest, {"refusal": self.refusal}, "box.paramability")
        self.assertEqual(text.split("\n")[0], "Saved box.paramability. Copy stopped at Extrude9 (extrude).")
        self.assertIn("Thin extrudes are not copied yet.", text)
        self.assertIn("Your parameters still come along as variables.", text)

    def test_a_recipe_keeps_the_usual_message(self):
        manifest = {"kind": "recipe", "notes": ["3 steps copied from Fusion."]}
        self.assertEqual(saved_message(manifest, {}, "a.paramability"), "Saved a.paramability. 3 steps copied from Fusion.")

    def test_the_status_line_names_the_step_only_for_a_fixed_shape(self):
        self.assertEqual(status_text({"outcome": "stepOnly", "refusal": self.refusal}),
                         "Paramability: saved as a fixed shape. Copy stopped at Extrude9 (extrude).")
        self.assertEqual(status_text({"outcome": "recipe"}), "")
