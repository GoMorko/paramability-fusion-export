import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeTimeline
from lib.export_plan.errors import StepExportError
from lib.export_plan.temp_copy import (
    delete_created_items, marker_at_end, remove_temporary_copy, require_marker_at_end, timeline_state)


class Occurrence:
    def __init__(self, fails=False):
        self.fails = fails

    def deleteMe(self):
        if self.fails:
            raise RuntimeError("cannot delete")


class TempCopyTest(unittest.TestCase):
    def test_marker_at_end_is_accepted(self):
        require_marker_at_end(FakeTimeline(["a", "b"]))

    def test_rolled_back_marker_is_refused(self):
        timeline = FakeTimeline(["a", "b", "c"], marker=1)
        self.assertFalse(marker_at_end(timeline))
        with self.assertRaises(StepExportError) as ctx:
            require_marker_at_end(timeline)
        self.assertIn("timeline marker", str(ctx.exception))

    def test_cleanup_removes_only_the_items_the_copy_added(self):
        timeline = FakeTimeline(["a", "b"])
        before = timeline_state(timeline)
        timeline.insert_at_marker("temp1")
        timeline.insert_at_marker("temp2")
        self.assertEqual(remove_temporary_copy(timeline, Occurrence(fails=True), before), 2)
        self.assertEqual(timeline.tokens(), ["a", "b"])

    def test_a_feature_whose_token_changed_is_never_deleted(self):
        timeline = FakeTimeline(["a", "b"])
        before = timeline_state(timeline)
        timeline.items[1].entity.entityToken = "b-after-recompute"
        timeline.insert_at_marker("temp")
        self.assertEqual(delete_created_items(timeline, before), 1)
        self.assertEqual(timeline.tokens(), ["a", "b-after-recompute"])

    def test_nothing_is_deleted_when_the_timeline_did_not_grow(self):
        timeline = FakeTimeline(["a", "b"])
        before = timeline_state(timeline)
        for item in timeline.items:
            item.entity.entityToken += "-changed"
        self.assertEqual(delete_created_items(timeline, before), 0)
        self.assertEqual(len(timeline.items), 2)

    def test_items_without_an_entity_are_never_deleted(self):
        timeline = FakeTimeline(["a"])
        before = timeline_state(timeline)
        timeline.insert_at_marker("temp")
        timeline.items[1].entity = None
        self.assertEqual(delete_created_items(timeline, before), 0)
        self.assertEqual(len(timeline.items), 2)


if __name__ == "__main__":
    unittest.main()
