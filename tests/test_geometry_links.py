"""A parameter that reaches the part through the geometry of another component: found, offered, tried and followed.

The fixture is a box with a pipe hole drawn around the pipe body of another component. pipe_d_mm is a dimension of a
sketch the root owns, which a step of the pipe component extrudes into that body, so no parameter of the box reads it.
"""
import copy
import json
import re
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.test_pipeline import FakePort
from tests.test_translate_sketch_motion import motion_of
from tests.translator_helpers import load_capture, steps_of

from lib.dialog_model.result_rows import NOT_USED, result_view, section, section_lines
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.export_plan.size_offers import offers, table_for_body
from lib.params import geometry_links, size_table
from lib.probe import plan
from lib.sketch_values.motion import Motion, Stuck
from lib.translator import translate

NAME = "linked_pipe_hole"
CAPTURE = load_capture(NAME)
USER = CAPTURE["parameters"]["user"]
MODEL = CAPTURE["parameters"]["model"]
ALL = [p["name"] for p in USER]
LINK = {"param": "pipe_d_mm", "sketch": "PipeHole", "component": "Pipe", "via": "body"}


def run(capture, motion, ticked=ALL):
    table = size_table.build(capture["parameters"]["user"], ticked, capture["parameters"]["model"])
    return translate(capture, size_table=table, motion=motion)


def dropped(result):
    return {d["name"]: d for d in result.dropped}


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


def _pipe_acts_through(capture, dependent):
    out = copy.deepcopy(capture)
    next(p for p in out["parameters"]["user"] if p["name"] == "pipe_d_mm")["dependents"] = [dependent]
    return out


class RuleTest(unittest.TestCase):
    def test_a_dimension_of_a_sketch_a_step_of_the_pipe_body_takes_reaches_the_hole(self):
        self.assertEqual(geometry_links.reach(CAPTURE), [LINK])

    def test_the_part_itself_and_sketches_other_steps_use_give_no_link(self):
        self.assertEqual(geometry_links.reach(CAPTURE, sketches={"BoxBase"}), [])
        own = copy.deepcopy(CAPTURE)
        own["sketch_links"][1]["links"][0].update(token="cmp_box", name="Box")
        self.assertEqual(geometry_links.reach(own), [])

    def test_with_the_body_known_only_its_own_steps_count_else_the_component_does(self):
        elsewhere = _pipe_acts_through(CAPTURE, {"name": "d40", "kind": "feature", "component": "cmp_pipe",
                                                 "feature": "PipeLabel"})
        self.assertEqual(geometry_links.reach(elsewhere), [])
        elsewhere["sketch_links"][1]["links"][0]["bodies"] = []
        self.assertEqual([link["via"] for link in geometry_links.reach(elsewhere)], ["component"])

    def test_a_reference_to_a_sketch_the_parameter_sits_on_reaches_it(self):
        drawn = copy.deepcopy(CAPTURE)
        drawn["sketch_links"][1]["links"][0].update(bodies=[], sketches=[{"token": "sk_pipe", "name": "PipeProfile"}])
        self.assertEqual([link["via"] for link in geometry_links.reach(drawn)], ["sketch"])

    def test_parameters_acting_on_a_tied_component_come_first_among_those_acting_outside(self):
        self.assertEqual(geometry_links.outside(CAPTURE), ["pipe_d_mm", "lid_mm"])
        self.assertEqual(geometry_links.outside(CAPTURE, sketches={"BoxBase"}), [])


class DialogTest(unittest.TestCase):
    def test_the_linked_parameter_is_ticked_to_start_with_and_says_why(self):
        table = table_for_body(USER, "mm", MODEL, CAPTURE)
        self.assertIn("pipe_d_mm", table.ticked)
        self.assertNotIn("spare_mm", table.ticked)
        rows = {o["param"]: o for o in offers(table, USER)}
        self.assertTrue(rows["pipe_d_mm"]["link"])
        self.assertEqual([n for n, o in rows.items() if o["link"]], ["pipe_d_mm"])


class ProbeRowsTest(unittest.TestCase):
    def sizes(self, names):
        return [{"param": n, "size": n, "unit": "mm", "value": 10.0, "min": 5.0, "max": 20.0} for n in names]

    def test_sizes_tried_on_a_guess_come_last_and_are_never_listed_as_untried(self):
        rows, untried = plan.probe_rows(self.sizes(["guess", "linked"]), {"linked"}, limit=3, extra={"guess"})
        self.assertEqual([r["varied"] for r in rows], [["linked"], ["linked"]])
        self.assertEqual(untried, [])

    def test_at_most_a_few_ticked_sizes_are_tried_on_a_guess(self):
        names = ["p%d" % n for n in range(plan.MAX_EXTRA_SIZES + 3)]
        params = [{"name": n, "expression": "5 mm", "value": 0.5, "unit": "mm", "kind": "length"} for n in names]
        table = size_table.build(params, names)
        self.assertEqual(plan.extra_sizes(table, ["p0"]), names[1:plan.MAX_EXTRA_SIZES + 1])


class TranslateTest(unittest.TestCase):
    def test_a_hole_that_follows_the_pipe_makes_the_pipe_a_size_its_arcs_read(self):
        result = run(CAPTURE, motion_of(NAME))
        self.assertIn("pipe_d_mm", result.recipe["sizes"])
        outline = steps_of(result.recipe, "extrude")[1]["sketch"]["outer"]
        self.assertEqual(expr(outline["start"][0]), "0.5 * pipe_d_mm")
        self.assertEqual(expr(outline["segments"][0]["to"][0]), "-0.5 * pipe_d_mm")
        self.assertEqual(set(dropped(result)), {"spare_mm", "lid_mm"})

    def test_a_circle_that_follows_the_pipe_writes_its_radius_as_a_formula(self):
        capture = copy.deepcopy(CAPTURE)
        profile = capture["items"][5]["data"]["profiles"][0]
        profile["loops"][0]["curves"] = [{"kind": "circle", "center": [0, 0], "radius": 6.0, "entity": "c0"}]

        def edit(values):
            for key in [k for k in values if k.startswith("5/")]:
                del values[key]
            values["5/p0/l0/radius"] = {"const": 0, "terms": {"pipe_d_mm": 0.5}, "sketch": "PipeHole"}

        result = run(capture, motion_of(NAME, edit))
        outline = steps_of(result.recipe, "extrude")[1]["sketch"]["outer"]
        self.assertEqual((outline["kind"], expr(outline["radius"]), outline["center"]),
                         ("circle", "0.5 * pipe_d_mm", [0.0, 0.0]))

    def test_a_hole_that_stays_put_leaves_the_pipe_out_as_unused(self):
        def edit(values):
            for key in [k for k in values if k.startswith("5/")]:
                del values[key]

        found = dropped(run(CAPTURE, motion_of(NAME, edit)))["pipe_d_mm"]
        self.assertFalse(found["used"])

    def test_a_hole_whose_outline_changes_shape_leaves_the_pipe_out_naming_the_sketch(self):
        def edit(values):
            for key in [k for k in values if k.startswith("5/")]:
                values[key] = Stuck(["pipe_d_mm"], "shape", "PipeHole").json()

        found = dropped(run(CAPTURE, motion_of(NAME, edit)))["pipe_d_mm"]
        self.assertTrue(found["used"])
        self.assertIn("PipeHole", found["reason"])

    def test_a_hole_the_probe_did_not_measure_leaves_the_pipe_out_as_untried(self):
        for motion in (None, Motion(unmeasured={"PipeHole": "its first read did not match the capture"})):
            with self.subTest(motion=motion):
                found = dropped(run(CAPTURE, motion))["pipe_d_mm"]
                self.assertTrue(found["used"])
                self.assertIn("PipeHole", found["reason"])


class MeasuredSpanTest(unittest.TestCase):
    """pipe_d_mm is 12, with the range 6 to 24; the probe tried it alone at the values in `failed` and `built`."""

    def run_with(self, failed, built=(), moved=False, ranges=None):
        def edit(values):
            if not moved:
                for key in [k for k in values if k.startswith("5/")]:
                    del values[key]

        motion = motion_of(NAME, edit)
        low, high = min((12.0,) + tuple(built)), max((12.0,) + tuple(built))
        motion.spans = {"pipe_d_mm": {"low": low, "high": high, "failed": [list(f) for f in failed]}}
        table = size_table.build(CAPTURE["parameters"]["user"], ALL, CAPTURE["parameters"]["model"], ranges=ranges)
        return translate(CAPTURE, size_table=table, motion=motion)

    def test_a_size_whose_rows_never_built_was_not_measured_and_is_not_called_unchanging(self):
        found = dropped(self.run_with([(6.0, "Fillet16"), (24.0, "Chamfer3")]))["pipe_d_mm"]
        self.assertTrue(found["used"])
        self.assertNotIn("tried", found)
        self.assertIn("Fillet16", found["reason"])
        self.assertIn("Chamfer3", found["reason"])

    def test_nothing_moved_over_part_of_the_range_says_between_which_values(self):
        part = dropped(self.run_with([(6.0, "Fillet16")], built=[24.0]))["pipe_d_mm"]
        whole = dropped(self.run_with([], built=[6.0, 24.0]))["pipe_d_mm"]
        self.assertTrue(part["tried"] and whole["tried"])
        self.assertNotEqual(part["reason"], whole["reason"])
        self.assertIn("between 12 and 24", part["reason"])

    def test_a_size_tried_over_part_of_its_range_stays_a_size_with_the_values_it_was_followed_between(self):
        result = self.run_with([], built=[24.0], moved=True)
        self.assertEqual((result.recipe["sizes"]["pipe_d_mm"]["min"], result.recipe["sizes"]["pipe_d_mm"]["max"]),
                         (6.0, 24.0))
        loose = {f["name"]: f["reason"] for f in result.loose}
        self.assertIn("between 12 and 24", loose["pipe_d_mm"])

    def test_the_range_stops_at_the_last_value_that_rebuilt_where_fusion_did_not_rebuild(self):
        result = self.run_with([(6.0, "Extrude2")], built=[24.0], moved=True)
        size = result.recipe["sizes"]["pipe_d_mm"]
        self.assertEqual((size["min"], size["max"]), (12.0, 24.0))
        self.assertNotIn("pipe_d_mm", [f["name"] for f in result.loose])

    def test_a_cut_range_is_told_with_where_it_stops_and_what_was_seen_there(self):
        result = self.run_with([(6.0, "Extrude2")], built=[24.0], moved=True)
        [cut] = result.cuts
        self.assertEqual(cut["name"], "pipe_d_mm")
        self.assertEqual(cut["reason"], "pipe_d_mm: the range starts at 12, since Fusion did not rebuild the design "
                                        "at 6 (Extrude2).")

    def test_a_failure_in_a_step_of_another_component_does_not_cut_the_range(self):
        result = self.run_with([(6.0, "PipeExtrude")], built=[24.0], moved=True)
        size = result.recipe["sizes"]["pipe_d_mm"]
        self.assertEqual((size["min"], size["max"]), (6.0, 24.0))
        self.assertEqual(result.cuts, [])
        self.assertIn("between 12 and 24", {f["name"]: f["reason"] for f in result.loose}["pipe_d_mm"])

    def test_a_typed_range_end_is_kept_where_fusion_did_not_rebuild(self):
        result = self.run_with([(8.0, "Fillet16")], built=[24.0], moved=True, ranges={"pipe_d_mm": (8.0, 24.0)})
        size = result.recipe["sizes"]["pipe_d_mm"]
        self.assertEqual((size["min"], size["max"]), (8.0, 24.0))


# ---- the whole export against a simulated Fusion ---------------------------------------------------------------

START = {p["name"]: p["expression"] for p in USER}


def _mm(store, name):
    return float(re.match(r"\s*([-0-9.eE+]+)", store.exprs[name]).group(1))


class PipePort(FakePort):
    """Fusion where the box outline follows width and depth and the hole follows the pipe (unless `still`)."""

    def __init__(self, still=False, bad_when=None, bad_item="Fillet1"):
        super().__init__(capture=CAPTURE, store=FakeStore(START, bad_when=bad_when, bad_item=bad_item))
        self.units = {p["name"]: p["unit"] for p in USER}
        self.still = still
        self.varied = []

    def probe_reader(self):
        def read(request):
            self.reads += 1
            out = copy.deepcopy(self.e0)
            scale = {"s1": (_mm(self.store, "width_mm") / 40.0, _mm(self.store, "depth_mm") / 30.0),
                     "s2": (1.0, 1.0) if self.still else (_mm(self.store, "pipe_d_mm") / 12.0,) * 2}
            for token, (sx, sy) in scale.items():
                for loop in out["sketches"][token]["profiles"][0]["loops"]:
                    for curve in loop["curves"]:
                        for key in ("start", "end", "mid", "center"):
                            if key in curve:
                                curve[key] = [curve[key][0] * sx, curve[key][1] * sy]
                        if "radius" in curve:
                            curve["radius"] *= sx
            self.varied.append({n for n in START if self.store.exprs[n] != START[n]})
            return out
        return read


def export(port, ticked):
    request = ExportRequest(title="Box", writer="test", up_axis="z", parameters=USER, model_params=MODEL,
                            design_unit="mm", ticked=ticked, ranges={})
    with tempfile.TemporaryDirectory() as tmp:
        return run_pipeline(port, request, tmp)


def pipe_range(result):
    recipe = json.loads(result.files["recipe.json"])
    return recipe["sizes"]["pipe_d_mm"]["min"], recipe["sizes"]["pipe_d_mm"]["max"]


class RangeCutTest(unittest.TestCase):
    """Fusion does not rebuild the design when the pipe is wider than 20 (12 now, range 6 to 24)."""

    def export(self, step):
        port = PipePort(bad_when=lambda e: float(e["pipe_d_mm"].split()[0]) > 20, bad_item=step)
        return export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)

    def test_the_range_stops_near_the_failure_not_at_the_nearest_try_that_built(self):
        result = self.export("Extrude2")
        # The near try at 15 built and 24 did not: the values between are halved, so 19.5 is the last that built.
        self.assertEqual(pipe_range(result), (6.0, 19.5))

    def test_the_cut_is_in_the_report_the_manifest_and_the_result_window(self):
        result = self.export("Extrude2")
        [cut] = result.report["sizes"]["cut"]
        self.assertEqual(cut["name"], "pipe_d_mm")
        self.assertEqual(cut["reason"], "pipe_d_mm: the range stops at 19.5, since Fusion did not rebuild the design "
                                        "at 20.625 (Extrude2).")
        self.assertEqual(result.manifest["cuts"], [{"name": "pipe_d_mm", "reason": cut["reason"]}])
        self.assertNotIn("loose", result.manifest)
        self.assertTrue(any("pipe_d_mm" in note and "cut" in note for note in result.manifest["notes"]))
        view = result_view("Box.paramability", result.manifest, result.report, result.table, ALL)
        [line] = [x for x in section_lines(view, "sizes") if x.startswith("pipe_d_mm")]
        self.assertEqual(line, "pipe_d_mm: 6 to 19.5 mm, range cut (Fusion did not rebuild the design at 20.625 "
                               "(Extrude2))")

    def test_a_failure_in_a_step_of_another_component_leaves_the_range_alone(self):
        result = self.export("PipeExtrude")
        self.assertEqual(pipe_range(result), (6.0, 24.0))
        self.assertNotIn("cut", result.report["sizes"])


class OutlinePort(PipePort):
    """`PipePort` where the pipe hole's sketch reads with one more loop (another outline) when `outline_when` holds
    for the pipe diameter in mm."""

    def __init__(self, outline_when, **kw):
        super().__init__(**kw)
        self.outline_when = outline_when

    def probe_reader(self):
        read = super().probe_reader()

        def with_outline(request):
            out = read(request)
            if self.outline_when(_mm(self.store, "pipe_d_mm")):
                loops = out["sketches"]["s2"]["profiles"][0]["loops"]
                inner = copy.deepcopy(loops[0])
                inner["outer"] = False
                for curve in inner["curves"]:
                    curve["entity"] = curve.get("entity", "") + "x"
                loops.append(inner)
            return out
        return with_outline


class OutlineRangeTest(unittest.TestCase):
    """The pipe (12 now, range 6 to 24) does not rebuild in Fusion below `low`, and its hole makes another outline above
    `high`."""

    def export(self, low, high):
        port = OutlinePort(lambda d: d > high, bad_item="Extrude2",
                           bad_when=lambda e: float(e["pipe_d_mm"].split()[0]) < low)
        return export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)

    def test_a_size_that_fails_below_and_changes_its_outline_above_keeps_the_range_between(self):
        result = self.export(10, 18)
        # Each side is halved toward the value now: 10.125 is the last value that built, 17.25 the last that kept the
        # outline (19.5 and 18.375 did not).
        self.assertEqual(pipe_range(result), (10.125, 17.25))
        [cut] = result.report["sizes"]["cut"]
        self.assertEqual(cut["why"], "Fusion did not rebuild the design at 9.75 (Extrude2); PipeHole makes a "
                                     "different outline at 18.375")
        self.assertNotIn("loose", result.manifest)

    def test_a_size_with_no_working_value_but_its_own_is_dropped_with_why(self):
        result = self.export(11.99, 12.01)
        [found] = [d for d in result.report["sizes"]["dropped"] if d["name"] == "pipe_d_mm"]
        self.assertEqual(found["reason"], "pipe_d_mm is not a size: no value other than 12 could be copied, since "
                                          "Fusion did not rebuild the design at 11.4 (Extrude2) and PipeHole makes "
                                          "a different outline at 13.2.")


class LinkOutcomeTest(unittest.TestCase):
    def test_a_linked_formula_is_reported_as_a_formula_and_a_plain_unticked_one_as_not_ticked(self):
        from lib.export_plan.recipe_export import link_outcomes
        from tests.probe_helpers import user
        params = [user("tol_mm", "0.2 mm", 0.2), user("bore_mm", "16 mm + tol_mm", 16.2), user("wall_mm", "1 mm", 1)]
        links = [dict(LINK, param=name) for name in ("bore_mm", "wall_mm")]
        table = size_table.build(params, ["tol_mm"], links=links)
        found = {o["param"]: o["outcome"] for o in link_outcomes(table, {"free": [], "dropped": []})}
        self.assertEqual(found, {"bore_mm": "formula", "wall_mm": "not ticked"})


class ExportTest(unittest.TestCase):
    def test_the_export_tries_the_pipe_and_the_hole_follows_it(self):
        port = PipePort()
        result = export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)
        self.assertIn({"pipe_d_mm"}, port.varied)
        self.assertIn("pipe_d_mm", result.report["sizes"]["free"])
        self.assertEqual(result.report["links"], [dict(LINK, outcome="size")])

    def test_a_pipe_the_hole_does_not_follow_is_left_out_and_a_hand_ticked_spare_is_tried(self):
        port = PipePort(still=True)
        result = export(port, ALL)
        self.assertIn({"spare_mm"}, port.varied)
        [link] = result.report["links"]
        self.assertEqual(link["outcome"], "dropped")
        view = result_view("Box.paramability", result.manifest, result.report, result.table, ALL)
        rows = {r["name"]: r["check"] for r in section(view, "sizes")["rows"]}
        self.assertEqual((rows["pipe_d_mm"], rows["spare_mm"]), (NOT_USED, NOT_USED))
        spare = next(d for d in result.report["sizes"]["dropped"] if d["name"] == "spare_mm")
        self.assertEqual((spare["used"], spare.get("tried")), (False, True))

    def test_an_unticked_parameter_acting_on_the_pipe_is_tried_once_and_named_when_it_moves_the_hole(self):
        port = PipePort()
        ticked = ["width_mm", "depth_mm", "height_mm"]
        result = export(port, ticked)
        self.assertEqual([v for v in port.varied if v & {"pipe_d_mm", "lid_mm"}], [{"pipe_d_mm"}, {"lid_mm"}])
        self.assertEqual(result.report["also_changes"], ["pipe_d_mm"])
        self.assertNotIn("pipe_d_mm", result.report["sizes"]["free"])
        view = result_view("Box.paramability", result.manifest, result.report, result.table, ticked)
        self.assertEqual(len(section_lines(view, "more")), 1)


if __name__ == "__main__":
    unittest.main()
