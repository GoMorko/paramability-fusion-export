"""The row phases of a probe: which rows it offers before and after the far rows, and the cap on the nearer rows for
one part and for a group of parts."""
import unittest

from tests import context  # noqa: F401
from tests import test_probe_flow as flow

from lib.design_edit.runner import RowExport
from lib.export_plan.probe_flow import ProbeGroup
from lib.probe import plan


def names(rows):
    return [r["name"] for r in rows]


class RowPhaseTest(unittest.TestCase):
    def setUp(self):
        case = flow.SizeProbeTest()
        case.setUp()
        self.case, self.sizes = case, case.sizes

    def test_no_rows_are_offered_before_the_near_rows(self):
        probe = self.case.start()
        for rows in (probe.pair_rows, probe.far_rows, probe.far_pair_rows):
            self.assertEqual(rows(self.sizes, 50), [])

    def test_the_near_pair_rows_come_before_the_far_rows_and_the_far_pair_rows_once_after_them(self):
        probe = self.case.start()
        probe.probe_rows(self.sizes)
        self.assertEqual(probe.far_pair_rows(self.sizes, 50), [])
        self.assertEqual(names(probe.pair_rows(self.sizes, 50)), ["all lower", "all higher"])

        probe = self.case.start()
        flow.run(self.case.fusion, probe, self.sizes)
        self.assertEqual(probe.pair_rows(self.sizes, 50), [])
        self.assertEqual(names(probe.far_pair_rows(self.sizes, 50)), ["all min", "all max"])
        self.assertEqual(probe.far_pair_rows(self.sizes, 50), [])


class NearerCapTest(unittest.TestCase):
    """A row that does not build gets nearer rows; over every call they stop at `plan.MAX_NEARER_ROWS`."""

    def setUp(self):
        case = flow.SizeProbeTest()
        case.setUp()
        case.fusion = flow.Fusion(bad_when=lambda e: e["height"] == "40 mm")
        self.case, self.sizes = case, case.sizes

    def _measured(self, probe):
        rows = probe.probe_rows(self.sizes)
        rows += probe.far_rows(self.sizes, plan.MAX_PROBE_ROWS - len(rows))
        reads = []
        job = RowExport(self.case.fusion.store, flow.UNITS, lambda path: reads.append(probe.read_now()))
        results = job.run(rows, "", lambda *a: True, tolerate_build_errors=True)
        probe.add_states(flow.states([{p: r["state"][p] for p in r["varied"]} for r in rows], results, reads))
        return probe

    def _nearer_total(self, probe):
        return sum(len(probe.nearer_rows(self.sizes, 1)) for _ in range(plan.MAX_NEARER_ROWS + 5))

    def test_one_part(self):
        self.assertEqual(self._nearer_total(self._measured(self.case.start())), plan.MAX_NEARER_ROWS)

    def test_a_group_counts_its_shared_rows_once(self):
        group = ProbeGroup([self.case.start(), self.case.start()], ["A", "B"])
        self.assertEqual(self._nearer_total(self._measured(group)), plan.MAX_NEARER_ROWS)


if __name__ == "__main__":
    unittest.main()
