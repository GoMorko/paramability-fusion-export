"""Unused timeline items suppressed while the sketch tries run: which items, the store that suppresses them, and the
pipeline turning them back on on every way out."""
import copy
import dataclasses
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.test_marker_roll import LID, OWN, PIPE, RollingStore, box_capture, capture, item, profile_record
from tests.test_parts_pipeline import FakePartsPort
from tests.test_parts_pipeline import request as parts_request
from tests.test_pipeline import START, FakePort, shifted
from tests.test_pipeline import request as single_request
from tests.test_timeline_marker import Item, Timeline
from tests.fakes import FakeDesign

from lib.design_edit.runner import ExportCancelled
from lib.export_plan.parts_pipeline import run_parts_pipeline
from lib.export_plan.pipeline import run_pipeline
from lib.export_plan.timeline_trim import unused_items
from lib.fusion_reader.rows import DesignParameterStore


def picked(*captures, stop=None):
    found = [c for c in captures if isinstance(c, dict)]
    stop = found[0]["marker"]["position"] if stop is None else stop
    return [index for index, _ in unused_items(list(captures), stop)[0]]


def base():
    """A body made by one extrude of its own sketch."""
    return [item(0, "Sketch", "Base"),
            item(1, "ExtrudeFeature", target_changed=True, data={"profiles": [profile_record("Base")]})]


class UnusedItemsTest(unittest.TestCase):
    def test_items_of_an_unused_other_component_before_the_stop_are_listed(self):
        items = base() + [item(2, "Sketch", "Lid sketch", own=False), item(3, "ExtrudeFeature", own=False),
                          item(4, "Sketch", "Spare"), item(5, "ExtrudeFeature", own=False, suppressed=True),
                          item(6, "ExtrudeFeature", own=False)]
        self.assertEqual(picked(capture(items), stop=6), [2, 3])

    def test_a_component_the_body_needs_keeps_all_its_items(self):
        link = {"sketch": "Base", "token": "t", "unknown": 0, "links": [{"token": PIPE, "name": "Pipe", "sketches": []}]}
        pipe = [item(2, "Sketch", "Pipe sketch", own=False, component=PIPE),
                item(3, "ExtrudeFeature", own=False, component=PIPE)]
        lid = [item(4, "ExtrudeFeature", own=False)]
        tool = copy.deepcopy(pipe)
        tool[1]["helper_of"] = "tool"
        for name, captured in (("link", capture(base() + pipe + lid, links=[link])),
                               ("tool body", capture(base() + tool + lid))):
            with self.subTest(name):
                self.assertEqual(picked(captured), [4])

    def test_an_occurrence_is_never_listed(self):
        items = base() + [item(2, "Occurrence", own=False), item(3, "ExtrudeFeature", own=False)]
        self.assertEqual(picked(capture(items)), [3])

    def test_nothing_is_listed_when_unsure(self):
        lid = [item(3, "ExtrudeFeature", own=False)]
        nameless_ref = item(1, "ExtrudeFeature", target_changed=True,
                            data={"ref": {"slot": "plane", "token": "r", "component": {"name": "Pipe"}}})
        cases = {
            "joint": base() + [item(2, "Joint", own=False)] + lid,
            "unknown type": base() + [item(2, "BrandNewFeature", own=False)] + lid,
            "unmatched sketch": [item(0, "ExtrudeFeature", target_changed=True,
                                      data={"profiles": [{"sketch_token": "tok"}]})] + lid,
            "unnamed reference": [base()[0], nameless_ref] + lid,
            "needed item without a component": base() + [item(2, "ExtrudeFeature", own=False, component="",
                                                              target_changed=None)] + lid,
        }
        for name, items in cases.items():
            with self.subTest(name):
                self.assertEqual(picked(capture(items)), [])
        no_target_component = capture(base() + lid)
        no_target_component["target"].pop("component")
        self.assertEqual(picked(no_target_component), [])

    def test_several_bodies_keep_the_component_of_each(self):
        items = base() + [item(2, "ExtrudeFeature", own=False), item(3, "ExtrudeFeature", own=False, component=PIPE)]
        second = capture(copy.deepcopy(items))
        second["target"]["component"] = {"token": LID, "name": "Lid"}
        for each in second["items"]:
            each["in_target_component"] = each["component"] == LID
        second["items"][2]["target_changed"] = True
        self.assertEqual(picked(capture(items), second, "fixed shape"), [3])


def timeline_design(names, suppressed=()):
    design = FakeDesign([dict(name="width", expression="20 mm", value=2.0, unit="mm")])
    design.timeline = Timeline([Item(n) for n in names], len(names))
    for index in suppressed:
        design.timeline.items[index].isSuppressed = True
    return design


class StoreSuppressTest(unittest.TestCase):
    def test_items_are_suppressed_and_turned_back_on_and_one_the_person_suppressed_stays_off(self):
        design = timeline_design(["Sketch1", "Extrude1", "Lid1", "Lid2"], suppressed=[3])
        store = DesignParameterStore(design)
        self.assertEqual(store.suppress_items([(2, "Lid1")]), 1)
        self.assertEqual([i.isSuppressed for i in design.timeline.items], [False, False, True, True])
        self.assertEqual(store.unsuppress_items(), [])
        self.assertEqual([i.isSuppressed for i in design.timeline.items], [False, False, False, True])

    def test_nothing_is_touched_when_an_item_is_not_as_the_capture_saw_it(self):
        design = timeline_design(["Sketch1", "Extrude1", "Lid1", "Lid2"], suppressed=[3])
        store = DesignParameterStore(design)
        for items in ([(2, "Lid1"), (1, "Other")], [(2, "Lid1"), (3, "Lid2")], [(9, "Lid9")]):
            with self.subTest(items):
                self.assertEqual(store.suppress_items(items), 0)
                self.assertEqual([i.isSuppressed for i in design.timeline.items], [False, False, False, True])

    def test_an_item_that_will_not_turn_back_on_is_named(self):
        design = timeline_design(["Sketch1", "Lid1"])
        store = DesignParameterStore(design)
        store.suppress_items([(1, "Lid1")])
        design.timeline.items[1].__class__ = type("Stuck", (Item,), {
            "isSuppressed": property(lambda self: True, lambda self, value: None)})
        self.assertEqual(store.unsuppress_items(), ["Lid1"])


class TrimStore(RollingStore):
    """A rolling store that also suppresses timeline items and rebuilds once after each change, like the real one;
    `events` lists every roll and suppression in order and `off_at` the suppressed indexes at each recompute."""

    def __init__(self, expressions, refuse=False, stuck=()):
        super().__init__(expressions)
        self.off, self.off_at, self.refuse, self.stuck = (), [], refuse, list(stuck)

    def suppress_items(self, items):
        self.events.append(("suppress", [i for i, _ in items]))
        if self.refuse:
            return 0
        self.off = tuple(i for i, _ in items)
        self.recompute()
        return len(self.off)

    def unsuppress_items(self):
        self.events.append(("unsuppress", list(self.off)))
        self.off = ()
        self.recompute()
        return self.stuck

    def recompute(self):
        self.off_at.append(self.off)
        return super().recompute()


def trim_capture():
    """The sketch fixture, two unused items of another component, a sketch of the body that a link names and two
    items after it: the marker rolls to 9 of 11 and items 6 and 7 can be suppressed."""
    out = box_capture(end=6)
    out["sketch_links"] = [{"sketch": "Late", "token": "tok_late", "unknown": 0, "links": []}]
    out["items"] += [item(6, "Sketch", "Lid sketch", own=False), item(7, "ExtrudeFeature", own=False),
                     item(8, "Sketch", "Late", component=OWN),
                     item(9, "ExtrudeFeature", own=False, component=PIPE),
                     item(10, "ExtrudeFeature", own=False, component=PIPE)]
    out["marker"] = {"position": 11, "count": 11}
    return out


class LeftOffPort(FakePort):
    def __init__(self, **options):
        super().__init__(**options)
        self.left_off = []

    def warn_left_off(self, names):
        self.left_off.append(list(names))


def export(port, faster=True):
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, dataclasses.replace(single_request(), faster_tries=faster), tmp)


class PipelineTrimTest(unittest.TestCase):
    def port(self, store=None, **options):
        return LeftOffPort(capture=trim_capture(), store=store or TrimStore(START), **options)

    def test_the_tries_run_with_the_unused_items_off_and_they_come_back_before_the_marker(self):
        port = self.port()
        result = export(port)
        self.assertEqual(port.store.events, [("roll", 9), ("suppress", [6, 7]), ("unsuppress", [6, 7]),
                                             ("unroll", 9)])
        trimmed = [off for off in port.store.off_at if off]
        self.assertGreater(len(trimmed), 10)
        self.assertEqual(port.store.off_at[-1], ())
        timeline = result.report["probe"]["timeline"]
        self.assertEqual(timeline["suppressed"], {"asked": True, "on": True, "items": 2})
        self.assertIsInstance(timeline["try_seconds"], float)
        self.assertEqual(port.store.exprs, START)

    def test_with_the_box_off_the_store_gets_the_same_calls_as_without_the_option(self):
        port = self.port()
        result = export(port, faster=False)
        self.assertEqual(port.store.events, [("roll", 9), ("unroll", 9)])
        self.assertEqual(set(port.store.off_at), {()})
        self.assertEqual(result.report["probe"]["timeline"]["suppressed"]["on"], False)

    def test_a_body_that_reads_differently_with_the_items_off_is_tried_with_them_on(self):
        port = self.port()
        reader = port.probe_reader

        def probe_reader():
            read = reader()
            return lambda request: shifted(read(request), 1.0) if port.store.off else read(request)

        port.probe_reader = probe_reader
        result = export(port)
        self.assertEqual(port.store.events, [("roll", 9), ("suppress", [6, 7]), ("unsuppress", [6, 7]),
                                             ("unroll", 9)])
        self.assertEqual(port.store.off_at[-1], ())
        self.assertEqual(sum(1 for off in port.store.off_at if off), 1)
        suppressed = result.report["probe"]["timeline"]["suppressed"]
        self.assertEqual((suppressed["on"], suppressed["items"], bool(suppressed["reason"])), (False, 0, True))
        self.assertEqual(result.health["probe"], "measured")

    def test_a_cancel_or_a_failing_probe_turns_the_items_back_on_before_the_marker(self):
        cancelled = self.port(cancel_at=4)
        with self.assertRaises(ExportCancelled):
            export(cancelled)
        failed = self.port(fail_read_from=8)
        self.assertEqual(export(failed).health["probe"], "failed")
        for port in (cancelled, failed):
            self.assertEqual(port.store.events[-2:], [("unsuppress", [6, 7]), ("unroll", 9)])
            self.assertEqual(port.store.exprs, START)

    def test_items_that_will_not_turn_back_on_are_named_to_the_person(self):
        port = self.port(store=TrimStore(START, stuck=["Lid sketch"]))
        export(port)
        self.assertEqual(port.left_off, [["Lid sketch"]])


class PartsTrimTest(unittest.TestCase):
    def test_the_shared_tries_of_several_bodies_turn_the_items_off_and_back_on(self):
        port = FakePartsPort([trim_capture(), trim_capture()], store=TrimStore(START), cancel_at=3)
        with self.assertRaises(ExportCancelled):
            with tempfile.TemporaryDirectory() as tmp:
                run_parts_pipeline(port, dataclasses.replace(parts_request(), faster_tries=True), tmp)
        self.assertEqual(port.store.events, [("roll", 9), ("suppress", [6, 7]), ("unsuppress", [6, 7]),
                                             ("unroll", 9)])


if __name__ == "__main__":
    unittest.main()
