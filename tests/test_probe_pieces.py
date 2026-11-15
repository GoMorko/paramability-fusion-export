"""`probe.pieces`: how many separate pieces the part is in at a probe state, against E0."""
import unittest

from tests import context  # noqa: F401
from lib.probe import pieces

PART = {"min": [0, 0, 0], "max": [40, 20, 10]}


def box(lo, hi):
    return {"min": list(lo), "max": list(hi)}


def read(lumps=1, others=(), part=PART):
    return {"box": part, "pieces": {"lumps": lumps, "others": list(others)}}


class CameApartTest(unittest.TestCase):
    def test_a_target_of_several_solids_came_apart(self):
        self.assertEqual(pieces.came_apart(read(lumps=3), read()), 3)

    def test_a_new_body_next_to_the_part_is_a_piece_of_it(self):
        # A cut that cuts the body in two: the piece that lost the target's name lies where the part was.
        smaller = box((0, 0, 0), (20, 20, 10))
        self.assertEqual(pieces.came_apart(read(others=[box((20.5, 0, 0), (40, 20, 10))], part=smaller), read()), 2)

    def test_bodies_away_from_the_part_or_there_at_e0_are_not_pieces(self):
        kept_tool = box((5, 5, 0), (10, 10, 10))
        elsewhere = box((100, 0, 0), (120, 20, 10))
        e0 = read(others=[kept_tool, elsewhere])
        self.assertIsNone(pieces.came_apart(read(others=[kept_tool, elsewhere, box((200, 0, 0), (210, 5, 5))]), e0))

    def test_nothing_is_said_when_e0_was_in_pieces_already_or_the_read_has_no_pieces(self):
        self.assertIsNone(pieces.came_apart(read(lumps=2), read(lumps=2)))
        self.assertIsNone(pieces.came_apart({"box": PART}, read()))


if __name__ == "__main__":
    unittest.main()
