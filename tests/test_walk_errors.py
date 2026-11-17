"""An error of the add-in in one step's handling stops the copy at that step (lib/translator/walk.py)."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_floating import capture
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.translator import translate


def _raises(ctx, step):
    raise ZeroDivisionError("a bug in a handler")


class WalkErrorTest(unittest.TestCase):
    def test_a_handler_that_raises_stops_the_copy_at_its_step(self):
        # Extrude1, then Coil1 (whose handler raises), then Extrude2.
        result = translate(capture(join_z=10.0), handlers={"ThickenFeature": _raises})
        self.assertIsNone(result.recipe)
        self.assertEqual((result.refusal["index"], result.refusal_cause), (2, gap_hints.ADDIN_ERROR))
        self.assertEqual(result.refusal["hint"], gap_hints.hint(gap_hints.ADDIN_ERROR))
        self.assertEqual([(v["name"], v["verdict"]) for v in result.items],
                         [("Sketch1", "skipped"), ("Extrude1", "translated"), ("Coil1", "unsupported")])
        self.assertIn("ZeroDivisionError", result.error_trace)
        # The walk past the stop leaves the step out and goes on to the steps after it.
        self.assertEqual(result.after_stop["stopped_at"], 2)
        self.assertEqual([v["name"] for v in result.after_stop["items"]], ["Extrude2"])

    def test_a_handler_that_raises_in_a_tool_body_stops_the_copy_at_the_combine(self):
        result = translate(load_capture("combine_tool_filleted"), handlers={"FilletFeature": _raises})
        self.assertEqual((result.refusal["name"], result.refusal_cause), ("Combine1", gap_hints.ADDIN_ERROR))
        self.assertIn("ZeroDivisionError", result.error_trace)


if __name__ == "__main__":
    unittest.main()
