"""A parameter that reaches the part through the geometry of another component: found, offered, tried and followed.

The fixture is a box with a pipe hole drawn around the pipe body of another component. pipe_d_mm is a dimension of a
sketch the root owns, which a step of the pipe component extrudes into that body, so no parameter of the box reads it.
"""
import copy
import json
import re
import tempfile
import unittest
from unittest import mock

from tests import context  # noqa: F401
from tests.fakes import FakePort, FakeStore
from tests.test_translate_sketch_motion import motion_of
from tests.translator_helpers import load_capture, steps_of

from lib import orca_translate
from lib.dialog_model.result_rows import NOT_USED, result_view, section, section_lines
from lib.export_plan.pipeline import ExportRequest, run_pipeline
from lib.export_plan.probe_flow import size_probe
from lib.export_plan.size_offers import offers, table_for_body
from lib.design_model import step_links
from lib.params import size_table
from lib.probe import plan
from lib.sketch_values.motion import ENDED_STOPPED, ENDED_TIME, Motion, Stuck
from lib.timing.export_timing import ExportTiming
from lib.translator import notes, translate

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
        self.assertEqual(step_links.reach(CAPTURE), [LINK])

    def test_the_part_itself_and_sketches_other_steps_use_give_no_link(self):
        self.assertEqual(step_links.reach(CAPTURE, sketches={"BoxBase"}), [])
        own = copy.deepcopy(CAPTURE)
        own["sketch_links"][1]["links"][0].update(token="cmp_box", name="Box")
        self.assertEqual(step_links.reach(own), [])

    def test_with_the_body_known_only_its_own_steps_count_else_the_component_does(self):
        elsewhere = _pipe_acts_through(CAPTURE, {"name": "d40", "kind": "feature", "component": "cmp_pipe",
                                                 "feature": "PipeLabel"})
        self.assertEqual(step_links.reach(elsewhere), [])
        elsewhere["sketch_links"][1]["links"][0]["bodies"] = []
        self.assertEqual([link["via"] for link in step_links.reach(elsewhere)], ["component"])

    def test_a_reference_to_a_sketch_the_parameter_sits_on_reaches_it(self):
        drawn = copy.deepcopy(CAPTURE)
        drawn["sketch_links"][1]["links"][0].update(bodies=[], sketches=[{"token": "sk_pipe", "name": "PipeProfile"}])
        self.assertEqual([link["via"] for link in step_links.reach(drawn)], ["sketch"])

    def test_parameters_acting_on_a_tied_component_come_first_among_those_acting_outside(self):
        self.assertEqual(step_links.outside(CAPTURE), ["pipe_d_mm", "lid_mm"])
        self.assertEqual(step_links.outside(CAPTURE, sketches={"BoxBase"}), [])


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


class TranslateTest(unittest.TestCase):
    def test_a_hole_that_follows_the_pipe_makes_the_pipe_a_size_its_arcs_read(self):
        result = run(CAPTURE, motion_of(NAME))
        self.assertIn("pipe_d_mm", result.recipe["sizes"])
        outline = steps_of(result.recipe, "extrude")[1]["sketch"]["outer"]
        self.assertEqual(expr(outline["start"][0]), "0.5 * pipe_d_mm")
        self.assertEqual(expr(outline["segments"][0]["to"][0]), "-0.5 * pipe_d_mm")
        self.assertEqual(set(dropped(result)), {"spare_mm", "lid_mm"})
        self.assertEqual(result.follows_components, [{"token": "", "name": "Pipe"}])

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

        result = run(CAPTURE, motion_of(NAME, edit))
        found = dropped(result)["pipe_d_mm"]
        self.assertEqual(result.follows_components, [])
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

    def run_with(self, failed, built=(), moved=False, ranges=None, split=()):
        def edit(values):
            if not moved:
                for key in [k for k in values if k.startswith("5/")]:
                    del values[key]

        motion = motion_of(NAME, edit)
        low, high = min((12.0,) + tuple(built)), max((12.0,) + tuple(built))
        motion.spans = {"pipe_d_mm": {"low": low, "high": high, "failed": [list(f) for f in failed]}}
        if split:
            motion.spans["pipe_d_mm"]["split"] = [list(f) for f in split]
        table = size_table.build(CAPTURE["parameters"]["user"], ALL, CAPTURE["parameters"]["model"], ranges=ranges)
        return translate(CAPTURE, size_table=table, motion=motion)

    def test_a_size_whose_rows_never_built_was_not_measured_and_is_not_called_unchanging(self):
        found = dropped(self.run_with([(6.0, "Fillet16"), (24.0, "Chamfer3")]))["pipe_d_mm"]
        self.assertTrue(found["used"])
        self.assertNotIn("tried", found)
        self.assertIn("Fillet16", found["reason"])
        self.assertIn("Chamfer3", found["reason"])

    def test_a_size_that_failed_on_one_side_and_came_apart_on_the_other_was_not_measured(self):
        found = dropped(self.run_with([(6.0, "Fillet16")], split=[(24.0, 3)]))["pipe_d_mm"]
        self.assertTrue(found["used"])
        self.assertNotIn("tried", found)

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
        self.assertEqual([c["name"] for c in result.cuts], ["pipe_d_mm"])
        self.assertNotIn("pipe_d_mm", [f["name"] for f in result.loose])

    def test_a_typed_range_end_is_kept_where_fusion_did_not_rebuild(self):
        result = self.run_with([(8.0, "Fillet16")], built=[24.0], moved=True, ranges={"pipe_d_mm": (8.0, 24.0)})
        size = result.recipe["sizes"]["pipe_d_mm"]
        self.assertEqual((size["min"], size["max"]), (8.0, 24.0))


# ---- the whole export against a simulated Fusion ---------------------------------------------------------------

START = {p["name"]: p["expression"] for p in USER}


def _mm(store, name):
    return float(re.match(r"\s*([-0-9.eE+]+)", store.exprs[name]).group(1))


def pipe_port(still=False, bad_when=None, bad_item="Fillet1", outline_when=None, apart_when=None, breaks=None):
    """Fusion where the box outline (and the body's box and volume) follows width and depth and the hole follows the
    pipe (unless `still`). With `outline_when`, the pipe hole's sketch reads with one more loop (another outline) when
    it holds for the pipe diameter in mm; with `apart_when`, the body reads as two solids then. `breaks` is as for
    `FakeStore`. `varied` lists the parameters away from their start at every read."""
    def read(request):
        out = copy.deepcopy(port.e0)
        scale = {"s1": (_mm(port.store, "width_mm") / 40.0, _mm(port.store, "depth_mm") / 30.0),
                 "s2": (1.0, 1.0) if still else (_mm(port.store, "pipe_d_mm") / 12.0,) * 2}
        for token, (sx, sy) in scale.items():
            for loop in out["sketches"][token]["profiles"][0]["loops"]:
                for curve in loop["curves"]:
                    for key in ("start", "end", "mid", "center"):
                        if key in curve:
                            curve[key] = [curve[key][0] * sx, curve[key][1] * sy]
                    if "radius" in curve:
                        curve["radius"] *= sx
        port.varied.append({n for n in START if port.store.exprs[n] != START[n]})
        out["box"] = {"min": [0, 0, 0], "max": [_mm(port.store, "width_mm"), _mm(port.store, "depth_mm"), 10]}
        out["volume_mm3"] = _mm(port.store, "width_mm") * _mm(port.store, "depth_mm") * 10
        if outline_when is not None and outline_when(_mm(port.store, "pipe_d_mm")):
            loops = out["sketches"]["s2"]["profiles"][0]["loops"]
            inner = copy.deepcopy(loops[0])
            inner["outer"] = False
            for curve in inner["curves"]:
                curve["entity"] = curve.get("entity", "") + "x"
            loops.append(inner)
        if apart_when is not None:
            out["pieces"] = {"lumps": 2 if apart_when(_mm(port.store, "pipe_d_mm")) else 1, "others": []}
        return out

    port = FakePort(capture=CAPTURE, store=FakeStore(START, bad_when=bad_when, bad_item=bad_item, breaks=breaks),
                    reader=read)
    port.varied = []
    return port


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
        port = pipe_port(bad_when=lambda e: float(e["pipe_d_mm"].split()[0]) > 20, bad_item=step)
        return export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)

    def test_the_range_stops_near_the_failure_not_at_the_nearest_try_that_built(self):
        result = self.export("Extrude2")
        # The near try at 15 built and 24 did not: the values between are halved, so 19.5 is the last that built.
        self.assertEqual(pipe_range(result), (6.0, 19.5))

    def test_the_cut_is_in_the_report_the_manifest_and_the_result_window(self):
        result = self.export("Extrude2")
        [cut] = result.report["sizes"]["cut"]
        self.assertEqual((cut["name"], "Extrude2" in cut["reason"]), ("pipe_d_mm", True))
        self.assertEqual(result.manifest["cuts"], [{"name": "pipe_d_mm", "reason": cut["reason"]}])
        self.assertNotIn("loose", result.manifest)
        view = result_view("Box.paramability", result.manifest, result.report, result.table, ALL)
        [line] = [x for x in section_lines(view, "sizes") if x.startswith("pipe_d_mm")]
        self.assertIn("6 to 19.5 mm", line)
        self.assertIn("Extrude2", line)

    def test_a_failure_in_a_step_of_another_component_leaves_the_range_alone(self):
        result = self.export("PipeExtrude")
        self.assertEqual(pipe_range(result), (6.0, 24.0))
        self.assertNotIn("cut", result.report["sizes"])


class UnfinishedRangeTest(unittest.TestCase):
    """As `RangeCutTest`, with the pipe tried first (a favourite): its far end 24 fails. When the tries end before the
    values between 15 and 24 are tried, the range stays at 15, and the reason says those values were not tried. The far
    rows run one size at a time, each size followed by its nearer rows, so a later size that ends the tries comes after
    the pipe's halving."""

    def export(self, breaks=None, limit=None, favourite="pipe_d_mm"):
        port = pipe_port(bad_when=lambda e: float(e["pipe_d_mm"].split()[0]) > 20, bad_item="Extrude2", breaks=breaks)
        clock = [0.0]  # each recompute takes 10 s on the export's clock
        port.store.on_recompute = lambda store: clock.__setitem__(0, clock[0] + 10.0)
        port.timing = ExportTiming(lambda: clock[0])
        params = [dict(p, is_favorite=p["name"] == favourite) for p in USER]
        request = ExportRequest(title="Box", writer="test", up_axis="z", parameters=params, model_params=MODEL,
                                design_unit="mm", ticked=table_for_body(USER, "mm", MODEL, CAPTURE).ticked,
                                ranges={}, probe_time_limit=limit)
        # The pipe drives the extrude of the Pipe component, which puts its far rows last; these cases need them first.
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(size_probe, "outside_drivers", lambda c: []):
            result = run_pipeline(port, request, tmp)
        self.assertEqual(port.store.exprs, START)
        [cut] = result.report["sizes"]["cut"]
        return result, cut["reason"], result.report["probe"]["motion"]["spans"]["pipe_d_mm"]

    def test_tries_stopped_by_a_broken_design_leave_the_range_at_the_last_value_built_and_say_why(self):
        # The pipe's own far end (24) also leaves the design broken with the values back.
        result, reason, span = self.export(breaks=("pipe_d_mm", 20))
        self.assertIsNotNone(result.report["probe"]["stopped"])
        self.assertEqual(pipe_range(result), (6.0, 15.0))
        self.assertEqual(span["unfinished"], {"high": ENDED_STOPPED})
        self.assertIn(notes.untried_between_why(ENDED_STOPPED), reason)

    def test_a_later_size_that_breaks_the_design_comes_after_the_halving_of_a_size_whose_far_end_failed(self):
        # The far end of the width (80) leaves the design broken with the values back, after the pipe's 24 failed.
        result, reason, span = self.export(breaks=("width_mm", 50))
        self.assertIsNotNone(result.report["probe"]["stopped"])
        self.assertEqual(pipe_range(result), (6.0, 19.5))
        self.assertNotIn("unfinished", span)
        width = result.report["probe"]["motion"]["spans"]["width_mm"]
        self.assertEqual((width["high"], width["unfinished"]), (50.0, {"high": ENDED_STOPPED}))

    def test_tries_that_ran_out_of_time_leave_the_range_at_the_last_value_built_and_say_why(self):
        result, reason, span = self.export(limit=240)
        self.assertTrue(result.report["probe"]["time_limit"]["hit"])
        self.assertEqual(pipe_range(result), (6.0, 15.0))
        self.assertEqual(span["unfinished"], {"high": ENDED_TIME})
        self.assertIn(notes.untried_between_why(ENDED_TIME), reason)

    def test_a_time_limit_between_the_far_rows_of_two_sizes_keeps_the_halving_of_the_first(self):
        # The limit falls after the width's far minimum: its maximum and the far rows of the sizes after it never run.
        result, reason, span = self.export(limit=320)
        self.assertTrue(result.report["probe"]["time_limit"]["hit"])
        self.assertEqual(pipe_range(result), (6.0, 19.5))
        self.assertNotIn("unfinished", span)
        spans = result.report["probe"]["motion"]["spans"]
        self.assertEqual((spans["width_mm"]["low"], spans["width_mm"]["high"]), (20.0, 50.0))
        self.assertEqual((spans["depth_mm"]["low"], spans["depth_mm"]["high"]), (22.5, 37.5))

    def test_tries_that_end_early_after_the_last_value_built_was_found_keep_the_plain_reason(self):
        # The pipe is tried last: its halving ends at 19.5 before the time limit stops the tries.
        result, reason, span = self.export(limit=430, favourite=None)
        self.assertTrue(result.report["probe"]["time_limit"]["hit"])
        self.assertEqual(pipe_range(result), (6.0, 19.5))
        self.assertNotIn("unfinished", span)
        self.assertEqual(reason, notes.cut_reason("pipe_d_mm", "the range stops at 19.5",
                                                  notes.not_rebuilt_why([(20.625, "Extrude2")])))


class OutlineRangeTest(unittest.TestCase):
    """The pipe (12 now, range 6 to 24) does not rebuild in Fusion below `low`, and its hole makes another outline above
    `high`."""

    def export(self, low, high):
        port = pipe_port(outline_when=lambda d: d > high, bad_item="Extrude2",
                         bad_when=lambda e: float(e["pipe_d_mm"].split()[0]) < low)
        return export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)

    def test_a_size_that_fails_below_and_changes_its_outline_above_keeps_the_range_between(self):
        result = self.export(10, 18)
        # Each side is halved toward the value now: 10.125 is the last value that built, 17.25 the last that kept the
        # outline (19.5 and 18.375 did not).
        self.assertEqual(pipe_range(result), (10.125, 17.25))
        [cut] = result.report["sizes"]["cut"]
        self.assertTrue("Extrude2" in cut["why"] and "PipeHole" in cut["why"])
        self.assertNotIn("loose", result.manifest)

    def test_a_size_with_no_working_value_but_its_own_is_dropped_with_why(self):
        result = self.export(11.99, 12.01)
        [found] = [d for d in result.report["sizes"]["dropped"] if d["name"] == "pipe_d_mm"]
        self.assertTrue("Extrude2" in found["reason"] and "PipeHole" in found["reason"])


class ApartRangeTest(unittest.TestCase):
    """Fusion builds the part in two separate pieces when the pipe is narrower than 8 (12 now, range 6 to 24)."""

    def test_the_range_starts_at_the_last_value_tried_in_one_piece_and_says_why(self):
        port = pipe_port(apart_when=lambda d: d < 8)
        result = export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)
        # 6 and 7.5 came apart, 9 and 8.25 did not; the halving stops at 7.875.
        self.assertEqual(pipe_range(result), (8.25, 24.0))
        [cut] = result.report["sizes"]["cut"]
        self.assertIn(notes.split_why([(7.875, 2)]), cut["reason"])
        states = [s for s in result.report["probe"]["states"] if s.get("pieces")]
        self.assertEqual(sorted(s["values"]["pipe_d_mm"] for s in states), [6.0, 7.5, 7.875])


def placed_by_the_assembly():
    """The fixture with three more parameters in the root: `joint_x` sets a joint, `move_x` a Move of occurrences and
    `body_x` a Move of bodies. The first two may move Pipe against the box, so PipeHole may follow them."""
    capture = copy.deepcopy(CAPTURE)
    for name, kind, feature in (("joint_x", "joint", "Slider1"), ("move_x", "feature", "Move1"),
                                ("body_x", "feature", "Move2")):
        capture["parameters"]["user"].append(dict(copy.deepcopy(USER[-1]), name=name, dependents=[
            {"name": "d_" + name, "kind": kind, "component": "cmp_root", "feature": feature}]))
    for index, name, inputs in ((6, "Move1", "occurrences"), (7, "Move2", "bodies")):
        capture["items"].append({"index": index, "type": "MoveFeature", "name": name, "component": "cmp_root",
                                 "in_target_component": False, "target_changed": False, "bodies_before": [],
                                 "bodies_after": [], "data": {"input_kind": inputs}})
    return capture


class PlacedComponentTest(unittest.TestCase):
    def setUp(self):
        self.capture = placed_by_the_assembly()
        self.links = step_links.reach(self.capture)
        self.names = [p["name"] for p in self.capture["parameters"]["user"]]

    def test_a_size_that_places_an_occurrence_reaches_every_sketch_tied_to_another_component(self):
        found = {(link["param"], link["sketch"], link["via"]) for link in self.links}
        self.assertIn(("joint_x", "PipeHole", "assembly"), found)
        self.assertIn(("move_x", "PipeHole", "assembly"), found)
        self.assertNotIn("body_x", {link["param"] for link in self.links})

    def test_the_recipe_marks_such_a_size_when_no_try_set_it(self):
        result = run(self.capture, motion_of(NAME), self.names)
        self.assertTrue(dropped(result)["move_x"]["used"])

    def test_the_recipe_marks_such_a_size_without_a_motion_file(self):
        self.assertTrue(dropped(run(self.capture, None, self.names))["move_x"]["used"])

    def test_the_orca_copy_marks_such_a_size(self):
        table = size_table.build(self.capture["parameters"]["user"], self.names, self.capture["parameters"]["model"],
                                 links=self.links)
        outcomes = {p["name"]: p["outcome"] for p in orca_translate.translate(self.capture, table).parameters}
        self.assertNotEqual(outcomes["move_x"], "unused")
        self.assertEqual(outcomes["body_x"], "unused")


class UnreadTriedSizeTest(unittest.TestCase):
    """spare_mm is read by no step, and the probe tried it alone."""

    def test_only_a_size_whose_tries_kept_the_body_as_it_was_is_called_unchanging(self):
        for label, body, want in (("body changed", {"spare_mm": True}, (True, None)),
                                  ("body the same", {"spare_mm": False}, (False, True)),
                                  ("body not read", {}, (False, None))):
            with self.subTest(label):
                motion = motion_of(NAME)
                motion.states.append({"values": {"spare_mm": 3.0}, "built": True})
                motion.body_changes = body
                found = dropped(run(CAPTURE, motion))["spare_mm"]
                self.assertEqual((found["used"], found.get("tried")), want)


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
        port = pipe_port()
        result = export(port, table_for_body(USER, "mm", MODEL, CAPTURE).ticked)
        self.assertIn({"pipe_d_mm"}, port.varied)
        self.assertIn("pipe_d_mm", result.report["sizes"]["free"])
        self.assertEqual(result.report["links"], [dict(LINK, outcome="size")])

    def test_a_pipe_the_hole_does_not_follow_is_left_out_and_a_hand_ticked_spare_is_tried(self):
        port = pipe_port(still=True)
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
        port = pipe_port()
        ticked = ["width_mm", "depth_mm", "height_mm"]
        result = export(port, ticked)
        self.assertEqual([v for v in port.varied if v & {"pipe_d_mm", "lid_mm"}], [{"pipe_d_mm"}, {"lid_mm"}])
        self.assertEqual(result.report["also_changes"], ["pipe_d_mm"])
        self.assertNotIn("pipe_d_mm", result.report["sizes"]["free"])
        view = result_view("Box.paramability", result.manifest, result.report, result.table, ticked)
        self.assertEqual(len(section_lines(view, "more")), 1)


if __name__ == "__main__":
    unittest.main()
