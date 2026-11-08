import re
import unittest

from tests import context  # noqa: F401

from lib.translator import notes


class NotesTest(unittest.TestCase):
    def test_recipe_note(self):
        self.assertEqual(notes.recipe_note(12), "12 steps copied from Fusion.")
        self.assertEqual(notes.recipe_note(1), "1 step copied from Fusion.")

    def test_names_the_first_unsupported_feature(self):
        refusal = {"index": 4, "name": "Emboss1", "type": "EmbossFeature", "reason": "Steps of type emboss are not copied yet."}
        self.assertEqual(
            notes.step_only_note(refusal),
            "Added as a fixed shape: Emboss1 (emboss) could not be copied. Steps of type emboss are not copied yet.")

    def test_type_words_are_split(self):
        refusal = {"index": 1, "name": "", "type": "RectangularPatternFeature", "reason": "No."}
        self.assertIn("rectangular pattern", notes.step_only_note(refusal))

    def test_long_fusion_name_is_cut_to_60(self):
        refusal = {"index": 1, "name": "N" * 100, "type": "FilletFeature", "reason": "No."}
        text = notes.step_only_note(refusal)
        self.assertIn("N" * 57 + "...", text)
        self.assertNotIn("N" * 58, text)

    def test_refusal_without_a_feature(self):
        refusal = {"index": None, "name": "", "type": "", "reason": "Nothing in the timeline makes this body."}
        self.assertEqual(
            notes.step_only_note(refusal),
            "Added as a fixed shape: the part could not be copied. Nothing in the timeline makes this body.")

    def test_every_note_is_short_and_free_of_dashes(self):
        refusal = {"index": 1, "name": ("A %s B %s C" % (chr(0x2014), chr(0x2013))) * 20, "type": "FilletFeature", "reason": "Because. " * 60}
        texts = [notes.step_only_note(refusal), notes.recipe_note(400), notes.reader_failure_note(),
                 notes.translate_failure_note()]
        for text in texts:
            self.assertLessEqual(len(text), notes.MAX_NOTE)
            self.assertIsNone(re.search("[%s%s]" % (chr(0x2013), chr(0x2014)), text))


if __name__ == "__main__":
    unittest.main()
