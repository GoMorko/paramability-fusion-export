"""The tries stop at the first try that leaves a timeline step worse with the values back, after one attempt to bring
the design back the way the try took it away; a sketch read with new tokens but the same curves is no flip; the end
check counts a sketch on another outline and a changed body as a changed design."""
import copy
import dataclasses
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.probe_helpers import circle, line, loop, table
from tests.test_probe_flow import START, UNITS, Fusion, TwoSolutionFusion, keyed, number, on_other_solution, size_row
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, read_at

from lib.design_edit import walk_back
from lib.design_edit.runner import RowExport
from lib.export_plan import health as health_module
from lib.export_plan import undo_steps
from lib.export_plan.pipeline import ProbeRun, run_pipeline
from lib.export_plan.probe_flow import SizeProbe
from lib.export_plan.probe_flow.states import body_difference
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

    def warning_entries(self):
        """The steps in warning, as Fusion reads them from the same health as the timeline."""
        found = dict(super().warning_entries())
        for at, (name, health) in enumerate(self.steps(self).items(), start=1):
            if health == "warning" and name not in found.values():
                found[at] = name
        return list(found.items())


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

    def test_a_warning_that_does_not_count_and_is_gone_with_the_values_back_costs_no_timeline_read(self):
        class Counted(HealthStore):
            reads = 0

            def timeline_health(self):
                self.reads += 1
                return super().timeline_health()

        def warns(exprs):
            return [(2, "Fillet2")] if number(exprs["off"]) == 10 else []

        store = Counted(lambda s: {"Fillet2": "warning" if s.exprs != START else "ok"}, warns=warns)
        job, results = run_job(store, rows(("off", 10.0), ("cube", 20.0)), counts_warning=lambda name: False)
        self.assertEqual((len(results), job.not_back, store.reads), (2, None, 1))  # the baseline read only


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


def from_below(before, now):
    return number(before["height"]) < 20 and now == START


def back_from_tall(fusion_rows, flips_on, settles=from_below):
    """A run whose lid sketch flips when `flips_on(before, now)` holds and comes back when `settles(before, now)` holds
    (by default when the height returns from below its start value); no keeper. Returns the fusion, the run and the
    probe once `fusion_rows` ran."""
    fusion = TwoSolutionFusion(flips_on, settles)
    probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
    run = ProbeRun(FakePort(store=fusion.store, units=UNITS), "", probe)
    run.run_rows(fusion_rows)
    return fusion, run, probe


def pair_row(key, values):
    return {"name": key, "key": key, "values": dict(values), "varied": list(values), "state": dict(values),
            "step": False}


def from_tall_to_start(before, now):
    return number(before["height"]) == 40 and now == START


class WalkBackTargetTest(unittest.TestCase):
    """The walk back targets the rows run since a sketch last read as at its start, not only the row run last."""

    def test_a_flip_first_seen_two_rows_later_is_walked_back_with_the_size_of_the_row_that_made_it(self):
        # The tall row reads the first outline; the flip comes as the values go back and shows only in the next row.
        fusion, run, probe = back_from_tall(rows(("cube", 20.0), ("height", 40.0), ("off", 8.0), ("cube", 21.0)),
                                            from_tall_to_start)
        last = next(s for s in probe.states if s.values == {"cube": 21.0})
        self.assertEqual((probe.off_start(last.start), probe.off_start(last.put_back)), (["sk2"], []))
        brought = [w for w in run.job.walks if w.get("back")]
        self.assertEqual([(w["row"], list(w["set"][0])) for w in brought], [("r1", ["height"])])
        self.assertFalse(probe.off_outline(last.read))

    def test_after_the_tries_each_size_of_the_last_rows_is_walked_back_alone_until_the_sketch_is_back(self):
        def height_alone(before, now):  # the height comes back from below with every other size at its start
            return from_below(before, now) and number(before["off"]) == 5

        plan = keyed(size_row("cube", 20.0), pair_row("pair", {"off": 8.0, "height": 40.0}))
        fusion, run, probe = back_from_tall(plan, from_tall_to_start, height_alone)
        run.settle()
        self.assertFalse(fusion.flipped)
        self.assertTrue(run.end.back)
        self.assertEqual(fusion.store.exprs, START)
        attempts = probe.recovery["attempts"]
        self.assertEqual([(a["at"], list(a["set"][0]), a["back"]) for a in attempts],
                         [("end", ["off"], False), ("end", ["height"], True)])  # the cube is not tried

    def test_the_walks_after_the_tries_stop_at_their_bound(self):
        plan = keyed(size_row("cube", 20.0), size_row("off", 8.0), size_row("height", 40.0), size_row("cube", 5.0))
        fusion, run, probe = back_from_tall(plan, lambda before, now: False, lambda before, now: False)
        fusion.flipped = True  # a flip no walk brings back
        with mock.patch.object(walk_back, "END_TRIES", 3):
            run.settle()
        self.assertEqual(run.job.recoveries, 3)
        self.assertFalse(run.end.back)
        self.assertEqual(fusion.store.exprs, START)

class PendingCheckTest(unittest.TestCase):
    """The damage of the row run last is checked before any Undo drop and before the discovery baseline."""

    def damage_last(self):
        """A run whose last row does not build and leaves Sketch5 in warning for good; the sketches read as at the
        start, so no read asks for the row to run again."""
        damaged = []

        def solve(store):
            if number(store.exprs["off"]) == 10:
                damaged.append(True)

        fusion = Fusion()
        fusion.store = HealthStore(lambda s: {"Sketch5": "warning" if damaged else "ok"},
                                   bad_when=lambda e: number(e["off"]) == 10, on_recompute=solve)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        port = FakePort(store=fusion.store, units=UNITS)
        undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
        run = ProbeRun(port, "", probe, before_discovery=lambda: self.rebased.append(True))
        run.run_rows(rows(("off", 10.0)))
        return run, probe, port

    def setUp(self):
        self.rebased = []

    def test_the_last_row_is_checked_before_the_undo_data_is_dropped(self):
        run, probe, port = self.damage_last()
        dropped = port.undo_steps.record["steps"]
        run.settle()
        self.assertEqual(run.stopped["items"], ["Sketch5"])
        self.assertEqual(port.undo_steps.record["steps"], dropped)
        self.assertEqual(probe.stopped["items"], ["Sketch5"])

    def test_a_lasting_damage_of_the_last_measured_row_stops_before_the_discovery_rows(self):
        run, probe, port = self.damage_last()
        tbl = table(PARAMS, TICKED, MODEL)
        from tests.test_probe_flow import size
        found = run.discover([dict(size(tbl, "cube", "mm"), end=12.0)])
        self.assertEqual(found, [])
        self.assertIsNotNone(run.stopped)
        self.assertEqual(self.rebased, [])  # the items were not turned on and the baseline kept
        self.assertEqual(len(run.rows), 1)

    def test_an_unreadable_timeline_keeps_the_undo_data_but_does_not_stop_the_tries(self):
        def unreadable(store):
            raise RuntimeError("the timeline cannot be read")

        store = HealthStore(unreadable, bad_when=lambda e: number(e["off"]) == 10)
        port = FakePort(store=store, units=UNITS)
        undo_steps.attach(port, undo_steps.UndoSteps(lambda flag: True, port.log))
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), Fusion().read)
        run = ProbeRun(port, "", probe)
        run.run_rows(rows(("off", 10.0), ("cube", 20.0), ("height", 40.0)))
        run.settle()
        self.assertEqual((len(run.rows), run.stopped), (3, None))
        self.assertFalse(run.job.back_clean)
        self.assertEqual(port.undo_steps.record["steps"], 0)


class WalkErrorTest(unittest.TestCase):
    def test_an_error_inside_a_walk_still_puts_the_values_back(self):
        class Breaks(FakeStore):
            def read_value(self, name):
                if self.exprs != START:
                    raise RuntimeError("Fusion stopped answering")
                return super().read_value(name)

        store = Breaks(START)
        job = RowExport(store, UNITS, lambda path: None)
        job.run([], "", lambda *a: True)
        with self.assertRaises(RuntimeError):
            job.walk_back(size_row("height", 40.0), 0)
        self.assertEqual(store.exprs, START)


def body_read(volume, box=(10, 10, 10), others=None):
    found = {"box": {"min": [0, 0, 0], "max": list(box)}, "volume_mm3": volume, "pieces": {"lumps": 1}}
    if others is not None:
        found["pieces"].update(others=[{"min": [20, 0, 0], "max": [30, h, 10]} for _, h in others],
                               names=[name for name, _ in others])
    return found


class BodyDifferenceTest(unittest.TestCase):
    def test_a_rebuild_of_the_same_shape_is_no_difference_and_a_real_change_is_clear(self):
        same = body_difference(body_read(1601.25), body_read(1601.25 * (1 + 1e-9), box=(10, 10, 10 + 1e-6)))
        self.assertEqual((same.clear, same.small), ([], []))
        moved = body_difference(body_read(1601.25), body_read(1618.42, box=(10, 10, 10.35)))
        self.assertEqual((len(moved.clear), moved.small), (2, []))

    def test_a_tiny_volume_change_is_small_not_clear(self):
        found = body_difference(body_read(58384.6), body_read(58384.7))
        self.assertEqual((found.clear, len(found.small)), ([], 1))

    def test_other_bodies_are_compared_by_name_not_by_order(self):
        a = body_read(1000.0, others=[("Lid", 5), ("Pin", 8)])
        b = body_read(1000.0, others=[("Pin", 8), ("Lid", 5)])
        self.assertEqual(body_difference(a, b).texts, [])
        gone = body_read(1000.0, others=[("Pin", 8), ("Clip", 5)])
        self.assertEqual(len(body_difference(a, gone).clear), 1)

    def test_a_read_without_a_box_or_a_volume_cannot_be_compared(self):
        self.assertIsNone(body_difference(body_read(1000.0), {"volume_mm3": 1000.0}))
        self.assertIsNone(body_difference(body_read(1000.0), dict(body_read(1000.0), volume_mm3=None)))


class EndCheckTest(unittest.TestCase):
    def export(self, volumes, store=None, steps=None):
        """The health of one export whose body reads in turn `volumes` (mm3; the last one repeats) after its E0."""
        from tests.test_pipeline import request
        port, seen = None, []

        def reader(request):
            found = dict(port.e0, box={"min": [0, 0, 0], "max": [10, 10, 10]}, volume_mm3=1000.0)
            if request.get("target") and not request.get("sketches"):  # a read of the body alone
                found["volume_mm3"] = volumes[min(len(seen), len(volumes) - 1)]
                seen.append(found["volume_mm3"])
            return found

        port = FakePort(reader=reader, store=store)
        with tempfile.TemporaryDirectory() as tmp:
            return run_pipeline(port, dataclasses.replace(request(), faster_tries=False), tmp).health

    def test_a_body_that_differs_at_the_end_is_a_changed_design_with_a_warning(self):
        health = self.export([1000.0, 1010.0])
        self.assertEqual(len(health["body_changed"]), 1)
        self.assertTrue(health_module.design_changed(health))
        self.assertFalse(health_module.back_as_it_was(health))
        self.assertTrue(health_module.health_lines(health))

    def test_the_start_of_the_body_is_read_after_the_first_rebuild(self):
        # E0 reads 1000 before any rebuild; every read of the body alone after it reads 1001.
        health = self.export([1001.0])
        self.assertTrue(health_module.back_as_it_was(health))

    def test_a_tiny_difference_alone_is_not_confirmed_and_with_a_changed_outline_is_a_change(self):
        alone = make_health_with(body_small=["its volume"])
        self.assertNotIn("body_changed", alone)
        self.assertFalse(health_module.design_changed(alone))
        self.assertFalse(health_module.back_as_it_was(alone))
        backed = make_health_with(body_small=["its volume"], outlines_changed=["Sketch2 reads another outline"])
        self.assertEqual(backed["body_changed"], ["its volume"])

    def test_tries_that_stopped_are_back_when_the_end_check_confirms_every_part(self):
        stopped = {"after": "off (max)", "items": ["Sketch5"]}
        confirmed = make_health_with(stopped=stopped, gap_mm=0.0)
        self.assertTrue(health_module.back_as_it_was(confirmed))
        self.assertTrue(health_module.health_lines(confirmed))  # the stop is still told
        for missing in ({"gap_mm": None}, {"gap_mm": 0.0, "body_unchecked": True}):
            with self.subTest(missing=missing):
                self.assertFalse(health_module.back_as_it_was(make_health_with(stopped=stopped, **missing)))


def make_health_with(**inputs):
    inputs.setdefault("gap_mm", 0.0)
    return health_module.make_health(health_module.HealthInputs(probe=health_module.MEASURED, **inputs))


if __name__ == "__main__":
    unittest.main()
