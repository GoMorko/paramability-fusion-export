"""The reason a tool body cannot be copied (`design_model.words.ToolStop`, `tool_walk.cannot_copy`): it names the step
that stops the tool once, also when the step is a Combine whose own tool cannot be built."""
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.design_model.words import ToolStop
from lib import orca_translate
from lib.translator import translate
from lib.translator.combine import tool_walk
from lib.translator.handlers import HANDLERS
from lib.translator.result import Refusal


class ToolStopTest(unittest.TestCase):
    def test_a_step_that_stops_the_tool_is_named_with_its_reason(self):
        stop = ToolStop.through("Body2", "Sweep1", "Surface sweeps are not copied.")
        self.assertEqual((stop.tool, stop.step, stop.inside), ("Body2", "Sweep1", None))
        self.assertEqual(stop.reason.count("Sweep1"), 1)

    def test_a_tool_of_a_tool_names_the_step_that_really_stops_it_once(self):
        inner = ToolStop.through("Body3", "Sweep2", "Surface sweeps are not copied.")
        outer = ToolStop.through("Body2", "Cut1", inner.reason, inner)
        self.assertEqual((outer.tool, outer.step, outer.inside), ("Body2", "Sweep2", "Body3"))
        self.assertEqual(outer.reason.count("Sweep2"), 1)
        self.assertNotIn("Cut1", outer.reason)

    def test_three_levels_still_name_the_innermost_step_and_its_tool(self):
        first = ToolStop.through("Body4", "Sweep3", "Surface sweeps are not copied.")
        second = ToolStop.through("Body3", "Cut2", first.reason, first)
        third = ToolStop.through("Body2", "Cut1", second.reason, second)
        self.assertEqual((third.step, third.inside), ("Sweep3", "Body4"))
        self.assertEqual(third.reason.count("Sweep3"), 1)
        self.assertNotIn("Cut", third.reason)

    def test_a_step_without_a_name_is_still_a_sentence(self):
        stop = ToolStop.through("Body2", None, "This step could not be read from Fusion.")
        self.assertEqual((stop.tool, stop.step, stop.inside), ("Body2", "", None))


class CannotCopyTest(unittest.TestCase):
    def test_the_refusal_keeps_the_cause_of_the_step_and_its_stop(self):
        item = {"name": "Sweep1", "type": "SweepFeature"}
        refusal = tool_walk.cannot_copy({"token": "t2", "name": "Body2"}, item, "Surface sweeps are not copied.",
                                        gap_hints.UNSUPPORTED)
        self.assertEqual(refusal.cause, gap_hints.UNSUPPORTED)
        self.assertEqual((refusal.stop.tool, refusal.stop.step), ("Body2", "Sweep1"))

    def test_a_combine_step_that_stopped_for_its_own_tool_hands_its_stop_on(self):
        inner = tool_walk.cannot_copy({"token": "t3", "name": "Body3"}, {"name": "Sweep2"}, "Not copied.")
        outer = tool_walk.cannot_copy({"token": "t2", "name": "Body2"}, {"name": "Cut1"}, inner.reason, None,
                                      inner.stop)
        self.assertEqual((outer.stop.step, outer.stop.inside), ("Sweep2", "Body3"))
        self.assertNotIn("Cut1", outer.reason)


class ToolOfAToolTest(unittest.TestCase):
    def test_the_gap_of_a_tool_that_a_tool_stops_names_the_step_that_really_stops_it_and_keeps_its_cause(self):
        """The round stops the walk of the inner tool, and the inner Combine stops the walk of the outer tool (as a
        Combine does inside a tool of another component): the outer tool names the round, not the inner Combine."""
        real = HANDLERS["CombineFeature"]

        def combine(ctx, step):
            made = real(ctx, step)
            if isinstance(made, Refusal) and ctx.outer is not None:
                made.stops = True
            return made

        def round_(ctx, step):
            return Refusal("This round is not copied.", cause=gap_hints.ROUND_KIND, stops=ctx.outer is not None)

        result = translate(load_capture("combine_in_tool"), {"CombineFeature": combine, "FilletFeature": round_})
        gap = result.gaps[0]
        self.assertEqual(gap["name"], "Combine2")
        self.assertEqual(gap["reason"].count("Fillet1"), 1)
        self.assertNotIn("Combine1", gap["reason"])
        self.assertEqual(gap.get("hint"), gap_hints.hint(gap_hints.ROUND_KIND))


class OrcaToolOfAToolTest(unittest.TestCase):
    def test_the_step_of_the_inner_tool_that_has_no_copy_is_named_once_with_its_cause(self):
        capture = load_capture("combine_in_tool")
        next(i for i in capture["items"] if i["name"] == "Fillet1")["type"] = "CoilFeature"
        gap = orca_translate.translate(capture, None).left_out[0]
        self.assertEqual(gap["reason"].count("Fillet1"), 1)
        self.assertNotIn("Combine1", gap["reason"])
        self.assertEqual(gap["cause"], gap_hints.UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
