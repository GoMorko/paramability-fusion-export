"""The health of every timeline step compared between the start and the end of an export, and what is done when a
step differs (lib/design_edit/timeline_health.py, the store's reads, the pipeline's record and lines)."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeDesign, FakePort, FakeStore, shifted
from tests.test_pipeline import START, flip_port, request, view

from lib.design_edit import timeline_health as steps
from lib.design_edit.runner import ExportCancelled
from lib.dialog_model.result_rows import section_lines
from lib.export_plan import health as health_module
from lib.export_plan.pipeline import run_pipeline
from lib.fusion_reader.rows import DesignParameterStore


class StepStore(FakeStore):
    """A store with three timeline steps. `after_tries` is the health each step takes once a value changed; `heals`
    says what brings a step back to its start: "compute" (a full rebuild during the end check) or "values" (the start
    values set again). `suppressed` names steps that read turned off after the tries until turned back on."""

    START_STEPS = {"Sketch1": "ok", "Extrude1": "ok", "Fillet1": "ok"}

    def __init__(self, after_tries=None, heals=None, suppressed=(), marker_moved=False, **options):
        super().__init__(START, **options)
        self.saved = dict(START)
        self.health = dict(self.START_STEPS)
        self.after_tries, self.heals = dict(after_tries or {}), dict(heals or {})
        self.off, self.pending_off = set(), set(suppressed)
        self.marker_moved = marker_moved
        self.settling = False  # set once the parameters are back, like the end check sees it
        self.batches = []
        self.turned_on = []

    def set_expression(self, name, expression):
        super().set_expression(name, expression)
        if expression != self.saved[name]:
            self.health.update(self.after_tries)
            self.off |= self.pending_off

    def set_expressions(self, expressions):
        self.batches.append(dict(expressions))
        for name, text in expressions.items():
            self.set_expression(name, text)
        if self.exprs == self.saved and len(expressions) == len(self.saved):
            self._heal("values")
        return True

    def recompute(self):
        super().recompute()
        if self.exprs == self.saved:
            self._heal("compute")
        return True

    def _heal(self, how):
        for name, cause in self.heals.items():
            if cause == how and self.exprs == self.saved:
                self.health[name] = self.START_STEPS[name]

    def timeline_health(self):
        return [{"index": i, "name": name, "type": "FilletFeature" if name == "Fillet1" else "Feature",
                 "health": health, "message": "" if health == "ok" else "The fillet could not be made.",
                 "suppressed": name in self.off}
                for i, (name, health) in enumerate(self.health.items())]

    def turn_on(self, found):
        self.turned_on.extend(found)
        for _, name in found:
            self.off.discard(name)
        return []

    def return_marker(self):
        moved, self.marker_moved = self.marker_moved, False
        return "moved" if moved else ""


def settle(store, start):
    return steps.settle_timeline(store, start, START)


def tried(store):
    """The start read, then a try with another value and the values back, as an export leaves the design."""
    start = steps.read_timeline(store)
    store.set_expression("depth_mm", "77 mm")
    store.set_expression("depth_mm", START["depth_mm"])
    return start


class SettleTest(unittest.TestCase):
    def test_nothing_changed_needs_no_rebuild(self):
        store = StepStore()
        settled = settle(store, tried(store))
        self.assertEqual((settled.changed, settled.actions, store.recomputes), ([], [], 0))

    def test_a_step_that_a_full_rebuild_brings_back_is_recovered(self):
        store = StepStore({"Fillet1": "warning"}, heals={"Fillet1": "compute"})
        settled = settle(store, tried(store))
        self.assertEqual(settled.changed, [])
        self.assertEqual(settled.recovered, ["Fillet1"])
        self.assertEqual(settled.actions, [steps.FULL_COMPUTE])

    def test_a_step_still_worse_after_the_rebuild_gets_the_start_values_once_more(self):
        store = StepStore({"Fillet1": "error"}, heals={"Fillet1": "values"})
        settled = settle(store, tried(store))
        self.assertEqual(settled.changed, [])
        self.assertEqual(settled.actions, [steps.FULL_COMPUTE, steps.VALUES_AGAIN])
        self.assertEqual(store.batches[-1], START)

    def test_a_step_that_stays_worse_is_listed_with_its_states_and_message(self):
        store = StepStore({"Fillet1": "warning"})
        settled = settle(store, tried(store))
        self.assertEqual(settled.changed, [{"index": 2, "name": "Fillet1", "type": "FilletFeature", "before": "ok",
                                            "after": "warning", "message": "The fillet could not be made."}])
        self.assertEqual(settled.actions, [steps.FULL_COMPUTE, steps.VALUES_AGAIN])

    def test_a_step_that_is_only_better_asks_for_one_rebuild(self):
        store = StepStore()
        store.health["Fillet1"] = "warning"
        start = steps.read_timeline(store)
        store.health["Fillet1"] = "ok"
        settled = settle(store, start)
        self.assertEqual(settled.actions, [steps.FULL_COMPUTE])
        self.assertEqual([(c["before"], c["after"]) for c in settled.changed], [("warning", "ok")])
        self.assertFalse(steps.is_worse(settled.changed[0]))

    def test_steps_turned_off_during_the_export_are_turned_back_on(self):
        store = StepStore(suppressed={"Extrude1"})
        settled = settle(store, tried(store))
        self.assertEqual(store.turned_on, [(1, "Extrude1")])
        self.assertEqual(settled.changed, [])
        self.assertEqual(settled.actions, [steps.TURNED_ON, steps.FULL_COMPUTE])

    def test_a_marker_that_reads_elsewhere_goes_back(self):
        store = StepStore(marker_moved=True)
        self.assertEqual(settle(store, tried(store)).actions, [steps.MARKER_BACK])

    def test_a_store_with_only_the_steps_in_error_compares_those(self):
        store = FakeStore(START, bad_when=lambda exprs: True)
        start = steps.read_timeline(FakeStore(START))
        settled = settle(store, start)
        self.assertEqual([(c["name"], c["before"], c["after"]) for c in settled.changed], [("Fillet1", "ok", "error")])
        self.assertEqual(settled.broken, ["Fillet1"])


class RecordTest(unittest.TestCase):
    def test_a_long_list_is_capped_and_counted(self):
        changed = [{"index": i, "name": "Fillet%d" % i, "type": "FilletFeature", "before": "ok", "after": "warning",
                    "message": ""} for i in range(steps.MAX_STEPS + 3)]
        health = health_module.make_health(health_module.HealthInputs(
            steps=steps.TimelineSettle(changed, actions=[steps.FULL_COMPUTE])))
        self.assertEqual(len(health["steps_changed"]), steps.MAX_STEPS)
        self.assertEqual(health["steps_more"], 3)
        self.assertTrue(health_module.design_changed(health))
        line = health_module.health_lines(health)[0]
        self.assertLessEqual(len(line), health_module.MAX_LINE)
        self.assertIn("Undo", line)

    def test_a_worse_step_past_the_listed_ones_still_counts_as_a_changed_design(self):
        better = [{"index": i, "name": "Fillet%d" % i, "type": "FilletFeature", "before": "warning", "after": "ok",
                   "message": ""} for i in range(steps.MAX_STEPS)]
        worse = {"index": 99, "name": "Shell1", "type": "ShellFeature", "before": "ok", "after": "warning", "message": ""}
        health = health_module.make_health(health_module.HealthInputs(steps=steps.TimelineSettle(better + [worse])))
        self.assertTrue(health_module.design_changed(health))
        self.assertIn("Undo in Fusion until", health_module.health_lines(health)[0])


class Timeline:
    def __init__(self, items, marker):
        self.items, self.markerPosition = items, marker

    @property
    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i]

    def moveToEnd(self):
        self.markerPosition = self.count


class Item:
    def __init__(self, name, health=0, message="", group=False, suppressed=False):
        self.name, self.healthState, self.errorOrWarningMessage = name, health, message
        self.isGroup, self.isSuppressed = group, suppressed
        self.entity = type("Entity", (), {"objectType": "adsk::fusion::FilletFeature"})()


def design_with(items, marker):
    design = FakeDesign([dict(name="width", expression="20 mm", value=2.0, unit="mm")])
    design.timeline = Timeline(items, marker)
    return design


class StoreTest(unittest.TestCase):
    def test_the_store_reads_each_step_before_the_marker_without_groups(self):
        design = design_with([Item("Sketch1"), Item("Group1", group=True), Item("Fillet1", 1, "Too small"),
                              Item("Later", 2)], marker=3)
        found = DesignParameterStore(design).timeline_health()
        self.assertEqual([(s["index"], s["name"], s["health"], s["message"]) for s in found],
                         [(0, "Sketch1", "ok", ""), (2, "Fillet1", "warning", "Too small")])
        self.assertEqual(found[1]["type"], "FilletFeature")

    def test_the_store_puts_a_moved_marker_back_and_turns_on_only_the_named_steps(self):
        design = design_with([Item("Sketch1", suppressed=True), Item("Fillet1", suppressed=True)], marker=2)
        store = DesignParameterStore(design)
        design.timeline.markerPosition = 1
        self.assertEqual((store.return_marker(), store.return_marker()), ("moved", ""))
        self.assertEqual(design.timeline.markerPosition, 2)
        self.assertEqual(store.turn_on([(0, "Other"), (1, "Fillet1")]), [])
        self.assertEqual([i.isSuppressed for i in design.timeline.items], [True, False])


def export(port):
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, request(), tmp)


class PipelineTest(unittest.TestCase):
    def test_a_step_left_in_a_warning_is_recorded_and_the_person_told_to_use_undo(self):
        result = export(FakePort(store=StepStore({"Fillet1": "warning"})))
        changed = result.health["steps_changed"]
        self.assertEqual([(c["name"], c["before"], c["after"]) for c in changed], [("Fillet1", "ok", "warning")])
        self.assertEqual(result.health["end_actions"], [steps.FULL_COMPUTE, steps.VALUES_AGAIN])
        lines = section_lines(view(result), "check")
        self.assertTrue(any("Fillet1" in line and "Undo" in line for line in lines))

    def test_a_step_a_rebuild_brings_back_is_recorded_as_recovered_and_not_shown(self):
        result = export(FakePort(store=StepStore({"Fillet1": "warning"}, heals={"Fillet1": "compute"})))
        self.assertNotIn("steps_changed", result.health)
        self.assertEqual(result.health["steps_recovered"], ["Fillet1"])
        self.assertEqual(section_lines(view(result), "check"), [])

    def test_the_start_read_of_the_dialog_is_the_one_compared(self):
        store = StepStore()
        start = steps.read_timeline(store)
        store.health["Fillet1"] = "warning"  # the dialog's read of the design left the fillet in a warning
        port = FakePort(store=store)
        with tempfile.TemporaryDirectory() as tmp:
            req = request()
            req.timeline_start = start
            result = run_pipeline(port, req, tmp)
        self.assertEqual([c["name"] for c in result.health["steps_changed"]], ["Fillet1"])

    def test_a_cancelled_export_checks_the_steps_and_tells_the_person(self):
        port = FakePort(store=StepStore({"Fillet1": "error"}), cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(len(port.warned_steps), 1)
        self.assertTrue(any("Fillet1" in line for line in port.warned_steps[0]))

    def test_a_sketch_left_with_its_compute_deferred_is_recorded_as_a_change(self):
        port = flip_port()
        make = port.sketch_keeper

        def keeper(tokens):
            kept = make(tokens)
            kept.deferred_left = ["Sketch1"]
            return kept

        port.sketch_keeper = keeper
        result = export(port)
        self.assertEqual(result.health["deferred_left"], ["Sketch1"])
        self.assertTrue(health_module.design_changed(result.health))

    def test_a_sketch_the_end_rebuild_moves_is_reported_as_drift(self):
        moved = []  # the full rebuild of the end check, with every value back and a step changed, moves the sketch

        def rebuilt(store):
            if store.exprs == store.saved and store.health != store.START_STEPS:
                moved.append(True)

        store = StepStore({"Fillet1": "warning"}, heals={"Fillet1": "compute"}, on_recompute=rebuilt)
        port = FakePort(store=store, reader=lambda request: shifted(port.e0, 0.5) if moved else port.e0)
        result = export(port)
        self.assertTrue(result.health["sketch_drift"])
        self.assertTrue(health_module.design_changed(result.health))


if __name__ == "__main__":
    unittest.main()
