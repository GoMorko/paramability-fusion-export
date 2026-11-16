import ast
import os
import unittest

from tests import context
from tests.test_translate_gaps import FILLET, HOLE, SHELL, tray, unsupported
from lib.capture_model import gap_hints, step_kinds
from lib.translator import translate

# The translator gives the causes of its own refusals and of the problems of the shared layer it turns into refusals.
CAUSE_DIRS = [os.path.join(context.ADDIN_DIR, "lib", name) for name in ("translator", "design_model")]
NO_HINT = {gap_hints.REFUSED, gap_hints.UNSUPPORTED}


def _named_causes():
    """The causes the translator gives: every `gap_hints.NAME` it reads, and the causes of the step kind table (a step type's gap cause, a recipe kind's tool cause)."""
    found = {spec.gap_cause for spec in step_kinds.STEP_TYPES if spec.gap_cause}
    found |= {kind.tool_cause for kind in step_kinds.RECIPE_KINDS if kind.tool_cause}
    paths = sorted(os.path.join(folder, name) for root in CAUSE_DIRS for folder, _, names in os.walk(root)
                   for name in names)
    for path in paths:
        if not path.endswith(".py") or os.path.basename(path) == "gap_hints.py":
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "gap_hints" and node.attr.isupper()):
                found.add(getattr(gap_hints, node.attr))
    return found


def hint_of(result, name):
    return next(gap for gap in result.gaps if gap["name"] == name).get("hint")


class HintTableTest(unittest.TestCase):
    def test_every_cause_the_translator_gives_has_a_hint_and_every_hint_is_given(self):
        named = _named_causes()
        self.assertEqual(named - NO_HINT, set(gap_hints.HINTS))

    def test_hints_are_short_plain_sentences(self):
        for cause, text in gap_hints.HINTS.items():
            with self.subTest(cause):
                self.assertLessEqual(len(text), 120)
                self.assertTrue(text[0].isupper() and text.endswith("."))
                self.assertFalse(any(dash in text for dash in ("–", "—")))


class GapHintTest(unittest.TestCase):
    def test_a_step_type_with_advice_and_the_step_that_picks_its_faces_get_their_hints(self):
        result = translate(tray(unsupported(SHELL)))
        self.assertEqual(hint_of(result, "Shell1"), gap_hints.HINTS[gap_hints.SURFACE])
        self.assertEqual(hint_of(result, "Fillet1"), gap_hints.HINTS[gap_hints.AFTER_GAP])

    def test_a_pattern_of_a_gap_gets_the_hint_to_fix_that_step_first(self):
        result = translate(tray(unsupported(HOLE)))
        self.assertEqual(hint_of(result, "RectangularPattern1"), gap_hints.HINTS[gap_hints.AFTER_GAP])

    def test_a_refusal_with_a_cause_gets_its_hint_and_one_without_gets_none(self):
        for change, expected in (({"bodies_input": True}, gap_hints.HINTS[gap_hints.SHELL_KIND]),
                                 ({"shell_type": "rounded"}, None)):
            with self.subTest(change=change):
                result = translate(tray(lambda c: c["items"][SHELL]["data"].update(change)))
                self.assertEqual(hint_of(result, "Shell1"), expected)
                self.assertEqual("hint" in result.gaps[0], expected is not None)

    def test_each_listed_kind_that_does_not_copy_gets_its_own_reason_and_hint(self):
        kinds = {"ScaleFeature": gap_hints.SCALE, "ReplaceFaceFeature": gap_hints.REPLACE_FACE,
                 "RibFeature": gap_hints.RIB_WEB, "WebFeature": gap_hints.RIB_WEB,
                 "PathPatternFeature": gap_hints.PATH_PATTERN, "BoundaryFillFeature": gap_hints.BOUNDARY_FILL}
        generic = translate(tray(unsupported(SHELL, "MadeUpFeature"))).gaps[0]["reason"]
        for type_name, cause in kinds.items():
            with self.subTest(type_name):
                gap = translate(tray(unsupported(SHELL, type_name))).gaps[0]
                self.assertEqual(gap["hint"], gap_hints.HINTS[cause])
                self.assertNotEqual(gap["reason"], generic)

    def test_a_step_type_without_advice_gets_no_hint(self):
        result = translate(tray(unsupported(SHELL, "MadeUpFeature")))
        self.assertIsNone(hint_of(result, "Shell1"))
        self.assertEqual(hint_of(result, "Fillet1"), gap_hints.HINTS[gap_hints.AFTER_GAP])


if __name__ == "__main__":
    unittest.main()
