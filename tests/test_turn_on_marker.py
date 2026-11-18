"""Turning timeline items back on when a later step in error makes a plain set fail (`DesignParameterStore`)."""
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign
from lib.fusion_reader.rows import DesignParameterStore


class Item:
    """An item that turns on only while the marker is at or before its index, like an item followed by a step in
    error: Fusion rebuilds the later steps when it turns on and refuses."""

    def __init__(self, timeline, index, name, blocked):
        self.timeline, self.index, self.name, self.blocked = timeline, index, name, blocked
        self.off, self.stuck = False, False

    @property
    def isSuppressed(self):
        return self.off

    @isSuppressed.setter
    def isSuppressed(self, value):
        if not value and self.stuck:
            raise RuntimeError("cannot turn on")
        if not value and self.blocked and self.timeline.markerPosition > self.index:
            raise RuntimeError("Compute Failed")
        self.off = bool(value)


class Timeline:
    def __init__(self, names, blocked=(), marker=None, back_fails=False):
        self.items = [Item(self, i, name, name in blocked) for i, name in enumerate(names)]
        self._marker = len(names) if marker is None else marker
        self.back_fails, self.moves = back_fails, []

    count = property(lambda self: len(self.items))

    @property
    def markerPosition(self):
        return self._marker

    @markerPosition.setter
    def markerPosition(self, value):
        self.moves.append(value)
        if self.back_fails and len(self.moves) > 1:
            return
        self._marker = value

    def moveToEnd(self):
        self.markerPosition = self.count

    def item(self, i):
        return self.items[i]


def design_with(timeline):
    design = FakeDesign([])
    design.timeline = timeline
    return design


def suppressed_store(timeline, indexes):
    """A store that holds the items at `indexes` as turned off by it."""
    store = DesignParameterStore(design_with(timeline))
    for index in indexes:
        timeline.items[index].off = True
        store._suppressed.append((timeline.items[index].name, timeline.items[index]))
    return store


NAMES = ["A", "B", "C", "D", "E"]


class UnsuppressTest(unittest.TestCase):
    def test_items_a_later_step_blocks_turn_on_with_the_marker_held_and_the_marker_comes_back(self):
        timeline = Timeline(NAMES, blocked={"B", "C"})
        store = suppressed_store(timeline, [1, 2])
        self.assertEqual(store.unsuppress_items(), [])
        self.assertFalse(any(item.off for item in timeline.items))
        self.assertEqual(timeline.markerPosition, 5)
        self.assertEqual(timeline.moves[0], 1)

    def test_a_marker_held_early_by_the_tries_goes_back_to_that_place(self):
        timeline = Timeline(NAMES, blocked={"B"}, marker=3)
        store = suppressed_store(timeline, [1])
        self.assertEqual(store.unsuppress_items(), [])
        self.assertEqual(timeline.markerPosition, 3)

    def test_the_marker_never_moves_when_the_direct_set_works(self):
        timeline = Timeline(NAMES)
        store = suppressed_store(timeline, [1, 3])
        self.assertEqual(store.unsuppress_items(), [])
        self.assertEqual(timeline.moves, [])

    def test_an_item_that_stays_off_is_named_and_the_marker_still_goes_back(self):
        timeline = Timeline(NAMES, blocked={"B"})
        timeline.items[2].stuck = True
        store = suppressed_store(timeline, [1, 2])
        self.assertEqual(store.unsuppress_items(), ["C"])
        self.assertEqual(timeline.markerPosition, 5)

    def test_a_marker_that_does_not_go_back_is_reported_by_the_store(self):
        timeline = Timeline(NAMES, blocked={"B"}, back_fails=True)
        store = suppressed_store(timeline, [1])
        self.assertEqual(store.unsuppress_items(), [])
        self.assertNotEqual(timeline.markerPosition, 5)
        self.assertEqual(store.return_marker(), "lost")
        self.assertFalse(store.keep_marker())


class TurnOnTest(unittest.TestCase):
    def test_steps_a_later_step_blocks_turn_on_with_the_marker_held(self):
        timeline = Timeline(NAMES, blocked={"B", "D"})
        for index in (1, 3):
            timeline.items[index].off = True
        store = DesignParameterStore(design_with(timeline))
        self.assertEqual(store.turn_on([(1, "B"), (3, "D")]), [])
        self.assertFalse(any(item.off for item in timeline.items))
        self.assertEqual(timeline.markerPosition, 5)

    def test_an_index_that_holds_another_name_is_left_alone_and_the_marker_stays(self):
        timeline = Timeline(NAMES)
        timeline.items[1].off = True
        store = DesignParameterStore(design_with(timeline))
        self.assertEqual(store.turn_on([(1, "X")]), [])
        self.assertTrue(timeline.items[1].off)
        self.assertEqual(timeline.moves, [])

    def test_a_marker_that_does_not_go_back_is_reported_by_the_store(self):
        timeline = Timeline(NAMES, blocked={"B"}, back_fails=True)
        timeline.items[1].off = True
        store = DesignParameterStore(design_with(timeline))
        self.assertEqual(store.turn_on([(1, "B")]), [])
        self.assertEqual(store.return_marker(), "lost")


if __name__ == "__main__":
    unittest.main()
