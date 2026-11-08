import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeTimeline
from lib.export_plan.errors import StepExportError
from lib.export_plan.temp_copy import (
    delete_created_items, marker_at_end, remove_temporary_copy, require_marker_at_end, timeline_tokens)
from lib.fusion_reader.bodies import is_root_body


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

    def test_cleanup_with_rolled_back_marker_keeps_the_designers_later_features(self):
        timeline = FakeTimeline(["a", "b", "c"], marker=1)
        before = timeline_tokens(timeline)
        timeline.insert_at_marker("temp1")
        timeline.insert_at_marker("temp2")
        self.assertEqual(timeline.tokens(), ["a", "temp1", "temp2", "b", "c"])
        deleted = remove_temporary_copy(timeline, Occurrence(fails=True), before)
        self.assertEqual(deleted, 2)
        self.assertEqual(timeline.tokens(), ["a", "b", "c"])

    def test_cleanup_at_the_end_removes_only_the_created_items(self):
        timeline = FakeTimeline(["a", "b"])
        before = timeline_tokens(timeline)
        timeline.insert_at_marker("temp")
        delete_created_items(timeline, before)
        self.assertEqual(timeline.tokens(), ["a", "b"])

    def test_items_without_a_token_are_never_deleted(self):
        timeline = FakeTimeline(["a"])
        timeline.items[0].entity = None
        timeline.insert_at_marker("temp")
        self.assertEqual(delete_created_items(timeline, set()), 1)
        self.assertEqual(len(timeline.items), 1)
        self.assertIsNone(timeline.items[0].entity)


class Comp:
    def __init__(self, token):
        self.entityToken = token


class Body:
    def __init__(self, component, context=None):
        self.parentComponent = component
        self.assemblyContext = context


class RootBodyTest(unittest.TestCase):
    def test_only_root_bodies(self):
        root, child = Comp("root"), Comp("child")
        self.assertTrue(is_root_body(Body(root), root))
        self.assertFalse(is_root_body(Body(child), root))
        self.assertFalse(is_root_body(Body(root, context=object()), root))


if __name__ == "__main__":
    unittest.main()
