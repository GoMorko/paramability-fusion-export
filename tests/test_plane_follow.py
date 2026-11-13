"""Sketches and extrude reaches on construction planes built on the part (docs/capture-format.md, "Sketch values that
follow sizes"): the probe tries the sizes that move the plane, the copy follows the measured plane, and a size it
could not measure is marked, never kept as exact."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import size
from tests.translator_helpers import load_capture, steps_of

from lib.export_plan.probe_flow import SizeProbe
from lib.params import size_table
from lib.probe.plane_sizes import plane_driven
from lib.sketch_values.motion import Motion
from lib.translator import translate

PLATE = 10.0
TOP_FACE = {"entity_type": "BRepFace", "face_point": [20, 10, 10], "surface": "Plane",
            "body": {"token": "t1", "name": "Body1"}}
OFFSET = "ConstructionPlaneOffsetDefinition"


def plane_on_top(token="cp1", made_by=2, point=8.0, built_on=None):
    """A construction plane offset from the plate's top face (z = plate_mm), or from what `built_on` says."""
    return {"entity_type": "ConstructionPlane", "token": token, "definition": OFFSET, "made_by": made_by,
            "point": [0, 0, point], "normal": [0, 0, 1], "built_on": built_on or [TOP_FACE]}


def lifted(gap="-2 mm", gap_mm=-2.0):
    """The sketch_offset_plane fixture with Plane1 offset from the plate's top face by `gap` instead of from the
    base: Sketch2 (the pocket) sits on it, and Extrude3 (the post) reaches up to it."""
    capture = load_capture("sketch_offset_plane")
    plane = capture["parameters"]["model"][1]
    plane.update(expression=gap, value=gap_mm / 10.0, dependency_parameters=[n for n in ("gap_mm",) if n in gap])
    reference = capture["items"][4]["data"]["profiles"][0]["reference"]
    reference.update(definition=OFFSET, built_on=[TOP_FACE], made_by=2)
    side = capture["items"][5]["data"]["side_one"]
    side.update({k: v for k, v in plane_on_top().items() if k in ("definition", "built_on", "made_by")})
    return capture


def with_gap_size(capture):
    capture["parameters"]["user"].append(dict(capture["parameters"]["user"][0], name="gap_mm", expression="2 mm",
                                              value=0.2, display_value=2))
    return capture


def table_of(capture, ticked):
    params = capture["parameters"]
    return size_table.build(params["user"], ticked, params["model"], capture.get("design_units", "mm"))


def run(capture, ticked, motion):
    return translate(capture, size_table=table_of(capture, ticked), motion=motion)


def reasons(result):
    return {f["name"]: f["reason"] for f in result.loose}


def expr(value):
    return value["expr"] if isinstance(value, dict) else value


def read_at(capture, plate=PLATE, gap=2.0):
    """The probe read of `capture` with the plate `plate` thick: the pocket sketch sits `gap` below the top face."""
    sketches = {}
    for item in capture["items"]:
        for profile in (item.get("data") or {}).get("profiles") or []:
            frame = copy.deepcopy(profile["frame"])
            if profile["sketch"] == "Sketch2":
                frame["origin"][2] = plate - gap
            sketches.setdefault(profile["sketch_token"], {"frame": frame, "profiles": []})["profiles"].append(
                {"loops": profile["loops"]})
    params = {"plate_mm": plate / 10, "d1": plate / 10, "lift_mm": 0.8, "d20": -gap / 10, "gap_mm": gap / 10}
    return {"sketches": sketches, "points": {}, "lines": {}, "params": params,
            "box": {"min": [0, 0, 0], "max": [40, 20, plate]}}


def probed(capture, table, sizes):
    """The motion of a probe that runs every near and far row it plans, each read with the plate as the row set it."""
    probe = SizeProbe.start(capture, table, lambda request: read_at(capture))
    rows = probe.probe_rows(sizes)
    rows += probe.far_rows(sizes, 64 - len(rows))
    entries = []
    for row in rows:
        values = {p: row["state"][p] for p in row["varied"]}
        entries.append((values, {"name": row["name"]}, read_at(capture, values.get("plate_mm", PLATE))))
    probe.add_states(entries)
    probe.finish(read_at(capture), {})
    return rows, probe.motion


class SketchOnPlaneTest(unittest.TestCase):
    def setUp(self):
        self.capture = lifted()
        self.capture["items"].pop()

    def test_the_probe_tries_a_size_that_moves_the_plane_and_the_sketch_follows_it(self):
        table = table_of(self.capture, ["plate_mm"])
        rows, motion = probed(self.capture, table, [size(table, "plate_mm")])
        self.assertIn("plate_mm (near min)", [r["name"] for r in rows])
        self.assertEqual(motion.body_moved, [])
        result = translate(self.capture, size_table=table, motion=motion)
        self.assertEqual((result.loose, result.fixed), ([], []))
        pocket = steps_of(result.recipe, "extrude")[1]["sketch"]
        self.assertEqual(expr(pocket["on"]["origin"][2]), "plate_mm - 2")

    def test_a_size_that_moves_the_plane_and_was_not_tried_is_marked(self):
        untried = Motion(states=[{"values": {"lift_mm": 4.0}, "built": True}], untried=["plate_mm"])
        for label, motion in (("not tried", untried), ("no probe", None)):
            with self.subTest(label):
                result = run(copy.deepcopy(self.capture), ["plate_mm"], motion)
                self.assertIn("plane Sketch2 sits on", reasons(result)["plate_mm"])
                pocket = steps_of(result.recipe, "extrude")[1]["sketch"]
                self.assertEqual(pocket["on"]["origin"][2], 8.0)

    def test_a_plane_built_on_an_origin_plane_needs_no_tries_of_earlier_sizes(self):
        capture = load_capture("sketch_offset_plane")
        self.assertEqual(plane_driven(capture, table_of(capture, ["plate_mm"])), [])
        self.assertEqual(plane_driven(self.capture, table_of(self.capture, ["plate_mm"])), ["plate_mm"])


class PlaneChainTest(unittest.TestCase):
    """Plane2 is offset 1 mm from Plane1, which is offset -2 mm from the plate's top face."""

    def setUp(self):
        self.capture = lifted()
        chain = plane_on_top("cp2", 3, 9.0, [plane_on_top()])
        side = self.capture["items"][5]["data"]["side_one"]
        side.update(chain, plane={"point": [0, 0, 9], "normal": [0, 0, 1]})
        self.capture["items"][5]["data"]["end_offset"] = 9.0
        self.capture["items"][4]["data"]["profiles"][0]["reference"].update(
            token="cp2", made_by=3, built_on=chain["built_on"])

    def test_the_last_plane_of_a_chain_follows_the_face_under_it_and_is_tried_with_that_size(self):
        result = run(self.capture, ["plate_mm"], Motion())
        post = steps_of(result.recipe, "extrude")[2]
        self.assertEqual(expr(post["distance"]), "plate_mm - 1")
        self.assertNotIn("plate_mm", reasons(result))
        self.assertEqual(plane_driven(self.capture, table_of(self.capture, ["plate_mm"])), ["plate_mm"])

    def test_a_chain_on_a_plane_the_copy_cannot_place_marks_its_sizes(self):
        side = self.capture["items"][5]["data"]["side_one"]
        side["built_on"][0]["definition"] = "ConstructionPlaneAtAngleDefinition"
        result = run(self.capture, ["plate_mm"], Motion())
        self.assertIn("plane built on part geometry", reasons(result)["plate_mm"])


class PlaneOffsetSizeTest(unittest.TestCase):
    """Plane1 lies gap_mm below the plate's top face: its own offset is a size."""

    def setUp(self):
        self.capture = with_gap_size(lifted("-gap_mm", -2.0))

    def test_a_sketch_on_the_plane_follows_both_sizes_through_the_probe(self):
        capture = copy.deepcopy(self.capture)
        capture["items"].pop()
        table = table_of(capture, ["plate_mm", "gap_mm"])
        self.assertEqual(plane_driven(capture, table), ["plate_mm", "gap_mm"])
        probe = SizeProbe.start(capture, table, lambda request: read_at(capture))
        entries = [({"plate_mm": p, "gap_mm": g}, {"name": "row"}, read_at(capture, p, g))
                   for p, g in ((7.5, 2.0), (12.5, 2.0), (10.0, 1.5), (10.0, 2.5))]
        probe.add_states(entries)
        probe.finish(read_at(capture), {})
        result = translate(capture, size_table=table, motion=probe.motion)
        pocket = steps_of(result.recipe, "extrude")[1]["sketch"]
        self.assertEqual(expr(pocket["on"]["origin"][2]), "plate_mm - gap_mm")
        self.assertFalse([why for why in reasons(result).values() if "plane" in why])

    def test_a_reach_to_the_plane_follows_the_face_and_its_own_distance(self):
        result = run(self.capture, ["plate_mm", "gap_mm"], Motion())
        post = steps_of(result.recipe, "extrude")[2]
        self.assertEqual(expr(post["distance"]), "plate_mm - gap_mm")
        self.assertEqual((reasons(result), result.dropped), ({}, []))


class OlderCaptureTest(unittest.TestCase):
    def test_a_reach_to_a_plane_without_its_description_marks_the_sizes_read_before(self):
        capture = load_capture("sketch_offset_plane")
        for key in ("definition", "built_on", "made_by"):
            capture["items"][5]["data"]["side_one"].pop(key)
        result = run(capture, ["lift_mm", "plate_mm"], Motion())
        self.assertIn("does not say what the plane is built on", reasons(result)["plate_mm"])


if __name__ == "__main__":
    unittest.main()
