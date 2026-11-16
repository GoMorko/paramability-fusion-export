"""Modeled threads (a ThreadFeature and the thread of a tapped hole) and holes that end at a face or body."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.test_translate_sized import TICKED, on_fixture, param, run
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, verdict_of

from lib.capture_model import gap_hints
from lib.translator import translate
from lib.translator.step_walk import tool_refusal

INFO = {"thread_type": "ISO Metric profile", "designation": "M8x1.25", "internal": False, "right_hand": True,
        "pitch": 1.25, "major_diameter": 8.0, "minor_diameter": 6.5, "angle_deg": None}


def face(radius=4.0, span=(0.0, 10.0), outward=True, **more):
    return dict({"surface": "Cylinder", "origin": [20, 10, 0], "axis": [0, 0, 1], "radius": radius, "span": list(span),
                 "face_point": [20 + radius, 10, 5], "outward": outward}, **more)


def thread_data(**more):
    data = dict(INFO, modeled=True, full_length=True, length=10.0, offset=0.0, faces=[face()], made_span=None)
    data.update(more)
    return data


def on_thread(**more):
    """The plate fixture with its modeled thread replaced by one on a cylinder of 10 mm along z at (20, 10)."""
    capture = load_capture("thread_modeled")
    capture["items"][-1]["data"] = thread_data(**more)
    return capture


def threads(capture):
    result = translate(capture)
    return result, steps_of(result.recipe, "thread") if result.recipe else []


class ThreadFeatureTest(unittest.TestCase):
    def test_an_outside_thread_runs_the_face_from_its_low_end(self):
        result, (step,) = threads(on_thread())
        self.assertEqual((step["axis"], step["length"], step["internal"]),
                         ({"origin": [20, 10, 0], "dir": [0, 0, 1]}, 10, False))
        self.assertEqual((step["diameter"], step["pitch"], step["minorDiameter"]), (8, 1.25, 6.5))
        self.assertNotIn("hand", step)
        self.assertEqual(verdict_of(result, 4)["verdict"], "translatedWithNote")
        assert_schema_ok(self, result.recipe)

    def test_an_inside_thread_cuts_in_a_hole_of_its_minor_diameter_and_a_left_hand_thread_says_so(self):
        _, (step,) = threads(on_thread(faces=[face(radius=3.25, outward=False)], internal=True, right_hand=False))
        self.assertEqual((step["internal"], step["hand"]), (True, "left"))

    def test_the_two_halves_of_a_split_cylinder_make_one_thread(self):
        halves = [face(span=(0.0, 10.0)), face(span=(0.0, 10.0), face_point=[16, 10, 5])]
        self.assertEqual(len(threads(on_thread(faces=halves))[1]), 1)

    def test_a_part_length_thread_starts_at_the_end_its_made_faces_touch(self):
        _, (step,) = threads(on_thread(full_length=False, length=6.0, made_span=[4.0, 10.0]))
        self.assertEqual((step["axis"], step["length"]), ({"origin": [20, 10, 10], "dir": [0, 0, -1]}, 6))
        _, (step,) = threads(on_thread(full_length=False, length=6.0, made_span=[0.0, 6.0]))
        self.assertEqual((step["axis"]["origin"], step["axis"]["dir"]), ([20, 10, 0], [0, 0, 1]))

    def test_the_length_follows_the_extrude_that_made_the_face(self):
        capture = load_capture("filter_tray_sized")
        capture["items"] = capture["items"][:2]
        data = thread_data(faces=[face(span=(0.0, 32.0), origin=[40, 30, 0], face_point=[80, 30, 16])], length=32.0)
        capture["items"].append(dict(load_capture("thread_modeled")["items"][-1], index=2, data=data))
        result, table = run(capture)
        (step,) = steps_of(result.recipe, "thread")
        self.assertEqual(step["length"], {"expr": "FilterBox_height_mm"})
        self.assertEqual(step["axis"]["origin"], [40, 30, 0])
        self.assertEqual(result.fixed, [])

    def test_a_cylinder_that_may_change_its_diameter_marks_the_sizes_read_before(self):
        capture = load_capture("filter_tray_sized")
        capture["items"] = capture["items"][:2]
        data = thread_data(faces=[face(span=(0.0, 32.0), origin=[40, 30, 0], face_point=[44, 30, 16])], length=32.0)
        capture["items"].append(dict(load_capture("thread_modeled")["items"][-1], index=2, data=data))
        result, _ = run(capture)
        self.assertTrue(result.loose or result.fixed)


class ThreadRefusalTest(unittest.TestCase):
    def test_a_thread_the_recipe_cannot_build_is_left_out(self):
        cases = {
            "acme": dict(thread_type="ACME"),
            "trapezoidal": dict(thread_type="ISO Metric trapezoidal"),
            "pipe": dict(thread_type="NPT"),
            "other angle": dict(angle_deg=29.0),
            "no profile": dict(thread_type=None),
            "no pitch": dict(pitch=None),
            "no hand": dict(right_hand=None),
            "too fine": dict(pitch=0.1),
            "too coarse": dict(pitch=12.0),
            "no depth": dict(minor_diameter=8.0),
            "wrong diameter": dict(faces=[face(radius=6.0)]),
            "inside and outside disagree": dict(internal=True),
            "not a cylinder": dict(faces=[{"surface": "Cone"}]),
            "no faces": dict(faces=[]),
            "unknown length": dict(full_length=None, length=None),
            "part length with no made faces": dict(full_length=False, length=5.0),
            "part length from the middle": dict(full_length=False, length=2.0, made_span=[4.0, 6.0]),
            "offset": dict(full_length=False, length=5.0, made_span=[0.0, 5.0], offset=2.0),
            "offset unreadable": dict(full_length=False, length=5.0, made_span=[0.0, 5.0], offset=None),
            "full length that stops short": dict(made_span=[0.0, 5.0]),
            "longer than the face": dict(full_length=False, length=12.0, made_span=[0.0, 10.0]),
            "over the turn cap": dict(faces=[face(span=(0.0, 200.0))], length=200.0),
            "faces apart": dict(faces=[face(span=(0.0, 3.0)), face(span=(5.0, 10.0))]),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                result = translate(on_thread(**edit))
                self.assertIsNotNone(left_out(result), label)
                self.assertEqual(left_out(result)["type"], "ThreadFeature")

    def test_a_thread_over_the_caps_of_the_recipe_is_left_out_with_its_hint(self):
        capture = on_thread()
        item = capture["items"][-1]
        for n in range(9):
            capture["items"].append(dict(copy.deepcopy(item), index=5 + n, name="Thread%d" % (n + 2)))
        result = translate(capture)
        self.assertEqual(len(steps_of(result.recipe, "thread")), 8)
        gap = next(g for g in result.gaps if g["type"] == "ThreadFeature")
        self.assertEqual(gap["hint"], gap_hints.hint(gap_hints.THREAD_LIMITS))

    def test_the_turns_of_all_threads_stay_under_the_cap(self):
        capture = on_thread(faces=[face(span=(0.0, 100.0))], length=100.0, pitch=1.0)
        item = capture["items"][-1]
        capture["items"].append(dict(copy.deepcopy(item), index=5, name="Thread2"))
        result = translate(capture)
        self.assertEqual(len(steps_of(result.recipe, "thread")), 1)
        self.assertIsNotNone(left_out(result, 5))

    def test_a_profile_refusal_has_the_profile_hint(self):
        result = translate(on_thread(thread_type="ACME"))
        gap = next(g for g in result.gaps if g["type"] == "ThreadFeature")
        self.assertEqual(gap["hint"], gap_hints.hint(gap_hints.THREAD_PROFILE))


class ToolRuleTest(unittest.TestCase):
    def test_the_refusal_for_a_step_kept_out_of_a_tool_fits_its_kind(self):
        self.assertEqual(tool_refusal([{"kind": "thread"}]).cause, gap_hints.THREAD_TOOL)
        self.assertEqual(tool_refusal([{"kind": "extrude"}, {"kind": "toolBody", "features": [{"kind": "coil"}]}]).cause,
                         gap_hints.COIL_TOOL)
        self.assertIsNone(tool_refusal([{"kind": "extrude"}, {"kind": "hole"}]))
        self.assertNotEqual(gap_hints.hint(gap_hints.THREAD_TOOL), gap_hints.hint(gap_hints.COIL_TOOL))


HOLE_INFO = dict(INFO, internal=True, major_diameter=6.0, minor_diameter=5.0, pitch=1.0, full_length=True, depth=None)


def tapped(name="hole_blind_flat", **more):
    def edit(data):
        data.update(tap_type="tapped", thread_modeled=True, diameter=6.0, thread=dict(HOLE_INFO), tip_angle_deg=None,
                    side_cylinders=[{"origin": [10, 10, 10], "axis": [0, 0, -1], "radius": 2.5}])
        for key, value in more.items():
            data[key] = value
    return edit


def tapped_hole(name="hole_blind_flat", **more):
    capture = load_capture(name)
    tapped(name, **more)(capture["items"][-1]["data"])
    return translate(capture)


class TappedHoleTest(unittest.TestCase):
    def test_a_blind_tapped_hole_is_a_hole_at_the_minor_diameter_and_a_thread_of_the_hole_depth(self):
        result = tapped_hole()
        (hole,) = steps_of(result.recipe, "hole")
        (step,) = steps_of(result.recipe, "thread")
        self.assertEqual((hole["diameter"], hole["depth"]), (5, 8))
        self.assertEqual((step["axis"], step["length"], step["internal"], step["diameter"], step["minorDiameter"]),
                         ({"origin": [10, 10, 10], "dir": [0, 0, -1]}, 8, True, 6, 5))
        assert_schema_ok(self, result.recipe)

    def test_a_through_hole_thread_runs_to_the_measured_exit(self):
        result = tapped_hole("hole_through")
        (step,) = steps_of(result.recipe, "thread")
        self.assertEqual(step["length"], 10)
        self.assertIsNone(steps_of(result.recipe, "hole")[0]["depth"])

    def test_a_part_depth_thread_and_several_holes(self):
        (step,) = steps_of(tapped_hole(thread=dict(HOLE_INFO, full_length=False, depth=5.0,
                                                          made_span=[0.0, 5.0])).recipe, "thread")
        self.assertEqual(step["length"], 5)
        result = tapped_hole("hole_three_points")
        self.assertEqual(len(steps_of(result.recipe, "thread")), 3)

    def test_the_hole_depth_formula_is_the_thread_length(self):
        capture, ticked = on_fixture("hole_blind_flat", tapped(), TICKED)
        capture["items"][-1]["data"]["params"] = {"extent.depth": param("d8", "wall_mm * 4", 8.0)}
        result, _ = run(capture, ticked)
        self.assertEqual(steps_of(result.recipe, "hole")[0]["depth"], {"expr": "wall_mm * 4"})
        self.assertEqual(steps_of(result.recipe, "thread")[0]["length"], {"expr": "wall_mm * 4"})

    def test_a_tapped_hole_that_cannot_get_its_thread_is_left_out(self):
        cases = {
            "tapered": dict(tap_type="taperTapped"),
            "other profile": dict(thread=dict(HOLE_INFO, thread_type="NPT")),
            "no pitch": dict(thread=dict(HOLE_INFO, pitch=None)),
            "no hand": dict(thread=dict(HOLE_INFO, right_hand=None)),
            "depth unknown": dict(thread=dict(HOLE_INFO, full_length=None)),
            "deeper than the hole": dict(thread=dict(HOLE_INFO, full_length=False, depth=9.0)),
            "does not match the measured bore": dict(side_cylinders=[{"origin": [10, 10, 10], "axis": [0, 0, -1],
                                                                       "radius": 2.0}]),
            "no thread record": dict(thread=None),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                result = tapped_hole(**edit)
                self.assertIsNotNone(left_out(result), label)

    def test_a_pattern_of_a_threaded_hole_is_left_out_and_not_copied_without_its_thread(self):
        capture = _patterned()
        result = translate(capture)
        hole = next(i for i in capture["items"] if i["type"] == "HoleFeature")
        self.assertEqual(len(steps_of(result.recipe, "thread")), len(hole["data"]["positions"]))
        self.assertEqual(steps_of(result.recipe, "pattern"), [])
        self.assertIsNotNone(left_out(result, 4))


def _patterned():
    capture = load_capture("rpattern_multi_hole")
    hole = next(i for i in capture["items"] if i["type"] == "HoleFeature")
    tapped()(hole["data"])
    return capture


class HoleUpToTest(unittest.TestCase):
    def up_to(self, **more):
        capture = load_capture("hole_blind_flat")
        data = capture["items"][-1]["data"]
        data.update(extent={"kind": "toEntity", "entity_type": "BRepFace", "face_point": [20, 20, 2], "plane":
                            {"point": [0, 0, 2], "normal": [0, 0, 1]}}, end_points=[[10, 10, 2]],
                    end_face_types=["plane"], tip_angle_deg=None)
        data.update(more)
        return translate(capture)

    def test_a_hole_up_to_a_flat_face_is_a_blind_hole_of_the_measured_depth(self):
        result = self.up_to()
        (hole,) = steps_of(result.recipe, "hole")
        self.assertEqual((hole["depth"], hole["direction"]), (8, [0, 0, -1]))
        assert_schema_ok(self, result.recipe)

    def test_a_hole_up_to_a_face_that_cannot_be_measured_or_ends_in_a_point_is_left_out(self):
        cases = {
            "no end": dict(end_points=[]),
            "drill point": dict(end_face_types=["cone"]),
            "unmeasured end": dict(end_face_types=[]),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                self.assertIsNotNone(left_out(self.up_to(**edit)), label)

    def test_holes_that_end_at_different_depths_are_left_out(self):
        capture = load_capture("hole_three_points")
        data = capture["items"][-1]["data"]
        data.update(extent={"kind": "toEntity", "entity_type": "BRepFace", "face_point": [20, 20, 2]},
                    end_points=[[8, 6, 2], [20, 10, 3], [32, 14, 2]], end_face_types=["plane"] * 3)
        self.assertIsNotNone(left_out(translate(capture)))


if __name__ == "__main__":
    unittest.main()
