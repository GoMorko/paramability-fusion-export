"""Extrudes that end on a tilted or curved face (`extent: { upTo }`), that start at a distance from a face, and two
sided intersects (lib/translator/extrude/)."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, verdict_of
from tests.test_translate_start_from_face import as_extrude

from lib import orca_translate
from lib.capture_model import gap_hints
from lib.params import size_table
from lib.params.expressions import evaluate
from lib.translator import translate

LID = "emboss_lid_outline"
ITEM = 3
BODY = {"token": "t1", "name": "Body1"}
# A slanted post sketched above the lid, its normal leaning 37 degrees off the lid's, that ends on the lid top.
SLANTED = {"origin": [30.0, 20.0, 20.0], "x": [0.8, 0.0, 0.6], "y": [0.0, -1.0, 0.0], "z": [0.6, 0.0, -0.8]}
# The same post sketched straight above the lid: the lid top is square to it.
STRAIGHT = {"origin": [30.0, 20.0, 20.0], "x": [1.0, 0.0, 0.0], "y": [0.0, -1.0, 0.0], "z": [0.0, 0.0, -1.0]}
SQUARE = [{"kind": "line", "start": a, "end": b}
          for a, b in (([-3, -3], [3, -3]), ([3, -3], [3, 3]), ([3, 3], [-3, 3]), ([-3, 3], [-3, -3]))]


def lid_face(point=(30.0, 20.0, 4.0), **more):
    """The lid top as the face a side reaches to (flat; Fusion extends it to its plane)."""
    return dict({"kind": "toEntity", "offset": 0.0, "chained": False, "entity_type": "BRepFace",
                 "plane": {"point": [0, 0, 4], "normal": [0, 0, 1]}, "face_point": list(point), "body": BODY}, **more)


def lid_outline(width=60.0):
    """The lid top as `read_face.face_loops` gives it: a rectangle `width` x 40 mm from the origin, at z 4."""
    corners = [[0.0, 0.0], [width, 0.0], [width, 40.0], [0.0, 40.0]]
    return {"frame": {"origin": [0.0, 0.0, 4.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]},
            "loops": [{"outer": True, "curves": [{"kind": "line", "start": a, "end": b}
                                                 for a, b in zip(corners, corners[1:] + corners[:1])]}]}


def slanted_post(side=None, frame=SLANTED, **more):
    """The lid capture with item ITEM a join from the sketch `frame` up to `side` (the lid top by default)."""
    capture = load_capture(LID)
    item = capture["items"][ITEM]
    item["type"] = "ExtrudeFeature"
    item["data"] = dict({
        "operation": "join",
        "profiles": [{"sketch": "Sketch2", "frame": frame, "loops": [{"outer": True, "curves": SQUARE}]}],
        "start": {"kind": "profilePlane"}, "extent_type": "one", "side_one": side or lid_face(),
        "side_two": None, "symmetric": None, "thin": False, "participants": [BODY],
        "target_box_before": {"min": [0.0, 0.0, 0.0], "max": [60.0, 40.0, 4.0]}, "end_offset": None}, **more)
    return capture


def sized(capture, ticked=("lid_mm",)):
    params = capture["parameters"]
    return translate(capture, size_table=size_table.build(params["user"], list(ticked), params["model"], "mm"))


def gap_cause(result):
    (gap,) = result.gaps
    return gap["hint"]


class UpToFaceTest(unittest.TestCase):
    def test_a_tilted_face_is_picked_by_a_point_on_it(self):
        result = translate(slanted_post())
        post = steps_of(result.recipe, "extrude")[-1]
        self.assertEqual(post["extent"], {"upTo": {"near": [[30, 20, 4]]}})
        self.assertNotIn("distance", post)
        self.assertEqual(verdict_of(result, ITEM)["verdict"], "translated")
        assert_schema_ok(self, result.recipe)

    def test_the_point_follows_the_face_when_a_size_moves_it(self):
        result = sized(slanted_post())
        (x, y, z) = steps_of(result.recipe, "extrude")[-1]["extent"]["upTo"]["near"][0]
        self.assertEqual((x, y), (30, 20))
        for lid in (3.0, 9.0):
            self.assertAlmostEqual(evaluate(z["expr"], {"lid_mm": lid}), lid)
        assert_schema_ok(self, result.recipe)

    def test_a_face_that_may_move_and_that_no_step_places_is_left_out(self):
        # A point inside the lid lies on no face the copy built: it could pick another face once the lid changes.
        capture = slanted_post(lid_face(point=(30.0, 20.0, 3.0)))
        self.assertIsNotNone(left_out(sized(capture), ITEM))
        self.assertIsNone(left_out(translate(capture), ITEM))

    def test_sides_the_app_cannot_build_or_pick_are_left_out(self):
        cases = {
            # Fusion may also stop at the faces next to the lid top, and no outline of the face shows where it ends.
            "chained": slanted_post(lid_face(chained=True)),
            "chained unread": slanted_post(lid_face(chained=None)),
            "chained past the face": slanted_post(lid_face(chained=True, face_outline=lid_outline(31.0))),
            "offset": slanted_post(lid_face(offset=1.0)),
            "taper": slanted_post(params={"side_one.taper_deg": {"name": "d9", "expression": "2 deg", "value": 2.0}}),
            "other body": slanted_post(lid_face(body={"token": "t2", "name": "Body2"})),
        }
        self.assertIsNone(left_out(translate(slanted_post()), ITEM))
        for name, capture in cases.items():
            with self.subTest(name):
                result = translate(capture)
                self.assertIsNotNone(left_out(result, ITEM))
                self.assertEqual(gap_cause(result), gap_hints.HINTS[gap_hints.EXTRUDE_END_FACE])

    def test_a_face_an_earlier_gap_may_have_made_is_left_out(self):
        self.assertIsNone(left_out(translate(slanted_post()), ITEM))
        capture = slanted_post()
        extra = copy.deepcopy(capture["items"][ITEM])
        extra.update(index=2, name="Extrude9", type="OtherFeature", data={})
        capture["items"][2] = extra
        result = translate(capture)
        self.assertIsNotNone(left_out(result, ITEM))
        self.assertEqual([(g["id"], g["dependsOn"]) for g in result.gaps], [("gap_2", []), ("gap_3", ["gap_2"])])

    def test_a_chained_face_that_holds_the_whole_outline_is_copied(self):
        result = translate(slanted_post(lid_face(chained=True, face_outline=lid_outline())))
        self.assertIn("upTo", steps_of(result.recipe, "extrude")[-1]["extent"])

    def test_orca_still_leaves_it_out(self):
        result = orca_translate.translate(slanted_post())
        self.assertEqual([g["index"] for g in result.left_out], [ITEM])


class ChainedFaceTest(unittest.TestCase):
    """A post straight above the lid that ends on the lid top, a face Fusion may chain to the faces next to it."""

    def test_the_post_is_copied_only_when_its_outline_lands_on_the_face(self):
        for outline, copied in ((lid_outline(), True), (lid_outline(31.0), False), (None, False)):
            with self.subTest(width=outline and outline["loops"][0]["curves"][1]["start"][0]):
                capture = slanted_post(lid_face(chained=True, face_outline=outline), frame=STRAIGHT)
                self.assertEqual(left_out(translate(capture), ITEM) is None, copied)
                orca = orca_translate.translate(capture)
                self.assertEqual(ITEM not in [g["index"] for g in orca.left_out], copied)

    def test_the_sizes_that_may_carry_the_outline_past_the_face_are_marked(self):
        chained = sized(slanted_post(lid_face(chained=True, face_outline=lid_outline()), frame=STRAIGHT))
        self.assertEqual([entry["name"] for entry in chained.loose], ["lid_mm"])
        extended = sized(slanted_post(lid_face(face_outline=lid_outline()), frame=STRAIGHT))
        self.assertEqual(extended.loose, [])
        capture = slanted_post(lid_face(chained=True, face_outline=lid_outline()), frame=STRAIGHT)
        params = capture["parameters"]
        table = size_table.build(params["user"], ["lid_mm"], params["model"], "mm")
        (lid,) = orca_translate.translate(capture, size_table=table).parameters
        self.assertEqual(lid["outcome"], orca_translate.PARTLY)


    def test_a_face_of_another_component_is_checked_by_its_outline_in_the_part(self):
        def cover(right):
            """The face's outline as the reader brings it into the part: a square from x -20 to `right` at z 25."""
            corners = [[-20.0, -10.0], [right, -10.0], [right, 10.0], [-20.0, 10.0]]
            return {"frame": {"origin": [0.0, 0.0, 25.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0],
                              "z": [0.0, 0.0, 1.0]},
                    "loops": [{"outer": True, "curves": [{"kind": "line", "start": a, "end": b}
                                                         for a, b in zip(corners, corners[1:] + corners[:1])]}]}

        # The boss is a 3 mm circle at x -10: it lands on the face that reaches to x 0, not on the one to x -9.
        for outline, copied in ((cover(0.0), True), (cover(-9.0), False), (None, False)):
            with self.subTest(outline=outline and outline["loops"][0]["curves"][0]["end"][0]):
                capture = load_capture("component_ref_reach")
                side = capture["items"][3]["data"]["side_one"]
                side["chained"] = True
                if outline is not None:
                    side["ref"]["face_outline"] = outline
                self.assertEqual(left_out(translate(capture), 3) is None, copied)


class StartOffsetTest(unittest.TestCase):
    """The extrude is sketched on the lid top (z 4), starts 2 mm from it and is 1 mm long; Fusion's offset parameter is
    `start_mm`. `measured` is the start face, from the sketch plane."""

    def capture(self, measured, expression="2 mm"):
        capture = as_extrude(load_capture(LID))
        capture["parameters"]["user"].append(dict(capture["parameters"]["user"][1], name="start_mm",
                                                  expression=expression, value=0.2))
        capture["parameters"]["model"].append(dict(capture["parameters"]["model"][1], name="d4",
                                                   expression="start_mm", dependency_parameters=["start_mm"]))
        data = capture["items"][ITEM]["data"]
        data["params"] = {"start.offset": {"name": "d4", "expression": "start_mm", "value": 2.0}}
        data["start_offset"] = measured
        data["end_offset"] = None if measured is None else measured + 1.0
        return capture

    def test_the_start_follows_the_sign_the_measured_start_face_shows(self):
        for measured, way in ((2.0, 1), (-2.0, -1)):
            with self.subTest(measured=measured):
                result = sized(self.capture(measured), ("start_mm",))
                origin = steps_of(result.recipe, "extrude")[-1]["sketch"]["on"]["origin"][2]
                for offset in (1.0, 3.0):
                    self.assertAlmostEqual(evaluate(origin["expr"], {"start_mm": offset}), 4.0 + way * offset)

    def test_without_a_measured_start_face_it_is_left_out(self):
        self.assertIsNotNone(left_out(translate(self.capture(None)), ITEM))


class TwoSidedIntersectTest(unittest.TestCase):
    def test_both_sides_make_one_tool_body_that_the_part_intersects(self):
        capture = load_capture("extrude_intersect")
        capture["items"][-1]["data"].update(
            extent_type="two", side_two={"kind": "distance", "distance": 2.0, "taper_deg": 0.0}, end_offset=None)
        result = translate(capture)
        tool = result.recipe["features"][-1]
        self.assertEqual((tool["kind"], tool["combine"]), ("toolBody", "intersect"))
        self.assertEqual([(s["combine"], s["distance"], s["sketch"]["on"]["normal"]) for s in tool["features"]],
                         [("new", 10, [0, 0, 1]), ("add", 2, [0, 0, -1])])
        self.assertGreaterEqual(result.recipe["version"], 15)
        assert_schema_ok(self, result.recipe)


if __name__ == "__main__":
    unittest.main()
