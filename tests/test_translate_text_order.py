"""The order the outlines of one extrude are written in, and what it costs with many outlines
(lib/translator/extrude/order.py, `_touching_order`)."""
import random
import time
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import load_capture, steps_of

from lib.translator import translate
from lib.translator.extrude.order import _touching_order

LID = "emboss_lid_outline"
EMBOSS = 3
FRAME = {"origin": [0, 0, 4], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
TIME_LIMIT_S = 2.0


def rect(x, y, w, h):
    corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    curves = [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]} for n in range(4)]
    return {"sketch": "Sketch2", "frame": FRAME, "loops": [{"outer": True, "curves": curves}]}


def embossed(rects):
    """The lid emboss with `rects` (x, y, width, height) as its outlines."""
    capture = load_capture(LID)
    data = capture["items"][EMBOSS]["data"]
    areas = [w * h for _, _, w, h in rects]
    data.update(profiles=[rect(*r) for r in rects], areas=areas,
                volume_after=data["volume_before"] + sum(areas) * data["depth"], end_area=areas[0])
    return capture


def corners_of(step):
    """The lower left corner of the outline a step writes (rects are written as polygons or rects)."""
    outer = step["sketch"]["outer"]
    if outer["kind"] == "rect":
        return (outer["center"][0] - outer["width"] / 2, outer["center"][1] - outer["height"] / 2)
    return tuple(min(p[i] for p in outer["points"]) for i in range(2))


def written_order(rects):
    result = translate(embossed(rects))
    assert result.recipe is not None, result.refusal
    placed = [corners_of(step) for step in steps_of(result.recipe, "extrude")[1:]]
    return [rects.index(next(r for r in rects if (r[0], r[1]) == p)) for p in placed]


class ManyOutlinesTest(unittest.TestCase):
    def test_two_hundred_outlines_translate_quickly(self):
        rects = [(5.0 + 2.0 * (n % 20), 5.0 + 3.0 * (n // 20), 1.0, 2.0) for n in range(200)]
        capture = embossed(rects)
        started = time.perf_counter()
        result = translate(capture)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 201)
        self.assertLess(elapsed, TIME_LIMIT_S)


class OrderTest(unittest.TestCase):
    def test_outlines_standing_on_the_face_keep_the_order_of_the_sketch(self):
        # The third outline meets the first, the second stands alone: all of them stand on the lid, so none waits.
        rects = [(5.0, 5.0, 4.0, 4.0), (20.0, 5.0, 4.0, 4.0), (7.0, 7.0, 4.0, 4.0)]
        self.assertEqual(written_order(rects), [0, 1, 2])


class _Context:
    slabs = []
    placers = []


def _corner_in(a, b):
    """True when a corner of rectangle `a` lies in or on rectangle `b` (x, y, width, height)."""
    return any(b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3]
               for x in (a[0], a[0] + a[2]) for y in (a[1], a[1] + a[3]))


def _plain_order(units):
    """The order by its plain definition: the next outline is the first one that meets one already taken, or the
    first left when none does. `units` are (rectangle, side) pairs."""
    def joins(n, m):
        a, b = units[n], units[m]
        return a[0] is b[0] or (a[1] is b[1] and _corner_in(a[0], b[0]))

    order, left = [], list(range(len(units)))
    while left:
        pick = next((n for n in left if any(joins(n, m) for m in order)), left[0])
        order.append(pick)
        left.remove(pick)
    return order


class SearchTest(unittest.TestCase):
    def test_the_order_matches_the_plain_search_on_random_layouts(self):
        rng = random.Random(3)
        sides = [{"extent": "oneSide", "sign": 1, "distance": 2.0}, {"extent": "oneSide", "sign": -1, "distance": 2.0}]
        for _ in range(60):
            boxes = [(rng.randint(0, 12), rng.randint(0, 12), rng.randint(1, 4), rng.randint(1, 4))
                     for _ in range(rng.randint(2, 9))]
            used = sides[:rng.randint(1, 2)]
            built = [(rect(*box), None, None) for box in boxes]
            units = [(built[n], entry, box) for n, box in enumerate(boxes) for entry in used]
            rng.shuffle(units)
            pairs = [(one, entry) for one, entry, _ in units]
            found = _touching_order(_Context, pairs, 0.0, False)
            expected = _plain_order([(box, entry) for _, entry, box in units])
            self.assertEqual([next(n for n, pair in enumerate(pairs) if pair is f) for f in found], expected)


if __name__ == "__main__":
    unittest.main()
