"""Modeled threads in the Orca copy: a ThreadFeature on a rod or in a hole becomes an Orca thread that stays half a
pitch inside each end, with a lead-in at each end where the thread runs out of the part; an end the copy cannot judge,
and what Orca cannot make, are left out; a cosmetic thread writes nothing."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import model, user
from tests.test_orca_finishes import finish_item, finishes
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, limits, translate
from lib.orca_translate.formulas import orca_value
from lib.orca_translate.place import Placement
from lib.params import size_table

M8 = {"thread_type": "ISO Metric profile", "designation": "M8x1.25", "thread_class": "6g", "internal": False,
      "right_hand": True, "pitch": 1.25, "major_diameter": 8.0, "minor_diameter": 6.466, "angle_deg": None}
# A lead-in is half a pitch less 0.05 mm deep.
M8_LEAD = 0.5 * 1.25 - 0.05


def face(radius=4.0, span=(0.0, 12.0), outward=True, origin=(0, 0, 0)):
    return {"surface": "Cylinder", "origin": list(origin), "axis": [0, 0, 1], "radius": radius, "span": list(span),
            "face_point": [origin[0] + radius, origin[1], 6], "outward": outward}


def rod(**thread):
    """A rod of radius 4, 12 high, with a modeled M8 thread over its whole face unless `thread` says otherwise."""
    capture = copy.deepcopy(load_capture("fillet_closed_edge"))
    data = capture["items"][1]["data"]
    data["profiles"][0]["loops"][0]["curves"][0]["radius"] = 4.0
    data["side_one"]["distance"], data["end_offset"] = 12.0, 12.0
    capture["target"]["box"] = {"min": [-4, -4, 0], "max": [4, 4, 12]}
    found = dict(M8, modeled=True, full_length=True, length=12.0, offset=0.0, faces=[face()], made_span=[0.0, 12.0])
    found.update(thread)
    capture["items"][2] = dict(capture["items"][2], name="Thread1", type="ThreadFeature", data=found)
    return capture


def joined(capture, curves, z, height, at=2):
    """`capture` with an extrude that joins an outline (`curves` in the XY plane) from height `z` up by `height`,
    put in as timeline item `at`."""
    extrude = copy.deepcopy(capture["items"][1])
    profile = extrude["data"]["profiles"][0]
    profile["frame"] = dict(profile["frame"], origin=[0, 0, z])
    profile["loops"] = [{"outer": True, "curves": curves}]
    extrude["data"].update(operation="join", end_offset=height)  # measured from its own sketch plane
    extrude["data"]["side_one"]["distance"] = height
    extrude.update(index=at, name="Extrude%d" % at)
    capture["items"].insert(at, extrude)
    for n, item in enumerate(capture["items"]):
        item["index"] = n
    return capture


def square(half, centre=(0.0, 0.0)):
    x0, y0, x1, y1 = centre[0] - half, centre[1] - half, centre[0] + half, centre[1] + half
    return [{"kind": "line", "start": [x0, y0], "end": [x1, y0]}, {"kind": "line", "start": [x1, y0], "end": [x1, y1]},
            {"kind": "line", "start": [x1, y1], "end": [x0, y1]}, {"kind": "line", "start": [x0, y1], "end": [x0, y0]}]


def threads(result):
    return [f for f in result.recipe.features if f.type == FeatureType.THREAD]


def lead_cuts(result):
    """The ring cuts at the open ends of an outside thread: (plane origin, plane normal, depth, radii)."""
    out = []
    for f in result.recipe.features:
        if f.type == FeatureType.EXTRUDE and f.mode == BooleanMode.CUT:
            sketch = result.recipe.features[f.sketch_ref]
            out.append((sketch.plane.origin, sketch.plane.normal, f.distance, sorted(e.radius for e in sketch.entities)))
    return out


class ThreadFeatureTest(unittest.TestCase):
    def test_a_rod_thread_stays_half_a_pitch_inside_and_gets_a_lead_in_at_each_open_end(self):
        capture = rod()
        result = translate(capture)
        (made,) = threads(result)
        self.assertEqual((made.thread_radius, made.thread_pitch, made.thread_internal, made.thread_major_nominal),
                         (4.0, 1.25, False, True))
        self.assertAlmostEqual(made.thread_depth, (8.0 - 6.466) / 2)
        self.assertAlmostEqual(made.thread_height, 12.0 - 1.25)
        place = Placement(capture)
        self.assertEqual(made.plane.origin, place.point([0, 0, 0.625]))
        self.assertEqual(made.plane.normal, (0.0, 0.0, 1.0))
        cuts = lead_cuts(result)
        self.assertEqual([(o, n) for o, n, _, _ in cuts], [(place.point([0, 0, 0]), (0.0, 0.0, 1.0)),
                                                          (place.point([0, 0, 12]), (0.0, 0.0, -1.0))])
        for _, _, depth, radii in cuts:
            self.assertAlmostEqual(depth, M8_LEAD)
            self.assertAlmostEqual(radii[0], 6.466 / 2)
            self.assertAlmostEqual(radii[1], 4.1)
        self.assertEqual(result.left_out, [])

    def test_a_rod_on_a_shoulder_gets_a_lead_in_at_its_free_end_only(self):
        capture = rod(faces=[face(span=(4.0, 12.0))], length=8.0, made_span=[4.0, 12.0])
        rim = capture["items"][1]["data"]["profiles"][0]["loops"][0]["curves"]
        capture["items"][1]["data"]["side_one"]["distance"] = 4.0
        capture["items"][1]["data"]["end_offset"] = 4.0
        capture["items"][1]["data"]["profiles"][0]["loops"] = [{"outer": True, "curves": square(7.0)}]
        capture = joined(capture, rim, 4.0, 8.0)
        capture["target"]["box"] = {"min": [-7, -7, 0], "max": [7, 7, 12]}
        result = translate(capture)
        (made,) = threads(result)
        self.assertAlmostEqual(made.thread_height, 8.0 - 1.25)
        self.assertEqual([n for _, n, _, _ in lead_cuts(result)], [(0.0, 0.0, -1.0)])

    def test_a_part_length_thread_starts_at_the_end_it_touches_and_follows_its_length(self):
        capture = rod(full_length=False, length=6.0, made_span=[6.0, 12.0])
        capture["parameters"] = {"user": [user("len", "6 mm", 6)], "model": [model("d9", "len", 6)]}
        capture["items"][2]["data"]["params"] = {"length": {"name": "d9", "expression": "len", "value": 6.0}}
        table = size_table.build(capture["parameters"]["user"], ["len"], capture["parameters"]["model"])
        result = translate(capture, table)
        (made,) = threads(result)
        self.assertEqual(made.plane.normal, (0.0, 0.0, -1.0))
        self.assertAlmostEqual(orca_value(made.expr["thread_height"], {"len": 8.0}), 8.0 - 1.25)
        self.assertEqual([n for _, n, _, _ in lead_cuts(result)], [(0.0, 0.0, -1.0)])  # the far end is in the rod
        (param,) = result.parameters
        self.assertEqual((param["outcome"], len(param["follows"])), ("variable", 2))  # where it is used, its limits

    def test_an_inside_thread_gets_a_wider_shallow_hole_at_each_open_end(self):
        capture = copy.deepcopy(load_capture("thread_modeled"))
        capture["items"][3]["data"]["diameter"] = 6.647
        capture["items"][4]["data"] = dict(M8, modeled=True, internal=True, minor_diameter=6.647, full_length=True,
                                           length=10.0, offset=0.0, made_span=[0.0, 10.0],
                                           faces=[face(radius=3.3235, span=(0, 10), outward=False, origin=(10, 10, 0))])
        result = translate(capture)
        (made,) = threads(result)
        self.assertTrue(made.thread_internal)
        leads = [f for f in result.recipe.features if f.type == FeatureType.HOLE][1:]
        self.assertEqual(sorted(f.plane.normal[2] for f in leads), [-1.0, 1.0])
        for lead in leads:
            self.assertAlmostEqual(lead.hole_diameter, 8.1)
            self.assertAlmostEqual(lead.hole_depth, M8_LEAD)
            self.assertFalse(lead.hole_through)

    def test_an_end_the_copy_cannot_judge_leaves_the_thread_out(self):
        # A block over half of the rod's top: past that end the thread's ring is part material, part air.
        result = translate(joined(rod(), square(3.0, (3.0, 0.0)), 12.0, 2.0))
        self.assertEqual(threads(result), [])
        self.assertEqual([g["cause"] for g in result.left_out], [causes.THREAD_END])

    def test_threads_orca_cannot_make_are_left_out(self):
        cases = {"left hand": (dict(right_hand=False), gap_hints.REFUSED),
                 "deep for its size": (dict(major_diameter=1.2, minor_diameter=0.5, pitch=0.6,
                                            faces=[face(radius=0.6)]), gap_hints.THREAD_LIMITS),
                 "acme": (dict(thread_type="ACME"), gap_hints.THREAD_PROFILE),
                 "on a cone": (dict(faces=[dict(face(), surface="Cone")]), gap_hints.THREAD_PROFILE),
                 "off the end": (dict(offset=2.0), gap_hints.REFUSED)}
        for name, (more, cause) in cases.items():
            with self.subTest(name):
                result = translate(rod(**more))
                self.assertEqual(threads(result), [])
                self.assertEqual([g["cause"] for g in result.left_out], [cause])

    def test_a_thread_off_the_copied_part_is_left_out(self):
        result = translate(rod(faces=[face(origin=(30, 0, 0))]))
        self.assertEqual(threads(result), [])
        self.assertEqual([g["cause"] for g in result.left_out], [causes.MISSES_PART])

    def test_a_cosmetic_thread_writes_nothing(self):
        result = translate(load_capture("thread_cosmetic"))
        self.assertEqual(threads(result), [])
        self.assertEqual(result.left_out, [])
        self.assertEqual(result.items[-1]["verdict"], "skipped")

    def test_a_round_after_a_thread_is_left_out(self):
        capture = rod()
        capture["items"].append(finish_item(3, "FilletFeature", [{"token": "c", "closed": True,
                                                                  "points": [[0, 4, 12], [0, -4, 12]]}], 1.0))
        result = translate(capture)
        self.assertEqual(finishes(result), [])
        self.assertEqual([g["cause"] for g in result.left_out], [causes.EDGES_CHANGED])


class _Variables:
    """The part of a translation context that `limits.ranges` reads."""

    def __init__(self, variables):
        self._variables = variables

    def variables(self):
        return dict(self._variables)


class LimitsTest(unittest.TestCase):
    def test_the_range_a_variable_may_take_before_a_check_fails(self):
        thread = threads(translate(rod()))[0]
        thread.expr = {"thread_height": "len - 1.25"}
        found = limits.ranges(_Variables({"len": "6", "other": "len * 2"}), [(thread, "thread_height")],
                              lambda heights: 1.0 < heights[0] < 10.0)
        self.assertEqual(set(found), {"len"})
        self.assertAlmostEqual(found["len"][0], 2.25, places=6)
        self.assertAlmostEqual(found["len"][1], 11.25, places=6)

    def test_a_variable_the_check_does_not_limit_has_no_range(self):
        thread = threads(translate(rod()))[0]
        thread.expr = {"thread_x": "len - 1.25"}
        self.assertEqual(limits.ranges(_Variables({"len": "6"}), [(thread, "thread_x")], lambda h: True), {})

    def test_a_size_of_a_shape_stops_above_zero_whatever_the_check_says(self):
        thread = threads(translate(rod()))[0]
        thread.expr = {"thread_height": "len - 1.25"}
        found = limits.ranges(_Variables({"len": "6"}), [(thread, "thread_height")], lambda h: True)
        self.assertAlmostEqual(found["len"][0], 1.25, places=6)
        self.assertGreater(found["len"][0], 1.25)
        self.assertIsNone(found["len"][1])


if __name__ == "__main__":
    unittest.main()
