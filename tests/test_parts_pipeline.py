"""The export of several bodies in one file, run against a simulated Fusion."""
import copy
import json
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePartsPort, FakeStore
from tests.schema_check import load_schema, validate
from tests.test_manifest import PACKAGE_SCHEMA
from tests.test_pipeline import MODEL, START, TICKED, USER
from tests.test_translate_sketch_motion import motion_of
from tests.translator_helpers import load_capture

from lib.design_edit.errors import StepExportError
from lib.design_edit.runner import ExportCancelled
from lib.dialog_model.result_rows import also_lines, not_tried_lines, parts_result_view, section, section_lines
from lib.export_plan import fixed_parts, recipe_export
from lib.export_plan.recipe_export import PartInput, translate_capture
from lib.export_plan.pipeline.parts import run_parts_pipeline, shared_cuts
from lib.export_plan.probe_flow import ProbeGroup
from lib.export_plan.part_names import unique_names
from lib.export_plan.pipeline import ExportRequest
from lib.export_plan.size_offers import table_for_bodies, table_for_body
from lib.package.manifest import validate_manifest
from lib.params import size_table as size_tables

BASE = load_capture("sketch_rect_centred")
PIPE = load_capture("linked_pipe_hole")


def renamed(capture, old, new):
    """The capture with the body `old` (token and name) called `new` everywhere."""
    text = json.dumps(capture).replace('"%s"' % old[0], '"%s"' % new[0]).replace('"%s"' % old[1], '"%s"' % new[1])
    return json.loads(text)


def second_body():
    return renamed(BASE, ("t1", "Body1"), ("t2", "Body2"))


def with_joint_on(capture, size):
    """The capture with a joint that reads the user parameter `size`."""
    other = copy.deepcopy(capture)
    reader = next(m for m in other["parameters"]["model"] if size in m.get("expression", ""))
    other["parameters"]["model"].append(dict(reader, name="joint_offset", created_by={"kind": "joint"}))
    return other


def stuck_body():
    """A body whose last step does not build in Fusion."""
    capture = renamed(BASE, ("t1", "Body1"), ("t3", "Body3"))
    capture["items"][-1]["health"] = "error"
    return capture


def request(ticked=TICKED):
    return ExportRequest(
        title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL, design_unit="mm",
        ticked=ticked, ranges={})


def export(port, **options):
    with tempfile.TemporaryDirectory() as tmp:
        return run_parts_pipeline(port, request(**options), tmp)


def recipe_of(result, number):
    return json.loads(result.files["parts/%02d/recipe.json" % number])


class SharedSizesTest(unittest.TestCase):
    def test_two_bodies_that_read_one_size_make_one_size_in_both_recipes(self):
        port = FakePartsPort([BASE, second_body()])
        result = export(port)
        manifest = result.manifest
        self.assertEqual(manifest["kind"], "parts")
        self.assertEqual([p["name"] for p in manifest["parts"]], ["Body1", "Body2"])
        self.assertEqual(port.steps, 2)
        first, second = recipe_of(result, 1), recipe_of(result, 2)
        self.assertIn("wall_mm", first["sizes"])
        self.assertEqual(first["sizes"], second["sizes"])
        self.assertEqual([e.name for e in result.table.entries].count("wall_mm"), 1)
        self.assertEqual(result.report["sizes"]["free"].count("wall_mm"), 1)
        self.assertEqual(port.store.exprs, START)

    def test_the_package_follows_the_rules_and_the_schema_copy(self):
        result = export(FakePartsPort([BASE, second_body()]))
        self.assertEqual(validate_manifest(result.manifest), [])
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])
        self.assertEqual(sorted(result.files), [
            "parts/01/part.step", "parts/01/recipe.json", "parts/02/part.step", "parts/02/recipe.json", "report.json"])
        self.assertEqual([p["name"] for p in result.report["parts"]], ["Body1", "Body2"])
        self.assertTrue(all("capture" in p for p in result.report["parts"]))
        self.assertEqual([p["name"] for p in result.manifest["parameters"]], [p["name"] for p in USER])


class LooseAndFixedTest(unittest.TestCase):
    def test_a_size_loose_in_one_part_is_loose_in_every_part_that_has_it_and_names_the_parts(self):
        joined = with_joint_on(second_body(), "wall_mm")
        result = export(FakePartsPort([BASE, joined]))
        first, second = result.manifest["parts"]
        for part in (first, second):
            self.assertEqual([e["name"] for e in part["loose"]], ["wall_mm"])
        self.assertIn("joint", first["loose"][0]["reason"])
        self.assertTrue(first["loose"][0]["reason"].startswith("Body1, Body2: "))
        self.assertEqual([e["name"] for e in result.report["sizes"]["loose"]], ["wall_mm"])
        self.assertIn("wall_mm", recipe_of(result, 1)["sizes"])

    def test_a_size_that_one_part_has_to_fix_is_fixed_in_every_part(self):
        real = recipe_export.translate

        def fixes_wall_for_the_second_body(capture, size_table=None, motion=None, **_):
            result = real(capture, size_table=size_table, motion=motion)
            if capture["target"]["name"] == "Body2" and "wall_mm" in size_table.ticked:
                result.fixed = [{"name": "wall_mm", "reason": "wall_mm stays fixed: a formula is too long."}]
            return result

        with mock.patch.object(recipe_export, "translate", side_effect=fixes_wall_for_the_second_body):
            result = export(FakePartsPort([BASE, second_body()]))
        for number in (1, 2):
            self.assertNotIn("wall_mm", recipe_of(result, number).get("sizes", {}))
        self.assertEqual([e["name"] for e in result.manifest["fixed"]], ["wall_mm"])
        self.assertTrue(result.manifest["fixed"][0]["reason"].startswith("Body2: "))
        self.assertNotIn("wall_mm", result.report["sizes"]["free"])
        self.assertIn("height_mm", result.report["sizes"]["free"])


class SharedCutTest(unittest.TestCase):
    """The part that was probed saw Fusion fail at 40 for height_mm (20 now, range 10 to 40); the other part has no
    sketch to follow, so it has no motion."""

    def setUp(self):
        capture = load_capture("linked_pipe_hole")
        self.capture, params = capture, capture["parameters"]
        self.table = size_tables.build(params["user"], ["height_mm"], params["model"])
        motion = motion_of("linked_pipe_hole", lambda values: None)
        motion.spans = {"height_mm": {"low": 20.0, "high": 30.0, "failed": [[40.0, "Extrude2"]]}}
        self.motion = motion
        self.table = shared_cuts(self.table, [(self.table.with_links([]), motion, capture)])

    def test_a_part_with_no_probe_gets_the_range_the_probed_part_was_cut_to(self):
        result = translate_capture(self.capture, "z", self.table.with_links([]), None)
        self.assertEqual((result.recipe["sizes"]["height_mm"]["min"], result.recipe["sizes"]["height_mm"]["max"]),
                         (10.0, 30.0))

    def test_the_file_says_the_range_is_the_same_in_every_part_that_uses_the_size(self):
        table = self.table
        inputs = [PartInput(name, "part.step", self.capture, translate_capture(self.capture, "z", table, motion), motion)
                  for name, motion in (("Lid", self.motion), ("Base", None))]
        manifest, _, report = recipe_export.plan_parts_export(inputs, "Box", "test", "z", size_table=table)
        [cut] = report["sizes"]["cut"]
        self.assertTrue(cut["shared"] and cut["reason"].startswith("height_mm: the range stops at 30 in every part"))
        for part in manifest["parts"]:
            self.assertEqual(part["cuts"], [{"name": "height_mm", "reason": cut["reason"]}])
            self.assertNotIn("loose", part)


class StubProbe:
    """A probe that gives the loose entries it was made with."""
    table = None

    def __init__(self, entries):
        self.entries = entries

    def finish(self, after, labels):
        return self.entries


class GroupReasonsTest(unittest.TestCase):
    def entry(self, reason):
        return {"name": "wall", "reason": reason, "param": "wall", "size": "wall"}

    def finish(self, *reasons):
        probes = [StubProbe([self.entry(r)] if r else []) for r in reasons]
        probes[0].table = object()
        names = ["Lid", "Base", "Clip"][:len(reasons)]
        return ProbeGroup(probes, names).finish([None] * len(reasons), {})

    def test_parts_with_one_reason_for_a_size_share_it(self):
        (found,) = self.finish("it moves a joint.", "it moves a joint.")
        self.assertEqual(found["reason"], "Lid, Base: it moves a joint.")

    def test_parts_with_different_reasons_for_a_size_each_keep_theirs(self):
        (found,) = self.finish("it moves a joint.", "it moves a sketch.", None)
        self.assertIn("Lid: it moves a joint", found["reason"])
        self.assertIn("Base: it moves a sketch", found["reason"])


def parts_report(*, also, found, untried=0):
    """A parts report whose parts tried `found` ({part: [moved parameters]}) and left `untried` parameters."""
    parts = [{"name": name, "probe": {"discovery": [{"param": p, "moved": True} for p in moved]}}
             for name, moved in found.items()]
    parts[0]["probe"]["discovery"] += [{"param": "u%d" % n, "moved": None, "tried": False, "reason": "x"}
                                       for n in range(untried)]
    return {"parts": parts, "also_changes": also}


class DiscoveryLinesTest(unittest.TestCase):
    def test_a_parts_file_says_which_part_each_parameter_changed(self):
        (line,) = also_lines(parts_report(also=["wall", "gap"], found={"Lid": ["wall", "gap"], "Base": ["gap"]}))
        wall, gap = line.index("wall"), line.index("gap")
        self.assertIn("Lid", line[wall:gap])
        self.assertNotIn("Base", line[wall:gap])
        self.assertIn("Lid, Base", line[gap:])

    def test_the_parameters_the_export_did_not_try_are_counted_once_in_a_line(self):
        (line,) = not_tried_lines(parts_report(also=[], found={"Lid": [], "Base": []}, untried=5))
        self.assertIn("5 more", line)

    def test_the_parts_view_titles_and_lists_what_was_not_tried(self):
        result = export(FakePartsPort([BASE, second_body()]))
        report = dict(result.report, also_changes=["wall_mm"])
        report["parts"] = [dict(p, probe={"discovery": [
            {"param": "wall_mm", "moved": p["name"] == "Body2"},
            {"param": "u1", "moved": None, "tried": False, "reason": "x"}]}) for p in report["parts"]]
        view = parts_result_view("box.paramability", result.manifest, report, result.table, TICKED)
        also, untried = section_lines(view, "more")
        self.assertIn("Body2", also)
        self.assertNotIn("Body1", also)
        self.assertIn("1 more", untried)
        self.assertIn(untried, view["message"])


class FixedShapeTest(unittest.TestCase):
    def test_a_body_that_cannot_be_copied_lands_as_a_fixed_shape_next_to_the_editable_part(self):
        port = FakePartsPort([BASE, stuck_body()])
        result = export(port)
        editable, fixed = result.manifest["parts"]
        self.assertIn("recipe", editable)
        self.assertNotIn("recipe", fixed)
        self.assertIn(result.report["parts"][1]["refusal"]["name"], fixed["note"])
        self.assertIn("parts/02/part.step", result.files)
        self.assertNotIn("parts/02/recipe.json", result.files)
        self.assertEqual(result.report["parts"][1]["outcome"], "stepOnly")
        self.assertIn("refusal", result.report["parts"][1])
        self.assertIn("wall_mm", recipe_of(result, 1)["sizes"])
        self.assertEqual(validate(result.manifest, load_schema(PACKAGE_SCHEMA)), [])

    def test_a_body_whose_steps_could_not_be_read_is_a_fixed_shape_and_the_others_still_measure(self):
        port = FakePartsPort([RuntimeError("no steps"), BASE])
        result = export(port)
        broken, editable = result.manifest["parts"]
        self.assertNotIn("recipe", broken)
        self.assertIn("recipe", editable)
        self.assertEqual(result.health["probe"], "measured")
        self.assertEqual(port.store.exprs, START)

    def test_when_no_body_can_be_copied_the_file_holds_only_fixed_shapes(self):
        result = export(FakePartsPort([stuck_body(), RuntimeError("no steps")]))
        self.assertEqual(["recipe" in p for p in result.manifest["parts"]], [False, False])
        self.assertNotIn("fixed", result.manifest)
        self.assertEqual(validate_manifest(result.manifest), [])


    def test_a_size_that_moves_a_fixed_shape_is_loose_in_the_editable_part_and_names_the_fixed_part(self):
        result = export(FakePartsPort([BASE, stuck_body()]))
        editable, fixed = result.manifest["parts"]
        [entry] = [e for e in editable["loose"] if e["name"] == "wall_mm"]
        self.assertTrue(entry["reason"].startswith("Body3 stays a fixed shape in this file"))
        self.assertNotIn("loose", fixed)
        self.assertIn("wall_mm", result.report["sizes"]["free"])
        self.assertIn(entry, result.report["sizes"]["loose"])

    def test_a_size_that_was_loose_already_gets_the_fixed_part_in_front_of_its_reason(self):
        result = export(FakePartsPort([with_joint_on(BASE, "wall_mm"), stuck_body()]))
        [entry] = [e for e in result.manifest["parts"][0]["loose"] if e["name"] == "wall_mm"]
        self.assertTrue(entry["reason"].startswith("Body3 stays a fixed shape"))
        self.assertIn("joint", entry["reason"])

    def test_parts_that_are_all_recipes_mark_nothing_for_fixed_shapes(self):
        result = export(FakePartsPort([BASE, second_body()]))
        self.assertTrue(all("loose" not in p for p in result.manifest["parts"]))


class FixedPartsTest(unittest.TestCase):
    def table(self):
        return table_for_body(USER, "mm", MODEL, BASE)

    def test_sizes_reaching_a_part_are_the_ticked_ones_its_parameters_depend_on(self):
        table = self.table()
        self.assertIn("wall_mm", fixed_parts.sizes_reaching(table, BASE))

    def test_a_size_no_recipe_part_holds_is_not_listed(self):
        marked = fixed_parts.marked(self.table(), [("Lid", BASE)], free={"not_this_size"})
        self.assertEqual([e["name"] for e in marked], [])

    def test_several_fixed_parts_share_one_reason_per_size(self):
        marked = fixed_parts.marked(self.table(), [("Lid", BASE), ("Clip", BASE)], free={"wall_mm"})
        self.assertEqual(len(marked), 1)
        self.assertTrue(marked[0]["reason"].startswith("Lid, Clip stay fixed shapes"))


class MeasuringTest(unittest.TestCase):
    def test_the_sketches_of_all_bodies_are_measured_over_one_set_of_rows(self):
        both = FakePartsPort([BASE, second_body()])
        export(both)
        single = FakePartsPort([BASE])
        export(single)
        self.assertEqual(both.reads, 2 * single.reads)

    def test_a_probe_that_fails_stops_the_motions_of_all_parts_and_is_reported(self):
        port = FakePartsPort([BASE, second_body()], fail_read_from=3)
        result = export(port)
        self.assertEqual(result.health["probe"], "failed")
        self.assertEqual(result.manifest["kind"], "parts")
        self.assertTrue(all("recipe" in p for p in result.manifest["parts"]))
        self.assertEqual(port.store.exprs, START)


class GuessedSizesTest(unittest.TestCase):
    def test_a_ticked_size_that_nothing_ties_to_a_sketch_gets_its_own_tries_in_a_several_body_export(self):
        user = PIPE["parameters"]["user"]
        start = {p["name"]: p["expression"] for p in user}
        rebuilt_with = []  # the parameters at another value than at the start, at every rebuild

        def rebuilt(store):
            rebuilt_with.append({n for n, e in store.exprs.items() if e != start[n]})

        port = FakePartsPort([PIPE], store=FakeStore(start, on_recompute=rebuilt))
        with tempfile.TemporaryDirectory() as tmp:
            run_parts_pipeline(port, ExportRequest(
                title="Box", writer="test", up_axis="z", parameters=user, model_params=PIPE["parameters"]["model"],
                design_unit="mm", ticked=[p["name"] for p in user], ranges={}), tmp)
        self.assertIn({"spare_mm"}, rebuilt_with)


class RestoreTest(unittest.TestCase):
    def test_a_step_file_that_fails_on_the_second_body_leaves_the_parameters_as_they_were(self):
        port = FakePartsPort([BASE, second_body()], fail_step_at=2)
        with self.assertRaises(StepExportError):
            export(port)
        self.assertEqual(port.store.exprs, START)
        self.assertEqual(port.warned, [])

    def test_a_cancel_while_the_shared_rows_run_puts_the_parameters_back(self):
        port = FakePartsPort([BASE, second_body()], cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(port.store.exprs, START)

    def test_a_parameter_that_will_not_go_back_is_named_when_the_export_stops(self):
        port = FakePartsPort([BASE, second_body()], store=FakeStore(START, stuck=TICKED), cancel_at=2)
        with self.assertRaises(ExportCancelled):
            export(port)
        self.assertEqual(len(port.warned), 1)
        self.assertTrue(port.warned[0] and set(port.warned[0]) <= set(TICKED))

    def test_a_parameter_that_will_not_go_back_after_a_finished_export_is_in_the_health_record(self):
        port = FakePartsPort([BASE, second_body()], store=FakeStore(START, stuck=["height_mm"]))
        result = export(port)
        self.assertEqual(result.health["unrestored"], ["height_mm"])
        self.assertTrue(any("measured" in n for n in result.manifest["notes"]))


class NamesTest(unittest.TestCase):
    def test_names_are_made_unique_not_empty_and_short_enough(self):
        names = unique_names(["Lid", "LID", "", "x" * 100, "x" * 100])
        self.assertEqual(names[:3], ["Lid", "LID 2", "Body"])
        self.assertEqual(len({n.lower() for n in names}), 5)
        self.assertTrue(all(1 <= len(n) <= 60 for n in names))


class LinksPerPartTest(unittest.TestCase):
    def test_a_part_translates_with_its_own_geometry_links_only(self):
        """Two parts that both have a sketch named Sketch1: each is translated with the link of its own part."""
        own = {BASE["target"]["name"]: [{"param": "pipe_d", "sketch": "Sketch1", "component": "Pipe", "via": "sketch"}],
               "Body2": [{"param": "cover_h", "sketch": "Sketch1", "component": "Cover", "via": "sketch"}]}
        seen = {}

        def translate(capture, up_axis, table, motion, **_):
            seen[capture["target"]["name"]] = table.links
            return recipe_export.translate_capture(capture, up_axis, table, motion)

        with mock.patch("lib.export_plan.pipeline.parts.body_links", lambda c: own.get(c["target"]["name"], [])), \
                mock.patch("lib.export_plan.pipeline.parts.translate_capture", translate):
            export(FakePartsPort([BASE, renamed(BASE, ("t1", "Body1"), ("t2", "Body2"))]))
        self.assertEqual({name: [l["param"] for l in links] for name, links in seen.items()},
                         {"Body1": ["pipe_d"], "Body2": ["cover_h"]})


class DialogTableTest(unittest.TestCase):
    def test_a_parameter_that_any_picked_body_uses_is_ticked(self):
        a = table_for_body(USER, "mm", MODEL, BASE)
        only_height = copy.deepcopy(second_body())
        only_height["parameters"]["model"] = [m for m in only_height["parameters"]["model"]
                                              if "height_mm" in m["expression"]]
        b = table_for_body(USER, "mm", MODEL, only_height)
        both = table_for_bodies(USER, "mm", MODEL, [only_height, BASE])
        self.assertTrue(set(a.ticked) | set(b.ticked) <= set(both.ticked))
        self.assertGreater(len(both.ticked), len(b.ticked))

    def test_a_body_that_could_not_be_read_adds_nothing_unless_it_is_the_only_one(self):
        alone = table_for_body(USER, "mm", MODEL, BASE)
        self.assertEqual(table_for_bodies(USER, "mm", MODEL, [RuntimeError("x"), BASE]).ticked, alone.ticked)
        self.assertTrue(table_for_bodies(USER, "mm", MODEL, [RuntimeError("x")]).entries)


class ResultViewTest(unittest.TestCase):
    def test_the_view_lists_each_size_once_and_a_line_per_part(self):
        result = export(FakePartsPort([BASE, stuck_body()]))
        view = parts_result_view("box.paramability", result.manifest, result.report, result.table, TICKED)
        names = [row["name"] for row in section(view, "sizes")["rows"]]
        self.assertEqual(names.count("wall_mm"), 1)
        part_lines = [line for line in section_lines(view, "result") if line.startswith("Body")]
        self.assertEqual(len(part_lines), 2)
        self.assertTrue(part_lines[0].startswith("Body1: editable"))
        self.assertIn("fixed shape", part_lines[1])
        self.assertIn("Saved box.paramability", view["message"])

if __name__ == "__main__":
    unittest.main()
