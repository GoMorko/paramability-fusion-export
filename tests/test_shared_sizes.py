"""Sizes that a part shares with another component: a try that changes the body only through the part's own step
values is explained (export_plan/probe_flow/body_routes.py), and a size with a route the probe does not read keeps
its mark."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import model, size, table, user
from tests.test_probe_flow import states
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED
from tests.test_probe_refs_flow import UNITS, WallBody

from lib.design_edit.runner import RowExport
from lib.design_model import step_links
from lib.export_plan.probe_flow import SizeProbe
from lib.export_plan.probe_flow.body_routes import explained

# `wall` sets the length of Extrude4 and the shell of Box, another component that Sketch1 of the part is drawn around.
OWN_VALUE = {"name": "d10", "kind": "feature", "component": "c", "feature": "Extrude4"}
BOX_SHELL = {"name": "d20", "kind": "feature", "component": "box", "feature": "Shell1"}
BOX = {"token": "box", "name": "Box"}


def shared_capture(dependents=(OWN_VALUE, BOX_SHELL), value=True, tied=("Sketch1",)):
    """CAPTURE as one body of component `c` whose Extrude4 length reads `wall` (when `value`), and whose sketches in
    `tied` are drawn around Box. `wall` acts where `dependents` say; None leaves the list out."""
    out = copy.deepcopy(CAPTURE)
    out["target"] = {"token": "t1", "name": "Body1"}
    for item in out["items"]:
        item.update(component="c", in_target_component=True)
    if value:
        out["items"][0]["data"]["params"] = {"side_one.distance": {"name": "d10", "expression": "wall", "value": 0.2}}
    wall = user("wall", "2 mm", 2)
    if dependents is not None:
        wall["dependents"] = [dict(d) for d in dependents]
    out["parameters"] = {"user": PARAMS + [wall], "model": []}
    out["sketch_links"] = [{"sketch": name, "links": [dict(BOX)]} for name in tied]
    return out


def shared_table(capture, extra_model=()):
    model_params = MODEL + [model("d10", "wall", 2, kind="feature")] + list(extra_model)
    built = table(capture["parameters"]["user"], TICKED + ["wall"], model_params)
    return built.with_links(step_links.reach(capture))


def probed(capture, size_table):
    """The motion of the tries of a design whose body grows with `wall` while no sketch moves with it."""
    fusion = WallBody()
    probe = SizeProbe.start(capture, size_table, fusion.read)
    units = dict(UNITS, wall="mm")
    sizes = [size(size_table, n, units[n]) for n in TICKED + ["wall"]]
    rows = probe.probe_rows(sizes)
    reads = []
    job = RowExport(fusion.store, units, lambda path: reads.append(probe.read_now()))
    results = job.run(rows, "", lambda *a: True, tolerate_build_errors=True)
    probe.add_states(states([{p: r["state"][p] for p in r["varied"]} for r in rows], results, reads))
    probe.finish(probe.read_now(), {})
    return probe.motion


class SharedSizeTriesTest(unittest.TestCase):
    def test_a_shared_size_that_changes_the_part_through_its_own_values_is_not_marked(self):
        capture = shared_capture()
        size_table = shared_table(capture)
        self.assertEqual([link["via"] for link in size_table.links_of("wall")], ["component"])
        self.assertEqual(probed(capture, size_table).body_moved, [])

    def test_a_shared_size_that_no_value_of_the_part_reads_stays_marked(self):
        capture = shared_capture(value=False)
        self.assertEqual(probed(capture, shared_table(capture)).body_moved, ["wall"])


class ExplainedTest(unittest.TestCase):
    """`explained` with the sketches the probe follows (`followed`) and the measured references it reads (`refs`)."""

    def answer(self, capture, size_table=None, followed=("Sketch1", "Sketch2"), refs=()):
        size_table = size_table or shared_table(capture)
        return explained(capture, size_table, set(followed), set(refs))

    def test_a_size_that_only_feeds_the_part_and_a_followed_tied_sketch_is_explained(self):
        self.assertEqual(self.answer(shared_capture()), {"wall"})

    def test_a_tied_sketch_that_is_not_followed_keeps_every_mark(self):
        self.assertEqual(self.answer(shared_capture(), followed=("Sketch2",)), set())

    def test_a_tied_sketch_of_unreadable_references_that_is_not_followed_keeps_every_mark(self):
        capture = shared_capture(tied=())
        capture["sketch_links"] = [{"sketch": "Sketch1", "links": [], "unknown": True}]
        self.assertEqual(self.answer(capture, followed=("Sketch2",)), set())
        self.assertEqual(self.answer(capture), {"wall"})

    def test_a_size_whose_reach_the_capture_does_not_list_stays_marked(self):
        self.assertEqual(self.answer(shared_capture(dependents=None)), set())

    def test_a_size_that_may_place_an_occurrence_stays_marked(self):
        joint = {"name": "d30", "kind": "joint", "component": "root"}
        self.assertEqual(self.answer(shared_capture(dependents=(OWN_VALUE, joint))), set())

    def test_a_size_behind_construction_geometry_stays_marked(self):
        capture = shared_capture()
        plane = model("d40", "wall", 2, kind="constructionPlane", token="cp7")
        self.assertEqual(self.answer(capture, shared_table(capture, [plane])), set())

    def test_a_size_behind_a_dimension_is_explained_only_when_its_sketch_is_followed(self):
        capture = shared_capture()
        dimension = model("d50", "wall", 2, sketch="Sketch5")
        size_table = shared_table(capture, [dimension])
        self.assertEqual(self.answer(capture, size_table), set())
        self.assertEqual(self.answer(capture, size_table, followed=("Sketch1", "Sketch2", "Sketch5")), {"wall"})

    def test_a_reference_of_another_component_that_is_not_read_keeps_the_mark(self):
        capture = shared_capture()
        link = {"param": "wall", "sketch": "", "component": "Box", "via": "reference", "step": "Extrude6",
                "ref": "6.side_one"}
        size_table = shared_table(capture)
        size_table = size_table.with_links(list(size_table.links) + [link])
        self.assertEqual(self.answer(capture, size_table), set())
        self.assertEqual(self.answer(capture, size_table, refs=("6.side_one",)), {"wall"})

    def test_a_capture_that_does_not_name_the_body_explains_nothing(self):
        capture = shared_capture()
        del capture["target"]
        self.assertEqual(self.answer(capture, shared_table(shared_capture())), set())


if __name__ == "__main__":
    unittest.main()
