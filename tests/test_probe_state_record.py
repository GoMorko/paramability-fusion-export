"""A probe state keeps its `report.json` form, and a motion built from that form (a replay) equals the one built from
the records the probe made."""
import json
import unittest

from tests import context  # noqa: F401
from tests import test_probe_flow as flow
from tests.probe_helpers import table
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, states

from lib.probe import build
from lib.probe.state import ProbeState, as_states


class ReportFormTest(unittest.TestCase):
    def test_a_state_writes_its_keys_in_order_and_only_the_report_parts_of_its_reads(self):
        read = {"sketches": {"a": 1}, "box": {"min": [0, 0, 0]}, "target": True}
        state = ProbeState({"w": 2.0}, built=False, failed="Fillet1", start=read, put_back=read, again=True)
        self.assertEqual(json.dumps(state.json()),
                         '{"values": {"w": 2.0}, "built": false, "failed": "Fillet1", "again": true, '
                         '"start": {"sketches": {"a": 1}, "box": {"min": [0, 0, 0]}}, '
                         '"put_back": {"sketches": {"a": 1}, "box": {"min": [0, 0, 0]}}}')
        self.assertEqual(json.dumps(ProbeState(read=read, e0=True).json()),
                         '{"values": {}, "built": true, "e0": true, '
                         '"read": {"sketches": {"a": 1}, "box": {"min": [0, 0, 0]}}}')

    def test_a_probe_report_reads_back_as_the_same_states(self):
        case = flow.SizeProbeTest()
        case.setUp()
        probe = case.start()
        flow.run(case.fusion, probe, case.sizes)
        written = probe.report()["states"]
        self.assertEqual([s.json() for s in as_states(json.loads(json.dumps(written)))], written)

    def test_a_motion_from_report_states_equals_the_motion_from_records(self):
        tbl = table(PARAMS, TICKED, MODEL)
        from_dicts = build.build(CAPTURE, tbl, states())
        from_records = build.build(CAPTURE, tbl, as_states(states()))
        self.assertEqual(from_dicts.json(), from_records.json())


if __name__ == "__main__":
    unittest.main()
