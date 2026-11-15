import unittest
from types import SimpleNamespace

from tests import context  # noqa: F401

from lib.dialog_model import left_out_preview as preview


def verdict(index, gap, cause="own", tool_steps=()):
    return {"index": index, "verdict": "leftOut", "gap": gap, "cause": cause, "tool_steps": list(tool_steps)}


def result(items, *records):
    return SimpleNamespace(items=items, gaps=list(records))


def record(gap, name, reason="No.", hint=None):
    return dict({"id": gap, "name": name, "reason": reason}, **({"hint": hint} if hint else {}))


class FindTest(unittest.TestCase):
    def test_steps_come_in_timeline_order_also_from_inside_a_tool_body_walk(self):
        found = preview.find(result(
            [verdict(7, "g7"), verdict(3, "g3", tool_steps=[verdict(2, "g2")])],
            record("g7", "Shell1"), record("g3", "Combine1"), record("g2", "Extrude2")))
        self.assertEqual([step["name"] for step in found.steps], ["Extrude2", "Combine1", "Shell1"])

    def test_a_step_the_recipe_does_not_keep_as_a_gap_is_not_listed(self):
        self.assertEqual(preview.find(result([verdict(2, "gone")])).steps, [])

    def test_a_step_that_only_picks_faces_of_another_gap_is_not_listed_but_the_export_may_find_it(self):
        found = preview.find(result([verdict(2, "g2"), verdict(3, "g3", cause="picks")],
                                    record("g2", "Coil1"), record("g3", "Fillet1")))
        self.assertEqual([step["name"] for step in found.steps], ["Coil1"])
        self.assertTrue(found.waits_for_faces)

    def test_a_step_without_a_hint_keeps_an_empty_hint(self):
        found = preview.find(result([verdict(2, "g2")], record("g2", "Coil1", "A  long\nreason.")))
        self.assertEqual((found.steps[0]["hint"], found.steps[0]["reason"]), ("", "A long reason."))


class LinesTest(unittest.TestCase):
    def found(self, count, waits=False):
        return preview.Found([{"index": n, "name": "S%d" % n, "reason": "No.", "hint": "Fix it."}
                              for n in range(count)], waits)

    def test_nothing_left_out_gives_no_lines_even_when_the_export_may_find_more(self):
        self.assertEqual(preview.lines(self.found(0, True), "Heading:"), [])

    def test_a_long_reason_is_cut_in_the_box_but_the_hint_stays(self):
        step = {"index": 1, "name": "S", "reason": "word " * 60, "hint": "Fix it."}
        line = preview.lines(preview.Found([step]), "H:")[1]
        self.assertTrue(line.endswith("... Tip: Fix it."))
        self.assertLess(len(line), 140)
        self.assertGreater(len(preview.step_text(step, whole=True)), 300)

    def test_at_most_a_few_steps_are_listed_and_the_rest_is_counted(self):
        shown = preview.lines(self.found(5, True), "H:")
        self.assertEqual(shown[0], "H:")
        self.assertEqual(shown[1], "S0: No. Tip: Fix it.")
        self.assertEqual(shown[-2:], ["and 2 more.", preview.MORE_MAY_SHOW])
        self.assertEqual(len(shown), 1 + preview.MAX_LISTED + 2)

    def test_the_closing_line_can_be_left_to_the_caller(self):
        self.assertNotIn(preview.MORE_MAY_SHOW, preview.lines(self.found(1, True), "H:", closing=False))


if __name__ == "__main__":
    unittest.main()
