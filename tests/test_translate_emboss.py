"""Emboss on a flat face: copied as an extrude that starts on the face; each case it cannot copy is refused."""
import unittest

from tests import context  # noqa: F401
from tests.test_translate_start_from_face import height_at, origin_height
from tests.translator_helpers import assert_schema_ok, load_capture, steps_of, not_copied

from lib.params import size_table
from lib.probe import plan
from lib.translator import translate

LID = "emboss_lid_outline"
EMBOSS = 3


def emboss_data(capture):
    return capture["items"][EMBOSS]["data"]


def with_edit(edit, name=LID):
    capture = load_capture(name)
    edit(emboss_data(capture))
    return translate(capture)


def sunk(data, depth=-1.0):
    """The same outline sunk into the lid: the part loses its volume and the floor lies below the face."""
    data.update(depth=depth, volume_after=data["volume_before"] - 304.0 * abs(depth), end_offset=depth)
    data["params"]["depth"].update(value=depth, expression="-raise_mm")


def sized(capture, ticked=("lid_mm", "raise_mm")):
    params = capture["parameters"]
    return translate(capture, size_table=size_table.build(params["user"], list(ticked), params["model"], "mm"))


def reason_of(result):
    assert not_copied(result) is not None, "the emboss was copied"
    assert not_copied(result)["index"] == EMBOSS
    return not_copied(result)["reason"]


class EmbossCopyTest(unittest.TestCase):
    def test_a_raised_outline_joins_the_part_from_the_face(self):
        result = translate(load_capture(LID))
        self.assertEqual(result.refusal, None)
        base, raised = steps_of(result.recipe, "extrude")
        self.assertEqual((raised["combine"], raised["extent"], raised["distance"]), ("add", "oneSide", 1.0))
        self.assertEqual(raised["sketch"]["on"]["origin"], [0.0, 0.0, 4.0])
        self.assertEqual(raised["sketch"]["on"]["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(len(raised["sketch"]["inner"]), 1)
        assert_schema_ok(self, result.recipe)

    def test_a_sunk_outline_cuts_into_the_part(self):
        result = with_edit(sunk)
        _, cut = steps_of(result.recipe, "extrude")
        self.assertEqual((cut["combine"], cut["distance"], cut["sketch"]["on"]["normal"]), ("cut", 1.0, [0.0, 0.0, -1.0]))
        assert_schema_ok(self, result.recipe)

    def test_a_sketch_that_faces_into_the_part_still_raises_away_from_the_face(self):
        for measured in (-1.0, None):
            def flip(data, measured=measured):
                data["profiles"][0]["frame"].update(y=[0, -1, 0], z=[0, 0, -1])
                data["end_offset"] = measured
            with self.subTest(end_offset=measured):
                _, raised = steps_of(with_edit(flip).recipe, "extrude")
                self.assertEqual((raised["combine"], raised["sketch"]["on"]["normal"]), ("add", [0.0, 0.0, 1.0]))


class EmbossSizesTest(unittest.TestCase):
    def test_a_depth_driven_by_a_parameter_is_a_free_size_the_recipe_reads(self):
        result = sized(load_capture(LID))
        _, raised = steps_of(result.recipe, "extrude")
        self.assertEqual(raised["distance"], {"expr": "raise_mm"})
        self.assertEqual(raised["sketch"]["on"]["origin"][2], {"expr": "lid_mm"})
        self.assertIn("raise_mm", result.recipe["sizes"])
        self.assertEqual((result.fixed, result.loose, result.dropped), ([], [], []))

    def test_the_depth_of_a_sunk_outline_is_the_size_itself(self):
        capture = load_capture(LID)
        sunk(emboss_data(capture))
        _, cut = steps_of(sized(capture).recipe, "extrude")
        self.assertEqual((cut["combine"], cut["distance"]), ("cut", {"expr": "raise_mm"}))

    def test_with_the_sketch_plane_following_the_lid_the_emboss_still_starts_on_the_face(self):
        written = origin_height(load_capture(LID), ("lid_mm", "raise_mm"), {"lid_mm": 1.0})
        for lid in (4.0, 10.0):
            self.assertAlmostEqual(height_at(written, {"lid_mm": lid, "raise_mm": 1.0}), lid)

    def test_a_depth_that_reaches_zero_inside_the_size_range_is_written_as_a_number_with_a_reason(self):
        capture = load_capture(LID)
        capture["parameters"]["user"][1].update(expression="2 mm", value=0.2, display_value=2.0)
        ref = emboss_data(capture)["params"]["depth"]
        ref.update(expression="raise_mm - 1 mm", value=1.0)
        result = sized(capture)
        _, raised = steps_of(result.recipe, "extrude")
        self.assertEqual(raised["distance"], 1.0)
        self.assertEqual([(d["name"], d["used"]) for d in result.dropped], [("raise_mm", True)])


class EmbossPinTest(unittest.TestCase):
    def test_a_size_behind_the_horizontal_distance_does_not_stay_free(self):
        # A distance of "raise_mm - 1 mm" is 0 now, but it moves the outline at other values of raise_mm.
        capture = load_capture(LID)
        emboss_data(capture)["params"]["offset_x"] = {"name": "d9", "expression": "raise_mm - 1 mm", "value": 0.0}
        result = sized(capture)
        self.assertIsNone(result.refusal)
        self.assertEqual([d["name"] for d in result.loose], ["raise_mm"])
        self.assertIn("moves its outline", result.loose[0]["reason"])


class EmbossTangentChainTest(unittest.TestCase):
    FILLET = {"surface": "Cylinder", "plane": None}
    FLAT = {"surface": "Plane", "plane": {"point": [0, 0, 4], "normal": [0, 0, 1]}}

    def test_a_curved_neighbour_with_tangent_chain_on_is_refused(self):
        result = with_edit(lambda d: d.update(tangent_chain=True, tangent_faces=[self.FILLET]))
        self.assertIn("Tangent Chain", reason_of(result))

    def test_flat_neighbours_on_the_plane_or_tangent_chain_off_are_copied(self):
        for edit in (lambda d: d.update(tangent_faces=[self.FLAT]),
                     lambda d: d.update(tangent_chain=False, tangent_faces=[self.FILLET])):
            self.assertIsNone(with_edit(edit).refusal)

    def test_without_neighbours_a_curved_made_face_refuses_and_flat_ones_copy(self):
        refused = with_edit(lambda d: d.update(tangent_faces=None, made_surfaces=["Plane", "Cylinder"]))
        self.assertIn("Tangent Chain", reason_of(refused))
        self.assertIsNone(not_copied(with_edit(lambda d: d.update(tangent_faces=None, made_surfaces=["Plane"]))))
        self.assertIsNone(not_copied(with_edit(lambda d: d.update(tangent_faces=None, made_surfaces=None))))


class EmbossRefusalTest(unittest.TestCase):
    def check(self, edit, word):
        self.assertIn(word, reason_of(with_edit(edit)))

    def test_a_curved_input_face(self):
        self.check(lambda d: d["faces"][0].update(surface="Cylinder", plane=None), "curved face")

    def test_input_faces_that_are_not_on_one_plane(self):
        def two_levels(data):
            data["faces"].append(dict(data["faces"][0], plane={"point": [0, 0, 6], "normal": [0, 0, 1]}))
        self.check(two_levels, "not on one plane")

    def test_an_outline_moved_or_turned_on_its_face(self):
        for key, value in (("offset_x", 2.0), ("offset_y", -1.0), ("rotation_deg", 15.0)):
            with self.subTest(key):
                self.check(lambda d, key=key, value=value: d.update({key: value}), "moved or turned")

    def test_sketch_text(self):
        def add_text(data):
            data["profiles"].append({"text": True, "sketch": "Sketch2", "problem": "open"})
            data["areas"].append(None)
        self.check(add_text, "text could not be closed")

    def test_an_outline_made_of_curves_the_copy_cannot_write(self):
        def spline(data):
            data["profiles"][0]["loops"][0]["curves"][0] = {"kind": "other", "type": "NurbsCurve3D",
                                                            "start": [5, 5], "end": [55, 5], "samples": []}
        self.check(spline, "could not be read closely enough")

    def test_a_sketch_plane_tilted_to_the_face(self):
        self.check(lambda d: d["profiles"][0]["frame"].update(z=[0, 0.6, 0.8]), "tilted")

    def test_an_outline_that_runs_past_its_face(self):
        self.check(lambda d: d.update(volume_after=d["volume_before"] + 200.0), "does not match")

    def test_a_result_that_goes_the_other_way_than_the_depth_says(self):
        self.check(lambda d: d.update(volume_after=d["volume_before"] - 304.0), "the way its depth says")

    def test_a_change_of_the_part_that_was_not_measured(self):
        for key in ("volume_after", "volume_before", "areas"):
            with self.subTest(key):
                self.check(lambda d, key=key: d.update({key: None}), "could not be measured")

    def test_a_setting_that_could_not_be_read(self):
        for key in ("depth", "offset_x", "rotation_deg"):
            with self.subTest(key):
                self.check(lambda d, key=key: d.update({key: None}), "could not be read")
        self.check(lambda d: d.update(faces=[]), "could not be read")

    def test_a_depth_of_zero(self):
        self.check(lambda d: d.update(depth=0.0), "no depth")

    def test_no_outline(self):
        self.check(lambda d: d.update(profiles=[], areas=[]), "no sketch outline")


class SketchTextTest(unittest.TestCase):
    def test_text_in_the_sketch_of_an_extrude_stops_the_copy_with_its_own_reason(self):
        capture = load_capture("extrude_plate")
        data = capture["items"][-1]["data"]
        data["profiles"] = [{"text": True, "sketch": "Sketch1", "problem": "unread"}]
        result = translate(capture)
        self.assertIsNone(result.recipe)
        self.assertIn("outlines of this text", result.refusal["reason"])


class EmbossProbeTest(unittest.TestCase):
    def test_the_sketch_of_an_emboss_is_followed_like_the_sketch_of_an_extrude(self):
        capture = load_capture(LID)
        profile = emboss_data(capture)["profiles"][0]
        profile["sketch_token"] = "tok_sketch2"
        for loop in profile["loops"]:
            for number, curve in enumerate(loop["curves"]):
                curve["entity"] = "tok_%s_%d" % (loop["outer"], number)
        found = plan.scan(capture)
        self.assertEqual(found.covered, {"tok_sketch2": "Sketch2"})
        self.assertEqual([t["item"] for t in found.targets], [EMBOSS])


if __name__ == "__main__":
    unittest.main()
