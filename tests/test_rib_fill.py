"""A rib To Next that Fusion fills up to the part (a gusset in a corner), copied as the closed outline Fusion made
(`design_model/steps/rib_fill.py`) in both outputs: the outline is proven by the faces Fusion made, the faces of the
part and the volume, else the step is left out. The gusset fixture is saved from a Fusion export of a test design;
the other cases edit it or build the faces by hand."""
import copy
import unittest

from tests import context  # noqa: F401
from tests.orca_cuts import Section
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of
from scripts.orca_live_check import table_for

from lib import orca_translate
from lib.capture_model import gap_hints
from lib.design_model.problem import is_problem
from lib.design_model.steps import rib_fill, rib_web
from lib.geometry import vec
from lib.orca_translate.halfplanes import in_polygon
from lib.translator import translate

# The gusset of the fixture: the triangle between the rib line and the bracket, 2 mm thick about y = 20.
GUSSET = [(4.0, 4.0), (4.0, 34.0), (50.0, 4.0)]


def gusset_capture(edit=None):
    capture = copy.deepcopy(load_capture("rib_tonext_gusset"))
    if edit is not None:
        edit(capture["items"][-1]["data"])
    return capture


def fill_of(data):
    before = data["target_faces_before"]
    return rib_fill.fill(data, before, rib_web.walls(data, before))


def _caps_and_sides(corners_xz, line_xz, y0, y1):
    """Faces Fusion would make for a filled outline in the XZ plane between y0 and y1: both ends and a side along
    each line of the rib (all in model coordinates)."""
    faces = [{"surface": "Plane", "point": [corners_xz[0][0], y1, corners_xz[0][1]], "normal": [0.0, 1.0, 0.0],
              "vertices": [[x, y1, z] for x, z in corners_xz]},
             {"surface": "Plane", "point": [corners_xz[0][0], y0, corners_xz[0][1]], "normal": [0.0, -1.0, 0.0],
              "vertices": [[x, y0, z] for x, z in corners_xz]}]
    for a, b in zip(line_xz, line_xz[1:]):
        d = [b[0] - a[0], b[1] - a[1]]
        normal = vec.unit([-d[1], 0.0, d[0]])  # away from the bracket corner for a line from top left to bottom right
        faces.append({"surface": "Plane", "point": [a[0], y0, a[1]], "normal": normal,
                      "vertices": [[a[0], y1, a[1]], [a[0], y0, a[1]], [b[0], y0, b[1]], [b[0], y1, b[1]]]})
    return faces


def bent_line(data):
    """The rib along two lines (4, 34) to (20, 14) to (50, 4), filled into the corner as a four corner outline."""
    line = [(4.0, 34.0), (20.0, 14.0), (50.0, 4.0)]
    curve = data["path"]["curves"][0]
    data["path"]["curves"] = [
        dict(curve, start=[a[0], 20.0, a[1]], end=[b[0], 20.0, b[1]], entity="e%d" % n,
             flat={"kind": "line", "start": [a[0], -a[1]], "end": [b[0], -b[1]]})
        for n, (a, b) in enumerate(zip(line, line[1:]))]
    corners = [(4.0, 4.0), (4.0, 34.0), (20.0, 14.0), (50.0, 4.0)]
    data["wall_faces"] = _caps_and_sides(corners, line, 19.0, 21.0)
    area = 0.5 * abs(sum(corners[n - 1][0] * corners[n][1] - corners[n][0] * corners[n - 1][1] for n in range(4)))
    data["volume_after"] = data["volume_before"] + area * 2.0


class FillProofTest(unittest.TestCase):
    def test_the_gusset_is_the_triangle_fusion_filled_centred_on_the_sketch_plane(self):
        found = fill_of(gusset_capture()["items"][-1]["data"])
        self.assertFalse(is_problem(found))
        self.assertEqual((found.way, found.length), (0, 2.0))
        self.assertEqual(sorted((u, -v) for u, v in found.points), sorted(GUSSET))

    def test_a_rib_on_one_side_of_its_sketch_plane_runs_the_way_its_ends_lie(self):
        def one_side(data):
            data["symmetric"] = False
            for face in data["wall_faces"]:
                face["vertices"] = [[x, y + 1.0, z] for x, y, z in face["vertices"]]
                face["point"] = vec.add(face["point"], [0.0, 1.0, 0.0])
        found = fill_of(gusset_capture(one_side)["items"][-1]["data"])
        self.assertEqual((found.way, found.length), (1, 2.0))

    def test_a_rib_along_a_chain_of_lines_fills_an_outline_of_four_corners(self):
        found = fill_of(gusset_capture(bent_line)["items"][-1]["data"])
        self.assertFalse(is_problem(found))
        self.assertEqual(len(found.points), 4)

    def test_what_the_faces_or_the_volume_do_not_prove_keeps_the_problem(self):
        def more_volume(data):
            data["volume_after"] += 50.0

        def no_side_along_the_line(data):
            data["wall_faces"] = data["wall_faces"][1:]

        def ends_apart(data):
            data["wall_faces"][2]["vertices"][0] = [4.0, 19.0, 30.0]

        def part_face_not_square(data):
            for face in data["target_faces_before"]:
                if face["normal"] == [1.0, 0.0, 0.0] and face["point"][0] == 4.0:
                    face["normal"] = vec.unit([1.0, 0.1, 0.0])

        def to_a_distance(data):
            data.update(extent="distance", depth=30.0)

        for edit in (more_volume, no_side_along_the_line, ends_apart, part_face_not_square, to_a_distance):
            with self.subTest(edit.__name__):
                data = gusset_capture(edit)["items"][-1]["data"]
                self.assertTrue(is_problem(fill_of(data)))

    def test_a_distance_rib_that_runs_into_the_corner_is_not_filled(self):
        data = copy.deepcopy(load_capture("rib_into_corner")["items"][-1]["data"])
        self.assertEqual(fill_of(data), rib_web.MEETS_PART)


class FillRecipeTest(unittest.TestCase):
    def test_the_gusset_is_one_extrude_of_its_outline_with_the_volume_of_fusion(self):
        capture = gusset_capture()
        result = translate(capture, size_table=table_for(capture))
        assert_schema_ok(self, result.recipe)
        (step,) = [s for s in steps_of(result.recipe, "extrude") if s.get("label") == "Rib1"]
        self.assertEqual((step["combine"], step["extent"], step["distance"]), ("add", "symmetric", {"expr": "rt"}))
        on, outer = step["sketch"]["on"], step["sketch"]["outer"]
        self.assertEqual(outer["kind"], "polygon")
        y = vec.cross(on["normal"], on["xDir"])
        model = sorted(tuple(round(c, 6) for c in vec.add(on["origin"], vec.add(vec.scale(on["xDir"], u),
                                                                                  vec.scale(y, v))))
                       for u, v in outer["points"])
        self.assertEqual(model, sorted((x, 20.0, z) for x, z in GUSSET))
        points = outer["points"]
        area = 0.5 * abs(sum(points[n - 1][0] * points[n][1] - points[n][0] * points[n - 1][1]
                             for n in range(len(points))))
        data = capture["items"][-1]["data"]
        self.assertAlmostEqual(area * 2.0, data["volume_after"] - data["volume_before"], places=6)
        # The outline keeps its numbers: the sizes before the step are marked.
        self.assertEqual(sorted(e["name"] for e in result.loose), ["bt"])

    def test_a_gusset_whose_volume_differs_is_left_out(self):
        def more_volume(data):
            data["volume_after"] += 50.0
        capture = gusset_capture(more_volume)
        result = translate(capture, size_table=table_for(capture))
        self.assertIsNotNone(left_out(result, capture["items"][-1]["index"]))


class FillOrcaTest(unittest.TestCase):
    def test_the_gusset_body_is_the_bracket_and_the_measured_prism(self):
        capture = gusset_capture()
        result = orca_translate.translate(capture, table_for(capture))
        verdicts = {i["name"]: i["verdict"] for i in result.items}
        self.assertEqual(verdicts["Rib1"], "copied")
        outcomes = {p["name"]: p["outcome"] for p in result.parameters}
        self.assertEqual(outcomes["rt"], "variable")
        self.assertNotEqual(outcomes["bt"], "variable")
        inside = Section(result.recipe).bodies[0]

        def expected(x, y, z):
            bracket = 0 <= x <= 60 and 0 <= y <= 40 and 0 <= z <= 40 and (z <= 4 or x <= 4)
            return bracket or (19.0 <= y <= 21.0 and in_polygon(GUSSET, (x, z)))
        for x in (1.5, 6.5, 12.5, 25.5, 40.5, 48.5, 55.5):
            for y in (18.5, 19.5, 20.5, 21.5):
                for z in (2.5, 6.5, 15.5, 25.5, 32.5, 38.5):
                    with self.subTest(point=(x, y, z)):
                        self.assertEqual(inside(list(result.place.point([x, y, z]))), expected(x, y, z))

    def test_a_gusset_whose_volume_differs_is_left_out(self):
        def more_volume(data):
            data["volume_after"] += 50.0
        capture = gusset_capture(more_volume)
        result = orca_translate.translate(capture, table_for(capture))
        self.assertEqual([g["cause"] for g in result.left_out], [gap_hints.RIB_WEB])


if __name__ == "__main__":
    unittest.main()
