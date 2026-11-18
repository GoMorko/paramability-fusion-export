"""Pipes in the Orca copy (`orca_translate/pipes.py`): the section as a circle swept along the path, a hollow pipe as
a sweep less the sweep of its hole, the sizes that follow and their limits, and the pipes left out with their causes,
against the captures of tests/orca_pipes.py and the pipe fixture."""
import math
import unittest

from tests import context  # noqa: F401
from tests import orca_pipes as op
from tests.orca_extents import UP, capture, circle, extrude, model, profile, side, sketch_item
from tests.probe_helpers import user
from tests.test_orca_extents import at, limit_of, outcome, run
from tests.translator_helpers import load_capture

from lib.capture_model import gap_hints
from lib.orca_recipe.enums import BooleanMode, EntityType, FeatureType, SketchShape
from lib.orca_translate import FIXED, VARIABLE, causes, limits


def types(result):
    return [f.type for f in result.recipe.features]


def left_causes(found):
    return [g["cause"] for g in run(found).left_out]


def pipe_data(found):
    return next(i for i in found["items"] if i["type"] == "PipeFeature")["data"]


def sweeps(result):
    return [f for f in result.recipe.features if f.type == FeatureType.SWEEP]


def hollow_on_plate(operation="join"):
    """`solid_pipe_on_plate` with a hollow pipe of 8 and a wall of 1, joined to the plate or cut into it."""
    out = op.solid_pipe_on_plate(size=8.0)
    data = pipe_data(out)
    data.update(operation=operation, hollow=True, section_thickness=1.0)
    data["params"]["section_thickness"] = {"name": "d_wall", "expression": "wall", "value": 1.0}
    out["parameters"]["user"].append(user("wall", "1 mm", 1.0))
    out["parameters"]["model"].append(model("d_wall", "wall", 1.0))
    return out


def ring_pipe(radius=20.0, size=4.0):
    """A pipe of diameter `size` along a full circle of `radius` about the Z axis, as a new body."""
    path = op.path_of([{"kind": "circle", "center": [0.0, 0.0, 0.0], "radius": radius, "normal": [0.0, 0.0, 1.0],
                        "opposed": False, "flat": {"kind": "circle", "center": [0.0, 0.0], "radius": radius}}],
                      UP, closed=True)
    volume = math.pi * (size / 2.0) ** 2 * 2.0 * math.pi * radius
    users, models = op.pipe_parameters(size)
    reach = radius + size / 2.0
    return capture([sketch_item(0, "Path"), op.pipe_item(1, path, size, volume=volume)],
                      ((-reach, -reach, -size / 2.0), (reach, reach, size / 2.0)), volume, users, models)


def with_pin(part, y):
    """A pin of radius 0.5 cut 10 mm along the first line of `hollow_pipe_bend` from x 5, `y` off the path."""
    across = {"origin": [5.0, 0.0, 0.0], "x": [0.0, 1.0, 0.0], "y": [0.0, 0.0, 1.0], "z": [1.0, 0.0, 0.0]}
    pin = extrude(3, "Pin", [profile("Pin sketch", across, circle(0.5, cx=y))], operation="cut",
                  side_one=side(10.0), end_offset=10.0, target_box_before=part["target"]["box"])
    part["items"] += [sketch_item(2, "Pin sketch"), pin]
    return part


class PipeTest(unittest.TestCase):
    def test_a_hollow_pipe_is_its_circle_swept_from_the_path_start_less_its_hole(self):
        result = run(op.hollow_pipe_bend())
        self.assertEqual(result.left_out, [])
        self.assertEqual(types(result), [FeatureType.SKETCH, FeatureType.SKETCH, FeatureType.SWEEP,
                                         FeatureType.SKETCH, FeatureType.SWEEP])
        outer, path, made, hole, cut = result.recipe.features
        self.assertEqual((outer.shape, hole.shape), (SketchShape.CIRCLE, SketchShape.CIRCLE))
        self.assertEqual((outer.radius, hole.radius), (4.0, 3.0))
        self.assertEqual((made.sketch_ref, made.sweep_path_ref, made.mode), (0, 1, BooleanMode.NEW))
        self.assertEqual((cut.sketch_ref, cut.sweep_path_ref, cut.mode), (3, 1, BooleanMode.CUT))
        # The section is square to the path at its start, where Orca starts the wire of the path.
        self.assertAlmostEqual(math.dist(outer.plane.normal, (1.0, 0.0, 0.0)), 0.0, places=9)
        self.assertAlmostEqual(math.dist(outer.plane.origin, path.plane.origin), 0.0, places=9)
        self.assertEqual([e.type for e in path.entities], [EntityType.LINE, EntityType.ARC, EntityType.LINE])
        self.assertAlmostEqual(math.dist(path.entities[0].p0, (0.0, 0.0)), 0.0, places=9)

    def test_the_size_and_the_wall_follow_with_how_far_they_may_go(self):
        result = run(op.hollow_pipe_bend(size=8.0, wall=1.0))
        outer, _, _, hole, _ = result.recipe.features
        self.assertEqual(at(outer, "radius", pipe_d=10), 5.0)
        self.assertEqual(at(hole, "radius", pipe_d=10, wall=2), 3.0)
        size, wall = outcome(result, "pipe_d"), outcome(result, "wall")
        self.assertEqual((size["outcome"], wall["outcome"]), (VARIABLE, VARIABLE))
        # The wall closes the hole at the radius, 4; the size may not shrink below twice the wall, nor reach the
        # centre of the bend of radius 20.
        self.assertAlmostEqual(limit_of(wall).high, 4.0, delta=0.01)
        self.assertAlmostEqual(limit_of(size).low, 2.0, delta=0.01)
        self.assertAlmostEqual(limit_of(size).high, 40.0, delta=0.11)
        self.assertEqual(limit_of(size).why[1], limits.SWEEP_BEND)

    def test_a_hollow_pipe_on_a_part_is_a_tool_body_worked_in_with_the_steps_operation(self):
        for operation, mode in (("join", BooleanMode.ADD), ("cut", BooleanMode.CUT)):
            with self.subTest(operation):
                result = run(hollow_on_plate(operation))
                self.assertEqual(result.left_out, [])
                self.assertEqual([s.mode for s in sweeps(result)], [BooleanMode.NEW, BooleanMode.CUT])
                last = result.recipe.features[-1]
                self.assertEqual((last.type, last.mode), (FeatureType.BOOLEAN, mode))

    def test_a_straight_path_and_a_full_circle_are_orca_sweeps(self):
        straight = run(op.solid_pipe_on_plate())
        self.assertEqual([s.mode for s in sweeps(straight)], [BooleanMode.ADD])
        self.assertEqual([e.type for e in straight.recipe.features[-2].entities], [EntityType.LINE])
        ring = run(ring_pipe())
        self.assertEqual(ring.left_out, [])
        path = ring.recipe.features[1]
        self.assertEqual([e.type for e in path.entities], [EntityType.ARC, EntityType.ARC])
        self.assertAlmostEqual(math.dist(path.entities[0].p0, (0.0, 0.0)), 0.0, places=9)
        self.assertAlmostEqual(math.dist(path.entities[-1].p1, path.entities[0].p0), 0.0, places=6)

    def test_a_cut_pipe_must_meet_the_part(self):
        self.assertEqual(left_causes(op.pipe_cut_into_block()), [])
        apart = op.pipe_cut_into_block(low=(100.0, 100.0, 0.0), high=(120.0, 120.0, 20.0))
        self.assertEqual(left_causes(apart), [causes.MISSES_PART])

    def test_the_shape_for_later_cuts_has_the_hole_of_a_hollow_pipe(self):
        # A pin along the hole meets nothing; the same pin in the wall cuts it.
        self.assertEqual(left_causes(with_pin(op.hollow_pipe_bend(), 0.0)), [causes.MISSES_PART])
        self.assertEqual(left_causes(with_pin(op.hollow_pipe_bend(), 3.5)), [])

    def test_the_sizes_of_the_path_keep_their_numbers(self):
        result = run(load_capture("pipe_line_arc"))
        self.assertEqual(result.left_out, [])
        self.assertEqual(outcome(result, "pipe_mm")["outcome"], VARIABLE)
        self.assertEqual((outcome(result, "run_mm")["outcome"], outcome(result, "bend_mm")["outcome"]),
                         (FIXED, FIXED))

    def test_pipes_the_copy_cannot_build_the_same_way_stay_out(self):
        square = op.hollow_pipe_bend()
        pipe_data(square)["section"] = "square"
        part = op.hollow_pipe_bend()
        pipe_data(part)["distance_one"] = 0.5
        corner = op.solid_pipe_on_plate()
        frame = pipe_data(corner)["path"]["frame"]
        pipe_data(corner)["path"] = op.path_of([op.line((0.0, 0.0, 6.0), (20.0, 0.0, 6.0), frame),
                                                op.line((20.0, 0.0, 6.0), (20.0, 8.0, 6.0), frame)], frame)
        first = op.pipe_cut_into_block()
        first["items"] = first["items"][2:]
        cases = (("a square section", square, gap_hints.PIPE),
                 ("part of the path", part, gap_hints.PIPE_PART_OF_PATH),
                 ("a sharp corner", corner, gap_hints.SHARP_CORNER),
                 ("a cut with no part before it", first, gap_hints.AFTER_GAP))
        for name, found, cause in cases:
            with self.subTest(name):
                self.assertEqual(left_causes(found), [cause])


if __name__ == "__main__":
    unittest.main()
