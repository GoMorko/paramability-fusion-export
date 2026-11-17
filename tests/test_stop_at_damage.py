"""The tries stop at the first try that leaves a timeline step worse with the values back, after one attempt to bring
the design back the way the try took it away; a sketch read with new tokens but the same curves is no flip; the end
check counts a sketch on another outline and a changed body as a changed design."""
import copy
import dataclasses
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.probe_helpers import circle, line, loop, table
from tests.test_probe_flow import START, UNITS, Fusion, TwoSolutionFusion, keyed, number, on_other_solution, size_row
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, read_at

from lib.design_edit.runner import RowExport
from lib.export_plan import health as health_module
from lib.export_plan import undo_steps
from lib.export_plan.pipeline import ProbeRun, run_pipeline
from lib.export_plan.probe_flow import SizeProbe
from lib.geometry.tolerances import FLIP_TOLERANCE
from lib.probe.same_shape import shape_gap


def step(index, name, health="ok"):
    return {"index": index, "name": name, "type": "Sketch", "health": health, "message": "", "suppressed": False}


class HealthStore(FakeStore):
    """A store whose timeline reads its steps through `steps(store)`: `{ name: health }` of the steps after the first,
    which is always fine."""

    def __init__(self, steps, **options):
        super().__init__(START, **options)
        self.steps = steps

    def timeline_health(self):
        return [step(0, "Sketch1")] + [step(at, name, health)
                                       for at, (name, health) in enumerate(self.steps(self).items(), start=1)]


def rows(*pairs):
    return keyed(*(size_row(name, value) for name, value in pairs))


def run_job(store, plan, counts_warning=None):
    job = RowExport(store, UNITS, lambda path: None, counts_warning=counts_warning)
    return job, job.run(plan, "", lambda *a: True, tolerate_build_errors=True)


class StopAtDamageTest(unittest.TestCase):
    """`RowExport` checks the steps after a row that may have left the design changed, against its baseline."""

    def test_a_step_that_stays_worse_after_a_row_stops_the_tries_there(self):
        damaged = []

        def solve(store):
            if number(store.exprs["off"]) == 10:
                damaged.append(True)

        store = HealthStore(lambda s: {"Sketch5": "warning" if damaged else "ok"},
                            bad_when=lambda e: number(e["off"]) == 10, on_recompute=solve)
        job, results = run_job(store, rows(("height", 30.0), ("off", 10.0), ("cube", 20.0), ("height", 40.0)))
        self.assertEqual(len(results), 2)
        self.assertEqual((job.not_back["after"], job.not_back["items"]), ("off (max)", ["Sketch5"]))
        self.assertEqual(job.recoveries, 2)  # both ways back were tried before the stop
        self.assertNotIn(("cube", "20 mm"), store.sets)
        self.assertEqual(store.exprs, START)

    def test_a_warning_that_a_full_recompute_clears_lets_the_tries_go_on(self):
        class Partial(HealthStore):
            """Values go in as one change; that rebuild leaves Sketch5 warned after a deep pocket, until a full
            recompute with the values back."""

            warn = False

            def set_expressions(self, expressions):
                self.exprs.update(expressions)
                self.warn = self.warn or number(self.exprs["off"]) == 10
                return True

            def recompute(self):
                self.warn = self.warn and self.exprs != START
                return super().recompute()

        store = Partial(lambda s: {"Sketch5": "warning" if s.warn else "ok"},
                        bad_when=lambda e: number(e["off"]) == 10)
        job, results = run_job(store, rows(("off", 10.0), ("cube", 20.0), ("height", 40.0)))
        self.assertEqual(len(results), 3)
        self.assertIsNone(job.not_back)
        self.assertEqual(job.recoveries, 0)

    def test_a_warning_the_design_had_before_the_tries_is_not_the_tries_doing(self):
        store = HealthStore(lambda s: {"Sketch5": "warning"}, bad_when=lambda e: number(e["off"]) == 10)
        job, results = run_job(store, rows(("off", 10.0), ("cube", 20.0), ("height", 40.0)))
        self.assertEqual((len(results), job.not_back), (3, None))

    def test_a_row_with_a_new_warning_is_checked_as_a_row_that_did_not_build(self):
        def warns(exprs):
            return [(2, "Fillet2")] if number(exprs["off"]) == 10 else []

        def steps(store):
            return {"Fillet2": "warning" if store.exprs != START else "ok", "Sketch5": "warning" if seen else "ok"}

        for counted in (True, False):
            with self.subTest(counted=counted):
                seen = []
                store = HealthStore(steps, warns=warns,
                                    on_recompute=lambda s: seen.append(1) if number(s.exprs["off"]) == 10 else None)
                job, results = run_job(store, rows(("off", 10.0), ("cube", 20.0)),
                                       counts_warning=lambda name: counted)
                self.assertEqual(len(results), 1)
                self.assertEqual(job.not_back["items"], ["Sketch5"])


def lid_with(curves):
    """A read whose lid sketch holds one profile of `curves`."""
    found = read_at()
    found["sketches"]["sk2"] = dict(found["sketches"]["sk2"], profiles=[{"loops": [loop(curves)]}])
    return found


SQUARE = [line((0, 0), (10, 0), "a"), line((10, 0), (10, 10), "b"), line((10, 10), (0, 10), "c"),
          line((0, 10), (0, 0), "d")]


class SameShapeTest(unittest.TestCase):
    """Only a real geometric difference between two reads of a sketch is a flip."""

    def sketch(self, *profiles):
        return {"frame": read_at()["sketches"]["sk2"]["frame"], "profiles": [{"loops": [loop(p)]} for p in profiles]}

    def test_new_tokens_another_direction_or_another_order_give_the_same_shape(self):
        other = [line((20, 0), (30, 0), "e"), line((30, 0), (25, 5), "f"), line((25, 5), (20, 0), "g")]
        before = self.sketch(SQUARE, other)
        renamed = [dict(c, entity=c["entity"] + "2") for c in SQUARE]
        turned = [dict(c, start=c["end"], end=c["start"]) for c in reversed(SQUARE)]
        for name, now in (("tokens", self.sketch(renamed, other)), ("direction", self.sketch(turned, other)),
                          ("order", self.sketch(other, SQUARE))):
            with self.subTest(name):
                self.assertEqual(shape_gap(before, now, FLIP_TOLERANCE), 0.0)

    def test_a_short_segment_lost_is_another_shape(self):
        with_step = SQUARE[:3] + [line((0, 10), (0, 0.01), "d"), line((0, 0.01), (0, 0), "s")]
        self.assertIsNone(shape_gap(self.sketch(with_step), self.sketch(SQUARE), FLIP_TOLERANCE))

    def test_a_line_read_as_two_tokens_where_profiles_meet_is_no_flip_and_another_outline_is(self):
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), Fusion().read)
        split = copy.deepcopy(read_at())
        curve = split["sketches"]["sk2"]["profiles"][0]["loops"][0]["curves"][0]
        curve["entity"] = "c2-new"
        self.assertEqual(probe.off_start(split), [])
        self.assertEqual(probe.off_start(on_other_solution(read_at())), ["sk2"])
        self.assertEqual(probe.off_start(lid_with([circle((0, 0), 3, "c2"), circle((0, 0), 0.5, "c9")])), ["sk2"])


class PerSketchPutBackTest(unittest.TestCase):
    def test_a_sketch_that_cannot_be_put_back_does_not_stop_the_put_back_of_another(self):
        fusion = TwoSolutionFusion(lambda before, now: number(before["cube"]) == 20 and now == START)
        read = fusion.read

        def base_stuck(request):  # Sketch1 lost its hole for good from the first read on
            found = read(request)
            if len(fusion.requests) > 1:
                found["sketches"]["sk1"] = read_at(with_hole=False)["sketches"]["sk1"]
            return found

        class Keeper:  # puts the lid back, never the base
            @staticmethod
            def put_back():
                fusion.flipped = False

        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), base_stuck)
        port = FakePort(store=fusion.store, units=UNITS, keeper=lambda tokens: Keeper())
        undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
        run = ProbeRun(port, "", probe)
        run.run_rows(rows(("height", 30.0), ("off", 8.0), ("height", 40.0), ("cube", 20.0), ("off", 9.0)))
        last = next(s for s in probe.states if s.values == {"off": 9.0})
        self.assertEqual(probe.off_start(last.start), ["sk1", "sk2"])
        self.assertEqual(probe.off_start(last.put_back), ["sk1"])
        # Only the first row starts with every sketch as at the start: the undo data is dropped before it alone.
        self.assertEqual(port.undo_steps.record["steps"], 1)


class SketchStepFusion(TwoSolutionFusion):
    """The lid sketch flips at a tall lid; a later sketch that projects an edge of it shows a warning while it stays
    flipped. `back_from_below` brings it back when the height comes back from below its start value."""

    def __init__(self, back_from_below):
        def flips(before, now):
            return number(now["height"]) == 40

        def settles(before, now):
            return back_from_below and number(before["height"]) < 20 and now == START

        super().__init__(flips, settles)
        store = self.store
        self.store = HealthStore(lambda s: {"Sketch3": "warning" if self.flipped else "ok"},
                                 on_recompute=store.on_recompute)


def damage_run(back_from_below):
    fusion = SketchStepFusion(back_from_below)
    probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
    port = FakePort(store=fusion.store, units=UNITS)
    undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
    run = ProbeRun(port, "", probe)
    run.run_rows(rows(("off", 8.0), ("height", 40.0), ("cube", 20.0), ("off", 9.0)))
    run.settle()
    return fusion, run, probe, port


class WalkBackTest(unittest.TestCase):
    def test_a_flipped_sketch_comes_back_from_the_other_side_and_the_tries_go_on(self):
        fusion, run, probe, _ = damage_run(back_from_below=True)
        self.assertIsNone(run.stopped)
        self.assertEqual(len(run.rows), 4)
        self.assertEqual(run.job.recoveries, 1)
        self.assertFalse(fusion.flipped)
        self.assertEqual(fusion.store.exprs, START)

    def test_a_walk_back_that_fails_stops_the_tries_and_keeps_the_undo_data_from_then_on(self):
        fusion, run, probe, port = damage_run(back_from_below=False)
        self.assertEqual((run.stopped["after"], run.stopped["items"]), ("height (max)", ["Sketch3"]))
        self.assertEqual(len(run.rows), 2)
        self.assertEqual(probe.stopped["steps"], [{"name": "Sketch3", "before": "ok", "after": "warning"}])
        self.assertEqual(port.undo_steps.record["steps"], 2)  # before the first two rows only
        self.assertEqual(fusion.store.exprs, START)

    def test_a_flip_the_keeper_cannot_fix_is_walked_back_before_the_next_row(self):
        fusion = TwoSolutionFusion(lambda before, now: number(now["height"]) == 40,
                                   lambda before, now: number(before["height"]) < 20 and now == START)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        run = ProbeRun(FakePort(store=fusion.store, units=UNITS), "", probe)
        run.run_rows(rows(("height", 40.0), ("off", 8.0), ("cube", 20.0)))
        nxt = next(s for s in probe.states if s.values == {"off": 8.0})
        self.assertEqual((probe.off_start(nxt.start), probe.off_start(nxt.put_back)), (["sk2"], []))
        self.assertEqual(run.job.recoveries, 1)
        later = next(s for s in probe.states if s.values == {"cube": 20.0})
        self.assertFalse(probe.off_outline(later.read))  # the later row ran on the first solution

    def test_after_the_tries_a_sketch_still_flipped_is_walked_back(self):
        fusion = TwoSolutionFusion(lambda before, now: False,
                                   lambda before, now: number(before["height"]) < 20 and now == START)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        run = ProbeRun(FakePort(store=fusion.store, units=UNITS), "", probe)
        run.run_rows(rows(("height", 40.0)))
        fusion.flipped = True  # the last try left it there
        run.settle()
        self.assertFalse(fusion.flipped)
        self.assertEqual(fusion.store.exprs, START)


class EndCheckTest(unittest.TestCase):
    def test_a_body_that_differs_at_the_end_is_a_changed_design_with_a_warning(self):
        from tests.test_pipeline import request
        port = None

        def reader(request):
            found = dict(port.e0, box={"min": [0, 0, 0], "max": [10, 10, 10]}, volume_mm3=1000.0)
            if request.get("target") and not request.get("sketches"):  # the body read after the export
                found["volume_mm3"] = 1010.0
            return found

        port = FakePort(reader=reader)
        with tempfile.TemporaryDirectory() as tmp:
            health = run_pipeline(port, dataclasses.replace(request(), faster_tries=False), tmp).health
        self.assertTrue(health["body_changed"])
        self.assertTrue(health_module.design_changed(health))
        self.assertFalse(health_module.back_as_it_was(health))
        self.assertTrue(any("1010" in text for text in health_module.health_lines(health)))


if __name__ == "__main__":
    unittest.main()
