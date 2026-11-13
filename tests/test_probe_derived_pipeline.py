"""Shadow mode in the export: the `derived` block reaches `report.json`, and nothing else the export writes changes."""
import copy
import json
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePartsPort, FakePort
from tests.derived_fixtures import box_capture
from tests.test_parts_pipeline import export as export_parts
from tests.test_pipeline import export, view

from lib.export_plan import probe_flow
from lib.probe import derived


def outputs(result):
    """Everything an export writes that shadow mode must not change: the manifest, the recipe, the report without its
    `derived` block and the sketch graphs it reads, the health record and what the result window shows."""
    report = {k: v for k, v in result.report.items() if k not in ("derived", "timing")}
    report["capture"] = {k: v for k, v in report["capture"].items() if k != "sketch_graphs"}
    return (result.manifest, result.files["recipe.json"], json.dumps(report, sort_keys=True, default=str),
            result.health, view(result))


class ShadowModeTest(unittest.TestCase):
    def test_the_graphs_add_a_derived_block_and_change_nothing_else(self):
        plain = export(FakePort(capture=box_capture(graph=False)))
        shadowed_port = FakePort(capture=box_capture())
        shadowed = export(shadowed_port)
        self.assertNotIn("derived", plain.report)
        self.assertEqual(outputs(plain), outputs(shadowed))
        block = shadowed.report["derived"]
        self.assertEqual(block["sketches"][0]["outcome"], "derived")
        self.assertEqual(block["summary"]["values"], 12)
        self.assertEqual(len([line for line in shadowed_port.logs if line.startswith("sketch reading, shadow:")]), 1)

    def test_the_block_is_in_the_written_report(self):
        result = export(FakePort(capture=box_capture()))
        written = json.loads(result.files["report.json"])
        self.assertEqual(written["derived"], json.loads(json.dumps(result.report["derived"])))

    def test_a_solver_that_raises_leaves_the_export_as_it_was(self):
        plain = export(FakePort(capture=box_capture(graph=False)))
        with mock.patch.object(derived, "solve_sketch", side_effect=RuntimeError("boom")):
            broken = export(FakePort(capture=box_capture()))
        self.assertEqual(outputs(plain), outputs(broken))
        self.assertEqual(broken.report["derived"]["sketches"][0]["error"], "RuntimeError: boom")

    def test_shadow_mode_that_fails_altogether_is_noted_and_the_export_goes_on(self):
        plain = export(FakePort(capture=box_capture(graph=False)))
        port = FakePort(capture=box_capture())
        with mock.patch.object(derived, "shadow", side_effect=ValueError("no")):
            broken = export(port)
        self.assertEqual(outputs(plain), outputs(broken))
        self.assertEqual(broken.report["derived"], {"error": "ValueError: no"})
        self.assertTrue(any("shadow: failed" in line for line in port.logs))

    def test_the_result_window_shows_nothing_of_it(self):
        shown = json.dumps(view(export(FakePort(capture=box_capture()))))
        self.assertNotIn("derived", shown)
        self.assertNotIn("shadow", shown)


class PartsTest(unittest.TestCase):
    @staticmethod
    def bodies():
        second = json.loads(json.dumps(box_capture()).replace('"t1"', '"t2"').replace('"Body1"', '"Body2"'))
        return [box_capture(), second]

    def test_each_part_records_its_own_block(self):
        port = FakePartsPort(self.bodies())
        result = export_parts(port)
        parts = result.report["parts"]
        self.assertEqual([p["derived"]["sketches"][0]["outcome"] for p in parts], ["derived", "derived"])
        self.assertNotIn("derived", result.report)
        self.assertEqual(len([line for line in port.logs if "sketch reading, shadow" in line]), 2)
        self.assertTrue(port.logs[-1].startswith("Body2: ") or port.logs[-2].startswith("Body2: "))

    def test_a_part_without_graphs_has_no_block_and_the_package_is_the_same(self):
        plain = export_parts(FakePartsPort([box_capture(graph=False), box_capture(graph=False)]))
        mixed = self.bodies()
        mixed[1] = copy.deepcopy(mixed[1])
        mixed[1].pop("sketch_graphs")
        result = export_parts(FakePartsPort(mixed))
        parts = result.report["parts"]
        self.assertIn("derived", parts[0])
        self.assertNotIn("derived", parts[1])
        self.assertEqual(result.manifest["parts"][0]["name"], "Body1")
        self.assertEqual({k: v for k, v in plain.files.items() if k.endswith("recipe.json")},
                         {k: v for k, v in result.files.items() if k.endswith("recipe.json")})

    def test_a_part_whose_solver_raises_does_not_stop_the_file(self):
        with mock.patch.object(derived, "solve_sketch", side_effect=RuntimeError("boom")):
            result = export_parts(FakePartsPort(self.bodies()))
        self.assertEqual(result.manifest["kind"], "parts")
        self.assertEqual([p["derived"]["sketches"][0]["error"] for p in result.report["parts"]],
                         ["RuntimeError: boom"] * 2)


class ShadowOfTest(unittest.TestCase):
    def test_a_probe_without_graphs_gives_no_block_and_no_log_line(self):
        lines = []

        class Probe:
            @staticmethod
            def derived_record():
                return None

        self.assertIsNone(probe_flow.shadow_of(Probe, lines.append))
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
