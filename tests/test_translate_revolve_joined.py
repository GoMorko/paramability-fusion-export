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
from lib.design_model.values import Quantity
from lib.translator.faces.revolve_joined import joined_revolves
from lib.translator.faces.revolve_placer import RevolvePlacer, Turn
from lib.translator.faces.shells import Shell
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


def _profile(outline):
    """A profile of the outline `outline`: a list of points, or a list of loops (outer first) of points or of
    curves."""
    loops = outline if isinstance(outline[0][0], (list, dict)) else [outline]
    return {"sketch": "Sketch1", "frame": XZ, "loops": [
        {"outer": n == 0, "curves": loop if isinstance(loop[0], dict) else _lines(loop)} for n, loop in enumerate(loops)]}


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
    profiles = [_profile(points) for points in outlines]
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


def run(outlines, sizes=SIZES, ranges=None, moved=None, rim=RIM):
    capture, profiles = cap(outlines, rim)
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
        # The rule keeps the inner wall of the leaning edge longer than its set back at the open bottom: SLANT less
        # 0.5 mm per mm of Wall stays above 0, so Wall stays below 2 * SLANT. The wall also runs on past the concave
        # corner at the body side; that length is not counted, so the range stops early, on the safe side.
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

    def test_three_outlines_with_one_leaning_line_across_two_of_them_follow_the_sizes(self):
        # The leaning edge is one sketch line from (21, -1) to (20, 1): the flange holds its lower piece and a small
        # lip on the body side its upper piece.
        lean = [{"kind": "line", "start": [21, -1], "end": [20.5, 0], "entity": "lean"},
                {"kind": "line", "start": [20.5, 0], "end": [20, 1], "entity": "lean"}]
        line = lambda a, b: {"kind": "line", "start": a, "end": b}
        flange = [[line([0, -1], [21, -1]), lean[0], line([20.5, 0], [20, 0]), line([20, 0], [0, 0]),
                   line([0, 0], [0, -1])]]
        lip = [[line([20, 0], [20.5, 0]), lean[1], line([20, 1], [20, 0])]]
        body = [[0, 0], [20, 0], [20, 1], [20, 10], [0, 10]]
        rim = turned_point(21 - 1.5 * math.hypot(1, 2) / 2, -1, 30)
        table, result = run([body, flange, lip], rim=rim)
        self.assertIsNone(result.refusal)
        self.assertEqual(marked(result), set())
        got = at_sizes(table, picks(result.recipe)[1], Radius=25, Height=12, Wall=2)
        for value, want in zip(got, turned_point(26 - 2 * math.hypot(1, 2) / 2, -1, 30)):
            self.assertAlmostEqual(value, want, places=6)

    def test_an_outline_with_a_hole_leaves_the_rim_marked(self):
        body = [[[0, 0], [20, 0], [20, 10], [0, 10]], [[5, 3], [8, 3], [8, 6], [5, 6]]]
        _, result = run([body, FLANGE])
        self.assertIsNone(result.refusal)
        self.assertFalse(follows(picks(result.recipe)[1]))
        self.assertIn("Wall", marked(result))

    def test_a_crossing_between_the_size_settings_of_the_ranges_leaves_the_pick_marked(self):
        # A body with a post on its top and a thin arm out of the post. A spike on the body has its tip at
        # (14, Lip): its edge from (3, 10) passes through the arm while Lip is between 15 and 21, and clears it
        # below and above. The ends and the middle of the range 12 to 46 all clear the arm.
        body = [[0, 0], [30, 0], [30, 10], [22, 10], [20, 10], [3, 10], [2, 10], [0, 10]]
        post = [[20, 10], [22, 10], [22, 25], [20, 25], [20, 15.3], [20, 15]]
        arm = [[8, 15], [20, 15], [20, 15.3], [8, 15.3]]
        spike = [[2, 10], [3, 10], [14, 12]]
        tip = {(14, 12): (Affine(14.0), Affine(0.0, {"Lip": 1.0}, "Sketch1"))}
        _, clear = spike_run([body, post, arm, spike], tip, (12.0, 14.5))
        self.assertEqual(marked(clear), set())
        _, through = spike_run([body, post, arm, spike], tip, (12.0, 46.0))
        self.assertIn("Lip", marked(through))


def spike_run(outlines, moved, lip_range):
    """The revolve of `outlines` and a round on the edge where the spike meets the top of the body, with Lip ticked
    in the range `lip_range`."""
    capture, profiles = cap(outlines, RIM)
    fillet = {"rolling_ball": True, "sets": [{"kind": "constant", "radius": 0.5, "continuity": "tangent",
                                              "input_kinds": ["edge"], "edges": [
                                                  {"token": "e0", "closed": True, "points": [turned_point(3, 10, 30)]}]}]}
    capture["items"] = capture["items"][:2] + [_item(2, "Fillet1", "FilletFeature", fillet)]
    capture["parameters"]["user"][3] = size_param("Lip", 12)
    params = capture["parameters"]
    table = size_table.build(params["user"], ["Lip"], params["model"], "mm", ranges={"Lip": lip_range})
    return table, translate(capture, size_table=table, motion=_motion(profiles, moved))


def _static(points, total=None):
    """The placer of `points` turned a full circle about the z axis, with the axis taken to move with sizes."""
    turn = Turn(_profile(points), None, None, [0, 0], [Affine(0.0), Affine(0.0)], [0, 1], 0.0, total)
    return RevolvePlacer("revolve_1", "Revolve1", turn, [])


class JoinedPartsTest(unittest.TestCase):
    def test_outlines_on_both_sides_of_the_axis_are_not_joined(self):
        ctx = type("Ctx", (), {"table": None})()
        side = [[0, 0], [20, 0], [20, 10], [0, 10]]
        for other, joined in (([[-15, 0], [0, 0], [0, 10], [-15, 10]], False), ([[0, 10], [20, 10], [20, 14],
                                                                                [0, 14]], True)):
            profiles = [_profile(side), _profile(other)]
            turns = [Turn(p, None, None, [0, 0], None, [0, 1]) for p in profiles]
            self.assertEqual(bool(joined_revolves(ctx, profiles, turns)), joined)

    def test_a_face_opened_on_the_joined_outline_is_open_for_its_outlines_too(self):
        # A flange 4 mm thick under the body, open at its bottom: 1.5 mm above the opening there is no floor inside.
        body, flange = _static([[0, 0], [20, 0], [20, 10], [0, 10]]), _static([[0, -4], [20, -4], [20, 0], [0, 0]])
        joined = _static([[0, -4], [20, -4], [20, 0], [20, 10], [0, 10], [0, 0]])
        joined.joins = (body, flange)
        opened = joined.place(turned_point(5, -4, 45), False)
        shell = Shell(Quantity(1.5), [], [opened], [body, flange, joined], before=[body, flange, joined])
        self.assertIsNone(shell.place(turned_point(10, -2.5, 30), False))
        self.assertIsNotNone(shell.place(turned_point(10, 8.5, 30), False))


if __name__ == "__main__":
    unittest.main()
