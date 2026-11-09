"""The size probe of one export, run against a simulated Fusion: recompute rows, motion, restore."""
import re
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.probe_helpers import size, table, user
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, W, read_at

from lib.export_plan.probe_flow import SizeProbe, covers_a_sketch, kept_size_names
from lib.design_edit.runner import RowExport

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


class RowWithoutStepTest(unittest.TestCase):
    def test_the_callback_gets_none_and_no_file_is_expected(self):
        store = FakeStore({"w": "5 mm"})
        calls = []
        job = RowExport(store, {"w": "mm"}, calls.append)
        results = job.run([{"name": "w (min)", "values": {"w": 2.0}, "step": False}], "", lambda *a: True)
        self.assertEqual((calls, results[0]["step_file"]), ([None], None))
        self.assertEqual(store.exprs, {"w": "5 mm"})
