"""The size probe of one export, run against a simulated Fusion: checks, extra recompute rows, motion, restore."""
import os
import re
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.probe_helpers import size, table
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, W, read_at

from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch, kept_size_names
from lib.export_plan.runner import RowExport
from lib.export_plan.size_checks import plan_checks

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


def run(fusion, probe, sizes, tmp, unchecked=()):
    """Phase 1 and phase 2 as the export runs them. Returns (checks, rows, results of the extra rows)."""
    checks, _ = plan_checks(sizes)
    reads = []

    def step(path):
        with open(path, "wb") as f:
            f.write(b"x")
        reads.append(probe.read_now())

    job = RowExport(fusion.store, UNITS, step)
    results = job.run([c["row"] for c in checks], tmp, lambda *a: True, tolerate_build_errors=True)
    probe.add_checks(checks, results, reads)
    rows = probe.probe_rows(sizes, checks, results, list(unchecked))
    tried_reads = []
    tried = RowExport(fusion.store, UNITS, lambda path: tried_reads.append(probe.read_now()))
    tried_results = tried.run(rows, "", lambda *a: True, tolerate_build_errors=True)
    probe.add_tried(tried_results, tried_reads)
    return checks, rows, tried_results


class SizeProbeTest(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        self.sizes = [size(self.table, n, UNITS[n]) for n in TICKED]
        self.fusion = Fusion()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = folder.name

    def start(self):
        return SizeProbe.start(CAPTURE, self.table, self.fusion.read)

    def test_start_keeps_the_sketches_that_read_back_as_captured(self):
        probe = self.start()
        self.assertEqual(probe.skip, {"Sketch1", "Sketch2"})
        self.assertTrue(covers_a_sketch(CAPTURE))

    def test_a_design_that_reads_nothing_gives_no_probe(self):
        self.assertIsNone(SizeProbe.start(CAPTURE, self.table, lambda request: {}))

    def test_sizes_that_move_sketches_get_rows_without_a_step_and_the_motion_follows_the_width(self):
        probe = self.start()
        checks, rows, tried = run(self.fusion, probe, self.sizes, self.tmp)
        self.assertEqual(len(os.listdir(self.tmp)), len(checks))
        self.assertTrue(rows and all(r["step"] is False for r in rows))
        self.assertTrue(all(r["step_file"] is None for r in tried))
        self.assertEqual(self.fusion.store.exprs, START)
        found = probe.finish(probe.read_now(), {})
        self.assertEqual(found, [])
        self.assertEqual(probe.motion.get("4/p0/l0/width").terms, {W: 1.0})
        self.assertEqual(probe.motion.get("6/p0/plane").terms, {"height": 1.0})
        self.assertEqual(probe.restore_gap_mm, 0.0)

    def test_a_size_that_moves_no_sketch_gets_no_row(self):
        flat = [size(table(PARAMS, ["height"], MODEL), "height", "mm")]
        probe = self.start()
        checks, _ = plan_checks(flat)
        results = [{"name": "height", "values": {}, "step_file": "x"}]
        probe.add_checks(checks, results, [read_at()])
        self.assertEqual(probe.probe_rows(flat, checks, results, []), [])

    def test_an_unchecked_size_behind_a_sketch_gets_both_ends(self):
        probe = self.start()
        sizes = [s for s in self.sizes if s["param"] == "off"]
        results = []
        rows = probe.probe_rows(sizes, [], results, ["off"])
        self.assertEqual([r["name"] for r in rows], ["off (min)", "off (max)"])

    def test_a_size_left_without_rows_stays_fixed_with_its_reason(self):
        probe = self.start()
        probe.untried = ["off"]
        fixed = probe.finish(probe.read_now(), {"off": "Hole offset"})
        self.assertEqual([(f["param"], f["size"]) for f in fixed], [("off", "off")])
        self.assertIn("Hole offset stays fixed", fixed[0]["reason"])

    def test_a_state_that_does_not_build_is_dropped_and_reported(self):
        self.fusion = Fusion(bad_when=lambda e: e["height"] == "40 mm")
        probe = self.start()
        run(self.fusion, probe, self.sizes, self.tmp)
        self.assertTrue(any(not s["built"] for s in probe.states))
        self.assertEqual([d["name"] for d in probe.dropped][:1], ["height"])
        probe.finish(probe.read_now(), {})
        self.assertIsNotNone(probe.report()["motion"])

    def test_the_report_keeps_the_request_the_states_and_the_motion(self):
        probe = self.start()
        run(self.fusion, probe, self.sizes, self.tmp)
        probe.finish(probe.read_now(), {})
        report = probe.report()
        self.assertEqual(report["request"]["sketches"], ["sk1", "sk2"])
        self.assertTrue(report["states"][0]["e0"])
        self.assertIn("4/p0/l0/width", report["motion"]["values"])

    def test_kept_sizes_include_the_ones_that_only_reach_a_sketch(self):
        self.assertEqual(kept_size_names(self.table, []), {self.table.size_name(n) for n in ("count", "cube", "off", "height")})


class RowWithoutStepTest(unittest.TestCase):
    def test_the_callback_gets_none_and_no_file_is_expected(self):
        store = FakeStore({"w": "5 mm"})
        calls = []
        job = RowExport(store, {"w": "mm"}, calls.append)
        results = job.run([{"name": "w (min)", "values": {"w": 2.0}, "step": False}], "", lambda *a: True)
        self.assertEqual((calls, results[0]["step_file"]), ([None], None))
        self.assertEqual(store.exprs, {"w": "5 mm"})
