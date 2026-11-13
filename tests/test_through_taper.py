"""The room left inside a written outline at other sizes, which a tapered cut through all needs to stay open
(lib/translator/through_taper.py, lib/translator/written_loops.py)."""
import unittest

from tests import context  # noqa: F401

from lib.translator.through_taper import inner_reach
from lib.translator.written_loops import profile_at


def slot(width):
    """A slot 20 mm long between its arc centres and `width` (a size name) wide, centred on the origin."""
    half, minus = {"expr": "%s / 2" % width}, {"expr": "-(%s / 2)" % width}
    return {"kind": "profile", "start": [-10.0, minus],
            "segments": [{"kind": "line", "to": [10.0, minus]},
                         {"kind": "arc", "through": [{"expr": "10 + %s / 2" % width}, 0.0], "to": [10.0, half]},
                         {"kind": "line", "to": [-10.0, half]},
                         {"kind": "arc", "through": [{"expr": "-10 - %s / 2" % width}, 0.0], "to": [-10.0, minus]}]}


class WrittenOutlineRoomTest(unittest.TestCase):
    def test_a_slot_with_arc_ends_is_worked_out_at_the_size_given(self):
        for w, room in ((8.0, 4.0), (2.0, 1.0)):
            with self.subTest(w=w):
                self.assertAlmostEqual(inner_reach(profile_at(slot("w"), [], {"w": w})), room, delta=0.15)

    def test_a_hole_takes_its_room(self):
        square = {"kind": "rect", "center": [0.0, 0.0], "width": 20.0, "height": 20.0}
        hole = {"kind": "circle", "center": [0.0, 0.0], "radius": {"expr": "r"}}
        self.assertLess(inner_reach(profile_at(square, [hole], {"r": 8.0})), 3.0)
        self.assertGreater(inner_reach(profile_at(square, [hole], {"r": 1.0})), 4.0)

if __name__ == "__main__":
    unittest.main()
