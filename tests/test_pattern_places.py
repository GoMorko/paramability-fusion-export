"""Where the copies of a pattern sit (lib/design_model/steps/pattern_places.py): circular copies placed by their ids
with the turn read from their faces, and the checks that leave a pattern out when Fusion's places cannot be right."""
import copy
import math
import unittest

from tests import context  # noqa: F401
from tests.orca_sized import fixture
from tests.test_capture_reader import Coll, Obj, P, param
from tests.test_capture_reader_finish import element as fake_element, read_pattern, rectangular as fake_rectangular
from tests.translator_helpers import left_out, load_capture, steps_of, verdict_of

from lib.design_model.steps import pattern_places
from lib.fusion_reader import read_repeat
from lib.orca_recipe.enums import FeatureType
from lib.orca_translate import translate as orca_translate
from lib.results.verdicts import LEFT_OUT
from lib.translator import translate
from lib.translator.repeat import body_copies

AXIS_POINT = [20.0, 10.0, 0.0]
# The faces of the cut of `cpattern_full`: a cylinder and its floor, off the axis.
SOURCE = [{"center": [32.0, 10.0, 2.5], "area": 94.2}, {"center": [32.0, 10.0, 5.0], "area": 12.6}]
# Turns Fusion 2706 gives as element transforms: one step ahead after the original, a full circle wraps to it.
FULL_SIX_READ = [0, 120, 180, 240, 300, 0]
PART_THREE_READ = [0, 120, 180]


def turn(degrees, point=AXIS_POINT):
    """The frame of a turn about the vertical axis through `point`."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return {"origin": [point[0] - (c * point[0] - s * point[1]), point[1] - (s * point[0] + c * point[1]), 0.0],
            "x": [c, s, 0.0], "y": [-s, c, 0.0], "z": [0.0, 0.0, 1.0]}


def faces_at(degrees, faces=SOURCE):
    frame = turn(degrees)
    return [{"center": [frame["origin"][i] + sum(frame[n][i] * f["center"][k] for k, n in enumerate("xyz"))
                        for i in range(3)], "area": f["area"]} for f in faces]


def circular(name, count, total, read, real=None, source=SOURCE):
    """`name` as a circular pattern of `count` copies over `total` degrees whose element transforms turn `read`
    degrees, and whose copies' faces (when `real` is given) sit `real` degrees round."""
    capture = fixture(name)
    data = next(i for i in capture["items"] if i["type"] == "CircularPatternFeature")["data"]
    data.update(quantity=count, total_angle_deg=total, suppressed_ids=[])
    data["elements"] = [{"id": n, "suppressed": False, "frame": turn(angle)} for n, angle in enumerate(read)]
    if real is not None:
        data["source_faces"] = source
        for element, angle in zip(data["elements"], real):
            element["faces"] = faces_at(angle)
    return capture


def polar_of(capture):
    (step,) = steps_of(translate(capture).recipe, "pattern")
    return step


class CircularPlacesTest(unittest.TestCase):
    def test_a_full_circle_keeps_every_copy_when_the_transforms_run_one_step_ahead(self):
        for label, real in (("faces read", [0, 60, 120, 180, 240, 300]), ("no faces", None)):
            with self.subTest(label):
                step = polar_of(circular("cpattern_full", 6, 360.0, FULL_SIX_READ, real))
                self.assertEqual((step["polar"]["count"], step.get("skip")), (6, None))
                (orca,) = [f for f in orca_translate(circular("cpattern_full", 6, 360.0, FULL_SIX_READ, real))
                           .recipe.features if f.type == FeatureType.PATTERN]
                self.assertEqual((orca.pattern_count, orca.pattern_angle), (6, 360.0))

    def test_a_part_turn_takes_its_way_from_the_faces(self):
        for real, axis in (([0, 60, 120], [0, 0, 1]), ([0, -60, -120], [0, 0, -1])):
            with self.subTest(axis=axis):
                step = polar_of(circular("cpattern_part", 3, 120.0, PART_THREE_READ, real))
                self.assertEqual((step["polar"]["count"], step["polar"]["angleDeg"], step["polar"]["axis"]),
                                 (3, 120, axis))
                (orca,) = [f for f in orca_translate(circular("cpattern_part", 3, 120.0, PART_THREE_READ, real))
                           .recipe.features if f.type == FeatureType.PATTERN]
                self.assertEqual((orca.pattern_count, orca.pattern_angle, orca.plane.normal[2]), (3, 120.0, axis[2]))

    def test_a_part_turn_whose_way_nothing_shows_is_left_out(self):
        capture = circular("cpattern_part", 3, 120.0, PART_THREE_READ)
        self.assertEqual(left_out(translate(capture))["reason"], pattern_places.TURN_UNREAD.words)

    def test_copies_whose_faces_are_off_their_places_are_left_out(self):
        capture = circular("cpattern_full", 6, 360.0, FULL_SIX_READ, [0, 120, 60, 180, 240, 300])
        self.assertEqual(left_out(translate(capture))["reason"], pattern_places.DISAGREE.words)
        self.assertEqual(verdict_of(orca_translate(capture), 4)["verdict"], LEFT_OUT)

    def test_ids_that_share_a_place_or_leave_one_empty_are_left_out(self):
        for label, ids, problem in (("shared", [0, 1, 1, 3, 4, 5], pattern_places.SHARED),
                                    ("missing", [0, 1, 2, 3, 4], pattern_places.UNFILLED)):
            with self.subTest(label):
                capture = circular("cpattern_full", 6, 360.0, [n * 60 for n in range(len(ids))])
                data = capture["items"][4]["data"]
                for element, n in zip(data["elements"], ids):
                    element["id"] = n
                del data["elements"][len(ids):]
                self.assertEqual(left_out(translate(capture))["reason"], problem.words)

    def test_a_pattern_of_bodies_pairs_its_copies_by_their_ids(self):
        capture = load_capture("pattern_bodies_subset")
        data = next(i for i in capture["items"] if (i.get("data") or {}).get("entity_type") == "bodies")["data"]
        point = data["axis"]["point"]
        data["elements"] = [dict(e, frame=turn(angle, point)) for e, angle in zip(data["elements"], FULL_SIX_READ)]
        self.assertEqual(len(body_copies.match(data)), 5)


class RectangularPlacesTest(unittest.TestCase):
    def row(self, origins, faces=None):
        capture = copy.deepcopy(load_capture("rpattern_row"))
        data = capture["items"][4]["data"]
        for element, x in zip(data["elements"], origins):
            element["frame"] = dict(element["frame"], origin=[x, 0, 0])
        if faces is not None:
            data["source_faces"] = [{"center": [5.0, 5.0, 1.0], "area": 30.0}]
            for element, x in zip(data["elements"], faces):
                element["faces"] = [{"center": [5.0 + x, 5.0, 1.0], "area": 30.0}]
        return capture

    def test_two_copies_on_one_place_leave_the_pattern_out(self):
        capture = self.row([0, 20, 0])
        self.assertEqual(left_out(translate(capture))["reason"], pattern_places.SHARED.words)
        self.assertEqual(verdict_of(orca_translate(capture), 4)["verdict"], LEFT_OUT)

    def test_a_copy_whose_faces_are_not_at_its_transform_leaves_the_pattern_out(self):
        self.assertEqual(len(steps_of(translate(self.row([0, 20, 40], [0, 20, 40])).recipe, "pattern")), 1)
        capture = self.row([0, 20, 40], [0, 40, 60])
        self.assertEqual(left_out(translate(capture))["reason"], pattern_places.DISAGREE.words)
        self.assertEqual(verdict_of(orca_translate(capture), 4)["verdict"], LEFT_OUT)


class FaceCheckTest(unittest.TestCase):
    def test_a_pattern_in_a_placed_component_checks_its_faces_in_the_component(self):
        # Fusion gives the element transforms in assembly space and the faces of native objects in the component's
        # own space (as the T19 exports of a component placed 2400 mm along Y show for the transforms).
        shift = [0.0, 2400.0, 0.0]
        capture = circular("cpattern_full", 6, 360.0, [n * 60 for n in range(6)], [n * 60 for n in range(6)])
        capture["target"]["placement"] = {"frame": {"origin": shift, "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
        for element in capture["items"][4]["data"]["elements"]:
            frame = element["frame"]
            turned = [sum(frame[n][i] * shift[k] for k, n in enumerate("xyz")) for i in range(3)]
            frame["origin"] = [o + t - r for o, t, r in zip(frame["origin"], shift, turned)]
        step = polar_of(capture)
        self.assertEqual((step["polar"]["count"], step.get("skip")), (6, None))

    def test_a_face_the_place_leaves_where_it_is_tells_nothing(self):
        on_axis = [{"center": [20.0, 10.0, 3.0], "area": 9.0}]
        element = {"faces": [{"center": [20.0, 10.0, 3.0], "area": 9.0}]}
        self.assertIsNone(pattern_places.agrees(on_axis, element, turn(60)))


class ReaderTest(unittest.TestCase):
    def test_the_faces_of_the_original_and_of_each_copy_are_read(self):
        def face(x):
            return Obj("fusion::BRepFace", centroid=P(x, 0, 0), area=0.5)
        copies = [fake_element(0, (0, 0, 0)), fake_element(1, (10, 0, 0)), fake_element(2, (20, 0, 0))]
        # A face seen through an occurrence is read as its native face, in the component's own space.
        copies[0].faces = [face(1)]
        copies[1].faces = [Obj("fusion::BRepFace", centroid=P(999, 0, 0), area=0.5, assemblyContext=Obj(),
                               nativeObject=face(11))]
        source = Obj("fusion::ExtrudeFeature", timelineObject=Obj(index=1), faces=Coll([face(1)]))
        data = read_pattern("RectangularPatternFeature", copies,
                            **fake_rectangular(inputEntities=Coll([source])))
        self.assertEqual(data["source_faces"], [{"center": [1.0, 0.0, 0.0], "area": 50.0}])
        self.assertEqual([e["faces"] for e in data["elements"]],
                         [[{"center": [1.0, 0.0, 0.0], "area": 50.0}], [{"center": [11.0, 0.0, 0.0], "area": 50.0}],
                          None])


    def test_a_pattern_of_many_copies_has_the_faces_of_a_spread_sample_read(self):
        copies = [fake_element(n, (n, 0, 0)) for n in range(30)]
        for copy_ in copies:
            copy_.faces = [Obj("fusion::BRepFace", centroid=P(1, 0, 0), area=0.5)]
        data = read_pattern("RectangularPatternFeature", copies, **fake_rectangular(quantityOne=param(30.0)))
        read = [e["id"] for e in data["elements"] if "faces" in e]
        self.assertEqual(len(read), read_repeat.SAMPLED_ELEMENTS)
        self.assertTrue({0, 1, 29} <= set(read))


if __name__ == "__main__":
    unittest.main()
