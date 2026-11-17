"""A step that Fusion shows in error (translator/walk.py): passed by when the part stayed as it was, left out as a gap
when the part changed, a stop when the part could not be measured around it."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_gaps import FILLET, SHELL, tray
from tests.test_translate_sized import CUBE, H, TICKED, table_of
from tests.translator_helpers import steps_of, stopped, verdict_of

from lib.capture_model import gap_hints
from lib.sketch_values.motion import Motion
from lib.translator import translate


def in_error(index, changed):
    def edit(capture):
        capture["items"][index].update(health="error", target_changed=changed)
    return edit


class StepInErrorTest(unittest.TestCase):
    def test_a_step_in_error_that_left_the_part_as_it_was_is_passed_by_with_a_note(self):
        result = translate(tray(in_error(FILLET, False)))
        self.assertIsNone(stopped(result))
        self.assertEqual(result.gaps, [])
        self.assertEqual(steps_of(result.recipe, "fillet"), [])
        self.assertEqual(len(steps_of(result.recipe, "hole")), 1)
        verdict = verdict_of(result, FILLET)
        self.assertEqual(verdict["verdict"], "skipped")
        self.assertIn(verdict["note"], result.notes)

    def test_a_step_in_error_that_changed_the_part_is_a_gap_and_a_step_on_its_faces_comes_after_it(self):
        result = translate(tray(in_error(SHELL, True)))
        self.assertIsNone(stopped(result))
        hints = {gap["name"]: gap.get("hint") for gap in result.gaps}
        self.assertEqual(hints, {"Shell1": gap_hints.HINTS[gap_hints.FAILS_IN_FUSION],
                                 "Fillet1": gap_hints.HINTS[gap_hints.AFTER_GAP]})
        self.assertEqual(len(steps_of(result.recipe, "hole")), 1)

    def test_a_step_in_error_around_which_the_part_could_not_be_measured_stops_the_copy(self):
        result = translate(tray(in_error(SHELL, None)))
        self.assertEqual((stopped(result)["index"], result.recipe), (SHELL, None))
        self.assertEqual(result.refusal_cause, gap_hints.FAILS_IN_FUSION)


class UntriedSizesTest(unittest.TestCase):
    """A step passed by because it is in error may build at other sizes. Without a try of a size that may make it
    build, that size stays fixed; a size only later steps read stays free."""

    def outcome(self, motion=None):
        capture = tray(in_error(FILLET, False))
        result = translate(capture, size_table=table_of(capture, TICKED), motion=motion)
        return {f["name"] for f in result.fixed}, set(result.recipe.get("sizes") or {})

    def test_without_tries_the_sizes_of_the_steps_before_it_and_of_its_own_radius_are_fixed(self):
        fixed, free = self.outcome()
        self.assertEqual(fixed, {H, CUBE, "wall_mm", "corner_mm"})
        self.assertEqual(free, {"pipe_d_mm", "holes_count"})

    def test_sizes_the_tries_set_keep_their_range(self):
        values = {e.name: e.value for e in table_of(tray(), TICKED).entries}
        spans = {name: {"low": values[name], "high": values[name] + 1.0, "failed": []} for name in TICKED}
        fixed, _ = self.outcome(Motion(spans=spans))
        self.assertEqual(fixed, set())


if __name__ == "__main__":
    unittest.main()
