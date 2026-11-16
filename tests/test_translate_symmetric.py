"""Rectangular and circular patterns that spread copies to both sides of the original."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_copies import FLAT, copy_extrude, copy_item, edges_set, turned_copy
from tests.test_translate_sized import CUBE, TICKED, param, table_of
from tests.translator_helpers import assert_schema_ok, edited, left_out, load_capture, steps_of, translate_fixture

from lib.params import size_table
from lib.params.expressions import evaluate
from lib.sketch_values.motion import Motion
from lib.translator import translate
from lib.translator.ranges import range_check

CENTRE = 60.0
PITCH = {"distance_one": param("d21", CUBE + " + 4 mm", 24.0)}


def places_of(n):
    """Signed steps from the original of `n` symmetric copies as Fusion puts them: the original in the middle, an even
    count with the extra step ahead of it."""
    return list(range(-((n - 1) // 2), n // 2 + 1))


def centred(*later):
    """A 120 by 20 plate with a 8 mm post on the middle of its top, then `later`."""
    capture = load_capture("filter_tray_sized")
    top = dict(FLAT, origin=[0, 0, 10])
    capture["items"] = [copy_extrude(1, "Plate", "newBody", FLAT, (0, 0, 120, 20), 10.0),
                        copy_extrude(2, "Post", "join", top, (56, 4, 64, 12), 10.0)] + list(later)
    return capture


def row(index, sources, count, step, kind="spacing", params=None, symmetric=True, name="Pattern1"):
    """A rectangular pattern along x with `count` copies spread to both sides of the original."""
    elements = [{"id": n, "suppressed": False, "frame": dict(FLAT, origin=[k * step, 0, 0])}
                for n, k in enumerate(places_of(count))]
    distance = step if kind == "spacing" else step * max(count // 2, 1)
    return copy_item(index, name, "RectangularPatternFeature", {
        "entity_type": "features", "sources": sources, "direction_one": [1, 0, 0], "quantity_one": count,
        "distance_one": distance, "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
        "distance_type": kind, "symmetric_one": symmetric, "symmetric_two": False, "elements": elements,
        "params": params or {}})


def fillet(index, x):
    return copy_item(index, "Fillet1", "FilletFeature", {
        "sets": [edges_set("constant", [[x, 12, 15]], radius=1.0, continuity="tangent")]})


def sized(capture, ranges=None, tries=None):
    """The translation with the sizes ticked and, when `tries` are given, a probe that read the copies in them."""
    params = capture["parameters"]
    table = size_table.build(params["user"], TICKED, params["model"], ranges=ranges)
    return translate(capture, size_table=table, motion=Motion(states=tries) if tries else None), table


def tried(size, value, index, count, frames, built=True):
    """A probe state with `size` set to `value` where the pattern at timeline `index` made `count` copies at
    `frames` (element origins)."""
    elements = [{"id": n, "suppressed": False, "frame": frame} for n, frame in enumerate(frames)]
    return {"values": {size: value}, "built": built,
            "patterns": {str(index): {"count": [count, 1], "elements": elements}}}


def along_x(step, places):
    return [dict(FLAT, origin=[k * step, 0, 0]) for k in places]


def offsets(recipe, env=None, axis=0):
    """Distances from the original, along x (or the plate axis `axis`), of every place the pattern steps fill, the
    original included. Formulas are worked out at the sizes `env`."""
    def value(v):
        return evaluate(v["expr"], env) if isinstance(v, dict) else v

    found = {0.0}
    for step in steps_of(recipe, "pattern"):
        linear = step["linear"]
        skip = set(step.get("skip", ()))
        for n in range(1, int(value(linear["count"]))):
            if n not in skip:
                found.add(round(linear["dir"][axis] * n * value(linear["step"]), 6))
    return sorted(found)


def at(table, **overrides):
    """The sizes of a table with some recipe sizes changed."""
    return range_check.recipe_size_values(table, {table.size_name(name): v for name, v in overrides.items()})


def in_assembly(place, frame):
    """The component transform `frame` as Fusion gives it for a part placed at `place` (component to assembly)."""
    def apply(m, v):
        return [sum(m[name][i] * v[k] for k, name in enumerate("xyz")) for i in range(3)]

    def back(w):
        return [sum(place[name][i] * w[i] for i in range(3)) for name in "xyz"]

    units = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    axes = {name: apply(place, apply(frame, back(unit))) for name, unit in units.items()}
    moved = apply(place, apply(frame, back([-c for c in place["origin"]])))
    origin = [a + b + c for a, b, c in zip(moved, apply(place, frame["origin"]), place["origin"])]
    return dict(axes, origin=origin)


def placed_at(capture, place):
    """`capture` with its part placed at `place`: the pattern copies read in assembly space."""
    capture["target"]["placement"] = {"frame": place}
    for element in capture["items"][-1]["data"]["elements"]:
        element["frame"] = in_assembly(place, element["frame"])
    return capture


class SymmetricRowTest(unittest.TestCase):
    def test_odd_and_even_counts_fill_the_measured_places(self):
        for name, measured in (("rpattern_symmetric_odd", [-20, -10, 0, 10, 20]),
                               ("rpattern_symmetric_even", [-20, -10, 0, 10])):
            with self.subTest(name):
                result = translate_fixture(name)
                self.assertEqual(offsets(result.recipe), measured)
                self.assertEqual(len(steps_of(result.recipe, "pattern")), 2)
                assert_schema_ok(self, result.recipe)

    def test_an_extent_reaches_that_far_to_each_side(self):
        result = translate_fixture("rpattern_symmetric_extent")
        self.assertEqual(offsets(result.recipe), [-20, -10, 0, 10, 20])

    def test_both_directions_fill_the_whole_grid_once(self):
        result = translate_fixture("rpattern_symmetric_grid")
        steps = steps_of(result.recipe, "pattern")
        self.assertEqual(len(steps), 4)
        made = set()
        for step in steps:
            first, second = step["linear"], step["linear2"]
            skip = set(step.get("skip", ()))
            for n in range(1, first["count"] * second["count"]):
                if n not in skip:
                    col, line = n % first["count"], n // first["count"]
                    made.add((round(col * first["step"] * first["dir"][0], 6), round(line * second["step"] * second["dir"][1], 6)))
        self.assertEqual(made | {(0.0, 0.0)}, {(x, y) for x in (-10, 0, 10) for y in (-6, 0, 6)})
        assert_schema_ok(self, result.recipe)

    def test_one_symmetric_and_one_ordinary_direction_make_two_grids(self):
        def edit(capture):
            data = capture["items"][-1]["data"]
            data["symmetric_two"] = False
            for element, y in zip(data["elements"], (0, 0, 0, 6, 6, 6, 12, 12, 12)):
                element["frame"]["origin"][1] = y
        result = edited("rpattern_symmetric_grid", edit)
        steps = steps_of(result.recipe, "pattern")
        self.assertEqual([[step["linear"]["dir"][0], step["linear2"]["dir"][1]] for step in steps], [[1, 1], [-1, 1]])
        assert_schema_ok(self, result.recipe)

    def test_a_copy_left_out_is_skipped_by_number(self):
        def edit(capture):
            capture["items"][-1]["data"]["elements"][0]["suppressed"] = True
        result = edited("rpattern_symmetric_odd", edit)
        self.assertEqual(offsets(result.recipe), [-20, -10, 0, 10])

    def test_a_pattern_of_a_round_gets_a_round_on_each_copy(self):
        capture = centred(fillet(3, CENTRE + 4), row(4, [2, 3], 3, 24.0))
        result = translate(capture)
        (_, copies) = steps_of(result.recipe, "round")
        self.assertEqual(sorted(p[0] for p in copies["edges"]["near"]), [40, 88])
        assert_schema_ok(self, result.recipe)

    def test_copies_that_do_not_follow_the_rule_are_refused(self):
        def one_way_flag(capture):
            capture["items"][-1]["data"]["symmetric_one"] = True
        for label, result in (("copies run one way", translate_fixture("rpattern_symmetric")),
                              ("original between two copies", translate_fixture("rpattern_symmetric_between")),
                              ("flag on, extent misread", edited("rpattern_symmetric_extent", lambda capture: capture[
                                  "items"][-1]["data"].update(distance_one=40.0)))):
            with self.subTest(label):
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 4)

    def test_copies_on_both_sides_need_the_flag(self):
        result = edited("rpattern_symmetric_odd", lambda capture: capture["items"][-1]["data"].update(
            symmetric_one=False))
        self.assertIsNotNone(left_out(result))
        self.assertEqual(left_out(result)["index"], 4)


class UnusedDirectionTest(unittest.TestCase):
    def test_a_second_direction_with_a_distance_of_zero_adds_no_place(self):
        # Fusion keeps a quantity of 3 in the second direction, and makes the copies one on another.
        def edit(capture):
            data = capture["items"][-1]["data"]
            data.update(direction_two=[0, 1, 0], quantity_two=3, distance_two=0.0)
            data["elements"] = [dict(e, id=3 * n + k) for n, e in enumerate(data["elements"]) for k in range(3)]
        result = edited("rpattern_symmetric_odd", edit)
        self.assertIsNone(left_out(result))
        self.assertEqual(offsets(result.recipe), [-20, -10, 0, 10, 20])
        self.assertEqual(len(steps_of(result.recipe, "pattern")), 2)
        assert_schema_ok(self, result.recipe)


class SymmetricSizedTest(unittest.TestCase):
    def test_an_even_count_from_a_ceil_formula_and_a_spacing_follow_the_size(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5)" % CUBE, 4.0)}
        result, table = sized(centred(row(3, [2], 4, 24.0, params=dict(PITCH, **count))))
        self.assertEqual((result.fixed, result.loose), ([], []))
        self.assertEqual(offsets(result.recipe, at(table)), [-24, 0, 24, 48])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 30})), [-68, -34, 0, 34, 68, 102])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25})), [-58, -29, 0, 29, 58])
        assert_schema_ok(self, result.recipe)

    def test_an_odd_count_that_can_turn_even_puts_the_extra_copy_ahead_like_fusion(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        result, table = sized(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))))
        self.assertEqual(result.loose, [])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 30})), [-102, -68, -34, 0, 34, 68, 102])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25})), [-58, -29, 0, 29, 58, 87])

    def test_a_negative_spacing_puts_the_extra_copy_the_way_the_distance_points(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        back = {"distance_one": param("d21", "-(%s + 4 mm)" % CUBE, -24.0)}
        pattern = row(3, [2], 5, 24.0, params=dict(back, **count))
        pattern["data"]["distance_one"] = -24.0
        result, table = sized(centred(pattern))
        self.assertEqual(result.loose, [])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25})), [-87, -58, -29, 0, 29, 58])

    def test_an_even_extent_reaches_the_distance_ahead_and_a_gap_short_behind(self):
        # 8 copies, extent 30: Fusion spaces them 7.5 apart, from 22.5 behind the original to 30 ahead.
        params = {"distance_one": param("d21", "%s / 2 - 10 mm" % CUBE, 30.0)}
        result, table = sized(centred(row(3, [2], 8, 7.5, kind="extent", params=params)))
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 80})), [-22.5, -15, -7.5, 0, 7.5, 15, 22.5, 30])
        self.assertEqual(result.fixed, [])
        assert_schema_ok(self, result.recipe)

    def test_an_odd_count_that_can_turn_even_follows_the_places_the_tries_read(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        # CUBE 25 gives 6 copies a spacing of 29 apart; Fusion kept the extra copy behind or ahead of the original.
        for label, places, offsets_at_25 in (
                ("extra copy behind", [-3, -2, -1, 0, 1, 2], [-87, -58, -29, 0, 29, 58]),
                ("extra copy ahead", [-2, -1, 0, 1, 2, 3], [-58, -29, 0, 29, 58, 87])):
            with self.subTest(label):
                tries = [tried(CUBE, 25.0, 3, 6, along_x(29.0, places))]
                result, table = sized(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))), tries=tries)
                self.assertEqual(result.loose, [])
                self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25})), offsets_at_25)
                self.assertEqual(offsets(result.recipe, at(table)), [-48, -24, 0, 24, 48])
                assert_schema_ok(self, result.recipe)

    def test_tries_of_a_part_turned_in_the_assembly_are_read_in_its_own_frame(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        # A quarter turn about z: the copies run along y in assembly space and in the recipe.
        place = {"origin": [200, 0, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
        frames = [in_assembly(place, f) for f in along_x(29.0, [-3, -2, -1, 0, 1, 2])]
        capture = placed_at(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))), place)
        result, table = sized(capture, tries=[tried(CUBE, 25.0, 3, 6, frames)])
        self.assertEqual(result.loose, [])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25}), axis=1), [-87, -58, -29, 0, 29, 58])

    def test_tries_that_break_the_rule_leave_the_mark(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        centred_even = along_x(29.0, [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5])
        for label, tries in (("the original is not a copy", [tried(CUBE, 25.0, 3, 6, centred_even)]),
                             ("the copies do not fill the count",
                              [tried(CUBE, 25.0, 3, 6, along_x(29.0, [-2, 0, 1, 2]))]),
                             ("the tries disagree on the side",
                              [tried(CUBE, 25.0, 3, 6, along_x(29.0, range(-3, 3))),
                               tried(CUBE, 15.0, 3, 4, along_x(19.0, range(-1, 3)))])):
            with self.subTest(label):
                result, _ = sized(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))), tries=tries)
                self.assertEqual([f["name"] for f in result.loose], [CUBE])

    def test_tries_with_no_even_count_or_that_did_not_build_leave_the_side_fusion_uses(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        for label, tries in (("no try with an even count", [tried(CUBE, 30.0, 3, 7, along_x(34.0, range(-3, 4)))]),
                             ("the try did not build",
                              [tried(CUBE, 25.0, 3, 6, along_x(29.0, range(-3, 3)), built=False)])):
            with self.subTest(label):
                result, table = sized(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))), tries=tries)
                self.assertEqual(result.loose, [])
                self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 25})), [-58, -29, 0, 29, 58, 87])

    def test_an_odd_count_that_never_changes_is_not_marked(self):
        count = {"quantity_one": param("d22", "5", 5.0)}
        result, _ = sized(centred(row(3, [2], 5, 24.0, params=dict(PITCH, **count))))
        self.assertEqual(result.loose, [])

    def test_an_extent_follows_its_size_and_the_count(self):
        params = {"distance_one": param("d21", CUBE, 20.0)}
        result, table = sized(centred(row(3, [2], 5, 10.0, kind="extent", params=params)))
        self.assertEqual(offsets(result.recipe, at(table)), [-20, -10, 0, 10, 20])
        self.assertEqual(offsets(result.recipe, at(table, **{CUBE: 40})), [-40, -20, 0, 20, 40])

    def test_a_pick_on_a_copy_follows_the_spacing_when_the_count_is_fixed(self):
        result, table = sized(centred(row(3, [2], 3, 24.0, params=PITCH), fillet(4, CENTRE + 4 + 24)))
        self.assertEqual((result.fixed, result.loose), ([], []))
        (step,) = steps_of(result.recipe, "round")
        x = step["edges"]["near"][0][0]
        self.assertEqual(evaluate(x["expr"], at(table, **{CUBE: 30})), CENTRE + 4 + 34)

    def test_a_pick_on_a_copy_keeps_a_count_that_moves_the_places(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5)" % CUBE, 4.0)}
        result, _ = sized(centred(row(3, [2], 4, 24.0, params=dict(PITCH, **count)), fillet(4, CENTRE + 4 + 24)))
        reasons = {f["name"]: f["reason"] for f in result.loose}
        self.assertIn("picks a copy made by Pattern1", reasons[CUBE])

    def test_a_round_repeated_with_its_post_follows_the_count_on_every_copy(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5) - 1" % CUBE, 3.0)}
        result, table = sized(centred(fillet(3, CENTRE + 4), row(4, [2, 3], 3, 24.0, params=dict(PITCH, **count))))
        self.assertEqual(result.fixed, [])

        def rounded(**sizes):
            """x of every copy round the recipe keeps at these sizes."""
            env = at(table, **sizes)
            kept = [s for s in steps_of(result.recipe, "round")[1:] if not s.get("when") or evaluate(s["when"], env)]
            return sorted(round(evaluate(s["edges"]["near"][0][0]["expr"], env), 6) for s in kept)

        self.assertEqual(rounded(), [40.0, 88.0])
        self.assertEqual(rounded(**{CUBE: 30}), [64 - 2 * 34, 64 - 34, 64 + 34, 64 + 68])
        assert_schema_ok(self, result.recipe)

    def test_a_count_that_can_pass_the_copy_cap_marks_its_size(self):
        count = {"quantity_one": param("d22", "ceil(%s / 5)" % CUBE, 4.0)}
        result, _ = sized(centred(row(3, [2], 4, 24.0, params=dict(PITCH, **count))), ranges={CUBE: (10.0, 3000.0)})
        self.assertIn("more than 256 copies", {f["name"]: f["reason"] for f in result.loose}[CUBE])


def circular(index, count, total, degrees, symmetric=True, params=None):
    elements = [{"id": n, "suppressed": False, "frame": turned_copy([6, 6, 0], a, True)}
                for n, a in enumerate(degrees)]
    return copy_item(index, "C-Pattern1", "CircularPatternFeature", {
        "entity_type": "features", "sources": [2], "axis": {"point": [6, 6, 0], "dir": [0, 0, 1]}, "quantity": count,
        "total_angle_deg": total, "symmetric": symmetric, "elements": elements, "params": params or {}})


class SymmetricCircularTest(unittest.TestCase):
    def test_a_part_turn_runs_both_ways_from_the_original(self):
        result = translate_fixture("cpattern_symmetric_part")
        forward, backward = steps_of(result.recipe, "pattern")
        self.assertEqual((forward["polar"]["axis"], forward["polar"]["count"], forward["polar"]["angleDeg"]),
                         ([0, 0, 1], 3, 45))
        self.assertEqual((backward["polar"]["axis"], backward["polar"]["count"], backward["polar"]["angleDeg"]),
                         ([0, 0, -1], 3, 45))
        assert_schema_ok(self, result.recipe)

    def test_an_even_count_has_the_extra_turn_on_the_side_it_was_measured(self):
        # 4 copies over 90 degrees: 30 degrees apart, from 60 behind the original to 30 ahead of it.
        capture = centred(circular(3, 4, 90.0, [-60, -30, 0, 30]))
        result = translate(capture)
        forward, backward = steps_of(result.recipe, "pattern")
        self.assertEqual((forward["polar"]["count"], forward["polar"]["angleDeg"]), (2, 30))
        self.assertEqual((backward["polar"]["count"], backward["polar"]["angleDeg"]), (3, 60))

    def test_an_odd_turn_count_that_can_turn_even_follows_the_places_the_tries_read(self):
        count = {"quantity": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        base = centred(circular(3, 5, 120.0, [-60, -30, 0, 30, 60], params=count))
        # CUBE 25 gives 6 copies over 120 degrees: 24 degrees apart, the extra one ahead of the original.
        turns = [-48, -24, 0, 24, 48, 72]
        frames = [turned_copy([6, 6, 0], a, True) for a in turns]
        result, table = sized(base, tries=[tried(CUBE, 25.0, 3, 6, frames)])
        self.assertEqual(result.loose, [])
        forward, backward = steps_of(result.recipe, "pattern")
        env = at(table, **{CUBE: 25})

        def value(v):
            return evaluate(v["expr"], env) if isinstance(v, dict) else v

        self.assertEqual([value(forward["polar"]["count"]), round(value(forward["polar"]["angleDeg"]), 6)], [4, 72])
        self.assertEqual([value(backward["polar"]["count"]), round(value(backward["polar"]["angleDeg"]), 6)], [3, 48])
        other = [turned_copy([6, 6, 0], a, True) for a in (-60, -36, -12, 12, 36, 60)]
        result, _ = sized(base, tries=[tried(CUBE, 25.0, 3, 6, other)])
        self.assertEqual([f["name"] for f in result.loose], [CUBE])

    def test_a_part_that_sits_in_the_assembly_has_its_copies_turned_back_into_its_own_frame(self):
        # Fusion gives the copies in assembly space: here the part sits 180 mm along y, so the axis through its own
        # point (6, 6) turns about (6, 186) in the frames.
        capture = centred(circular(3, 5, 120.0, [0, 0, 0, 0, 0]))
        capture["target"]["placement"] = {"frame": {"origin": [0, 180, 0], "x": [1, 0, 0], "y": [0, 1, 0],
                                                    "z": [0, 0, 1]}}
        elements = capture["items"][-1]["data"]["elements"]
        for element, angle in zip(elements, (-60, -30, 0, 30, 60)):
            element["frame"] = turned_copy([6, 186, 0], angle, True)
        result = translate(capture)
        self.assertIsNone(left_out(result))
        forward, backward = steps_of(result.recipe, "pattern")
        self.assertEqual((forward["polar"]["count"], forward["polar"]["angleDeg"]), (3, 60))
        self.assertEqual((backward["polar"]["count"], backward["polar"]["angleDeg"]), (3, 60))

    def test_tries_of_a_part_turned_over_read_the_extra_turn_on_its_own_side(self):
        # Half a turn about a line along x through the axis point: a turn one way in the part reads the other way in
        # assembly space.
        place = {"origin": [0, 12, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}
        count = {"quantity": param("d22", "ceil(%s / 5) + 1" % CUBE, 5.0)}
        capture = placed_at(centred(circular(3, 5, 120.0, [-60, -30, 0, 30, 60], params=count)), place)
        frames = [in_assembly(place, turned_copy([6, 6, 0], a, True)) for a in (-48, -24, 0, 24, 48, 72)]
        result, table = sized(capture, tries=[tried(CUBE, 25.0, 3, 6, frames)])
        self.assertEqual(result.loose, [])
        forward, backward = steps_of(result.recipe, "pattern")
        env = at(table, **{CUBE: 25})
        self.assertEqual(evaluate(forward["polar"]["count"]["expr"], env), 4)
        self.assertEqual(evaluate(backward["polar"]["count"]["expr"], env), 3)

    def test_an_odd_count_is_centred_when_the_copies_behind_the_original_read_as_not_turned(self):
        # Fusion's transforms of a symmetric turn can show the copies behind the original as unturned (a 60, a 0, a
        # 0, a 30 and a 90 here), while the part has them at -60, -30, 0, 30 and 60.
        turns = [60, 0, 0, 30, 90]
        capture = centred(circular(3, 5, 120.0, turns))
        forward, backward = steps_of(translate(capture).recipe, "pattern")
        self.assertEqual((forward["polar"]["count"], forward["polar"]["angleDeg"]), (3, 60))
        self.assertEqual((backward["polar"]["count"], backward["polar"]["angleDeg"]), (3, 60))
        capture["items"][-1]["data"]["elements"][0]["suppressed"] = True
        self.assertIsNotNone(left_out(translate(capture)))

    def test_an_odd_count_is_not_centred_when_a_copy_is_left_out_or_turned_off_the_steps(self):
        for label, turns, left in (("a copy left out by number", [60, 0, 0, 30, 90], [2]),
                                   ("a turn off the steps", [60, 0, 0, 30, 85], []),
                                   ("no original", [60, 30, 30, 30, 90], [])):
            with self.subTest(label):
                capture = centred(circular(3, 5, 120.0, turns))
                capture["items"][-1]["data"]["suppressed_ids"] = left
                self.assertIsNotNone(left_out(translate(capture)))

    def test_a_full_circle_ignores_the_flag(self):
        (step,) = steps_of(translate_fixture("cpattern_symmetric").recipe, "pattern")
        self.assertNotIn("angleDeg", step["polar"])

    def test_turns_off_the_rule_are_refused(self):
        for label, capture in (("original between two copies", centred(circular(3, 4, 90.0, [-45, -15, 15, 45]))),
                               ("copies run one way", centred(circular(3, 4, 90.0, [0, 30, 60, 90])))):
            with self.subTest(label):
                result = translate(capture)
                self.assertIsNotNone(left_out(result))
                self.assertEqual(left_out(result)["index"], 3)


if __name__ == "__main__":
    unittest.main()
