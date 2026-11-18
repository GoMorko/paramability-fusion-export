"""Picks where the touching outlines of one revolve meet follow the outline they make together
(faces/revolve_joined.py)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_revolve_picks import XZ, at_sizes, marked, size_param, turned_point
from tests.translator_helpers import assert_schema_ok, steps_of

from lib.params import size_table
from lib.sketch_values.motion import Affine, Motion
from lib.translator import translate
from lib.translator.sketch.curved import combine
from lib.translator.sketch.loops import profile_loops

# A cap turned about the z axis: a body from the axis to Radius (20) and from 0 to Height (10), and below it a flange
# 1 mm thick whose outer edge leans out by 0.5 mm. Shelled Wall (1.5) thick, open at the flange's bottom face.
BODY = [[0, 0], [20, 0], [20, 10], [0, 10]]
FLANGE = [[0, -1], [20.5, -1], [20, 0], [0, 0]]
SLANT = math.hypot(0.5, 1.0)
SIZES = ["Radius", "Height", "Wall"]


def _item(index, name, kind, data=None):
    return {"index": index, "name": name, "type": kind, "suppressed": False, "health": "ok", "message": "",
            "in_target_component": True, "bodies_after": [] if kind == "Sketch" else [{"token": "t1", "name": "Body1"}],
            "data": data or {}}


def _lines(points):
    return [{"kind": "line", "start": a, "end": b} for a, b in zip(points, points[1:] + points[:1])]


def _place(uv, moved):
    """How the probe saw the corner `uv` move: the side and the flange edge with Radius, the top with Height, and the
    corners in `moved` (uv tuple to raw x and y) as given there."""
    if tuple(uv) in moved:
        return moved[tuple(uv)]
    x = Affine(uv[0] - 20.0, {"Radius": 1.0}, "Sketch1") if uv[0] >= 19.99 else Affine(float(uv[0]))
    y = Affine(uv[1] - 10.0, {"Height": 1.0}, "Sketch1") if uv[1] >= 9.99 else Affine(float(uv[1]))
    return x, y


def _motion(profiles, moved):
    values = {}
    for n, profile in enumerate(profiles):
        outer, _ = profile_loops(profile)
        key = "1/p%d/l0/" % n
        if outer["kind"] == "polygon":
            for i, uv in enumerate(outer["points"]):
                for k, value in enumerate(_place(uv, moved)):
                    values[key + "points.%d.%d" % (i, k)] = value
            continue
        (cx, cy), w, h = outer["center"], outer["width"], outer["height"]
        low, high = _place([cx - w / 2, cy - h / 2], moved), _place([cx + w / 2, cy + h / 2], moved)
        for k in range(2):
            values[key + "center.%d" % k] = combine([(0.5, low[k]), (0.5, high[k])], "Sketch1")
        values[key + "width"] = combine([(1.0, high[0]), (-1.0, low[0])], "Sketch1")
        values[key + "height"] = combine([(1.0, high[1]), (-1.0, low[1])], "Sketch1")
    return Motion(values=values, states=[{"values": {"Radius": 22.0, "Height": 11.0}, "built": True}])


def cap(outlines, rim):
    """The revolve of `outlines` (point lists), its shell and a chamfer: 0.5 mm on the inner ceiling picked as a face
    (one of its edges is the inner top corner), and 0.3 mm on the inner rim at the point `rim`."""
    profiles = [{"sketch": "Sketch1", "frame": XZ, "loops": [{"outer": True, "curves": _lines(points)}]}
                for points in outlines]
    revolve = {"operation": "newBody", "profiles": profiles,
               "axis": {"point": [0, 0, 0], "dir": [0, 0, 1], "entity_type": "SketchLine", "sketch": "Sketch1"},
               "project_axis": False, "extent": {"kind": "angle", "angle_deg": 360.0, "symmetric": False},
               "participants": [{"token": "t1", "name": "Body1"}], "start_face_normal": None}
    shell = {"faces": [{"token": "f1", "point": turned_point(5, -1, 45)}], "bodies_input": False, "inside": 1.5,
             "outside": 0.0, "shell_type": "sharp", "params": {"inside": {"name": "Wall", "expression": "Wall",
                                                                         "value": 1.5}}}
    chamfer = {"corner_type": "chamfer", "sets": [
        {"kind": "equal", "distance": 0.5, "input_kinds": ["face"], "tangent_chain": True,
         "edges": [{"token": "c0", "closed": True, "points": [turned_point(18.5, 8.5, 45)]}],
         "faces": [{"token": "c1", "point": turned_point(5, 8.5, 45)}]},
        {"kind": "equal", "distance": 0.3, "input_kinds": ["edge"], "tangent_chain": False,
         "edges": [{"token": "c2", "closed": True, "points": [rim]}]}]}
    items = [_item(0, "Sketch1", "Sketch"), _item(1, "Revolve1", "RevolveFeature", revolve),
             _item(2, "Shell1", "ShellFeature", shell), _item(3, "Chamfer1", "ChamferFeature", chamfer)]
    params = [size_param("Radius", 20), size_param("Height", 10), size_param("Wall", 1.5), size_param("Lip", 4)]
    capture = {"capture": 3, "fusion": "2.0.0", "design": "Test", "up_axis": "z",
               "target": {"token": "t1", "name": "Body1"}, "items": items,
               "parameters": {"user": params, "model": []}}
    return capture, profiles


RIM = turned_point(20.5 - 1.5 * SLANT, -1, 30)


def run(outlines, sizes=SIZES, ranges=None, moved=None):
    capture, profiles = cap(outlines, RIM)
    params = capture["parameters"]
    table = size_table.build(params["user"], sizes, params["model"], "mm", ranges=ranges)
    return table, translate(capture, size_table=table, motion=_motion(profiles, moved or {}))


def picks(recipe):
    ceiling, rim = steps_of(recipe, "bevel")
    return ceiling["edges"]["faceEdges"]["near"][0], rim["edges"]["near"][0]


def follows(point):
    return any(isinstance(c, dict) for c in point)


class JoinedOutlineTest(unittest.TestCase):
    def test_the_inner_ceiling_and_the_inner_rim_across_two_outlines_follow_the_sizes(self):
        table, result = run([BODY, FLANGE])
        self.assertIsNone(result.refusal)
        assert_schema_ok(self, result.recipe)
        self.assertEqual(marked(result), set())
        ceiling, rim = picks(result.recipe)
        self.assertAlmostEqual(at_sizes(table, ceiling, Radius=25, Height=12, Wall=2)[2], 10.0, places=6)
        for got, want in zip(at_sizes(table, rim, Radius=25, Height=12, Wall=2), turned_point(25.5 - 2 * SLANT, -1, 30)):
            self.assertAlmostEqual(got, want, places=6)
        # The inner wall of the flange's edge is gone once the wall is 1 / 0.5 * SLANT mm thick.
        self.assertLess(result.recipe["sizes"]["Wall"]["max"], 2 * SLANT)
        self.assertGreater(result.recipe["sizes"]["Wall"]["max"], 2 * SLANT - 0.05)

    def test_an_outline_that_overlaps_another_leaves_the_rim_marked(self):
        # A second body outline inside the first one, sharing its top line.
        inside = [[0, 10], [20, 10], [20, 6], [0, 6]]
        _, result = run([BODY, FLANGE, inside])
        self.assertIsNone(result.refusal)
        self.assertFalse(follows(picks(result.recipe)[1]))
        self.assertIn("Wall", marked(result))

    def test_a_meeting_point_that_slides_off_its_line_within_the_range_leaves_the_rim_marked(self):
        # A lip on the side of the body, its tip at Lip (4 mm) up the side. Past Height (10) the tip leaves the side.
        lip = [[20, 2], [21, 2], [20, 4]]
        body = [[0, 0], [20, 0], [20, 2], [20, 4], [20, 10], [0, 10]]
        tip = {(20, 4): (Affine(0.0, {"Radius": 1.0}, "Sketch1"), Affine(0.0, {"Lip": 1.0}, "Sketch1"))}
        self.assert_kept_only_inside([body, FLANGE, lip], tip, (2.0, 12.0), keeps=(2.0, 8.0))

    def test_an_outline_that_turns_over_onto_its_neighbour_within_the_range_leaves_the_rim_marked(self):
        # A bump on the side of the body, its tip Lip - 3 (1 mm) out. Below Lip 3 the bump lies inside the body.
        bump = [[20, 2], [21, 4], [20, 6]]
        body = [[0, 0], [20, 0], [20, 2], [20, 6], [20, 10], [0, 10]]
        tip = {(21, 4): (Affine(-3.0, {"Radius": 1.0, "Lip": 1.0}, "Sketch1"), Affine(4.0))}
        self.assert_kept_only_inside([body, FLANGE, bump], tip, (2.0, 6.0), keeps=(3.5, 6.0))

    def assert_kept_only_inside(self, outlines, moved, slides, keeps):
        """The rim follows with the range `keeps` of Lip, which keeps the outlines as they meet, and is marked with the
        range `slides`."""
        _, kept = run(outlines, sizes=SIZES + ["Lip"], ranges={"Lip": keeps}, moved=moved)
        self.assertTrue(follows(picks(kept.recipe)[1]))
        self.assertNotIn("Wall", marked(kept))
        _, past = run(outlines, sizes=SIZES + ["Lip"], ranges={"Lip": slides}, moved=moved)
        self.assertFalse(follows(picks(past.recipe)[1]))
        self.assertIn("Wall", marked(past))


if __name__ == "__main__":
    unittest.main()
