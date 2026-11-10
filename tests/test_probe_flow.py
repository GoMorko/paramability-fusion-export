"""The size probe of one export, run against a simulated Fusion: recompute rows, motion, restore."""
import re
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.probe_helpers import size, table, user
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, W, read_at

from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch, kept_size_names
from lib.design_edit.runner import RowExport
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
        self.assertEqual([r["name"] for r in rows], ["off (min)", "off (max)"])

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
        self.assertTrue(any(not s["built"] for s in probe.states))
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

    def test_kept_sizes_include_the_ones_that_only_reach_a_sketch(self):
        self.assertEqual(kept_size_names(self.table, []), {self.table.size_name(n) for n in ("count", "cube", "off", "height")})


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
        from lib.export_plan.health import health_lines, make_health
        self.assertIsNone(self.probe.measure_restore(self.flipped()))
        self.assertEqual(len(self.probe.restore_unchecked), 1)
        self.assertIn("Sketch2", self.probe.restore_unchecked[0])
        health = make_health(gap_mm=None, probe="measured", unchecked=self.probe.restore_unchecked)
        self.assertTrue(any("Sketch2" in line for line in health_lines(health)))
        stayed = make_health(gap_mm=0.0, probe="measured", flipped=["Sketch2"])
        self.assertEqual(sum("Sketch2" in line for line in health_lines(stayed)), 1)
        self.assertEqual(self.probe.measure_restore(read_at()), 0.0)
        self.assertEqual(self.probe.restore_unchecked, [])


class _Port:
    """What `ProbeRun` needs of Fusion: the store, the units, a progress window and a log."""

    def __init__(self, fusion):
        self.store, self.units, self.logs = fusion.store, UNITS, []

    def progress(self, verb):
        import contextlib

        class Step:
            @staticmethod
            def step(*args):
                return True

        return contextlib.nullcontext(Step())

    def log(self, text):
        self.logs.append(text)


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
        ProbeRun(_Port(fusion), "", probe).run_rows(rows)
        self.assertEqual([("start" in s, s["built"]) for s in probe.states[1:]], [(False, False), (True, True),
                                                                                   (False, True)])
        self.assertEqual(probe.states[2]["start"], read_at())
        self.assertIn("start", probe.report()["states"][2])


class RowWithoutStepTest(unittest.TestCase):
    def test_the_callback_gets_none_and_no_file_is_expected(self):
        store = FakeStore({"w": "5 mm"})
        calls = []
        job = RowExport(store, {"w": "mm"}, calls.append)
        results = job.run([{"name": "w (min)", "values": {"w": 2.0}, "step": False}], "", lambda *a: True)
        self.assertEqual((calls, results[0]["step_file"]), ([None], None))
        self.assertEqual(store.exprs, {"w": "5 mm"})
