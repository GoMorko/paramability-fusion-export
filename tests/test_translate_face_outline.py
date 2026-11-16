"""An extrude whose outline is a flat face of the part (lib/translator/sketch/face_outline.py)."""
import math
import unittest

from tests import context  # noqa: F401
from tests.test_translate_follow import at, loose_names, tray
from tests.test_translate_sized import CUBE, H, run
from tests.test_translate_tool_body import sized, tool_of
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, verdict_of

from lib.translator import translate
from lib.design_model.values import number

# The tray's height at other sizes (recipe size names).
TALLER = {"FilterBox___height__contains_CeramicMedium": 2.5, CUBE: 30}
UP = {"origin": [0, 0, 32], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
DOWN = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, -1, 0], "z": [0, 0, -1]}


def square(lo, hi, y_sign=1):
    corners = [[lo[0], lo[1] * y_sign], [hi[0], lo[1] * y_sign], [hi[0], hi[1] * y_sign], [lo[0], hi[1] * y_sign]]
    return [{"outer": True, "curves": [{"kind": "line", "start": corners[n], "end": corners[(n + 1) % 4]}
                                       for n in range(4)]}]


def face(frame, loops, point, made_by=None, body="t1"):
    owner = {"token": body, "name": "Body1" if body == "t1" else "Body2"}
    record = {"face": True, "type": "BRepFace", "surface": "Plane", "token": "f9", "frame": frame, "space": "sketch",
              "loops": loops, "face_point": point, "body": owner}
    if made_by:
        record["made_by"] = made_by
    return record


def face_extrude(index, profile, distance=5.0, taper=0.0, body="t1", operation="join", **extra):
    data = {"operation": operation, "profiles": [profile], "start": {"kind": "profilePlane"}, "extent_type": "one",
            "side_one": {"kind": "distance", "distance": distance, "taper_deg": taper}, "side_two": None,
            "symmetric": None, "thin": False, "participants": [], "target_box_before": None, "end_offset": distance}
    data.update(extra)
    return {"index": index, "name": "Extrude%d" % index, "type": "ExtrudeFeature", "suppressed": False, "health": "ok",
            "message": "", "in_target_component": True,
            "bodies_after": [{"token": body, "name": "Body1" if body == "t1" else "Body2"}], "data": data}


def on_tray(profile, **extra):
    """The tray's base block (80 x 60, its height a size) and an extrude of `profile` after it."""
    def edit(capture):
        capture["items"].append(face_extrude(2, profile, **extra))
    return tray(edit, keep=[0, 1])


def corners_in_model(step):
    """The model points of a rect or polygon outline of a written extrude, rounded."""
    on, outer = step["sketch"]["on"], step["sketch"]["outer"]
    n, x = on["normal"], on["xDir"]
    y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]]
    if outer["kind"] == "rect":
        (cx, cy), w, h = outer["center"], outer["width"], outer["height"]
        uv = [(cx + sx * w / 2, cy + sy * h / 2) for sx in (-1, 1) for sy in (-1, 1)]
    else:
        uv = [tuple(p) for p in outer["points"]]
    origin = [number(c) for c in on["origin"]]
    return sorted(tuple(round(origin[i] + u * x[i] + v * y[i], 6) + 0.0 for i in range(3)) for u, v in uv)


class SameOutlineTest(unittest.TestCase):
    def test_the_end_face_of_a_sized_extrude_follows_its_length(self):
        made = face(UP, square((0, 0), (80, 60)), [40, 30, 32], {"index": 1, "name": "Extrude1", "which": "end"})
        result, table = run(on_tray(made))
        self.assertIsNone(result.refusal)
        self.assertEqual(loose_names(result), [])
        base, top = steps_of(result.recipe, "extrude")
        self.assertEqual(top["sketch"]["outer"], base["sketch"]["outer"])
        z = top["sketch"]["on"]["origin"][2]
        self.assertEqual(at(result.recipe, table, z, TALLER), 77.0)
        self.assertEqual((top["distance"], top["combine"]), (5.0, "add"))
        assert_schema_ok(self, result.recipe)

    def test_a_start_face_facing_down_keeps_the_outline_in_place(self):
        made = face(DOWN, square((0, 0), (80, 60), -1), [40, 30, 0], {"index": 1, "name": "Extrude1", "which": "start"})
        result, _ = run(on_tray(made, end_offset=5.0))
        self.assertEqual(loose_names(result), [])
        base, bottom = steps_of(result.recipe, "extrude")
        self.assertEqual((bottom["sketch"]["on"]["normal"], bottom["sketch"]["on"]["origin"]), ([0, 0, -1], [0, 0, 0]))
        self.assertEqual(corners_in_model(bottom), corners_in_model(dict(base, sketch=dict(
            base["sketch"], on=dict(base["sketch"]["on"], origin=[0, 0, 0])))))
        assert_schema_ok(self, result.recipe)

    def test_a_cut_between_that_reaches_the_face_only_at_other_sizes_marks_the_sizes(self):
        # A pocket from the base whose depth follows pipe_d_mm: at 12 mm it stays below the 32 mm top face.
        made = face(UP, square((0, 0), (80, 60)), [40, 30, 32], {"index": 1, "name": "Extrude1", "which": "end"})
        pocket = face_extrude(2, dict(load_capture("filter_tray_sized")["items"][1]["data"]["profiles"][0],
                                      loops=square((10, 10), (20, 20))), distance=12.0, operation="cut",
                              params={"side_one.distance": {"name": "d9", "expression": "pipe_d_mm", "value": 12.0}})

        def edit(capture):
            capture["items"] += [pocket, dict(face_extrude(3, made), name="Extrude3")]
        result, _ = run(tray(edit, keep=[0, 1]))
        self.assertIsNone(result.refusal)
        self.assertIn("pipe_d_mm", loose_names(result))
        self.assertEqual(steps_of(result.recipe, "extrude")[2]["sketch"]["outer"],
                         steps_of(result.recipe, "extrude")[0]["sketch"]["outer"])


class AsMeasuredTest(unittest.TestCase):
    def tapered_tray(self):
        grow = 32 * math.tan(math.radians(5))
        made = face(UP, square((-grow, -grow), (80 + grow, 60 + grow)), [40, 30, 32],
                    {"index": 1, "name": "Extrude1", "which": "end"})
        capture = on_tray(made)
        base = capture["items"][1]["data"]
        base["side_one"]["taper_deg"] = 5.0
        base.update(profile_area=4800.0, end_area=(80 + 2 * grow) * (60 + 2 * grow))
        return capture, grow

    def test_the_end_face_of_a_tapered_extrude_is_written_as_measured_with_its_sizes_marked(self):
        capture, grow = self.tapered_tray()
        result, _ = run(capture)
        self.assertIsNone(result.refusal)
        self.assertTrue({H, CUBE} <= set(loose_names(result)))
        top = steps_of(result.recipe, "extrude")[1]
        self.assertEqual(top["sketch"]["on"]["origin"], [0, 0, 32])
        self.assertAlmostEqual(top["sketch"]["outer"]["width"], 80 + 2 * grow, places=6)
        assert_schema_ok(self, result.recipe)

    def test_a_face_the_reader_did_not_tie_to_an_extrude_is_written_as_measured(self):
        result, _ = run(on_tray(face(UP, square((0, 0), (80, 60)), [40, 30, 32])))
        self.assertTrue({H, CUBE} <= set(loose_names(result)))
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["sketch"]["on"]["origin"], [0, 0, 32])


class WithSketchOutlinesTest(unittest.TestCase):
    def test_a_face_and_sketch_outlines_on_its_plane_are_all_extruded(self):
        made = face(UP, square((40, 30), (50, 40)), [45, 35, 32])
        sketch = dict(load_capture("filter_tray_sized")["items"][1]["data"]["profiles"][0], frame=UP,
                      loops=square((10, 10), (20, 20)))
        capture = on_tray(made)
        capture["items"][-1]["data"]["profiles"] = [made, sketch]
        result, _ = run(capture)
        self.assertIsNone(result.refusal)
        joins = steps_of(result.recipe, "extrude")[1:]
        self.assertEqual([(s["combine"], s["sketch"]["on"]["origin"]) for s in joins], [("add", [0, 0, 32])] * 2)
        self.assertEqual(sorted(corners_in_model(s)[0] for s in joins), [(10, 10, 32), (40, 30, 32)])
        assert_schema_ok(self, result.recipe)


def tool_with_face_step():
    """The peg tool of `combine_tool_cut_inside` without its core, with a tapered join on its top face: a tool that only
    adds material, cut from the plate by the Combine."""
    capture = load_capture("combine_tool_cut_inside")
    top = {"origin": [0, 0, 12], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
    loops = [{"outer": True, "curves": [{"kind": "circle", "center": [20, 10], "radius": 5}]}]
    made = face(top, loops, [20, 10, 12], {"index": 3, "name": "Extrude3", "which": "end"}, body="t2")
    small = math.pi * (5 - 3 * math.tan(math.radians(25))) ** 2
    step = face_extrude(4, made, distance=3.0, taper=-25.0, body="t2", profile_area=math.pi * 25, end_area=small)
    step["body_states"] = {"t2": {"box_before": {"min": [15, 5, -2], "max": [25, 15, 12]}, "volume_before": 1099.6,
                                  "volume_after": 1275.4}}
    capture["items"][4] = step
    del capture["items"][5]
    capture["items"][-1]["data"]["tools"][0]["volume"] = 1275.4
    return capture


class ToolBodyTest(unittest.TestCase):
    def test_a_face_step_inside_a_tool_follows_the_tool_length(self):
        result = sized(tool_with_face_step())
        self.assertIsNone(result.refusal)
        self.assertNotIn("peg_len_mm", [d["name"] for d in result.loose + result.fixed])
        kinds = [(s["kind"], s["combine"]) for s in tool_of(result)["features"]]
        self.assertEqual(kinds, [("extrude", "new"), ("extrude", "add")])
        cap = tool_of(result)["features"][1]
        self.assertEqual(cap["sketch"]["outer"], {"kind": "circle", "center": [20, 10], "radius": 5})
        self.assertEqual(cap["sketch"]["on"]["origin"][2], {"expr": "-2 + peg_len_mm"})
        self.assertEqual(cap["taperDeg"], 25.0)
        self.assertEqual([v["verdict"] for v in verdict_of(result, 6)["tool_steps"]], ["translated"] * 2)
        assert_schema_ok(self, result.recipe)


class RefusalTest(unittest.TestCase):
    def test_each_face_that_cannot_be_an_outline_is_left_out(self):
        made = face(UP, square((0, 0), (80, 60)), [40, 30, 32])
        sketch = load_capture("filter_tray_sized")["items"][1]["data"]["profiles"][0]
        cases = {
            "read before faces were read in full": [{"face": True, "type": "BRepFace"}],
            "curved": [{"face": True, "type": "BRepFace", "surface": "Cylinder"}],
            "edges unread": [{"face": True, "type": "BRepFace", "surface": "Plane", "problem": "unread"}],
            "open loop": [dict(made, loops=[{"outer": True, "curves": made["loops"][0]["curves"][:3]}])],
            "with a sketch outline on another plane": [made, sketch],
            "two faces": [made, made],
        }
        for name, profiles in cases.items():
            with self.subTest(name):
                capture = on_tray(made)
                capture["items"][-1]["data"]["profiles"] = profiles
                result = translate(capture)
                self.assertEqual(left_out(result)["index"], 2)


if __name__ == "__main__":
    unittest.main()
