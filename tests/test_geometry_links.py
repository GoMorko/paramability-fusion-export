"""A parameter that reaches the part through the geometry of another component: found, offered, tried and followed.

The fixture is a box with a pipe hole drawn around the pipe of another component. pipe_d_mm sets the pipe and has its
model parameters only there, so no parameter of the box reads it.
"""
import copy
import re
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeStore
from tests.test_pipeline import FakePort
from tests.test_translate_sketch_motion import motion_of
from tests.translator_helpers import load_capture, steps_of

from lib.dialog_model.result_rows import NOT_USED, result_view
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
LINK = {"param": "pipe_d_mm", "sketch": "PipeHole", "component": "Pipe"}


def run(capture, motion, ticked=ALL):
    table = size_table.build(capture["parameters"]["user"], ticked, capture["parameters"]["model"])
    return translate(capture, size_table=table, motion=motion)


def dropped(result):
    return {d["name"]: d for d in result.dropped}


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


class RuleTest(unittest.TestCase):
    def test_a_parameter_with_model_parameters_in_the_linked_component_reaches_the_sketch(self):
        self.assertEqual(geometry_links.reach(CAPTURE), [LINK])

    def test_the_part_itself_and_sketches_other_steps_use_give_no_link(self):
        self.assertEqual(geometry_links.reach(CAPTURE, sketches={"BoxBase"}), [])
        own = copy.deepcopy(CAPTURE)
        own["sketch_links"][1]["links"][0].update(token="cmp_box", name="Box")
        self.assertEqual(geometry_links.reach(own), [])

    def test_components_without_tokens_match_by_name(self):
        bare = copy.deepcopy(CAPTURE)
        bare["sketch_links"][1]["links"][0]["token"] = ""
        for p in bare["parameters"]["user"]:
            for c in p.get("dependent_components") or []:
                c["token"] = ""
        self.assertEqual(geometry_links.reach(bare), [LINK])


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
        self.assertEqual(set(dropped(result)), {"spare_mm"})

    def test_a_circle_that_follows_the_pipe_writes_its_radius_as_a_formula(self):
        capture = copy.deepcopy(CAPTURE)
        profile = capture["items"][3]["data"]["profiles"][0]
        profile["loops"][0]["curves"] = [{"kind": "circle", "center": [0, 0], "radius": 6.0, "entity": "c0"}]

        def edit(values):
            for key in [k for k in values if k.startswith("3/")]:
                del values[key]
            values["3/p0/l0/radius"] = {"const": 0, "terms": {"pipe_d_mm": 0.5}, "sketch": "PipeHole"}

        result = run(capture, motion_of(NAME, edit))
        outline = steps_of(result.recipe, "extrude")[1]["sketch"]["outer"]
        self.assertEqual((outline["kind"], expr(outline["radius"]), outline["center"]),
                         ("circle", "0.5 * pipe_d_mm", [0.0, 0.0]))

    def test_a_hole_that_stays_put_leaves_the_pipe_out_as_unused(self):
        def edit(values):
            for key in [k for k in values if k.startswith("3/")]:
                del values[key]

        found = dropped(run(CAPTURE, motion_of(NAME, edit)))["pipe_d_mm"]
        self.assertFalse(found["used"])

    def test_a_hole_whose_outline_changes_shape_leaves_the_pipe_out_naming_the_sketch(self):
        def edit(values):
            for key in [k for k in values if k.startswith("3/")]:
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


# ---- the whole export against a simulated Fusion ---------------------------------------------------------------

START = {p["name"]: p["expression"] for p in USER}


def _mm(store, name):
    return float(re.match(r"\s*([-0-9.eE+]+)", store.exprs[name]).group(1))


class PipePort(FakePort):
    """Fusion where the box outline follows width and depth and the hole follows the pipe (unless `still`)."""

    def __init__(self, still=False):
        super().__init__(capture=CAPTURE, store=FakeStore(START))
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
        rows = {r["name"]: r["check"] for r in view["rows"]}
        self.assertEqual((rows["pipe_d_mm"], rows["spare_mm"]), (NOT_USED, NOT_USED))


if __name__ == "__main__":
    unittest.main()
