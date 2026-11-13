"""The size probe of one export, run against a simulated Fusion: recompute rows, motion, restore."""
import re
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.probe_helpers import circle, loop, size, table, user
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, W, read_at

from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch
from lib.design_edit.runner import RowExport
from lib.probe import plan
from lib.sketch_values import coverage
from lib.sketch_values.motion import Motion
from lib.translator.sizes import sketch_answer, sketch_sizes

UNITS = {"count": "", "cube": "mm", "off": "mm", "height": "mm"}
START = {"count": "3", "cube": "10 mm", "off": "5 mm", "height": "20 mm"}


def number(text):
    return float(re.match(r"\s*([-0-9.eE+]+)", text).group(1))


class Fusion:
    """A design whose sketches follow four user parameters, as `read_at` draws them."""

    def __init__(self, bad_when=None):
        self.store = FakeStore(START, bad_when=bad_when)
        self.requests = []

    def read(self, request):
        self.requests.append(request)
        e = self.store.exprs
        return read_at(count=number(e["count"]), cube=number(e["cube"]), off=number(e["off"]),
                       height=number(e["height"]))


def states(values, results, reads):
    """(values, result, read) per row; `reads` were taken at the rows that built, in order."""
    pending = list(reads)
    return [(v, r, None if r.get("error") else pending.pop(0)) for v, r in zip(values, results)]


def run(fusion, probe, sizes):
    """The probe's rows as the export runs them. Returns (rows, results)."""
    rows = probe.probe_rows(sizes)
    rows += probe.far_rows(sizes, plan.MAX_PROBE_ROWS - len(rows))
    reads = []
    job = RowExport(fusion.store, UNITS, lambda path: reads.append(probe.read_now()))
    results = job.run(rows, "", lambda *a: True, tolerate_build_errors=True)
    probe.add_states(states([{p: r["state"][p] for p in r["varied"]} for r in rows], results, reads))
    return rows, results


class SizeProbeTest(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        self.sizes = [size(self.table, n, UNITS[n]) for n in TICKED]
        self.fusion = Fusion()

    def start(self):
        return SizeProbe.start(CAPTURE, self.table, self.fusion.read)

    def test_a_probe_starts_when_the_sketches_read_back_as_captured_and_not_when_nothing_reads(self):
        self.assertIsNotNone(self.start())
        self.assertTrue(covers_a_sketch(CAPTURE))
        self.assertIsNone(SizeProbe.start(CAPTURE, self.table, lambda request: {}))

    def test_a_sketch_that_reads_as_before_is_kept_once_across_reads(self):
        probe = self.start()
        first, again = probe.read_now({}), probe.read_now({})
        token = next(iter(first["sketches"]))
        self.assertIsNot(first, again)
        self.assertIs(first["sketches"][token], again["sketches"][token])
        self.assertIs(again["sketches"][token], probe.e0["sketches"][token])

    def test_sizes_that_move_sketches_get_rows_without_a_step_and_the_motion_follows_the_width(self):
        probe = self.start()
        rows, results = run(self.fusion, probe, self.sizes)
        self.assertTrue(rows and all(r["step"] is False for r in rows))
        self.assertTrue(all(r["step_file"] is None for r in results))
        self.assertEqual(self.fusion.store.exprs, START)
        found = probe.finish(probe.read_now(), {})
        self.assertEqual(found, [])
        self.assertEqual(probe.motion.get("4/p0/l0/width").terms, {W: 1.0})
        self.assertEqual(probe.motion.get("6/p0/plane").terms, {"height": 1.0})
        self.assertEqual(probe.restore_gap_mm, 0.0)

    def test_a_size_that_moves_no_sketch_gets_no_row(self):
        tbl = table(PARAMS + [user("wall", "2 mm", 2)], ["wall"], MODEL)
        probe = SizeProbe.start(CAPTURE, tbl, self.fusion.read)
        self.assertEqual(probe.probe_rows([size(tbl, "wall", "mm")]), [])

    def test_a_size_behind_a_sketch_gets_both_ends(self):
        probe = self.start()
        sizes = [s for s in self.sizes if s["param"] == "off"]
        rows = probe.probe_rows(sizes)
        self.assertEqual([r["name"] for r in rows], ["off (near min)", "off (near max)"])
        self.assertEqual([r["name"] for r in probe.far_rows(sizes, 10)], ["off (min)", "off (max)"])
        self.assertEqual(probe.far_rows(sizes, 10), [])

    def test_a_size_left_without_rows_is_loose_with_its_reason(self):
        probe = self.start()
        probe.untried = ["off"]
        found = probe.finish(probe.read_now(), {"off": "Hole offset"})
        self.assertEqual([(f["param"], f["size"]) for f in found], [("off", "off")])
        self.assertIn("Hole offset", found[0]["reason"])

    def test_a_size_left_without_rows_is_not_measured_for_the_sketches_that_read_it(self):
        probe = self.start()
        run(self.fusion, probe, [s for s in self.sizes if s["param"] != "off"])
        probe.untried = ["off"]
        probe.finish(probe.read_now(), {})
        self.assertEqual(Motion.from_json(probe.motion.json()).untried, ["off"])
        sketches = [n for n in ("Sketch1", "Sketch2", "Sketch3") if "off" in sketch_sizes(self.table, n)]
        self.assertTrue(sketches)
        for name in sketches:
            answer = sketch_answer(self.table, probe.motion, name, "off")
            self.assertEqual((answer.kind, answer.reason), (coverage.NOT_MEASURED, coverage.NOT_TRIED))
            self.assertNotEqual(sketch_answer(self.table, probe.motion, name, "height").kind, coverage.NOT_MEASURED)

    def test_a_state_that_does_not_build_is_dropped_and_reported(self):
        self.fusion = Fusion(bad_when=lambda e: e["height"] == "40 mm")
        probe = self.start()
        run(self.fusion, probe, self.sizes)
        self.assertTrue(any(not s.built for s in probe.states))
        self.assertEqual([d["name"] for d in probe.dropped][:1], ["height (max)"])
        self.assertEqual(probe.dropped[0]["detail"]["items"], ["Fillet1"])
        probe.finish(probe.read_now(), {})
        self.assertIsNotNone(probe.report()["motion"])

    def test_the_report_keeps_the_request_the_states_and_the_motion(self):
        probe = self.start()
        run(self.fusion, probe, self.sizes)
        probe.finish(probe.read_now(), {})
        report = probe.report()
        self.assertEqual(report["request"]["sketches"], ["sk1", "sk2"])
        self.assertTrue(report["states"][0]["e0"])
        self.assertIn("4/p0/l0/width", report["motion"]["values"])


class DiscoveryTest(unittest.TestCase):
    """Discovery rows are compared with the design as it reads once the parameters are back, not with E0."""

    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        self.fusion = Fusion()
        self.probe = SizeProbe.start(CAPTURE, self.table, self.fusion.read)

    @staticmethod
    def flipped(**sizes):
        found = read_at(**sizes)
        found["sketches"]["sk2"] = dict(found["sketches"]["sk2"], profiles=[{"loops": []}])
        return found

    def test_a_sketch_left_on_another_solution_after_the_rows_is_not_a_move_of_every_parameter_tried_later(self):
        self.probe.set_discovery_base(self.flipped())
        self.probe.discover([({"varied": ["lid"], "state": {"lid": 4.0}}, {}, self.flipped()),
                             ({"varied": ["pipe"], "state": {"pipe": 9.0}}, {}, self.flipped(cube=20))])
        self.assertEqual(self.probe.also_changes, ["pipe"])
        self.assertEqual(self.probe.after_rows["changed"], ["Sketch2"])
        self.assertEqual([d["moved"] for d in self.probe.discovery], [False, True])
        self.assertIn("Sketch1", self.probe.discovery[1]["changed"])

    def test_a_row_that_did_not_build_or_was_not_read_is_not_tried(self):
        self.probe.set_discovery_base(read_at())
        failed = {"error": "x", "detail": {"items": ["Chamfer3"]}}
        self.probe.discover([({"varied": ["lid"], "state": {"lid": 4.0}}, failed, None),
                             ({"varied": ["pipe"], "state": {"pipe": 9.0}}, {}, None)])
        self.assertEqual([(d["moved"], d["tried"]) for d in self.probe.discovery], [(None, False), (None, False)])
        self.assertEqual(self.probe.discovery[0]["failed"], "Chamfer3")
        self.assertEqual(self.probe.also_changes, [])

    def test_the_restore_check_names_the_sketch_it_could_not_compare_and_the_person_is_told(self):
        from lib.export_plan.health import HealthInputs, health_lines, make_health
        self.assertIsNone(self.probe.measure_restore(self.flipped()))
        self.assertEqual(len(self.probe.restore_unchecked), 1)
        self.assertIn("Sketch2", self.probe.restore_unchecked[0])
        health = make_health(HealthInputs(gap_mm=None, probe="measured", unchecked=self.probe.restore_unchecked))
        self.assertTrue(any("Sketch2" in line for line in health_lines(health)))
        stayed = make_health(HealthInputs(gap_mm=0.0, probe="measured", flipped=["Sketch2"]))
        self.assertEqual(sum("Sketch2" in line for line in health_lines(stayed)), 1)
        self.assertEqual(self.probe.measure_restore(read_at()), 0.0)
        self.assertEqual(self.probe.restore_unchecked, [])


def runner_port(fusion, keeper=None):
    """What `ProbeRun` needs of Fusion: the store, the units, a progress window, a log and `keeper(tokens)`, the sketch
    keeper (else none)."""
    return FakePort(store=fusion.store, units=UNITS, keeper=keeper)


class StartReadTest(unittest.TestCase):
    """After a row that did not build, the design is read again once the parameters are back, before the next row."""

    def test_the_row_after_a_failed_row_keeps_the_read_it_started_from(self):
        from lib.export_plan.pipeline import ProbeRun
        fusion = Fusion(bad_when=lambda e: number(e["off"]) == 10)
        tbl = table(PARAMS, TICKED, MODEL)
        probe = SizeProbe.start(CAPTURE, tbl, fusion.read)
        rows = [{"name": "off (max)", "key": "a", "values": {"off": 10.0}, "varied": ["off"], "state": {"off": 10.0},
                 "step": False},
                {"name": "height (max)", "key": "b", "values": {"height": 40.0}, "varied": ["height"],
                 "state": {"height": 40.0}, "step": False},
                {"name": "cube (max)", "key": "c", "values": {"cube": 20.0}, "varied": ["cube"], "state": {"cube": 20.0},
                 "step": False}]
        ProbeRun(runner_port(fusion), "", probe).run_rows(rows)
        self.assertEqual([(s.start is not None, s.built) for s in probe.states[1:]], [(False, False), (True, True),
                                                                                   (False, True)])
        self.assertEqual(probe.states[2].start, read_at())
        self.assertIn("start", probe.report()["states"][2])
        # The start read asks only for what tells the outlines apart.
        start_request = fusion.requests[-3]
        self.assertTrue(start_request["sketches"])
        self.assertFalse({"params", "refs", "target"} & set(start_request))


def on_other_solution(found):
    """`found` with the lid sketch on its other solution: another outline."""
    lid = found["sketches"]["sk2"]
    found["sketches"]["sk2"] = dict(lid, profiles=[{"loops": [loop([circle((0, 0), 4, "c2")]),
                                                              loop([circle((1, 0), 1, "c3")], False)]}])
    return found


class TwoSolutionFusion(Fusion):
    """The lid sketch has a second solution. A recompute moves it there when `flips(before, now)` holds for the
    expressions of the recompute before and of this one, and back when `settles(before, now)` holds; else it stays
    until the keeper puts its points back."""

    def __init__(self, flips, settles=lambda before, now: False, bad_when=None):
        super().__init__()
        self.flipped = False
        last = [dict(START)]

        def solve(store):
            if flips(last[0], store.exprs):
                self.flipped = True
            elif settles(last[0], store.exprs):
                self.flipped = False
            last[0] = dict(store.exprs)

        self.store = FakeStore(START, bad_when=bad_when, on_recompute=solve)

    def read(self, request):
        found = super().read(request)
        return on_other_solution(found) if self.flipped else found


def keeper_port(fusion):
    """A runner port whose sketch keeper puts the lid sketch back on its first solution."""
    class Keeper:
        @staticmethod
        def put_back():
            fusion.flipped = False

    return runner_port(fusion, lambda tokens: Keeper())


def size_row(name, value):
    return {"name": "%s (max)" % name, "key": name, "values": {name: value}, "varied": [name], "state": {name: value},
            "step": False}


def keyed(*rows):
    for n, row in enumerate(rows):
        row["key"] = "r%d" % n
    return list(rows)


def inert_keeper_port(fusion):
    """A runner port whose keeper finds points to move but whose moves do not bring the sketch back."""
    class Keeper:
        @staticmethod
        def put_back():
            return 3

    return runner_port(fusion, lambda tokens: Keeper())


class StartAfterGivingUpTest(unittest.TestCase):
    """Once put backs are given up (or there is no keeper), a row may still bring the sketch back, so a row that
    needs its start reads it again."""

    def start_of_last_row(self, make_port):
        from lib.export_plan.pipeline import ProbeRun

        def leaves_after_height(before, now):
            return number(before["height"]) != 20 and now == START

        def back_after_cube(before, now):
            return number(before["cube"]) != 10 and now == START

        fusion = TwoSolutionFusion(leaves_after_height, back_after_cube)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        run = ProbeRun(make_port(fusion), "", probe)
        run.run_rows(keyed(size_row("height", 40.0), size_row("off", 10.0), size_row("height", 30.0),
                           size_row("cube", 20.0), size_row("off", 8.0)))
        return probe, next(s for s in probe.states if s.values == {"off": 8.0}).start

    def test_a_row_that_needs_its_start_reads_it_with_a_keeper_that_cannot_help_or_none(self):
        for name, make_port in (("a keeper that cannot help", inert_keeper_port), ("no keeper", runner_port)):
            with self.subTest(name):
                probe, start = self.start_of_last_row(make_port)
                self.assertFalse(probe.left_start(start))


class PutBackTest(unittest.TestCase):
    def test_a_put_back_that_moves_no_point_still_rebuilds_and_reads(self):
        from lib.export_plan.pipeline import ProbeRun

        def leaves_after_a_failed_row(before, now):
            return number(before["off"]) == 10 and now == START

        fusion = TwoSolutionFusion(leaves_after_a_failed_row, lambda before, now: before == now,
                                   bad_when=lambda e: number(e["off"]) == 10)

        class Keeper:  # the sketch's own points are gone: nothing to move
            @staticmethod
            def put_back():
                return 0

        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        run = ProbeRun(runner_port(fusion, lambda tokens: Keeper()), "", probe)
        run.run_rows(keyed(size_row("off", 10.0), size_row("height", 40.0)))
        back = probe.states[2].put_back
        self.assertTrue(isinstance(back, dict) and not probe.left_start(back))

    def test_after_the_tries_every_kept_sketch_goes_back_also_one_whose_move_reads_within_tolerance(self):
        from lib.export_plan.pipeline import ProbeRun
        fusion = Fusion()
        left = set()

        class Keeper:
            @staticmethod
            def put_back():
                moved = len(left)
                left.clear()
                return moved

        read = fusion.read
        fusion.read = lambda request: on_other_solution(read(request)) if "sk2" in left else read(request)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        left.update({"sk1", "sk2"})  # sk1 moved too little to read as moved
        ProbeRun(runner_port(fusion, lambda tokens: Keeper()), "", probe).settle()
        self.assertEqual(left, set())

    def test_the_discovery_base_after_a_put_back_holds_the_whole_state(self):
        from lib.export_plan.pipeline import ProbeRun
        fusion = TwoSolutionFusion(lambda before, now: False)
        read = fusion.read

        def asked_only(request):
            found = read(request)
            return {k: v for k, v in found.items() if (k != "params" or "params" in request)
                    and (k != "box" or request.get("target"))}

        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), asked_only)
        fusion.flipped = True
        ProbeRun(keeper_port(fusion), "", probe).discover([])
        self.assertEqual(set(probe.discovery_base) & {"params", "box"}, set(probe.e0) & {"params", "box"})
        self.assertTrue(set(probe.e0) & {"params", "box"})


class StartCheckTest(unittest.TestCase):
    def test_checking_where_a_try_starts_does_not_scan_the_capture_again(self):
        from unittest import mock
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), Fusion().read)
        probe.left_start(read_at())
        with mock.patch.object(plan, "scan", side_effect=AssertionError("scanned again")):
            self.assertFalse(probe.left_start(read_at()))
            self.assertTrue(probe.left_start(on_other_solution(read_at())))
            self.assertTrue(probe.off_outline(on_other_solution(read_at())))


class ReadTimerTest(unittest.TestCase):
    def test_only_the_probe_runs_own_reads_time_their_parts(self):
        from lib.export_plan.pipeline import ProbeRun
        fusion = Fusion(bad_when=lambda e: number(e["off"]) == 10)
        port, lent = runner_port(fusion), []
        read = fusion.read

        def timed(request):
            lent.append(getattr(port, "read_timer", None) is not None)
            return read(request)

        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), timed)
        run = ProbeRun(port, "", probe)
        run.run_rows(keyed(size_row("off", 10.0), size_row("height", 40.0)))
        probe.read_now()
        self.assertEqual(lent, [False] + [True] * run.timer.count("read") + [False])


class SolverFlipTest(unittest.TestCase):
    """A sketch left on its other solution after a try is put back before the next row, and the row that may have
    run on it is run again."""

    def run_flip(self, flips):
        from lib.export_plan.pipeline import ProbeRun
        fusion = TwoSolutionFusion(flips)
        probe = SizeProbe.start(CAPTURE, table(PARAMS, TICKED, MODEL), fusion.read)
        run = ProbeRun(keeper_port(fusion), "", probe)
        run.run_rows([size_row("height", 40.0), size_row("off", 10.0), size_row("cube", 20.0)])
        run.settle()
        probe.finish(fusion.read(probe.request), {})
        return fusion, run, probe

    def test_a_flip_left_by_a_restore_is_put_back_and_the_row_that_ran_on_it_is_run_again(self):
        def restore_after_tall(before, now):
            return number(before["height"]) == 40 and now == START

        fusion, run, probe = self.run_flip(restore_after_tall)
        self.assertEqual([s.values for s in probe.states[1:]], [{"height": 40.0}, {"cube": 20.0}, {"off": 10.0}])
        self.assertEqual((run.put_backs, run.redone), (1, ["off"]))
        self.assertEqual((probe.motion.flipped, probe.motion.apart), ([], []))
        self.assertEqual(probe.states[3].read, read_at(off=10))
        self.assertEqual(probe.report()["recovery"], {"put_backs": 1, "again": 1})

    def test_a_row_that_flips_again_from_a_checked_start_limits_its_own_size(self):
        fusion, run, probe = self.run_flip(lambda before, now: number(now["off"]) == 10)
        self.assertEqual(probe.motion.spans["off"]["changed"], [[10.0, "Sketch2"]])
        self.assertEqual((probe.motion.flipped, probe.motion.apart), ([], []))
        self.assertEqual(run.put_backs, 2)  # before the next row, and once more after the tries
        self.assertFalse(fusion.flipped)


class ProgressTextTest(unittest.TestCase):
    """The window counts the tries of the whole export and shows the row's own line."""

    def test_two_batches_are_numbered_as_one_run_and_labelled_with_the_value_tried(self):
        from lib.export_plan import messages
        from lib.export_plan.pipeline import ProbeRun
        fusion = Fusion()
        tbl = table(PARAMS, TICKED, MODEL)
        probe = SizeProbe.start(CAPTURE, tbl, fusion.read)
        port = runner_port(fusion)
        sizes = [s for s in [size(tbl, n, UNITS[n]) for n in TICKED] if s["param"] in ("off", "height")]
        rows, _ = plan.probe_rows(sizes, {"off", "height"})
        run = ProbeRun(port, "", probe)
        run.run_rows(rows[:2])
        run.run_rows(rows[2:4])
        self.assertEqual(port.verb, messages.TRY_VERB)
        self.assertEqual([(i, n) for i, n, _ in port.shown], [(1, 2), (2, 2), (3, 4), (4, 4)])
        self.assertEqual([label for _, _, label in port.shown],
                         ["off at 3.75 mm", "off at 6.25 mm", "height at 15 mm", "height at 25 mm"])
        self.assertEqual(messages.try_line(5, 31, "HolderWidth at 32 mm"), "Try 5 of 31: HolderWidth at 32 mm")


class RowWithoutStepTest(unittest.TestCase):
    def test_the_callback_gets_none_and_no_file_is_expected(self):
        store = FakeStore({"w": "5 mm"})
        calls = []
        job = RowExport(store, {"w": "mm"}, calls.append)
        results = job.run([{"name": "w (min)", "values": {"w": 2.0}, "step": False}], "", lambda *a: True)
        self.assertEqual((calls, results[0]["step_file"]), ([None], None))
        self.assertEqual(store.exprs, {"w": "5 mm"})
