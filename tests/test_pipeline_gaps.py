"""An export whose translation leaves steps out: the package with a gaps file, the reach pass and the result window."""
import copy
import json
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests import fakes
from tests.fakes import (FakeEdge, FakeFace, FakeMadeFeature, FakeMarkerTimeline, FakePartsPort, FakePort,
                         FakeReachDesign)
from tests.schema_check import load_schema, validate
from tests.test_manifest import GAPS_SCHEMA, GAPS_SCHEMA_V2, PACKAGE_SCHEMA, PACKAGE_SCHEMA_V2
from tests.test_parts_pipeline import renamed
from tests.translator_helpers import load_capture

from lib.design_edit.errors import StepExportError
from lib.dialog_model.result_rows import parts_result_view, result_view, section_lines
from lib.export_plan.pipeline.parts import run_parts_pipeline
from lib.translator.gap_hints import COIL, HINTS
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.export_plan.reach_pass import left_out_indexes, needs_reach
from lib.fusion_reader.capture import MarkerError
from lib.fusion_reader.read_gap_reach import read_reach
from lib.translator import gaps as translator_gaps, translate
from lib.translator.result import TranslateResult
from lib.package import gaps_file
from lib.package.caps import PackageCapError, check_package_caps
from lib.package.manifest import validate_manifest

fakes.install_adsk_core()
from lib.fusion_ui import result_dialog  # noqa: E402

TRAY = "filter_tray_sized"
SHELL, FILLET = 2, 3  # timeline indexes of the shell and of the fillet that picks edges of it
USER = load_capture(TRAY)["parameters"]["user"]
MODEL = load_capture(TRAY)["parameters"]["model"]
START = {p["name"]: p["expression"] for p in USER}
TICKED = ["wall_mm", "pipe_d_mm", "holes_count"]


def tray(leave_out=True, name=None):
    capture = load_capture(TRAY)
    if leave_out:
        capture["items"][SHELL]["type"] = "CoilFeature"
    return renamed(capture, ("t1", "Body1"), (name[0], name[1])) if name else capture


def tray_design(fillet_on_the_sweep=False):
    """Fusion for the tray, for the real reach read: Extrude1 made the outer walls, the left out step made the inner
    ones. The fillet's edges join two outer walls, or two inner walls with `fillet_on_the_sweep`."""
    walls = [FakeFace("wall%d" % n) for n in range(4)]
    inner = [FakeFace("inner%d" % n) for n in range(4)]
    joined = inner if fillet_on_the_sweep else walls
    edges = [FakeEdge("e%d" % n, [joined[n], joined[(n + 1) % 4]]) for n in range(4)]
    features = [FakeMadeFeature([]) for _ in load_capture(TRAY)["items"]]
    features[1], features[SHELL] = FakeMadeFeature(walls), FakeMadeFeature(inner)
    return FakeReachDesign(FakeMarkerTimeline(features), edges + walls + inner)


def reach_port(capture, reach=None, answer=None, design=None):
    """Fusion for one body without a sketch to measure. The reach read is the real one on `design`, else it answers
    `reach`, or `answer(capture, gaps)`; `asked` keeps what it was asked."""
    def read(capture, gaps):
        port.asked.append((sorted(gaps), "reach" in capture))
        if design is not None:
            return read_reach(design, capture, gaps)
        if answer is not None:
            return answer(capture, gaps)
        return reach

    port = FakePort(capture, reach=read)
    port.asked = []
    return port


def request():
    return ExportRequest(title="Tray", writer="test", up_axis="z", parameters=USER, model_params=MODEL,
                         design_unit="mm", ticked=TICKED, ranges={})


def export(port):
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, request(), tmp)


def recipe_ids(features):
    out = []
    for step in features:
        out.append(step["id"])
        out += recipe_ids(step.get("features") or [])
    return out


class GapPackageTest(unittest.TestCase):
    def test_a_translation_with_gaps_is_a_version_2_package_with_its_gaps_file(self):
        port = reach_port(tray(), design=tray_design())
        result = export(port)
        manifest, files = result.manifest, result.files
        self.assertEqual((manifest["version"], manifest["kind"], manifest["gaps"]), (2, "recipe", "gaps.json"))
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(validate(manifest, load_schema(PACKAGE_SCHEMA_V2)), [])
        gaps = json.loads(files["gaps.json"])
        self.assertEqual(validate(gaps, load_schema(GAPS_SCHEMA)), [])
        self.assertEqual([g["name"] for g in gaps["gaps"]], ["Shell1"])
        self.assertEqual(gaps["gaps"][0]["hint"], HINTS[COIL])
        ids = recipe_ids(json.loads(files["recipe.json"])["features"])
        for gap in gaps["gaps"]:
            self.assertIn(gap["after"], ids)
            self.assertNotIn(gap["id"], ids)
        self.assertEqual(result.report["gaps"], gaps["gaps"])
        self.assertEqual(result.report["outcome"], "recipe")

    def test_the_reach_is_read_once_for_the_steps_left_out_for_their_own_reason_and_the_second_look_uses_it(self):
        port = reach_port(tray(), design=tray_design())
        result = export(port)
        self.assertEqual(port.asked, [([SHELL], False)])
        self.assertEqual(result.report["reach"], {"read": True, "gaps": [SHELL], "makers": {str(FILLET): []}, "moves": 1})

    def test_a_fillet_on_edges_the_left_out_step_made_is_left_out_by_the_real_reach_read(self):
        result = export(reach_port(tray(), design=tray_design(fillet_on_the_sweep=True)))
        self.assertEqual(result.report["reach"]["makers"], {str(FILLET): [SHELL]})
        self.assertEqual([(g["name"], g["dependsOn"]) for g in result.report["gaps"]],
                         [("Shell1", []), ("Fillet1", ["gap_%d" % SHELL])])

    def test_a_part_over_the_gap_cap_only_because_of_later_picks_is_read_and_translated_again(self):
        # The cap is one gap: the fillet that may pick the left out shell is the second, until the reach clears it.
        with mock.patch.object(translator_gaps, "MAX_GAPS", 1):
            port = reach_port(tray(), design=tray_design())
            result = export(port)
            parts = parts_port([tray(name=("t2", "Lid"))], {0: {"read": True, "gaps": [SHELL],
                                                               "makers": {str(FILLET): []}}})
            with tempfile.TemporaryDirectory() as tmp:
                parts_result = run_parts_pipeline(parts, request(), tmp)
        self.assertEqual(port.asked, [([SHELL], False)])
        self.assertEqual((result.report["outcome"], [g["name"] for g in result.report["gaps"]]), ("recipe", ["Shell1"]))
        self.assertEqual(parts.asked, [(0, [SHELL])])
        self.assertEqual([g["name"] for g in parts_result.report["parts"][0]["gaps"]], ["Shell1"])

    def test_a_reach_that_could_not_be_read_leaves_out_every_later_step_that_picks(self):
        port = reach_port(tray(), reach={"read": False, "error": "no"})
        result = export(port)
        self.assertEqual([g["name"] for g in result.report["gaps"]], ["Shell1", "Fillet1"])
        self.assertEqual(result.manifest["version"], 2)

    def test_a_marker_that_cannot_go_back_stops_the_export(self):
        def refuse(capture, gaps):
            raise MarkerError("The timeline marker did not go back.")
        port = reach_port(tray(), answer=refuse)
        with self.assertRaises(MarkerError):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_nothing_is_asked_and_the_package_is_the_same_as_before_when_no_step_is_left_out(self):
        port = reach_port(tray(leave_out=False))
        result = export(port)
        self.assertEqual(port.asked, [])
        self.assertEqual(result.manifest["version"], 1)
        self.assertNotIn("gaps", result.manifest)
        self.assertEqual(sorted(result.files), ["part.step", "recipe.json", "report.json"])
        self.assertNotIn("gaps", result.report)
        self.assertNotIn("reach", result.report)
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])

    def test_a_gaps_file_with_more_gaps_than_version_1_holds_is_version_2(self):
        gap = export(reach_port(tray(), design=tray_design())).report["gaps"][0]
        many = [dict(gap, id="gap_%d" % n) for n in range(gaps_file.VERSION_ONE_GAPS + 1)]
        written = json.loads(gaps_file.gaps_file_bytes(many, [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]))
        self.assertEqual((written["version"], len(written["gaps"])), (2, gaps_file.VERSION_ONE_GAPS + 1))
        self.assertEqual(validate(written, load_schema(GAPS_SCHEMA_V2)), [])

    def test_a_gaps_file_over_the_cap_is_written_without_the_fusion_data(self):
        full = len(gaps_file.gaps_file_bytes(export(reach_port(tray(), design=tray_design())).report["gaps"],
                                             [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]))
        with mock.patch.object(gaps_file, "MAX_GAPS_BYTES", full - 1):
            result = export(reach_port(tray(), design=tray_design()))
        gap = json.loads(result.files["gaps.json"])["gaps"][0]
        self.assertEqual((gap["data"], gap["trimmed"]), ({}, True))

    def test_a_gaps_file_that_cannot_fit_makes_the_part_a_fixed_shape(self):
        with mock.patch.object(gaps_file, "MAX_GAPS_BYTES", 10):
            result = export(reach_port(tray(), design=tray_design()))
        self.assertEqual(result.manifest["kind"], "stepOnly")
        self.assertNotIn("gaps", result.manifest)
        self.assertEqual(result.manifest["version"], 1)

    def test_a_package_writer_refuses_a_gaps_file_above_the_cap(self):
        with self.assertRaises(PackageCapError):
            check_package_caps({"gaps.json": b"x" * (1024 ** 2 + 1)})
        check_package_caps({"gaps.json": b"x" * 10, **{"parts/%02d/part.step" % i: b"x" for i in range(1, 100)}})


class ReachPassTest(unittest.TestCase):
    def test_the_read_is_asked_about_the_steps_left_out_for_their_own_reason_also_inside_tool_bodies(self):
        def gap(index, cause):
            return {"index": index, "verdict": "leftOut", "cause": cause}
        combine = {"index": 6, "verdict": "translated", "tool_steps": [gap(5, "own"), gap(4, "picks")]}
        result = TranslateResult(recipe={}, items=[gap(2, "own"), gap(3, "picks"), combine])
        self.assertEqual(left_out_indexes(result), [2, 5])


    def test_a_tool_body_stopped_at_the_gap_cap_still_names_its_own_gaps(self):
        capture = load_capture("combine_tool_two_steps")
        items = capture["items"]
        items[5]["type"] = "CoilFeature"
        items[6:] = [dict(copy.deepcopy(items[5]), index=6, name="Extrude4"), dict(items[6], index=7)]
        with mock.patch.object(translator_gaps, "MAX_GAPS", 1):
            result = translate(capture)
        self.assertTrue(needs_reach(result))
        self.assertEqual(left_out_indexes(result), [5])


class ResultWindowTest(unittest.TestCase):
    def view(self, reach):
        result = export(reach_port(tray(), reach=reach))
        return result_view("tray.paramability", result.manifest, result.report, result.table, TICKED)

    def test_the_view_lists_each_left_out_step_and_the_dialog_shows_the_section(self):
        view = self.view({"read": False, "error": "no"})
        lines = section_lines(view, "left_out")
        self.assertEqual(len(lines), 3)
        command = fakes.FakeCommand()
        result_dialog.build(command, view)
        self.assertIsNotNone(command.commandInputs.itemById("pm_result_left_out"))
        self.assertIn(lines[0].split(":")[0], view["message"])

    def test_a_list_longer_than_the_window_shows_is_cut_and_points_to_the_report(self):
        gaps = [{"name": "Step%d" % n, "reason": "No."} for n in range(8)]
        view = result_view("tray.paramability", {"kind": "recipe", "notes": []}, {"sizes": {"free": []}, "gaps": gaps},
                           export(reach_port(tray(leave_out=False))).table, [])
        lines = section_lines(view, "left_out")
        self.assertIn("report.json", lines[-2])


def parts_port(captures, reaches):
    """Fusion for several bodies whose reach reads answer `reaches` by body; `asked` keeps what it was asked."""
    def read(index, capture, gaps):
        port.asked.append((index, sorted(gaps)))
        return reaches[index]

    port = FakePartsPort(captures, reach=read)
    port.asked = []
    return port


class PartsGapsTest(unittest.TestCase):
    def run_parts(self, captures, reaches):
        port = parts_port(captures, reaches)
        with tempfile.TemporaryDirectory() as tmp:
            return port, run_parts_pipeline(port, request(), tmp)

    def test_each_part_with_gaps_names_its_own_gaps_file_and_the_others_are_as_before(self):
        captures = [tray(name=("t2", "Lid")), tray(leave_out=False, name=("t3", "Base"))]
        captures[0]["target"]["name"], captures[1]["target"]["name"] = "Lid", "Base"
        port, result = self.run_parts(captures, {0: {"read": True, "gaps": [SHELL], "makers": {str(FILLET): []}}})
        manifest = result.manifest
        self.assertEqual(port.asked, [(0, [SHELL])])
        self.assertEqual((manifest["version"], manifest["kind"]), (2, "parts"))
        self.assertEqual(manifest["parts"][0]["gaps"], "parts/01/gaps.json")
        self.assertNotIn("gaps", manifest["parts"][1])
        self.assertEqual(sorted(result.files),
                         ["parts/01/gaps.json", "parts/01/part.step", "parts/01/recipe.json", "parts/02/part.step",
                          "parts/02/recipe.json", "report.json"])
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(validate(manifest, load_schema(PACKAGE_SCHEMA_V2)), [])
        gaps = json.loads(result.files["parts/01/gaps.json"])
        self.assertEqual(validate(gaps, load_schema(GAPS_SCHEMA)), [])
        self.assertEqual([g["name"] for g in gaps["gaps"]], ["Shell1"])
        self.assertEqual(result.report["parts"][0]["gaps"], gaps["gaps"])
        self.assertNotIn("gaps", result.report["parts"][1])

    def test_a_parts_package_without_gaps_stays_version_1_and_reads_no_reach(self):
        port, result = self.run_parts([tray(leave_out=False, name=("t2", "Lid"))], {})
        self.assertEqual(port.asked, [])
        self.assertEqual(result.manifest["version"], 1)
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])

    def test_the_parts_view_lists_the_gaps_with_their_part(self):
        captures = [tray(name=("t2", "Lid"))]
        captures[0]["target"]["name"] = "Lid"
        port, result = self.run_parts(captures, {0: {"read": False, "error": "no"}})
        view = parts_result_view("two.paramability", result.manifest, result.report, result.table, TICKED)
        lines = section_lines(view, "left_out")
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line.startswith("Lid, ") for line in lines[:2]))

    def test_a_part_that_fails_its_step_file_still_restores_the_parameters(self):
        port = parts_port([tray(name=("t2", "Lid"))], {0: {"read": False, "error": "no"}})
        port.fail_step_at = 1
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(StepExportError):
            run_parts_pipeline(port, request(), tmp)
        self.assertEqual(port.store.exprs, START)


if __name__ == "__main__":
    unittest.main()
