"""The reads of the timeline after a try take the type and the message of a step only when the step is not fine or
differs from the start read (`timeline_health.read_timeline` with `against`), and compare as a full read does."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign, FakeStore
from tests.test_timeline_health import Item, Timeline, design_with

from lib.design_edit import timeline_health as steps
from lib.design_edit.runner import RowExport
from lib.fusion_reader.rows import DesignParameterStore


class CountedItem(Item):
    """An item that counts how often its entity and its message are read."""

    def __init__(self, *args, **kwargs):
        self.entity_reads = self.message_reads = 0
        super().__init__(*args, **kwargs)

    @property
    def entity(self):
        self.entity_reads += 1
        return self._entity

    @entity.setter
    def entity(self, value):
        self._entity = value

    @property
    def errorOrWarningMessage(self):
        self.message_reads += 1
        return self._message

    @errorOrWarningMessage.setter
    def errorOrWarningMessage(self, value):
        self._message = value


def timeline(*specs):
    return [CountedItem(*spec) if isinstance(spec, tuple) else CountedItem(spec) for spec in specs]


def read(items, against=None):
    return steps.read_timeline(DesignParameterStore(design_with(items, marker=len(items))), against)


def shape(found):
    return {key: dict(step) for key, step in found.steps.items()}


class LightReadTest(unittest.TestCase):
    def test_a_light_read_of_an_unchanged_design_reads_no_entity_and_no_message(self):
        items = timeline("Sketch1", "Extrude1", "Fillet1")
        start = read(items)
        before = [(i.entity_reads, i.message_reads) for i in items]
        now = read(items, start)
        self.assertEqual([(i.entity_reads, i.message_reads) for i in items], before)
        self.assertEqual(shape(now), shape(start))

    def test_only_the_steps_that_are_not_fine_or_changed_are_read_in_full(self):
        items = timeline("Sketch1", ("Extrude1", 1, "Warned already"), "Fillet1", "Shell1")
        start = read(items)
        items[2].healthState, items[2].errorOrWarningMessage = 2, "No room"  # changed
        items[3].isSuppressed = True  # changed
        before = [i.entity_reads for i in items]
        now = read(items, start)
        self.assertEqual([i.entity_reads - b for i, b in zip(items, before)], [0, 1, 1, 1])
        self.assertEqual(shape(now), shape(read(items)))

    def test_the_changes_and_the_verdict_are_the_same_as_for_a_full_read(self):
        cases = {"nothing": lambda items: None,
                 "worse": lambda items: setattr(items[1], "healthState", 1),
                 "better": lambda items: setattr(items[2], "healthState", 0),
                 "message only": lambda items: setattr(items[2], "errorOrWarningMessage", "Other text"),
                 "off": lambda items: setattr(items[0], "isSuppressed", True),
                 "gone": lambda items: items.pop(1)}
        for label, change in cases.items():
            items = timeline("Sketch1", "Extrude1", ("Fillet1", 1, "Too small"))
            start = read(items)
            change(items)
            light, full = read(items, start), read(items)
            found, wanted = steps.changes(start, light), steps.changes(start, full)
            self.assertEqual(found, wanted, label)
            self.assertEqual([steps.is_worse(c) for c in found], [steps.is_worse(c) for c in wanted], label)

    def test_a_step_that_was_not_at_the_start_is_read_in_full(self):
        items = timeline("Sketch1")
        start = read(items)
        items.append(CountedItem("Fillet1", 1, "Too small"))
        now = read(items, start)
        self.assertEqual(items[1].entity_reads, 1)
        self.assertEqual([(c["name"], c["before"], c["after"]) for c in steps.changes(start, now)],
                         [("Fillet1", steps.NEW, "warning")])

    def test_a_start_read_of_only_the_steps_in_error_asks_for_a_full_read(self):
        asked = []

        class Store(FakeStore):
            def timeline_health(self, known=None):
                asked.append(known)
                return []

        partial = steps.TimelineRead({}, complete=False)
        steps.read_timeline(Store({}), partial)
        steps.read_timeline(Store({}), steps.TimelineRead({}))
        self.assertEqual(asked, [None, {}])

    def test_a_store_that_fails_the_light_read_still_gives_a_full_read(self):
        class Store(FakeStore):
            def timeline_health(self, known=None):
                if known is not None:
                    raise TypeError("no known steps")
                return [{"index": 0, "name": "Sketch1", "type": "Sketch", "health": "ok", "message": "",
                         "suppressed": False}]

        found = steps.read_timeline(Store({}), steps.TimelineRead({}))
        self.assertEqual(list(found.steps), [(0, "Sketch1")])


class CheckUsesLightReadTest(unittest.TestCase):
    def test_the_check_after_a_row_reads_against_the_baseline_and_the_end_check_reads_in_full(self):
        asked = []

        class Store(FakeStore):
            def set_expressions(self, expressions):
                self.exprs.update(expressions)
                return True

            def timeline_health(self, known=None):
                asked.append(known)
                return [{"index": 0, "name": "Sketch1", "type": None if known else "Sketch", "health": "ok",
                         "message": None if known else "", "suppressed": False}]

        store = Store({"w": "5 mm"})
        job = RowExport(store, {"w": "mm"}, lambda path: None)
        with tempfile.TemporaryDirectory() as tmp:
            job.run([{"name": "r", "values": {"w": 6.0}, "step": False}], tmp, lambda *a: True,
                    tolerate_build_errors=True)
        job.check_back()
        self.assertFalse(job.check_pending())
        self.assertEqual(asked, [None, {(0, "Sketch1"): ("ok", False)}])
        self.assertTrue(job.back_clean)
        start = steps.read_timeline(store)
        self.assertEqual(steps.settle_timeline(store, start, {"w": "5 mm"}).changed, [])
        self.assertIsNone(asked[-1])


class StoreReadTest(unittest.TestCase):
    def test_the_store_gives_no_type_and_no_message_for_a_fine_step_as_it_was(self):
        items = timeline("Sketch1", ("Fillet1", 1, "Too small"))
        store = DesignParameterStore(design_with(items, marker=2))
        found = store.timeline_health({(0, "Sketch1"): ("ok", False), (1, "Fillet1"): ("ok", False)})
        self.assertEqual([(s["name"], s["type"], s["message"]) for s in found],
                         [("Sketch1", None, None), ("Fillet1", "FilletFeature", "Too small")])

    def test_the_store_without_known_steps_reads_everything(self):
        items = timeline("Sketch1")
        found = DesignParameterStore(design_with(items, marker=1)).timeline_health()
        self.assertEqual(found[0]["type"], "FilletFeature")  # the type of the fake entity
        self.assertEqual(items[0].entity_reads, 1)


if __name__ == "__main__":
    unittest.main()
