"""One shape for the answer of both outputs: the verdict of each timeline item, the record of a step left out, the
sentence of a shared problem, and the tips and the preview that read the records."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.capture_model.gap_hints import hint as gap_hint
from lib.capture_model.step_kinds import step_type
from lib.design_model import verdicts, words
from lib.design_model.paths import words as path_words
from lib.dialog_model import left_out_preview, orca_result
from lib.dialog_model.result_rows import section_lines
from lib.export_plan.recipe_export import translate_capture
from lib.orca_translate import causes, translate as orca_translate

VERDICT_KEYS = {"index", "name", "type", "verdict", "note"}
LEFT_OUT_KEYS = {"name", "type", "reason"}


def with_thicken(name="filter_tray_sized"):
    """A body whose shell step is a type neither output copies."""
    capture = load_capture(name)
    capture["items"][2]["type"] = "ThickenFeature"
    return capture


class RecordShapeTest(unittest.TestCase):
    def test_both_outputs_give_a_verdict_with_the_same_keys(self):
        capture = with_thicken()
        recipe = translate_capture(capture, "z")
        orca = orca_translate(capture)
        for item in list(recipe.items) + list(orca.items):
            self.assertTrue(VERDICT_KEYS <= set(item), item)

    def test_both_outputs_say_the_same_for_a_step_left_out_of_both(self):
        capture = with_thicken()
        gap = translate_capture(capture, "z").gaps[0]
        record = orca_translate(capture).left_out[0]
        self.assertTrue(LEFT_OUT_KEYS <= set(gap) and LEFT_OUT_KEYS <= set(record))
        for key in ("name", "type", "reason"):
            self.assertEqual(gap[key], record[key])
        self.assertEqual(record["hint"], gap_hint(gap_hints.SURFACE))
        self.assertEqual(gap["hint"], record["hint"])

    def test_the_name_of_an_unnamed_step_is_its_type_in_words(self):
        record = verdicts.left_out({"name": "  ", "type": "ThickenFeature"}, "Because.")
        self.assertEqual(record["name"], step_type("ThickenFeature").words)

    def test_a_record_has_a_hint_only_when_one_is_given(self):
        self.assertNotIn("hint", verdicts.left_out({"name": "A", "type": "X"}, "Because."))
        self.assertEqual(verdicts.left_out({"name": "A", "type": "X"}, "Because.", "Do this.")["hint"], "Do this.")


class SharedSentenceTest(unittest.TestCase):
    def test_orca_shows_the_sentence_of_the_shared_reader(self):
        capture = load_capture("extrude_to_tilted")
        gap = translate_capture(capture, "z").gaps[0]
        record = orca_translate(capture).left_out[0]
        self.assertEqual(record["reason"], gap["reason"])
        self.assertEqual(record["cause"], gap_hints.EXTRUDE_END_FACE)

    def test_a_shared_sentence_names_no_output_and_promises_nothing(self):
        for module in (words, path_words):
            for name, text in vars(module).items():
                if name.isupper() and isinstance(text, str) and " " in text:
                    with self.subTest(name):
                        for banned in ("Orca", "Paramability", " yet"):
                            self.assertNotIn(banned, text)


class OrcaTipTest(unittest.TestCase):
    def test_a_cause_that_fits_orca_gives_its_tip(self):
        self.assertEqual(causes.tip(gap_hints.SURFACE), gap_hint(gap_hints.SURFACE))

    def test_a_tip_about_the_app_is_not_shown_for_orca(self):
        for cause in (gap_hints.COIL, gap_hints.THREAD_LIMITS, gap_hints.CHANGED_FROM_OTHER_COMPONENT):
            self.assertIsNone(causes.tip(cause))

    def test_no_tip_shown_for_orca_names_the_app(self):
        shown = [causes.tip(cause) for cause in gap_hints.HINTS if causes.tip(cause)]
        self.assertTrue(shown)
        for text in shown:
            self.assertNotIn("assistant", text.lower())
            self.assertNotIn("parts together", text.lower())

    def test_a_cause_of_orca_alone_has_no_tip(self):
        self.assertIsNone(causes.tip(causes.TAPER_SHAPE))


class OrcaPreviewTest(unittest.TestCase):
    def test_the_preview_lists_the_steps_the_orca_copy_leaves_out(self):
        capture = with_thicken()
        result = orca_translate(capture)
        found = left_out_preview.find_orca(result)
        self.assertEqual([step["index"] for step in found.steps], [r["index"] for r in result.left_out])
        self.assertFalse(found.waits_for_faces)
        summary = orca_result.preview(capture)
        self.assertFalse(summary["stops"])
        self.assertEqual([s["name"] for s in summary["left_out"]], [r["name"] for r in result.left_out])
        self.assertIn(left_out_preview.step_text(found.steps[0]), summary["lines"])

    def test_nothing_is_shown_when_nothing_is_left_out(self):
        self.assertIsNone(orca_result.preview(load_capture("extrude_plate")))

    def test_nothing_is_shown_when_the_steps_were_not_read(self):
        self.assertIsNone(orca_result.preview(RuntimeError("no steps")))

    def test_the_result_window_shows_the_tip_of_a_left_out_step(self):
        report = {"orca": {"left_out": [{"index": 2, "name": "Shell1", "type": "ThickenFeature", "reason": "Nope.",
                                         "hint": "Do this."}]}}
        lines = section_lines(orca_result.orca_view("a.3mf", report), "left_out")
        self.assertEqual(lines[0], "Shell1: Nope. Tip: Do this.")


if __name__ == "__main__":
    unittest.main()
