"""Pipe steps: a circle (a ring when hollow) at the start of the path, square to it, carried along the path as the
sweep handler writes it."""
import math
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, stopped

from lib import orca_translate
from lib.capture_model import gap_hints
from lib.params import size_table
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate

PIPE = "pipe_line_arc"
ITEM = 1
SKETCH = "Sketch1"
# The probe measured the path sketch and found it still: only the section's own values move.
STILL = Motion({}, curves={"1/path"})


def pipe(edit=None):
    """The pipe capture with `edit(pipe data, capture)` applied."""
    capture = load_capture(PIPE)
    if edit is not None:
        edit(capture["items"][ITEM]["data"], capture)
    return capture


def sized(capture, motion=None, ranges=None):
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"], "mm",
                             ranges=ranges)
    return translate(capture, size_table=table, motion=motion)


def made(capture, volume):
    capture["items"][ITEM]["target_after"]["volume_mm3"] = volume


def hollow(data, capture):
    """A wall of 2 mm that the size wall_mm drives."""
    data.update(hollow=True, section_thickness=2.0)
    data["params"]["section_thickness"] = {"name": "d5", "expression": "wall_mm", "value": 2.0}
    params = capture["parameters"]
    params["user"].append(dict(params["user"][0], name="wall_mm", expression="2 mm", value=0.2, display_value=2))
    params["model"].append({"name": "d5", "expression": "wall_mm", "value": 0.2, "unit": "mm", "kind": "derived",
                            "role": "SectionThickness", "dependency_parameters": ["wall_mm"],
                            "created_by": params["model"][2]["created_by"]})
    made(capture, math.pi * (25 - 9) * (40 + 7.5 * math.pi))


def straight(data, capture, opposed=False):
    """The first leg alone, a line from z 0 to z 40 (listed from z 40 when `opposed`)."""
    line = data["path"]["curves"][0]
    if opposed:
        line.update(start=line["end"], end=line["start"], opposed=True,
                    flat=dict(line["flat"], start=line["flat"]["end"], end=line["flat"]["start"]))
    data["path"]["curves"] = [line]
    data["faces_after"]["end"] = [{"point": [0.0, 2.5, 40.0], "normal": [0.0, 0.0, 1.0]}]
    made(capture, math.pi * 25 * 40)


class CopyTest(unittest.TestCase):
    def test_a_round_pipe_is_a_sweep_of_its_circle_from_the_start_of_the_path(self):
        result = translate(pipe())
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["sketch"]["on"]["origin"], [0.0, 0.0, 0.0])
        self.assertEqual(step["sketch"]["on"]["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(step["sketch"]["outer"], {"kind": "circle", "center": [0.0, 0.0], "radius": 5.0})
        self.assertNotIn("inner", step["sketch"])
        self.assertEqual([s["kind"] for s in step["path"]["segments"]], ["line", "arc"])
        self.assertEqual(step["combine"], "new")
        assert_schema_ok(self, result.recipe)

    def test_a_hollow_pipe_has_a_hole_of_its_size_less_twice_the_wall(self):
        (step,) = steps_of(translate(pipe(hollow)).recipe, "sweep")
        self.assertEqual((step["sketch"]["outer"]["radius"], step["sketch"]["inner"][0]["radius"]), (5.0, 3.0))

    def test_a_straight_pipe_is_an_extrude_of_its_circle(self):
        (step,) = steps_of(translate(pipe(straight)).recipe, "extrude")
        self.assertEqual((step["distance"], step["sketch"]["outer"]["radius"]), (40.0, 5.0))

    def test_a_path_that_runs_against_its_curve_starts_at_the_far_end_of_it(self):
        result = translate(pipe(lambda data, capture: straight(data, capture, opposed=True)))
        (step,) = steps_of(result.recipe, "extrude")
        self.assertEqual(step["sketch"]["on"]["origin"], [0.0, 0.0, 0.0])

    def test_a_pipe_round_a_full_circle_is_a_full_turn_revolve(self):
        def ring(data, capture):
            data["path"] = {"closed": True, "kind": "sketch", "sketch": SKETCH, "sketch_token": "s1",
                            "frame": {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
                            "curves": [{"kind": "circle", "center": [0, 0, 0], "normal": [0, 0, 1], "radius": 30.0,
                                        "opposed": False, "entity": "p0",
                                        "flat": {"kind": "circle", "center": [0, 0], "radius": 30.0}}], "edges": []}
            data["faces_after"] = {"start": [], "end": []}
            made(capture, math.pi * 25 * 2 * math.pi * 30)
        (step,) = steps_of(translate(pipe(ring)).recipe, "revolve")
        self.assertNotIn("angleDeg", step)
        self.assertEqual(step["sketch"]["on"]["origin"], [0.0, 30.0, 0.0])


class LeftOutTest(unittest.TestCase):
    def refused(self, edit):
        result = translate(pipe(edit))
        self.assertIsNotNone(stopped(result), "the pipe was copied")
        return result.refusal_cause

    def test_square_and_triangle_sections_are_left_out_with_a_tip(self):
        for section in ("square", "triangular"):
            with self.subTest(section):
                self.assertEqual(self.refused(lambda data, _: data.update(section=section)), gap_hints.PIPE)

    def test_a_pipe_over_part_of_its_path_is_left_out(self):
        for change in ({"distance_one": 0.5}, {"distance_two": 1.0}):
            with self.subTest(change):
                cause = self.refused(lambda data, _: data.update(change))
                self.assertEqual(cause, gap_hints.PIPE_PART_OF_PATH)

    def test_a_path_with_a_sharp_corner_is_left_out(self):
        def corner(data, capture):
            data["path"]["curves"][1] = {"kind": "line", "start": [0, 0, 40], "end": [20, 0, 40], "opposed": False,
                                         "entity": "p1", "flat": {"kind": "line", "start": [0, -40], "end": [20, -40]}}
            made(capture, None)
        self.assertEqual(self.refused(corner), gap_hints.SHARP_CORNER)

    def test_a_new_body_that_does_not_match_the_section_and_path_is_left_out(self):
        self.refused(lambda data, capture: made(capture, 4000.0))

    def test_a_section_that_could_not_be_read_is_left_out(self):
        self.refused(lambda data, _: data.update(section=None))

    def test_a_pipe_captured_before_the_add_in_read_pipes_asks_for_a_new_export(self):
        self.assertEqual(self.refused(lambda data, _: data.clear()), gap_hints.OLD_EXPORT)

    def test_a_pipe_that_makes_a_new_component_is_left_out_with_a_tip(self):
        cause = self.refused(lambda data, _: data.update(operation="newComponent"))
        self.assertEqual(cause, gap_hints.NEW_COMPONENT)

    def test_the_orca_output_leaves_the_pipe_out_with_a_tip(self):
        (gap,) = orca_translate.translate(pipe()).left_out
        self.assertEqual((gap["index"], gap["cause"]), (ITEM, gap_hints.PIPE))
        self.assertIn("hint", gap)


class SizesTest(unittest.TestCase):
    def test_the_section_follows_its_size_as_the_radius(self):
        result = sized(pipe(), STILL)
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["sketch"]["outer"]["radius"], {"expr": "0.5 * pipe_mm"})
        self.assertIn("pipe_mm", result.recipe["sizes"])
        self.assertEqual(result.loose, [])

    def test_the_hole_of_a_hollow_pipe_follows_the_size_and_the_wall(self):
        result = sized(pipe(hollow), STILL, ranges={"pipe_mm": (8.0, 14.0), "wall_mm": (1.0, 3.0)})
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["sketch"]["inner"][0]["radius"], {"expr": "0.5 * pipe_mm - wall_mm"})
        self.assertEqual(result.loose, [])

    def test_a_wall_that_could_close_the_hole_marks_its_sizes(self):
        result = sized(pipe(hollow), STILL, ranges={"pipe_mm": (4.0, 14.0), "wall_mm": (1.0, 3.0)})
        self.assertIn("wall_mm", [d["name"] for d in result.dropped])

    def test_without_a_probe_the_section_keeps_its_size(self):
        result = sized(pipe())
        self.assertIn("pipe_mm", [d["name"] for d in result.dropped])

    def test_a_section_size_marks_its_size_only_when_it_can_outgrow_the_bend_of_the_path(self):
        self.assertEqual([f["name"] for f in sized(pipe(), STILL, ranges={"pipe_mm": (5.0, 40.0)}).loose],
                         ["pipe_mm"])
        self.assertEqual(sized(pipe(), STILL, ranges={"pipe_mm": (5.0, 20.0)}).loose, [])

    def test_the_path_follows_its_sizes(self):
        down = Affine(0, {"run_mm": -1.0}, SKETCH)
        motion = Motion({"1/path/c0/end.1": down, "1/path/c1/start.1": down, "1/path/c1/center.1": down,
                         "1/path/c1/mid.1": down.plus(-15 * math.sqrt(0.5)), "1/path/c1/end.1": down.plus(-15.0)},
                        curves={"1/path"})
        result = sized(pipe(), motion)
        self.assertIn("run_mm", result.recipe["sizes"])
        self.assertEqual(result.loose, [])

    def test_a_size_that_moves_the_start_of_the_path_is_marked(self):
        flat = {n: pipe()["items"][ITEM]["data"]["path"]["curves"][n]["flat"] for n in (0, 1)}
        shifted = {"1/path/c%d/%s.0" % (n, name): Affine(flat[n][name][0] - 40, {"run_mm": 1.0}, SKETCH)
                   for n, names in ((0, ("start", "end")), (1, ("start", "mid", "end", "center"))) for name in names}
        result = sized(pipe(), Motion(shifted, curves={"1/path"}))
        self.assertEqual([f["name"] for f in result.loose], ["run_mm"])


if __name__ == "__main__":
    unittest.main()
