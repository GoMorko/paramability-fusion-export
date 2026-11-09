"""Matching a sketch state read in Fusion to the captured profile, curve by curve."""
import unittest

from tests.probe_helpers import capture, extrude, line, loop, profile, read, sketch_state

from lib.probe import match, plan


def slot(dx=0.0):
    """A 4 by 2 outline whose bottom line is split in two pieces of one sketch line (entity "b"), listed from the
    second piece, moved `dx` along x."""
    corners = [(2, 0), (4, 0), (4, 2), (0, 2), (0, 0)]
    p = [(x + dx, y) for x, y in corners]
    return [line(p[0], p[1], "b"), line(p[1], p[2], "r"), line(p[2], p[3], "t"), line(p[3], p[4], "l"),
            line(p[4], p[0], "b")]


class PiecesOfOneLineTest(unittest.TestCase):
    def test_a_loop_that_moved_further_than_its_pieces_are_apart_pairs_each_piece_with_its_own(self):
        # Moved 2 mm, the first piece lands where the second one was captured: nearness alone would swap them.
        found = plan.scan(capture(extrude(1, profile("Slot", "sk1", [loop(slot())]))))
        target = found.targets[0]
        values, cause = match.state_values(target, read(sketch_state("sk1", [{"loops": [loop(slot(2.0))]}])))
        self.assertIsNone(cause)
        want = match.captured_values(target)
        moved = {k: round(values[k] - v, 9) for k, v in want.items() if "/l0/" in k}
        self.assertEqual({v for k, v in moved.items() if k.endswith(".0")}, {2.0})
        self.assertEqual({v for k, v in moved.items() if k.endswith(".1")}, {0.0})


if __name__ == "__main__":
    unittest.main()
