"""Patterns and mirrors of bodies whose copies a Combine joins to the part or cuts from it, in the Orca copy
(`orca_translate/body_pattern.py`, with the facts of `design_model/steps/body_pattern.py`).

The captures come from `tests/orca_body_patterns.py`. The recipe is read back with `orca_cuts.Section`, and its
volume is counted on a 1 mm grid of cell centres, which is exact for the square pegs and pockets of these captures.
"""
import copy
import unittest

from tests import context  # noqa: F401
from tests import orca_body_patterns as bp
from tests.orca_cuts import Section
from tests.orca_sized import fixture, table_of
from tests.translator_helpers import verdict_of

from lib.capture_model import gap_hints
from lib.geometry import vec
from lib.orca_recipe.enums import BooleanMode, FeatureType
from lib.orca_translate import causes, translate

PATTERN, COMBINE = 4, 5


def run(capture):
    return translate(capture, table_of(capture))


def of_type(result, kind):
    return [f for f in result.recipe.features if f.type == kind]


def volume(result, box, changed=None):
    """The volume of Orca's first body inside `box` (capture coordinates, whole mm), at the variable values
    `changed`."""
    inside = Section(result.recipe, changed).bodies[0]
    lo, hi = [int(v) for v in box["min"]], [int(v) for v in box["max"]]
    return sum(1 for x in range(lo[0], hi[0]) for y in range(lo[1], hi[1]) for z in range(lo[2], hi[2])
               if inside(list(result.place.point([x + 0.5, y + 0.5, z + 0.5]))))


def holds(result, point, changed=None):
    return Section(result.recipe, changed).bodies[0](list(result.place.point(point)))


def left_out(result):
    (gap,) = result.left_out
    return gap


def outcomes(result):
    return {p["name"]: p["outcome"] for p in result.parameters}


def item(capture, index):
    return next(i for i in capture["items"] if i["index"] == index)


def insert_before_combine(capture, extra):
    """Put `extra` at timeline index 5 and the Combine after it."""
    combine = capture["items"].pop()
    combine["index"] = 6
    capture["items"] += [dict(extra, index=5), combine]
    return capture


def joined_step(body):
    """A join extrude of a 2 mm square on top of the first peg that lists `body` as the body it changes."""
    found = copy.deepcopy(bp.peg_row()["items"][3])
    found.update(name="Extrude3", bodies_after=[dict(body)])
    found["data"].update(operation="join", params={})
    return found


class CopiedTest(unittest.TestCase):
    def test_a_row_of_pegs_is_one_pattern_of_the_peg_joined_to_the_plate(self):
        capture = bp.peg_row()
        result = run(capture)
        self.assertEqual(result.left_out, [])
        (pattern,) = of_type(result, FeatureType.PATTERN)
        (boolean,) = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual((pattern.target_body, boolean.mode, boolean.target_body, boolean.bool_tool_body),
                         (1, BooleanMode.ADD, 0, 1))
        self.assertEqual(volume(result, capture["target"]["box"]), capture["target"]["volume_mm3"])
        wider = bp.expected("peg_row", pitch=18.0)
        self.assertEqual(volume(result, wider["box"], {"pitch": 18}), wider["volume_mm3"])
        taller = bp.expected("peg_row", peg_h=10.0)
        self.assertEqual(volume(result, taller["box"], {"peg_h": 10}), taller["volume_mm3"])
        self.assertEqual(outcomes(result), {"peg_h": "variable", "count": "fixed", "pitch": "variable"})
        self.assertEqual([verdict_of(result, i)["verdict"] for i in (3, PATTERN, COMBINE)], ["copied"] * 3)

    def test_a_ring_of_pegs_turns_the_peg_about_the_axis(self):
        result = run(bp.peg_ring())
        self.assertEqual(result.left_out, [])
        for k in range(6):
            centre = vec.rotate([20.0, 0.0, 7.0], [0.0, 0.0, 1.0], 60.0 * k)
            between = vec.rotate([20.0, 0.0, 7.0], [0.0, 0.0, 1.0], 60.0 * k + 30.0)
            self.assertEqual((holds(result, centre), holds(result, between)), (True, False), k)
        self.assertTrue(holds(result, [20.0, 0.0, 13.0], {"peg_h": 10}))
        self.assertEqual(outcomes(result), {"peg_h": "variable", "count": "fixed"})

    def test_a_mirrored_peg_is_a_mirror_of_the_peg(self):
        capture = bp.mirrored_peg()
        result = run(capture)
        self.assertEqual(len(of_type(result, FeatureType.MIRROR)), 1)
        self.assertEqual(volume(result, capture["target"]["box"]), capture["target"]["volume_mm3"])
        taller = bp.expected("mirrored_peg", peg_h=10.0)
        self.assertEqual(volume(result, taller["box"], {"peg_h": 10}), taller["volume_mm3"])

    def test_a_row_of_cutters_is_cut_from_the_block(self):
        capture = bp.cutter_row()
        result = run(capture)
        (boolean,) = of_type(result, FeatureType.BOOLEAN)
        self.assertEqual(boolean.mode, BooleanMode.CUT)
        self.assertEqual(volume(result, capture["target"]["box"]), capture["target"]["volume_mm3"])
        wider = bp.expected("cutter_row", pitch=18.0)
        self.assertEqual(volume(result, wider["box"], {"pitch": 18}), wider["volume_mm3"])

    def test_a_row_to_both_sides_is_a_tool_body_each_way_whose_copies_land_on_the_bodies(self):
        capture = bp.peg_row(count=3)
        data = item(capture, PATTERN)["data"]
        data["symmetric_one"] = True
        data["elements"][2]["frame"]["origin"] = [-14.0, 0.0, 0.0]
        source = data["source_bodies"][0]["points"]
        data["result_bodies"][1]["points"] = [vec.add(p, [-14.0, 0.0, 0.0]) for p in source]
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual(len(of_type(result, FeatureType.BOOLEAN)), 2)
        self.assertEqual([holds(result, [x, 10.0, 7.0]) for x in (-6.0, 8.0, 22.0, 36.0)], [True, True, True, False])

    def test_copies_of_the_part_joined_to_it_are_a_pattern_of_the_part(self):
        capture = fixture("pattern_target_finish")
        del capture["items"][2]
        result = run(capture)
        self.assertEqual(result.left_out, [])
        self.assertEqual([f.type for f in result.recipe.features if f.type != FeatureType.SKETCH],
                         [FeatureType.EXTRUDE, FeatureType.PATTERN])
        self.assertEqual(volume(result, capture["target"]["box"]), 1300)


class LeftOutTest(unittest.TestCase):
    def assert_left_out(self, capture, cause):
        result = run(capture)
        gap = left_out(result)
        self.assertEqual((gap["index"], gap["cause"]), (max(i["index"] for i in capture["items"]), cause))
        self.assertEqual(of_type(result, FeatureType.BOOLEAN) + of_type(result, FeatureType.PATTERN), [])

    def test_a_combine_that_takes_some_copies_or_not_their_source(self):
        for drop in (1, 0):
            with self.subTest(drop):
                capture = bp.peg_row()
                del item(capture, COMBINE)["data"]["tools"][drop]
                self.assert_left_out(capture, causes.COPIES_TAKEN)

    def test_a_copy_or_the_source_changed_on_its_own_before_the_combine(self):
        for body in (bp.B2, {"token": "t3", "name": "Body3"}):
            with self.subTest(body["name"]):
                self.assert_left_out(insert_before_combine(bp.peg_row(), joined_step(body)), causes.COPY_CHANGED)

    def test_the_part_changed_between_its_pattern_and_the_combine(self):
        capture = fixture("pattern_target_finish")
        del capture["items"][2]
        later = copy.deepcopy(item(capture, 1))
        later["data"]["operation"] = "join"
        combine = capture["items"].pop()
        combine["index"] = 5
        capture["items"] += [dict(later, index=4, name="Extrude2"), combine]
        self.assert_left_out(capture, causes.COPY_CHANGED)

    def test_the_part_cut_by_its_own_copies(self):
        capture = fixture("pattern_target_finish")
        del capture["items"][2]
        capture["items"][-1]["data"].update(operation="cut", volume_before=None, volume_after=None)
        self.assert_left_out(capture, gap_hints.UNSUPPORTED)

    def test_copies_made_in_another_component(self):
        capture = bp.peg_row()
        rack = {"token": "c1", "name": "Rack"}
        for index in (3, PATTERN):
            item(capture, index).update(in_target_component=False, component="c1")
        for tool in item(capture, COMBINE)["data"]["tools"]:
            tool.update(foreign=True, component=dict(rack), place={"frame": dict(bp.UP)})
        self.assert_left_out(capture, gap_hints.OTHER_COMPONENT)

    def test_an_intersect_with_the_copies(self):
        capture = bp.peg_row()
        item(capture, COMBINE)["data"].update(operation="intersect", intersect_model="every")
        self.assert_left_out(capture, causes.COPIES_INTERSECT)

    def test_copies_that_do_not_sit_where_the_pattern_puts_them(self):
        capture = bp.peg_row()
        copy_ = item(capture, PATTERN)["data"]["result_bodies"][2]
        copy_["points"] = [vec.add(p, [1.0, 0.0, 0.0]) for p in copy_["points"]]
        self.assert_left_out(capture, causes.COPIES_UNEVEN)

    def test_a_suppressed_copy(self):
        capture = bp.peg_row()
        data = item(capture, PATTERN)["data"]
        data["elements"][3]["suppressed"] = True
        del data["result_bodies"][2]
        del item(capture, COMBINE)["data"]["tools"][3]
        self.assert_left_out(capture, causes.COPIES_SUPPRESSED)

    def test_cutters_that_miss_the_block(self):
        capture = bp.cutter_row()
        for index in (3,):
            item(capture, index)["data"]["profiles"][0]["frame"]["origin"][2] = 12.0
        data = item(capture, PATTERN)["data"]
        for body in data["source_bodies"] + data["result_bodies"]:
            body["points"] = [vec.add(p, [0.0, 0.0, 8.0]) for p in body["points"]]
        self.assert_left_out(capture, causes.MISSES_PART)


if __name__ == "__main__":
    unittest.main()
