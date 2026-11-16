"""What a shell leaves for the picks and joins after it (lib/translator/faces/shells.py)."""
import unittest

from tests import context  # noqa: F401

from lib.design_model.values import Quantity
from lib.translator.context import Context
from lib.translator.faces import follow
from lib.translator.faces.moved_placer import MovedPlacer
from lib.translator.faces.placer import CUT
from lib.translator.faces.placer_makers import ShellMaker
from lib.translator.faces.slabs import Motion, Slab
from lib.translator.faces.tool_placer import ToolPlacer

FRAME = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
ON = {"origin": [0, 0, 0], "normal": [0, 0, 1], "xDir": [1, 0, 0]}
WALL = 2.0


def block(x0, x1):
    """A 20 mm deep outline from x0 to x1."""
    pts = [[x0, 0], [x1, 0], [x1, 20], [x0, 20]]
    curves = [{"kind": "line", "start": pts[n], "end": pts[(n + 1) % 4]} for n in range(4)]
    return {"frame": FRAME, "loops": [{"outer": True, "curves": curves}]}


def part(outward):
    """A block 10 mm high, and a pocket cut from it that reaches 2 mm past its top: the end face of the pocket stands
    where a shell that grows outward puts the outer wall over the top, in the air."""
    ctx = Context({"target": {"token": "t"}, "items": []})
    ctx.enter({"index": 1})
    ctx.add_slab(Slab("a", ON, "oneSide", Quantity(10.0), block(0, 20)))
    ctx.add_slab(Slab("c", ON, "oneSide", Quantity(10.0 + WALL), block(5, 15), combine="cut"))
    ShellMaker(Quantity(WALL), [], outward).make(ctx, "shell", {})
    return ctx


OUTER_WALL = [10, 10, 10 + WALL]
ORIGINAL_FACE = [20, 10, 5]


class OutsideShellTest(unittest.TestCase):
    def test_a_point_on_the_new_outer_wall_is_placed_on_no_step_before_it(self):
        self.assertIsNotNone(follow.locate(part(False), OUTER_WALL))
        self.assertIsNone(follow.locate(part(True), OUTER_WALL))

    def test_a_point_on_a_face_the_shell_left_where_it_was_is_still_placed(self):
        self.assertIsNotNone(follow.locate(part(True), ORIGINAL_FACE))

    def test_an_edge_on_the_new_outer_wall_is_not_placed_either(self):
        self.assertIsNone(follow.locate(part(True), [10, 0, 10 + WALL], edge=True))

    def test_the_part_before_the_shell_is_the_hollow(self):
        shell = part(True).placers[-1]
        self.assertEqual((shell.material_at([2, 10, 5]), shell.material_at([2, 10, 11])), (CUT, None))

    def test_a_moved_shell_and_a_tool_holding_it_claim_the_same_points(self):
        shell = part(True).placers[-1]
        moved = MovedPlacer(shell, Motion())
        tool = ToolPlacer("t", [moved], "add", ())
        for holder in (moved, tool):
            self.assertTrue(holder.claims(OUTER_WALL))
            self.assertFalse(holder.claims(ORIGINAL_FACE))
        self.assertIsNone(tool.place(OUTER_WALL, False))

    def test_a_shell_inside_a_tool_claims_only_points_near_its_own_wall(self):
        tool_walk = Context({"target": {"token": "t"}, "items": []})
        tool_walk.enter({"index": 1})
        tool_walk.add_slab(Slab("b", ON, "oneSide", Quantity(10.0), block(100, 110)))
        ShellMaker(Quantity(WALL), [], True).make(tool_walk, "tool_shell", {})
        ctx = part(False)
        ctx.add_placer(ToolPlacer("tool", tool_walk.placers, "add", ()))
        self.assertIsNotNone(follow.locate(ctx, ORIGINAL_FACE))
        self.assertIsNone(follow.locate(ctx, [110 + WALL, 10, 5]))

    def test_a_shell_whose_wall_cannot_be_bounded_claims_every_point_outside_the_part(self):
        # The cut of `part` can leave a sharper corner than the outline shows, so the sharp wall is not bounded.
        shell = part(True).placers[-1]
        self.assertIsNone(shell.wall_box)
        self.assertTrue(shell.claims([500, 500, 500]))

    def test_an_inward_shell_claims_nothing(self):
        self.assertFalse(part(False).placers[-1].claims(OUTER_WALL))


if __name__ == "__main__":
    unittest.main()
