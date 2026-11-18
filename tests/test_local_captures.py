"""Checks of private exported packages, kept outside the repo.

Every package name, size name, step name and expected value lives in a local JSON file (default
`tests/local/captures.json`, or the path in PARAMABILITY_LOCAL_CAPTURES). Without that file the module skips.
The reports folder comes from PARAMABILITY_LOCAL_REPORTS, else from "reports_dir" in the JSON. The JSON holds
{"reports_dir": str, "cases": {<kind>: [case, ...]}}; each test below runs one kind over its cases, and a package
that is not in the folder skips its case."""
import json
import os
import unittest
import zipfile

from tests import context  # noqa: F401
from tests.schema_check import check_recipe

from lib.export_plan.body_scope import body_links, scope_inputs
from lib.export_plan.probe_flow import probe_view
from lib.package.naming import addin_of_writer
from lib.params import size_table
from lib.probe import build as probe_build
from lib.sketch_values.motion import Stuck, Terms
from lib.translator import translate

CONFIG = os.environ.get("PARAMABILITY_LOCAL_CAPTURES") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "local", "captures.json")


def _load():
    if not os.path.exists(CONFIG):
        return {}
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


DATA = _load()
REPORTS = os.path.expanduser(os.environ.get("PARAMABILITY_LOCAL_REPORTS") or DATA.get("reports_dir") or "")


def cases(kind):
    return DATA.get("cases", {}).get(kind, [])


def _path(case, key):
    return os.path.join(REPORTS, case[key])


def _present(case, key="package"):
    return os.path.exists(_path(case, key))


def package_report(case):
    """The report of a package; its capture names the add-in version its writer text gives (`addin`)."""
    with zipfile.ZipFile(_path(case, "package")) as package:
        return with_addin(json.loads(package.read("report.json")))


def with_addin(report):
    """`report` with the add-in version of its writer text in its capture, as a capture of the current reader holds it."""
    version = addin_of_writer(report.get("writer"))
    if version and isinstance(report.get("capture"), dict) and not report["capture"].get("addin"):
        report = dict(report, capture=dict(report["capture"], addin=version))
    return report


def table_for(case, capture):
    params = capture["parameters"]
    return size_table.build(params["user"], case["ticked"], params["model"], capture.get("design_units", "mm"))


def motion_for(capture, table, report):
    return probe_build.build(probe_view(capture), table, report["probe"]["states"])


def free_sizes(result):
    return {n: s for n, s in result.recipe["sizes"].items() if "value" in s}


def replay(case):
    """The translation of a package from its own probe states, with the sizes its rows varied as the ticked ones."""
    report = package_report(case)
    capture, states = report["capture"], report["probe"]["states"]
    varied = {n for s in states for n in s.get("values") or {}}
    ticked = [p["name"] for p in capture["parameters"]["user"] if p["name"] in varied]
    model, quantities = scope_inputs(capture, capture["parameters"]["model"])
    table = size_table.build(capture["parameters"]["user"], ticked, model, capture.get("design_units", "mm"),
                             quantity_params=quantities, links=body_links(capture))
    motion = probe_build.build(probe_view(capture), table, states)
    return translate(capture, size_table=table, motion=motion), motion


@unittest.skipUnless(DATA, "skipped: no local capture file (see the test section of docs/development.md)")
class OwnerCaptureTest(unittest.TestCase):
    def each(self, kind, check, key="package"):
        """Runs `check(case)` for every listed case whose package is present; skips when none is."""
        todo = [c for c in cases(kind) if _present(c, key)]
        if not todo:
            self.skipTest("skipped: no %s case with its file in the reports folder" % kind)
        for case in todo:
            with self.subTest(case[key]):
                check(case)

    def test_assembly_steps_are_skipped_and_the_walk_reaches_the_part(self):
        def check(case):
            with open(_path(case, "file"), encoding="utf-8") as f:
                capture = with_addin(json.load(f))["capture"]
            own = capture["target"]["component"]["token"]
            result = translate(capture)
            walked = {v["index"]: v["verdict"] for v in result.items}
            assembly = [i["index"] for i in capture["items"] if i["type"] in ("Occurrence", "ConstructionPlane")
                        and i["index"] in walked]
            self.assertTrue(assembly and all(walked[i] == "skipped" for i in assembly))
            # The walk passed the assembly items: it stops at a step of the part, or writes the recipe.
            if result.refusal is None:
                self.assertIsNotNone(result.recipe)
            else:
                self.assertEqual(capture["items"][result.refusal["index"]]["component"], own)
        self.each("assembly_walk", check, key="file")

    def test_steps_before_the_refusal_are_copied(self):
        def check(case):
            result = translate(package_report(case)["capture"])
            walked = {v["name"]: v["verdict"] for v in result.items if v["verdict"] != "skipped"}
            for name in case["translated"]:
                self.assertEqual(walked[name], "translated")
            # `refusal` names the first step that is not copied: the copy stops there, or leaves it out.
            not_copied = {v["name"] for v in result.items if v["verdict"] == "leftOut"}
            if result.refusal is not None:
                not_copied.add(result.refusal["name"])
            self.assertIn(case["refusal"], not_copied)
        self.each("steps_copied", check)

    def test_an_offset_becomes_an_offset_faces_step(self):
        def check(case):
            result = translate(package_report(case)["capture"])
            self.assertIsNone(result.refusal)
            self.assertEqual({v["index"]: v["verdict"] for v in result.items}[case["index"]], "translated")
            self.assertEqual(result.recipe["version"], case["version"])
            step = result.recipe["features"][-1]
            want = case["step"]
            self.assertEqual((step["kind"], step["label"], step["distance"]),
                             (want["kind"], want["label"], want["distance"]))
            self.assertEqual(len(step["faces"]["near"]), case["near"])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("offset_step", check)

    def test_probe_states_leave_the_sizes_free(self):
        def check(case):
            report = package_report(case)
            capture = report["capture"]
            table = table_for(case, capture)
            motion = motion_for(capture, table, report)
            rails = case["rails"]
            found = [v for k, v in motion.values.items() if k.split("/")[0] in rails["steps"] and "/l" in k]
            self.assertTrue(found)
            self.assertEqual({(tuple(r.terms), abs(r.terms[rails["term"]])) for r in found},
                             {((rails["term"],), rails["size"])})
            result = translate(capture, size_table=table, motion=motion)
            self.assertEqual(result.fixed, [])
            self.assertEqual(sorted(free_sizes(result)), sorted(case["free"]))
            for name, (low, high) in case["bounds"].items():
                size = result.recipe["sizes"][name]
                if low is not None:
                    self.assertEqual(size["min"], low)
                if high is not None:
                    self.assertEqual(size["max"], high)
            marked = {f["name"]: f["reason"] for f in result.loose}
            self.assertEqual(sorted(marked), sorted(case["marked"]))
            for name, fragment in case["reasons"].items():
                self.assertIn(fragment, marked[name])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("probe_free", check)

    def test_with_the_dialog_ranges_the_sizes_stay_free_and_are_marked(self):
        def check(case):
            report = package_report(case)
            capture = report["capture"]
            params = capture["parameters"]
            table = table_for(case, capture)
            # The dialog sends the range of every ticked row, also when it is the default one.
            ranges = {n: (table.sizes[table.size_name(n)]["min"], table.sizes[table.size_name(n)]["max"])
                      for n in case["ticked"]}
            table = size_table.build(params["user"], case["ticked"], params["model"],
                                     capture.get("design_units", "mm"), ranges=ranges)
            result = translate(capture, size_table=table, motion=motion_for(capture, table, report))
            self.assertEqual(result.fixed, [])
            self.assertEqual(sorted(f["name"] for f in result.loose), sorted(case["marked"]))
            self.assertEqual(len(free_sizes(result)), case["free_count"])
        self.each("dialog_ranges", check)

    def test_free_sizes_keep_their_ranges_and_cuts_are_told(self):
        def check(case):
            report = package_report(case)
            capture = report["capture"]
            table = table_for(case, capture)
            motion = motion_for(capture, table, report)
            self.assertEqual(motion.apart, case["apart"])
            result = translate(capture, size_table=table, motion=motion)
            self.assertEqual(result.fixed, [])
            marked = {f["name"]: f["reason"] for f in result.loose}
            self.assertEqual(sorted(marked), sorted(case["marked"]))
            for name, where in case["where"].items():
                self.assertIn("may give unexpected results %s:" % where, marked[name])
            for name, text in case["mentions"].items():
                self.assertIn(text, marked[name])
            verdicts = {v["index"]: v for v in result.items}
            self.assertNotIn(case["not_in_note"]["text"], verdicts[case["not_in_note"]["index"]]["note"])
            self.assertEqual(verdicts[case["translated_index"]]["verdict"], "translated")
            free = {n: (s["min"], s["max"]) for n, s in free_sizes(result).items()}
            self.assertEqual(free, {n: tuple(r) for n, r in case["free"].items()})
            cuts = {c["name"]: c["words"] for c in result.cuts}
            for name, words in case["cut_words"].items():
                self.assertEqual(cuts[name], words)
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("offset_back", check)

    def test_a_rim_picked_by_a_face_follows_the_part(self):
        def check(case):
            report = package_report(case)
            capture = report["capture"]
            # The capture may predate the face record, so the face is added here.
            picked = next(i for i in capture["items"] if i["index"] == case["item_index"])["data"]["sets"][case["set"]]
            self.assertEqual((picked["input_kinds"], len(picked["edges"])), (case["input_kinds"], case["edge_count"]))
            picked["faces"] = [case["face"]]
            table = table_for(case, capture)
            result = translate(capture, size_table=table, motion=motion_for(capture, table, report))
            bevels = [f for f in result.recipe["features"] if f["label"] == case["label"]]
            self.assertEqual(bevels[0]["edges"], case["first_edges"])
            self.assertEqual([list(b["edges"]) for b in bevels[1:]], case["other_edges"])
            self.assertEqual(result.recipe["version"], case["version"])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("rim_chamfer", check)

    def test_without_a_motion_the_sketch_sizes_are_marked_loose(self):
        def check(case):
            capture = package_report(case)["capture"]
            result = translate(capture, size_table=table_for(case, capture))
            self.assertEqual(result.fixed, [])
            free = {n: (s["min"], s["max"]) for n, s in free_sizes(result).items()}
            self.assertEqual(len(free), case["free_count"])
            for name, (low, high) in case["bounds"].items():
                self.assertEqual(free[name], (low, high))
            self.assertEqual(sorted(f["name"] for f in result.loose), sorted(case["marked"]))
            self.assertNotIn(case["not_marked"], [f["name"] for f in result.loose])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("no_motion", check)

    def test_a_size_no_row_built_is_not_called_unchanging(self):
        def check(case):
            result, motion = replay(case)
            self.assertEqual(len(free_sizes(result)), case["free_count"])
            never = {n for n, span in motion.spans.items() if span["low"] == span["high"]}
            self.assertTrue(never)
            for entry in result.dropped:
                if entry["name"] in never:
                    self.assertTrue(entry["used"])
                    self.assertNotIn("tried", entry)
        self.each("replay_free", check)

    def test_only_the_size_that_curves_its_points_is_dropped(self):
        def check(case):
            result, motion = replay(case)
            self.assertEqual((len(free_sizes(result)), len(result.dropped)), (case["free_count"], case["dropped_count"]))
            curved = {n for v in motion.values.values() if getattr(v, "cause", "") == "curve" for n in v.movers}
            self.assertEqual(curved, {d["name"] for d in result.dropped})
            self.assertEqual(result.loose, [])
            for name, (low, high) in case["bounds"].items():
                size = result.recipe["sizes"][name]
                self.assertEqual((size["min"], size["max"]), (low, high))
            self.assertTrue(any(isinstance(v, Terms) for v in motion.values.values()))
        self.each("replay_curve", check)

    def test_a_package_is_copied(self):
        self.each("copied", lambda case: self.assertIsNotNone(translate(package_report(case)["capture"]).recipe))

    def test_a_sketch_left_on_its_other_solution_blames_no_size(self):
        def check(case):
            result, motion = replay(case)
            self.assertEqual(len(motion.flipped), case["flipped"])
            self.assertFalse([f for f in result.loose if "different outline" in f["reason"]])
            self.assertEqual(len(free_sizes(result)), case["free_count"])
            step = next(f for f in result.recipe["features"] if f["id"] == case["step_id"])
            self.assertIn(case["expr_contains"], step["sketch"]["outer"]["center"][0]["expr"])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("replay_flipped", check)

    def test_pattern_copies_follow_the_count(self):
        def check(case):
            result, motion = replay(case)
            steps = {f["id"]: f for f in result.recipe["features"]}
            self.assertEqual(steps[case["step_id"]]["sketch"]["outer"]["kind"], case["outer_kind"])
            self.assertNotIn(case["absent_id"], steps)
            # A symmetric pattern is written as one part per side, each with its own count formula.
            counts = {s["linear"]["count"]["expr"] for s in steps.values() if s["kind"] == "pattern"}
            self.assertTrue(counts)
            copies = [s for s in steps.values() if s.get("when")]
            self.assertEqual(len(copies), case["copies"])
            self.assertTrue(all(any(count in s["when"] for count in counts) for s in copies))
            self.assertFalse([f for f in result.loose if "different outline" in f["reason"]])
            # A size that moves an outline along a curve stays loose because another step still follows it.
            curved = {n for v in motion.values.values() if isinstance(v, Stuck) and v.cause == "curve"
                      for n in v.movers}
            self.assertEqual(result.dropped, [])
            self.assertTrue(curved & {f["name"] for f in result.loose})
            self.assertTrue(any(isinstance(v, Terms) and any(f[0] == "cot" for _, fs in v.parts for f in fs)
                                for v in motion.values.values()))
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("replay_pattern", check)

    def test_a_size_that_changes_an_outline_above_its_value_keeps_the_range_below(self):
        def check(case):
            result, motion = replay(case)
            name = case["size"]
            self.assertEqual(motion.spans[name]["kept"], case["kept"])
            size = result.recipe["sizes"][name]
            self.assertEqual([size["min"], size["max"]], case["range"])
            self.assertEqual({c["name"]: c["why"] for c in result.cuts}[name], case["cut_why"])
            self.assertNotIn(name, [f["name"] for f in result.loose])
            self.assertEqual(check_recipe(result.recipe), [])
        self.each("replay_span", check)

    def test_sizes_are_dropped_for_their_own_tries(self):
        def check(case):
            result, _ = replay(case)
            found = {d["name"]: d["reason"] for d in result.dropped}
            for name, fragment in case["reasons"].items():
                self.assertIn(fragment, found[name])
        self.each("replay_dropped", check)


if __name__ == "__main__":
    unittest.main()
