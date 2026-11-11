"""The timeline marker held early while the sketch tries run: the position it needs, the store that holds it, and the
pipeline putting it back on every way out."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign, FakeStore
from tests.test_parts_pipeline import FakePartsPort
from tests.test_parts_pipeline import export as export_parts
from tests.test_pipeline import CAPTURE, START, FakePort, export, shifted
from tests.test_timeline_marker import Item, Timeline

from lib.design_edit.runner import ExportCancelled
from lib.export_plan.marker_roll import MarkerRoll, needed_position
from lib.fusion_reader.rows import DesignParameterStore

OWN = "cmp_own"
PIPE = "cmp_pipe"
LID = "cmp_lid"


def item(index, type_, name="", target_changed=False, own=True, component=None, **extra):
    return dict({"index": index, "type": type_, "name": name or "%s%d" % (type_, index), "suppressed": False,
                 "target_changed": target_changed, "in_target_component": own,
                 "component": component or (OWN if own else LID), "data": {}}, **extra)


def capture(items, end=None, links=(), **extra):
    return dict({"capture": 3, "target": {"token": "b1", "name": "Body", "component": {"token": OWN, "name": "Own"}},
                 "items": list(items), "sketch_links": list(links),
                 "marker": {"position": len(items) if end is None else end, "count": len(items) if end is None else end}},
                **extra)


def profile_record(sketch, **extra):
    return dict({"sketch": sketch, "sketch_token": "tok_" + sketch}, **extra)


class NeededPositionTest(unittest.TestCase):
    def position(self, *captures):
        return needed_position(list(captures))[0]

    def test_the_marker_goes_just_after_the_last_item_that_changes_the_body_or_is_a_sketch_it_uses(self):
        sketch = item(0, "Sketch", "Base")
        step = item(1, "ExtrudeFeature", target_changed=True, data={"profiles": [profile_record("Base")]})
        later = [item(2, "Sketch", "Unused"), item(3, "ExtrudeFeature", own=False), item(4, "FilletFeature")]
        self.assertEqual(needed_position([capture([sketch, step] + later)]), (2, ""))

    def test_a_sketch_a_step_uses_is_kept_even_when_it_comes_after_the_last_change_of_the_body(self):
        use = item(1, "ExtrudeFeature", target_changed=True, data={"profiles": [profile_record("Late")]})
        sketches = [item(0, "Sketch", "Early"), item(2, "Sketch", "Late"), item(3, "Sketch", "Other")]
        self.assertEqual(self.position(capture([sketches[0], use, sketches[1], sketches[2]])), 3)

    def test_a_borrowed_sketch_is_matched_in_its_own_component_not_by_name_alone(self):
        borrowed = profile_record("Shared", foreign=True, component={"token": LID, "name": "Lid"})
        use = item(1, "CombineFeature", target_changed=True, data={"profiles": [borrowed]})
        mine = item(2, "Sketch", "Shared")
        theirs = item(3, "Sketch", "Shared", own=False)
        self.assertEqual(self.position(capture([item(0, "Sketch", "Base"), use, mine, theirs, item(4, "Sketch", "Z")])), 4)

    def test_the_last_item_of_a_component_a_link_or_reference_depends_on_is_kept(self):
        link = {"sketch": "Base", "token": "t", "unknown": 0, "links": [{"token": PIPE, "name": "Pipe", "sketches": []}]}
        items = [item(0, "Sketch", "Base"), item(1, "ExtrudeFeature", target_changed=True),
                 item(2, "ExtrudeFeature", own=False, component=PIPE), item(3, "ExtrudeFeature", own=False),
                 item(4, "ExtrudeFeature", own=False, component=PIPE), item(5, "Sketch", "Free", own=False)]
        self.assertEqual(self.position(capture(items, links=[link])), 5)
        self.assertEqual(self.position(capture(items)), 2)
        reference = item(1, "ExtrudeFeature", target_changed=True,
                         data={"ref": {"slot": "plane", "token": "r", "component": {"token": PIPE, "name": "Pipe"}}})
        self.assertEqual(self.position(capture([items[0], reference] + items[2:])), 5)

    def test_a_reference_or_link_that_cannot_be_matched_keeps_every_other_component(self):
        items = [item(0, "ExtrudeFeature", target_changed=True), item(1, "ExtrudeFeature", own=False),
                 item(2, "ExtrudeFeature", own=False), item(3, "Sketch", "Free")]
        unknown = {"sketch": "Base", "token": "t", "unknown": 1, "links": []}
        self.assertEqual(self.position(capture(items, links=[unknown])), 3)
        nameless = item(0, "ExtrudeFeature", target_changed=True,
                        data={"ref": {"slot": "plane", "token": "r", "component": {"name": "Pipe"}}})
        self.assertEqual(self.position(capture([nameless] + items[1:])), 3)

    def test_a_tool_body_step_a_joint_and_an_unknown_item_are_kept_but_a_new_occurrence_is_not(self):
        base = [item(0, "ExtrudeFeature", target_changed=True)]
        tail = [item(1, "Occurrence", own=False), item(2, "ExtrudeFeature", own=False)]
        self.assertEqual(self.position(capture(base + tail + [item(3, "Sketch", "Free")])), 1)
        for extra in (item(3, "ExtrudeFeature", own=False, helper_of="tool"), item(3, "Joint", own=False),
                      item(3, "BrandNewFeature", own=False), item(3, "ExtrudeFeature", own=False, target_changed=None)):
            with self.subTest(extra["type"]):
                self.assertEqual(self.position(capture(base + tail + [extra, item(4, "Sketch", "Free")])), 4)

    def test_a_suppressed_item_is_not_needed(self):
        items = [item(0, "ExtrudeFeature", target_changed=True), item(1, "Joint", own=False, suppressed=True),
                 item(2, "Sketch", "Free")]
        self.assertEqual(self.position(capture(items)), 1)

    def test_no_roll_when_something_cannot_be_matched_or_nothing_would_be_skipped(self):
        step = item(0, "ExtrudeFeature", target_changed=True, data={"profiles": [{"sketch_token": "tok"}]})
        self.assertEqual(needed_position([capture([step, item(1, "Sketch", "Free")])])[0], None)
        every = [item(0, "ExtrudeFeature", target_changed=True), item(1, "ExtrudeFeature", target_changed=True)]
        self.assertEqual(needed_position([capture(every)]), (None, "nothing_to_skip"))
        bare = capture(every)
        del bare["marker"]
        self.assertEqual(needed_position([bare])[0], None)

    def test_several_captures_need_the_latest_position_and_must_share_the_marker(self):
        first = capture([item(0, "ExtrudeFeature", target_changed=True), item(1, "Sketch", "Free"),
                         item(2, "Sketch", "Free2")])
        second = capture([item(0, "ExtrudeFeature", target_changed=True), item(1, "ExtrudeFeature", target_changed=True),
                          item(2, "Sketch", "Free2")])
        self.assertEqual(self.position(first, second, "no tries"), 2)
        other = copy.deepcopy(second)
        other["marker"] = {"position": 9, "count": 9}
        self.assertEqual(self.position(first, other), None)


class TimelineDesign(FakeDesign):
    """A design whose recompute lets Fusion move the marker to the end, like the real one can."""

    def __init__(self, marker, names=("Sketch1", "Extrude1", "Fillet1", "Sketch2")):
        super().__init__([dict(name="width", expression="20 mm", value=2.0, unit="mm")])
        self.timeline = Timeline([Item(n) for n in names], marker)

    def computeAll(self):
        self.computed += 1
        self.timeline.markerPosition = self.timeline.count
        return True


class StoreRollTest(unittest.TestCase):
    def test_a_rolled_marker_stays_through_recomputes_and_goes_back_with_one_rebuild(self):
        design = TimelineDesign(marker=4)
        store = DesignParameterStore(design)
        self.assertTrue(store.roll_marker(2))
        store.recompute()
        self.assertEqual(design.timeline.markerPosition, 2)
        self.assertEqual(store.error_entries(), [])
        before = design.computed
        self.assertTrue(store.unroll_marker())
        self.assertEqual((design.timeline.markerPosition, design.computed), (4, before + 1))
        self.assertEqual(store.marker, {"position": 4, "count": 4})

    def test_a_marker_the_person_left_in_the_middle_comes_back_there(self):
        design = TimelineDesign(marker=3)
        store = DesignParameterStore(design)
        self.assertTrue(store.roll_marker(1))
        store.unroll_marker()
        self.assertEqual(design.timeline.markerPosition, 3)

    def test_only_the_items_before_the_rolled_marker_count_for_health(self):
        design = TimelineDesign(marker=4)
        design.timeline.items[2].healthState = 2
        store = DesignParameterStore(design)
        self.assertEqual(store.error_entries(), [(2, "Fillet1")])
        store.roll_marker(2)
        self.assertEqual(store.error_entries(), [])

    def test_a_position_that_does_not_skip_anything_or_a_second_roll_is_refused(self):
        design = TimelineDesign(marker=4)
        store = DesignParameterStore(design)
        for position in (0, 4, 5):
            self.assertFalse(store.roll_marker(position))
        self.assertTrue(store.roll_marker(2))
        self.assertFalse(store.roll_marker(1))
        self.assertFalse(DesignParameterStore(FakeDesign([])).roll_marker(1))

    def test_a_marker_fusion_will_not_move_leaves_the_store_unrolled(self):
        design = TimelineDesign(marker=4)
        store = DesignParameterStore(design)
        design.timeline.__class__ = type("Stuck", (Timeline,), {
            "markerPosition": property(lambda self: 4, lambda self, value: None)})
        self.assertFalse(store.roll_marker(2))
        self.assertEqual(store.marker, {"position": 4, "count": 4})

    def test_a_read_before_the_rolled_position_is_not_held(self):
        design = TimelineDesign(marker=4)
        store = DesignParameterStore(design)
        store.roll_marker(3)
        self.assertTrue(store.marker_holds())
        design.timeline.markerPosition = 1
        self.assertFalse(store.marker_holds())


class RollingStore(FakeStore):
    """A parameter store that records the marker position each recompute ran at."""

    def __init__(self, expressions, fail_roll=False):
        super().__init__(expressions)
        self.rolled, self.at, self.events, self.fail_roll, self.holds = None, [], [], fail_roll, True

    def roll_marker(self, position):
        self.events.append(("roll", position))
        if self.fail_roll:
            return False
        self.rolled = position
        return True

    def unroll_marker(self):
        self.events.append(("unroll", self.rolled))
        self.rolled = None
        return True

    def marker_holds(self):
        return self.holds

    def recompute(self):
        self.at.append(self.rolled)
        return super().recompute()


def box_capture(end=9):
    """The sketch fixture with three more items after its steps, none of which the part needs."""
    out = copy.deepcopy(CAPTURE)
    out["target"]["component"] = {"token": OWN, "name": "Own"}
    for each in out["items"]:
        each["target_changed"] = True
        each["component"] = OWN
    last = len(out["items"])
    out["items"] += [item(last + n, "ExtrudeFeature", own=False) for n in range(end - last)]
    out["marker"] = {"position": end, "count": end}
    return out


class PipelineRollTest(unittest.TestCase):
    def port(self, **options):
        port = FakePort(capture=box_capture(), store=options.pop("store", None) or RollingStore(START), **options)
        return port

    def test_the_tries_run_with_the_marker_held_early_and_it_goes_back_after_the_last_read(self):
        port = self.port()
        result = export(port)
        timeline = result.report["probe"]["timeline"]
        self.assertEqual((timeline["rolled"], timeline["items"], timeline["of"]), (True, 6, 9))
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])
        self.assertIsNone(port.store.rolled)
        rolled = [at for at in port.store.at if at == 6]
        self.assertGreater(len(rolled), 10)
        self.assertEqual(port.store.at[-1], 6)
        self.assertEqual(port.store.exprs, START)

    def test_a_design_that_reads_differently_at_the_rolled_marker_is_tried_at_the_full_marker(self):
        port = self.port()
        reader = port.probe_reader

        def probe_reader():
            read = reader()
            return lambda request: shifted(read(request), 1.0) if port.store.rolled else read(request)

        port.probe_reader = probe_reader
        result = export(port)
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])
        timeline = result.report["probe"]["timeline"]
        self.assertEqual((timeline["rolled"], timeline["items"], timeline["of"]), (False, 9, 9))
        self.assertIn("reads differently", timeline["reason"])
        self.assertEqual({at for at in port.store.at[1:]}, {None})

    def test_a_cancel_during_the_tries_puts_the_marker_back(self):
        port = self.port(cancel_at=4)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])
        self.assertEqual(port.store.exprs, START)

    def test_a_probe_that_fails_halfway_still_puts_the_marker_back(self):
        port = self.port(fail_read_from=8)
        result = export(port)
        self.assertEqual(result.health["probe"], "failed")
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])

    def test_a_read_after_the_marker_was_lost_counts_as_not_read_and_the_probe_is_not_used(self):
        port = self.port()
        reader = port.probe_reader

        def probe_reader():
            read = reader()

            def checked(request):
                port.store.holds = port.reads < 6
                return read(request)

            return checked

        port.probe_reader = probe_reader
        result = export(port)
        self.assertEqual(result.health["probe"], "failed")
        self.assertIsNone(result.report.get("probe"))
        self.assertEqual(port.store.events[-1][0], "unroll")

    def test_a_design_without_marker_support_or_a_marker_that_will_not_move_runs_as_before(self):
        plain = FakePort(capture=box_capture())
        self.assertEqual(export(plain).report["probe"]["timeline"]["rolled"], False)
        refused = self.port(store=RollingStore(START, fail_roll=True))
        result = export(refused)
        self.assertEqual(refused.store.events, [("roll", 6)])
        self.assertIn("could not be moved", result.report["probe"]["timeline"]["reason"])
        self.assertEqual(result.manifest["kind"], "recipe")

    def test_a_capture_that_needs_every_item_is_not_rolled_and_says_so(self):
        port = FakePort(capture=box_capture(end=6), store=RollingStore(START))
        result = export(port)
        self.assertEqual(port.store.events, [])
        timeline = result.report["probe"]["timeline"]
        self.assertEqual((timeline["rolled"], timeline["items"], timeline["of"]), (False, 6, 6))


class PartsRollTest(unittest.TestCase):
    def test_the_shared_tries_of_several_bodies_hold_the_marker_for_the_latest_body_and_put_it_back(self):
        port = FakePartsPort([box_capture(), box_capture()], store=RollingStore(START))
        result = export_parts(port)
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])
        parts = [p for p in result.report["parts"] if "probe" in p]
        self.assertTrue(parts)
        for part in parts:
            timeline = part["probe"]["timeline"]
            self.assertEqual((timeline["rolled"], timeline["items"], timeline["of"]), (True, 6, 9))

    def test_a_cancel_in_the_parts_tries_puts_the_marker_back(self):
        port = FakePartsPort([box_capture(), box_capture()], store=RollingStore(START), cancel_at=3)
        with self.assertRaises(ExportCancelled):
            export_parts(port)
        self.assertEqual(port.store.events, [("roll", 6), ("unroll", 6)])


class MarkerRollRecordTest(unittest.TestCase):
    def test_a_roll_that_raises_is_ended_and_recorded(self):
        store = RollingStore(START)
        roll = MarkerRoll(store, lambda text: None)

        def unchanged():
            raise RuntimeError("read failed")

        roll.begin([box_capture()], unchanged)
        self.assertFalse(roll.record["rolled"])
        self.assertEqual(store.events, [("roll", 6), ("unroll", 6)])
        roll.end()
        self.assertEqual(store.events, [("roll", 6), ("unroll", 6)])


if __name__ == "__main__":
    unittest.main()
