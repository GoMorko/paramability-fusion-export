"""A try that leaves only steps outside what the tries need worse with the values back ends the tries of the sizes
behind it, and the other sizes are tried in full; the export is undone at its end. A worse step that the tries need
still stops every try."""
import copy
import dataclasses
import json
import re
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.test_geometry_links import CAPTURE, MODEL, USER

from lib.design_edit.runner import row_key
from lib.export_plan import health as health_module
from lib.export_plan import undo_steps
from lib.export_plan.pipeline import ExportRequest, ProbeRun, run_pipeline
from lib.export_plan.pipeline.outside_damage import OutsideDamage
from lib.export_plan.probe_flow import ProbeGroup, SizeProbe
from lib.export_plan.rollback import ExportOutcome, decide
from lib.export_plan.size_offers import table_for_body

START = {p["name"]: p["expression"] for p in USER}
# A fillet of a holder component next to the box: no step of the box uses it.
HOLDER_FILLET = {"index": 6, "name": "Fillet1", "type": "FilletFeature", "component": "cmp_holder",
                 "in_target_component": False, "target_changed": False, "bodies_after": [], "data": {}}


def mm(store, name):
    return float(re.match(r"\s*([-0-9.eE+]+)", store.exprs[name]).group(1))


def holder_capture(drives=()):
    """The box with a pipe hole, and a holder fillet after its steps; the parameters in `drives` also drive a pocket
    of the holder."""
    capture = copy.deepcopy(CAPTURE)
    capture["items"].append(dict(HOLDER_FILLET))
    capture["marker"] = {"position": 7, "count": 7}
    for param in capture["parameters"]["user"]:
        if param["name"] in drives:
            param["dependents"] = param["dependents"] + [
                {"name": "d40", "kind": "feature", "component": "cmp_holder", "feature": "Pocket1"}]
    return capture


class HolderStore(FakeStore):
    """A store whose timeline reads every item of `capture` with its position. Once `damages(store)` held at a
    rebuild, the step named `lost` stays in warning for good, also with the values back, as a step that lost an edge.
    `at` is the position the timeline gives that step, when it is not its capture position (None: no position)."""

    def __init__(self, capture, damages, lost="Fillet1", at=False):
        super().__init__(START, on_recompute=self._rebuilt)
        self.items, self.damages, self.lost, self.damaged, self.at = capture["items"], damages, lost, False, at
        self.rebuilt = []  # hooks called at each rebuild

    def _rebuilt(self, store):
        self.damaged = self.damaged or self.damages(self)
        for hook in self.rebuilt:
            hook(self)

    def _health(self, item):
        return "warning" if self.damaged and item["name"] == self.lost else "ok"

    def _index(self, item):
        return self.at if self.at is not False and item["name"] == self.lost else item["index"]

    def timeline_health(self):
        return [{"index": self._index(i), "name": i["name"], "type": i["type"], "health": self._health(i),
                 "message": "", "suppressed": False} for i in self.items]

    def warning_entries(self):
        return [(self._index(i), i["name"]) for i in self.items if self._health(i) == "warning"]


def holder_port(capture, damages, lost="Fillet1", at=False, skew=None):
    """Fusion where the box outline (and its box and volume) follows width and depth, and the hole follows the pipe.
    With `skew`, once the step is damaged the part reads otherwise with the values back: "body" (another volume) or
    "sketch" (the hole moved)."""
    def read(request):
        out = copy.deepcopy(port.e0)
        sx, sy = mm(port.store, "width_mm") / 40.0, mm(port.store, "depth_mm") / 30.0
        scales = {"s1": (sx, sy), "s2": (mm(port.store, "pipe_d_mm") / 12.0,) * 2}
        for token, (fx, fy) in scales.items():
            for loop in out["sketches"][token]["profiles"][0]["loops"]:
                for curve in loop["curves"]:
                    for key in ("start", "end", "mid", "center"):
                        if key in curve:
                            curve[key] = [curve[key][0] * fx, curve[key][1] * fy]
                    if "radius" in curve:
                        curve["radius"] *= fx
        out["box"] = {"min": [0, 0, 0], "max": [mm(port.store, "width_mm"), mm(port.store, "depth_mm"), 10]}
        out["volume_mm3"] = mm(port.store, "width_mm") * mm(port.store, "depth_mm") * 10
        if skew == "body" and port.store.damaged:
            out["volume_mm3"] += 50.0
        if skew == "sketch" and port.store.damaged:
            for curve in out["sketches"]["s2"]["profiles"][0]["loops"][0]["curves"]:
                for key in ("start", "end", "mid", "center"):
                    curve[key] = [curve[key][0] + 1.0, curve[key][1]]
        return out

    port = FakePort(capture=capture, store=HolderStore(capture, damages, lost, at), reader=read)
    return port


def export(port, capture, light_undo=False):
    """The result and the rollback of one export of the box with every size ticked."""
    if light_undo:
        undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
    outcome = ExportOutcome()
    request = ExportRequest(title="Box", writer="test", up_axis="z", parameters=capture["parameters"]["user"],
                            model_params=MODEL, design_unit="mm",
                            ticked=table_for_body(USER, "mm", MODEL, capture).ticked, ranges={}, outcome=outcome)
    with tempfile.TemporaryDirectory() as tmp:
        result = run_pipeline(port, dataclasses.replace(request, faster_tries=False), tmp)
    return result, decide(outcome)


def wide(store):
    return mm(store, "width_mm") > 50


def far_states(result, name):
    """The values of `name` tried alone in the states of the report."""
    return sorted(s["values"][name] for s in result.report["probe"]["states"] if list(s["values"]) == [name])


def after_end(result, names):
    """The states of the report after the first state with the width past 50 mm that set one of `names`."""
    states = result.report["probe"]["states"]
    bad = next(at for at, s in enumerate(states) if s["values"].get("width_mm", 0) > 50)
    return bad, [s for s in states[bad + 1:] if set(names) & set(s["values"])]


def row(key, values):
    return {"name": key, "key": key, "label": key, "values": dict(values), "varied": sorted(values),
            "state": dict(values), "step": False}


class SizeOnlyStopTest(unittest.TestCase):
    def test_a_lasting_change_of_another_component_ends_only_the_sizes_behind_it(self):
        capture = holder_capture()
        port = holder_port(capture, wide)
        result, verdict = export(port, capture)
        probe = result.report["probe"]
        self.assertNotIn("stopped", probe)
        [ended] = probe["ended"]
        self.assertEqual((ended["items"], ended["sizes"]), (["Fillet1"], ["width_mm"]))
        # The depth got both range ends after the width ended, and no later try set the width.
        self.assertTrue({15.0, 60.0} <= set(far_states(result, "depth_mm")))
        self.assertEqual(after_end(result, ["width_mm"])[1], [])
        health = result.health
        self.assertEqual((health["tries_ended"][0]["items"], health["tries_ended"][0]["others_full"]),
                         (["Fillet1"], True))
        self.assertTrue(health_module.any_worse(health))  # the end check found the step changed
        self.assertTrue(verdict.abort)
        self.assertEqual(port.store.exprs, START)

    def test_once_lighter_on_memory_dropped_undo_data_every_try_stops(self):
        capture = holder_capture()
        port = holder_port(capture, wide)
        result, verdict = export(port, capture, light_undo=True)
        probe = result.report["probe"]
        self.assertEqual(probe["stopped"]["items"], ["Fillet1"])
        self.assertNotIn("ended", probe)
        self.assertTrue(verdict.undo_unavailable)
        bad, _ = after_end(result, [])
        self.assertTrue(0 < port.undo_steps.record["steps"] <= bad)  # dropped before the damaging try only

    def test_a_lasting_change_while_the_part_reads_otherwise_stops_every_try(self):
        for skew in ("body", "sketch"):
            with self.subTest(skew=skew):
                capture = holder_capture()
                result, verdict = export(holder_port(capture, wide, skew=skew), capture)
                self.assertEqual(result.report["probe"]["stopped"]["items"], ["Fillet1"])
                self.assertNotIn("ended", result.report["probe"])
                self.assertTrue(verdict.abort)

    def test_a_worse_step_that_a_part_is_built_from_stops_every_try(self):
        capture = holder_capture()
        # A step of another component that built a body the box was split from: the box is built from it.
        capture["items"][-1]["body_states"] = {"b0": {"box_before": None, "volume_before": None,
                                                      "volume_after": 100.0}}
        result, _ = export(holder_port(capture, wide), capture)
        self.assertEqual(result.report["probe"]["stopped"]["items"], ["Fillet1"])
        self.assertNotIn("ended", result.report["probe"])

    def test_a_worse_step_without_a_matching_position_stops_every_try(self):
        for at in (None, 9, 3):  # no position, a position no item has, the position of another item
            with self.subTest(at=at):
                capture = holder_capture()
                result, _ = export(holder_port(capture, wide, at=at), capture)
                self.assertEqual(result.report["probe"]["stopped"]["items"], ["Fillet1"])
                self.assertNotIn("ended", result.report["probe"])

    def test_the_sizes_walked_back_before_the_try_end_with_it(self):
        # A pipe of 20 mm leaves the hole sketch on another outline; walking the pipe back from below brings it back,
        # and that walk makes the holder fillet lose its edge. The depth row after it is blamed with the pipe.
        capture = holder_capture()
        port = holder_port(capture, lambda store: mm(store, "pipe_d_mm") < 12)
        port.flipped = False

        def flip(store):
            port.flipped = (port.flipped or mm(store, "pipe_d_mm") > 18) and not mm(store, "pipe_d_mm") < 12

        port.store.rebuilt.append(flip)
        read = port.reader

        def flipped_read(request):
            out = read(request)
            if port.flipped:
                loops = out["sketches"]["s2"]["profiles"][0]["loops"]
                loops.append(dict(copy.deepcopy(loops[0]), outer=False))
            return out

        port.reader = flipped_read
        probe = SizeProbe.start(capture, table_for_body(USER, "mm", MODEL, capture), port.probe_reader())
        run = ProbeRun(port, "", probe, captures=[capture])
        run._tried = {"pipe_d_mm", "depth_mm"}
        run.run_rows([row("pipe", {"pipe_d_mm": 20.0}), row("deep", {"depth_mm": 40.0})])
        run.check_pending()
        self.assertIsNone(run.stopped)
        [ended] = run.ended
        self.assertEqual(set(ended["sizes"]), {"depth_mm", "pipe_d_mm"})

    def test_the_sizes_that_drive_that_component_end_too_and_their_rows_do_not_run(self):
        capture = holder_capture(drives=("height_mm",))
        port = holder_port(capture, wide)
        result, _ = export(port, capture)
        [ended] = result.report["probe"]["ended"]
        self.assertEqual(set(ended["sizes"]), {"width_mm", "height_mm"})
        # No far row, far pair row or check row moves them after the end.
        self.assertEqual(after_end(result, ["width_mm", "height_mm"])[1], [])

    def test_only_an_ended_size_whose_far_tries_never_ran_stops_at_the_values_that_built(self):
        capture = holder_capture(drives=("height_mm",))
        result, _ = export(holder_port(capture, wide), capture)
        sizes = json.loads(result.files["recipe.json"])["sizes"]
        self.assertEqual({name: (size["min"], size["max"]) for name, size in sizes.items()},
                         {"width_mm": (20.0, 80.0), "depth_mm": (15.0, 60.0), "height_mm": (15.0, 25.0),
                          "pipe_d_mm": (6.0, 24.0)})
        self.assertEqual([cut["name"] for cut in result.report["sizes"]["cut"]], ["height_mm"])

    def test_a_row_planned_before_the_end_that_moves_an_ended_size_does_not_run(self):
        for parts in (1, 2):
            with self.subTest(parts=parts):
                capture = holder_capture()
                port = holder_port(capture, wide)
                tbl = table_for_body(USER, "mm", MODEL, capture)
                probes = [SizeProbe.start(capture, tbl, port.probe_reader()) for _ in range(parts)]
                probe = probes[0] if parts == 1 else ProbeGroup(probes, ["A", "B"])
                run = ProbeRun(port, "", probe, captures=[capture] * parts)
                run.run_rows([row("wide", {"width_mm": 80.0}), row("pair", {"width_mm": 30.0, "depth_mm": 40.0}),
                              row("deep", {"depth_mm": 40.0})])
                self.assertEqual([row_key(r) for r, _ in run.rows], ["wide", "deep"])
                self.assertEqual((run.stopped, run.ended_names), (None, ["width_mm"]))
                self.assertEqual([len(p.ended) for p in probes], [1] * parts)
                self.assertFalse(run.job.back_clean)

    def test_a_time_limit_after_the_end_means_the_other_sizes_were_not_tried_in_full(self):
        capture = holder_capture()
        port = holder_port(capture, wide)
        probe = SizeProbe.start(capture, table_for_body(USER, "mm", MODEL, capture), port.probe_reader())
        clock = [0.0]
        run = ProbeRun(port, "", probe, captures=[capture], time_limit=100, clock=lambda: clock[0])
        run.run_rows([row("wide", {"width_mm": 80.0}), row("deep", {"depth_mm": 40.0})])
        self.assertTrue(run.ended_records()[0]["others_full"])
        clock[0] = 1000.0
        run.run_rows([row("tall", {"height_mm": 30.0})])
        self.assertTrue(run.job.halted)
        self.assertFalse(run.ended_records()[0]["others_full"])

    def test_a_row_of_an_ended_size_that_would_run_again_keeps_its_first_run(self):
        capture = holder_capture()
        port = holder_port(capture, wide)
        probe = SizeProbe.start(capture, table_for_body(USER, "mm", MODEL, capture), port.probe_reader())
        run = ProbeRun(port, "", probe, captures=[capture])
        again = row("wide", {"width_mm": 80.0})
        # As if the read after the wide row had shown a sketch off its start.
        with mock.patch.object(ProbeRun, "_again", lambda self, since: [("wide", dict(again, key="wide (again)"))]):
            run.run_rows([again, row("deep", {"depth_mm": 40.0})])
        self.assertEqual(run.redone, [])
        self.assertTrue([s for s in probe.states if s.values == {"width_mm": 80.0}])

    def test_a_worse_step_that_the_tries_need_still_stops_every_try(self):
        capture = holder_capture()
        # The pipe's extrude: the hole of the box follows it through a link, so the tries need it.
        port = holder_port(capture, wide, lost="PipeExtrude")
        result, verdict = export(port, capture)
        probe = result.report["probe"]
        self.assertEqual(probe["stopped"]["items"], ["PipeExtrude"])
        self.assertNotIn("ended", probe)
        self.assertTrue(verdict.abort)


class OutsideDamageTest(unittest.TestCase):
    def test_a_step_of_another_part_of_the_export_is_not_outside_and_nor_is_a_part_not_read(self):
        capture = holder_capture()
        # The holder is a part of the same export too, with no sketch the tries follow.
        holder = copy.deepcopy(capture)
        holder["target"] = {"component": {"token": "cmp_holder", "name": "Holder"}}
        for item in holder["items"]:
            item["in_target_component"] = item["component"] == "cmp_holder"
        worse = [{"index": 6, "name": "Fillet1", "before": "ok", "after": "warning"}]
        tried = {"varied": ["width_mm"]}
        self.assertIsNotNone(OutsideDamage([capture]).judge(worse, tried))
        self.assertIsNone(OutsideDamage([capture], [capture, holder]).judge(worse, tried))
        self.assertIsNone(OutsideDamage([capture], [capture, RuntimeError("the read failed")]).judge(worse, tried))


if __name__ == "__main__":
    unittest.main()
