import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeTimeline
from lib.export_plan.temp_copy import (
    created_entities, delete_created_items, remove_temporary_copy, timeline_state)


class Occurrence:
    def __init__(self, entity=None, fails=False):
        self.entity, self.fails = entity, fails

    def deleteMe(self):
        if self.fails:
            raise RuntimeError("cannot delete")
        self.entity.deleteMe()


class TempCopyTest(unittest.TestCase):
    def test_cleanup_removes_only_the_items_the_copy_added(self):
        timeline = FakeTimeline(["a", "b"])
        before = timeline_state(timeline)
        timeline.insert_at_marker("temp1")
        timeline.insert_at_marker("temp2")
        self.assertEqual(remove_temporary_copy(timeline, Occurrence(fails=True), before), 2)
        self.assertEqual(timeline.tokens(), ["a", "b"])

    def test_with_the_marker_in_the_middle_the_steps_after_it_survive(self):
        timeline = FakeTimeline(["a", "b", "c", "d"], marker=2)
        before = timeline_state(timeline)
        occurrence = Occurrence(timeline.insert_at_marker("temp-occurrence"))
        timeline.insert_at_marker("temp-copy")
        self.assertEqual(timeline.tokens(), ["a", "b", "temp-occurrence", "temp-copy", "c", "d"])
        self.assertEqual(remove_temporary_copy(timeline, occurrence, before), 1)
        self.assertEqual((timeline.tokens(), timeline.marker), (["a", "b", "c", "d"], 2))

    def test_new_items_are_found_wherever_they_sit(self):
        timeline = FakeTimeline(["a", "b", "c"], marker=1)
        before = timeline_state(timeline)
        first = timeline.insert_at_marker("x")
        timeline.marker = 4
        second = timeline.insert_at_marker("y")
        self.assertEqual(created_entities(timeline, before), [first, second])

    def test_a_feature_whose_token_changed_is_never_deleted(self):
        timeline = FakeTimeline(["a", "b", "c"], marker=1)
        before = timeline_state(timeline)
        timeline.items[2].entity.entityToken = "c-after-recompute"
        timeline.insert_at_marker("temp")
        self.assertEqual(delete_created_items(timeline, before), 1)
        self.assertEqual(timeline.tokens(), ["a", "b", "c-after-recompute"])

    def test_nothing_is_deleted_when_more_items_look_new_than_were_added(self):
        timeline = FakeTimeline(["a", "b", "c"], marker=1)
        before = timeline_state(timeline)
        timeline.insert_at_marker("temp")
        timeline.items[3].entity = type(timeline.items[3].entity)(timeline, "c")  # no longer equal to the old c
        self.assertEqual(delete_created_items(timeline, before), 0)
        self.assertEqual(timeline.tokens(), ["a", "temp", "b", "c"])

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
