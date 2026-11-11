"""Sweep of one outline along a path: written as an extrude, a revolve or a sweep step; each case it cannot copy is left
out with its own reason."""
import copy
import math
import types
import unittest

from tests import context  # noqa: F401
from tests.translator_helpers import assert_schema_ok, left_out, load_capture, steps_of, stopped, verdict_of

from lib.params import size_table
from lib.sketch_values.motion import Affine, Motion
from lib.translator import paths, sweep, translate
from lib.translator.translate import _sweep_version

PIPE = "sweep_pipe"
PLATE = "sweep_edges"
PIPE_ITEM, PLATE_ITEM = 2, 3
PIPE_KINDS = {"join": "add", "cut": "cut", "intersect": "intersect"}


def sweep_of(capture, index):
    return capture["items"][index]["data"]


def edited(name, index, edit):
    """The capture `name` with `edit(sweep data)` applied to its sweep at timeline `index`."""
    capture = load_capture(name)
    edit(sweep_of(capture, index))
    return capture


def on_plate(edit):
    """Translation of the plate with its wire edited: the sweep is the second step, so a refusal is a gap."""
    return translate(edited(PLATE, PLATE_ITEM, edit))


def gap_reason(result):
    gap = left_out(result, PLATE_ITEM)
    assert gap is not None, "the sweep was copied"
    return gap["reason"]


def sized(capture, motion=None, ticked=None, ranges=None):
    params = capture["parameters"]
    names = ticked or [p["name"] for p in params["user"]]
    table = size_table.build(params["user"], names, params["model"], "mm", ranges=ranges)
    return translate(capture, size_table=table, motion=motion)


def line(a, b):
    return {"kind": "line", "start": list(a), "end": list(b), "opposed": False}


def quarter(centre, start_dir, end_dir, radius):
    def at(d):
        return [centre[i] + radius * d[i] for i in range(3)]

    size = math.hypot(*[start_dir[i] + end_dir[i] for i in range(3)])
    mid = [(start_dir[i] + end_dir[i]) / size for i in range(3)]
    a, b = start_dir, end_dir
    normal = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    return {"kind": "arc", "start": at(start_dir), "end": at(end_dir), "mid": at(mid), "center": list(centre),
            "normal": normal, "radius": radius, "opposed": False}


def pipe_along(curves):
    """The pipe capture with another path and no measured volume (the new path has another length)."""
    capture = edited(PIPE, PIPE_ITEM, lambda data: data["path"].update(curves=curves))
    capture["items"][PIPE_ITEM]["target_after"]["volume_mm3"] = None
    return capture


class CopyTest(unittest.TestCase):
    def test_a_straight_path_is_an_extrude_of_the_outline(self):
        result = translate(load_capture("sweep_straight"))
        self.assertIsNone(result.refusal)
        (step,) = steps_of(result.recipe, "extrude")
        self.assertEqual((step["combine"], step["extent"], step["distance"]), ("new", "oneSide", 40.0))
        self.assertEqual(step["sketch"]["on"]["normal"], [0.0, 0.0, 1.0])
        assert_schema_ok(self, result.recipe)

    def test_a_straight_path_against_the_outline_normal_extrudes_the_other_way(self):
        def turned(data):
            data["profiles"][0]["frame"].update(y=[0, -1, 0], z=[0, 0, -1])
        result = translate(edited("sweep_straight", 2, turned))
        (step,) = steps_of(result.recipe, "extrude")
        self.assertEqual((step["distance"], step["sketch"]["on"]["normal"]), (40.0, [0.0, 0.0, 1.0]))

    def test_a_path_drawn_from_the_far_end_gives_the_same_sweep(self):
        near, far = (translate(load_capture(name)).recipe["features"][0] for name in (PIPE, "sweep_far_end"))
        self.assertEqual(far["path"], near["path"])
        self.assertEqual(far["sketch"], near["sketch"])

    def test_a_flat_chain_of_lines_and_an_arc_is_a_sweep_step(self):
        result = translate(load_capture(PIPE))
        assert_schema_ok(self, result.recipe)
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["combine"], "new")
        self.assertEqual(step["sketch"]["outer"], {"kind": "circle", "center": [0.0, 0.0], "radius": 3.0})
        self.assertEqual(step["path"]["kind"], "flat")
        self.assertEqual([s["kind"] for s in step["path"]["segments"]], ["line", "arc", "line"])
        self.assertEqual(step["path"]["segments"][2]["to"], [30.0, 40.0])
        self.assertEqual(result.recipe["version"], 12)

    def test_lines_joined_by_tangent_arcs_in_3d_are_a_corners_path(self):
        curves = [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
                  line((15, 5, 0), (15, 15, 0)), quarter([15, 15, 5], [0, 0, -1], [0, 1, 0], 5),
                  line((15, 20, 5), (15, 20, 20))]
        result = translate(pipe_along(curves))
        assert_schema_ok(self, result.recipe)
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["path"], {"kind": "corners", "points": [[0.0, 0.0, 0.0], [15.0, 0.0, 0.0],
                                                                      [15.0, 20.0, 0.0], [15.0, 20.0, 20.0]],
                                        "bendRadius": 5.0})

    def test_a_full_circle_is_a_full_turn_revolve(self):
        result = translate(load_capture("sweep_ring"))
        assert_schema_ok(self, result.recipe)
        (step,) = steps_of(result.recipe, "revolve")
        self.assertNotIn("angleDeg", step)
        self.assertEqual(step["axis"]["point"], [-20.0, 0.0])
        self.assertEqual(step["sketch"]["outer"]["kind"], "polygon")

    def test_an_arc_is_a_revolve_that_turns_the_way_the_path_goes(self):
        # The wire leaves along +x. An arc bending towards +y turns about +z, one bending towards -y about -z.
        for side, axis in ((1, [0.0, 1.0]), (-1, [0.0, -1.0])):
            curves = [quarter([0, 10 * side, 0], [0, -side, 0], [1, 0, 0], 10)]
            result = translate(pipe_along(curves))
            with self.subTest(side=side):
                (step,) = steps_of(result.recipe, "revolve")
                self.assertEqual((step["angleDeg"], step["axis"]["dir"]), (90.0, axis))
                self.assertEqual(step["axis"]["point"], [10.0 * side, 0.0])
                assert_schema_ok(self, result.recipe)

    def test_every_operation_is_written_with_its_combine(self):
        for operation, combine in PIPE_KINDS.items():
            result = on_plate(lambda data, operation=operation: data.update(operation=operation))
            with self.subTest(operation=operation):
                self.assertEqual(steps_of(result.recipe, "sweep")[0]["combine"], combine)

    def test_a_parallel_outline_is_copied_on_a_straight_path(self):
        result = translate(edited("sweep_straight", 2, lambda data: data.update(orientation="parallel")))
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)

    def moved_into_component(self, capture):
        capture["target"]["component"] = {"token": "cTray", "name": "Tray", "root": False}
        capture["target"]["placement"] = {"path": "Tray:1", "source": "transform2", "checked_points": 3, "uses": 1,
                                          "linked": False, "frame": {"origin": [100, 50, 0], "x": [0, 1, 0],
                                                                     "y": [-1, 0, 0], "z": [0, 0, 1]}}
        for item in capture["items"]:
            item["component"] = "cTray"
        return steps_of(translate(capture).recipe, "sweep")[0]

    def test_a_flat_sweep_moves_with_its_component_in_the_assembly(self):
        step = self.moved_into_component(load_capture(PIPE))
        self.assertEqual(step["path"]["on"]["origin"], [100.0, 50.0, 0.0])
        self.assertEqual(step["path"]["on"]["xDir"], [0.0, 1.0, 0.0])
        self.assertEqual(step["sketch"]["on"]["normal"], [0.0, 1.0, 0.0])

    def test_the_corner_points_of_a_sweep_move_with_its_component_too(self):
        curves = [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
                  line((15, 5, 0), (15, 15, 0)), quarter([15, 15, 5], [0, 0, -1], [0, 1, 0], 5),
                  line((15, 20, 5), (15, 20, 20))]
        step = self.moved_into_component(pipe_along(curves))
        self.assertEqual(step["path"]["points"], [[100.0, 50.0, 0.0], [100.0, 65.0, 0.0], [80.0, 65.0, 0.0],
                                                  [80.0, 65.0, 20.0]])


class EdgesPathTest(unittest.TestCase):
    def test_a_path_of_body_edges_is_copied_and_cannot_be_repeated_by_a_pattern(self):
        written = []

        def recording(item, ctx):
            written.append(sweep.handle(item, ctx))
            return written[-1]

        result = translate(load_capture(PLATE), {"SweepFeature": recording})
        self.assertIsNone(left_out(result))
        self.assertEqual([e.repeatable for e in written[0].entries], [False])
        self.assertEqual(steps_of(result.recipe, "sweep")[0]["path"]["kind"], "flat")

    def test_the_sizes_the_plate_reads_stay_free_with_a_warning(self):
        result = sized(load_capture(PLATE), ticked=["plate_mm", "plate_w_mm"])
        self.assertEqual([f["name"] for f in result.loose], ["plate_mm"])
        self.assertEqual(result.fixed, [])

    def test_a_wire_along_edges_after_a_step_that_is_left_out_is_left_out_too(self):
        capture = load_capture(PLATE)
        coil = {"index": 2, "name": "Coil1", "type": "CoilFeature", "suppressed": False, "health": "ok", "message": "",
                "in_target_component": True, "bodies_after": [{"token": "t1", "name": "Body1"}], "data": {}}
        capture["items"].insert(2, coil)
        for position, item in enumerate(capture["items"]):
            item["index"] = position
        result = translate(capture)
        self.assertEqual(left_out(result, 4)["name"], "Sweep1")
        self.assertEqual(steps_of(result.recipe, "sweep"), [])


class SizesTest(unittest.TestCase):
    OUTLINE = Affine(0, {"wire_mm": 0.5}, "Sketch1")

    def run_pipe(self, values):
        return sized(load_capture(PIPE), Motion(values))

    def test_the_outline_follows_its_size_and_the_path_sizes_are_left_out_with_a_reason(self):
        result = self.run_pipe({"2/p0/l0/radius": self.OUTLINE})
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["sketch"]["outer"]["radius"], {"expr": "0.5 * wire_mm"})
        self.assertEqual(sorted(result.recipe["sizes"]), ["wire_mm"])
        self.assertEqual(sorted(d["name"] for d in result.dropped), ["bend_mm", "run_mm"])
        self.assertEqual(result.fixed, [])

    def test_the_path_sizes_of_a_straight_sweep_are_left_out_too(self):
        width = Motion({"2/p0/l0/width": Affine(0, {"width_mm": 1.0}, "Sketch1")})
        result = sized(load_capture("sweep_straight"), width)
        self.assertEqual(sorted(result.recipe["sizes"]), ["width_mm"])
        self.assertEqual([d["name"] for d in result.dropped], ["length_mm"])

    def test_a_size_that_moves_the_outline_plane_away_from_the_fixed_path_is_marked(self):
        result = self.run_pipe({"2/p0/l0/radius": self.OUTLINE, "2/p0/plane": Affine(-6, {"wire_mm": 1.0}, "Sketch1")})
        self.assertEqual([f["name"] for f in result.loose], ["wire_mm"])

    def test_a_size_that_moves_the_outline_plane_is_marked_for_the_straight_and_ring_forms(self):
        for name, size, shift in (("sweep_straight", "width_mm", -10), ("sweep_ring", "tri_mm", -6)):
            with self.subTest(name):
                moved = Motion({"2/p0/plane": Affine(shift, {size: 1.0}, "Sketch1")})
                self.assertEqual([f["name"] for f in sized(load_capture(name), moved).loose], [size])

    def test_a_size_that_also_drives_a_setting_the_copy_fixes_is_marked(self):
        capture = load_capture("sweep_straight")
        sweep_of(capture, 2)["params"] = {"taper_deg": {"name": "d1", "expression": "width_mm", "value": 0.0}}
        motion = Motion({"2/p0/l0/width": Affine(0, {"width_mm": 1.0}, "Sketch1")})
        result = sized(capture, motion, ticked=["width_mm"])
        self.assertEqual([f["name"] for f in result.loose], ["width_mm"])
        self.assertEqual(steps_of(result.recipe, "extrude")[0]["sketch"]["outer"]["width"], {"expr": "width_mm"})


class BorrowedOutlineTest(unittest.TestCase):
    def test_an_outline_from_another_component_is_copied_with_its_sizes_marked(self):
        outline = Motion({"1/p0/l0/radius": Affine(0, {"rim_mm": 0.5}, "Rim")})
        result = sized(load_capture("sweep_borrowed"), outline)
        (step,) = steps_of(result.recipe, "sweep")
        self.assertEqual(step["sketch"]["outer"]["radius"], {"expr": "0.5 * rim_mm"})
        self.assertEqual([f["name"] for f in result.loose], ["rim_mm"])
        assert_schema_ok(self, result.recipe)


class PathPlaceTest(unittest.TestCase):
    WIRE = Motion({"3/p0/l0/radius": Affine(0, {"wire_mm": 0.5}, "Sketch2")})

    def loose_of(self, edit, ticked=("wire_mm", "plate_mm")):
        capture = edited(PLATE, PLATE_ITEM, edit)
        return [f["name"] for f in sized(capture, self.WIRE, list(ticked)).loose]

    def test_edges_of_another_body_mark_every_size(self):
        def other_body(data):
            for edge in data["path"]["edges"]:
                edge["body"] = {"token": "t9", "name": "Other"}
        self.assertEqual(sorted(self.loose_of(other_body)), ["plate_mm", "wire_mm"])

    def test_edges_of_the_part_mark_only_the_sizes_read_so_far(self):
        def own_body(data):
            for edge in data["path"]["edges"]:
                edge["body"] = {"token": "t1", "name": "Body1"}
        self.assertEqual(self.loose_of(own_body), ["plate_mm"])

    def test_a_path_sketch_on_a_face_or_with_projected_curves_marks_the_sizes_read_so_far(self):
        def sketch_path(**more):
            def edit(data):
                data["path"].update(kind="sketch", edges=[], sketch="Sketch9", **more)
            return edit
        self.assertEqual(self.loose_of(sketch_path()), [])
        for label, more in (("face", {"reference": {"kind": "face", "token": "f1"}}), ("projected", {"projected": True})):
            with self.subTest(label):
                self.assertEqual(self.loose_of(sketch_path(**more)), ["plate_mm"])

    def test_a_path_sketch_on_a_construction_plane_marks_the_sizes_that_move_the_plane(self):
        capture = edited(PIPE, PIPE_ITEM, lambda d: d["path"].update(reference={"kind": "constructionPlane",
                                                                                "token": "tok_plane"}))
        capture["parameters"]["model"].append(
            {"name": "d9", "expression": "wire_mm", "value": 0.6, "unit": "mm", "kind": "derived", "role": "",
             "dependency_parameters": ["wire_mm"],
             "created_by": {"kind": "constructionPlane", "token": "tok_plane", "name": "", "sketch": "",
                            "component": ""}})
        outline = Motion({"2/p0/l0/radius": Affine(0, {"wire_mm": 0.5}, "Sketch1")})
        self.assertEqual([f["name"] for f in sized(capture, outline).loose], ["wire_mm"])

    def loose_for_wire_range(self, wire_range):
        outline = Motion({"2/p0/l0/radius": Affine(0, {"wire_mm": 0.5}, "Sketch1")})
        return sized(load_capture(PIPE), outline, ranges={"wire_mm": wire_range}).loose

    def test_an_outline_that_can_outgrow_the_tightest_bend_marks_its_sizes(self):
        self.assertEqual([f["name"] for f in self.loose_for_wire_range((2.0, 24.0))], ["wire_mm"])

    def test_an_outline_that_stays_clear_of_the_bend_is_not_marked(self):
        self.assertEqual(self.loose_for_wire_range((2.0, 12.0)), [])


class ToolBodyTest(unittest.TestCase):
    def sweep_tool(self, volume_after):
        """The plate and a Combine that cuts a tool body made by the straight sweep."""
        capture = load_capture("combine_cut")
        made = load_capture("sweep_straight")["items"][2]
        plate = capture["items"][1]["data"]
        made.update(index=3, bodies_after=[{"token": "t2", "name": "Body2"}],
                    target_before={"box": plate["target_box_before"], "volume_mm3": 7209.6},
                    target_after={"box": plate["target_box_before"], "volume_mm3": 7209.6},
                    body_states={"t2": {"box_before": None, "volume_before": None, "volume_after": volume_after}})
        capture["items"][3] = made
        return capture

    def test_a_tool_body_made_by_a_sweep_is_measured_on_the_tool_and_not_the_part(self):
        result = translate(self.sweep_tool(2400.0))
        self.assertIsNone(result.refusal)
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 2)

    def test_a_tool_body_that_was_not_measured_is_not_checked(self):
        self.assertIsNone(translate(self.sweep_tool(None)).refusal)

    def test_a_tool_body_with_the_wrong_volume_is_refused(self):
        self.assertIn(sweep.NOT_MATCHING, left_out(translate(self.sweep_tool(3000.0)))["reason"])


class VolumeTest(unittest.TestCase):
    def test_a_new_body_with_the_wrong_volume_is_refused_for_each_kind_of_path(self):
        for name in ("sweep_straight", PIPE, "sweep_ring"):
            capture = load_capture(name)
            capture["items"][2]["target_after"]["volume_mm3"] *= 1.2
            with self.subTest(name):
                self.assertEqual(stopped(translate(capture))["reason"], sweep.NOT_MATCHING)

    def test_a_bent_path_off_the_centre_of_the_outline_is_not_checked(self):
        def off_centre(data):
            data["profiles"][0]["loops"][0]["curves"][0]["center"] = [1.0, 0.0]
        capture = edited(PIPE, PIPE_ITEM, off_centre)
        capture["items"][2]["target_after"]["volume_mm3"] *= 2
        self.assertIsNone(translate(capture).refusal)

    def test_a_volume_that_was_not_measured_is_not_checked(self):
        capture = load_capture(PIPE)
        capture["items"][2]["target_after"]["volume_mm3"] = None
        self.assertIsNone(translate(capture).refusal)


class RefusalTest(unittest.TestCase):
    """Settings the copy does not follow leave the sweep out as a gap after the plate."""

    def reasons(self, cases):
        for label, edit, reason in cases:
            with self.subTest(label):
                self.assertEqual(gap_reason(on_plate(edit)), reason)

    def test_what_makes_a_new_body_or_a_surface_is_not_copied(self):
        self.reasons([
            ("new component", lambda d: d.update(operation="newComponent"),
             "Sweeps that make a new component are not copied."),
            ("other operation", lambda d: d.update(operation="other"),
             "This sweep combines with the part in a way that is not copied yet."),
            ("surface", lambda d: d.update(solid=False), "Surface sweeps are not copied."),
            ("solid unread", lambda d: d.update(solid=None), sweep.UNREADABLE),
        ])

    def test_outlines_that_are_not_one_sketch_outline(self):
        self.reasons([
            ("none", lambda d: d.update(profiles=[]), "This sweep has no sketch outline."),
            ("several", lambda d: d["profiles"].append(copy.deepcopy(d["profiles"][0])), sweep.SEVERAL_OUTLINES),
            ("a face", lambda d: d["profiles"][0].update(face=True), sweep.FACE_OUTLINE),
            ("unread", lambda d: d.update(profiles=None), sweep.UNREADABLE),
        ])

    def test_rails_and_other_kinds(self):
        self.reasons([
            ("rail", lambda d: d.update(rail=copy.deepcopy(d["path"])), sweep.RAIL),
            ("rail unread", lambda d: d.update(rail={"kind": "unread"}), sweep.RAIL_UNREADABLE),
            ("other orientation", lambda d: d.update(orientation="other"), sweep.OTHER_KIND),
            ("orientation unread", lambda d: d.update(orientation=None), sweep.UNREADABLE),
            ("twist unread", lambda d: d.update(twist_deg=None), sweep.UNREADABLE),
        ])

    def test_part_of_the_path(self):
        self.reasons([
            ("distance one", lambda d: d.update(distance_one=0.5), sweep.PART_OF_PATH),
            ("distance two", lambda d: d.update(distance_two=0.25), sweep.PART_OF_PATH),
            ("distance one unread", lambda d: d.update(distance_one=None), sweep.UNREADABLE),
        ])

    def test_a_parallel_outline_on_a_bent_path(self):
        self.reasons([("parallel", lambda d: d.update(orientation="parallel"), sweep.KEEPS_DIRECTION)])

    def test_paths_that_cannot_be_read(self):
        self.reasons([
            ("none", lambda d: d.update(path=None), sweep.PATH_UNREADABLE),
            ("sketch and edges", lambda d: d["path"].update(kind="mixed"), sweep.MIXED_PATH),
            ("an entity that is neither", lambda d: d["path"].update(kind="other"), paths.NOT_SKETCH),
            ("curves unread", lambda d: d["path"].update(curves=None), paths.UNREADABLE),
            ("longer than what is read", lambda d: d["path"].update(truncated=True), sweep.PATH_TOO_LONG),
        ])

    def test_a_path_of_another_component_is_not_copied(self):
        result = on_plate(lambda d: d["path"].update(foreign=True))
        self.assertIn("another component", gap_reason(result))

    def test_the_gap_keeps_the_plate_and_its_settings(self):
        result = on_plate(lambda d: d.update(rail=copy.deepcopy(d["path"])))
        self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)
        self.assertEqual(steps_of(result.recipe, "sweep"), [])


class PathShapeTest(unittest.TestCase):
    """Paths the recipe cannot hold leave the sweep out as a gap after the block."""

    def test_each_path_the_recipe_cannot_hold_leaves_the_sweep_out_with_its_reason(self):
        cases = (("sweep_closed_outline", paths.CLOSED_AT_CORNER), ("sweep_sharp_corner", paths.SHARP_CORNER),
                 ("sweep_middle_outline", paths.BOTH_SIDES), ("sweep_tilted_outline", paths.NOT_SQUARE),
                 ("sweep_bend_3d", paths.BENDS_3D))
        for name, reason in cases:
            with self.subTest(name):
                result = translate(load_capture(name))
                self.assertEqual(left_out(result, 4)["reason"], reason)
                self.assertEqual(len(steps_of(result.recipe, "extrude")), 1)

    def test_an_outline_wider_than_the_bend_is_refused(self):
        capture = edited(PIPE, PIPE_ITEM, lambda d: d["profiles"][0]["loops"][0]["curves"][0].update(radius=12.0))
        self.assertIn("bends in a radius", stopped(translate(capture))["reason"])


def arc_xy(centre, radius, from_deg, to_deg):
    """An arc in the xy plane turning counter clockwise from one angle about `centre` to another."""
    def at(deg):
        return [centre[0] + radius * math.cos(math.radians(deg)), centre[1] + radius * math.sin(math.radians(deg)), 0.0]
    return {"kind": "arc", "start": at(from_deg), "end": at(to_deg), "mid": at((from_deg + to_deg) / 2),
            "center": list(centre) + [0.0], "normal": [0, 0, 1], "radius": radius, "opposed": False}


def with_options(name, index, **settings):
    capture = edited(name, index, lambda data: data.update(**settings))
    capture["items"][index]["target_after"]["volume_mm3"] = None
    return capture


def only_sweep(testcase, result):
    testcase.assertIsNone(result.refusal)
    assert_schema_ok(testcase, result.recipe)
    (step,) = steps_of(result.recipe, "sweep")
    return step


class TwistTest(unittest.TestCase):
    def test_a_twist_on_a_straight_path_is_a_sweep_along_its_two_ends(self):
        capture = edited("sweep_straight", 2, lambda d: d.update(twist_deg=90.0))
        result = translate(capture)
        step = only_sweep(self, result)
        self.assertEqual(step["twistDeg"], 90.0)
        self.assertEqual(step["path"], {"kind": "corners", "points": [[0.0, 0.0, 0.0], [0.0, 0.0, 40.0]],
                                        "bendRadius": 1.0})
        self.assertEqual(result.recipe["version"], 16)

    def test_a_twist_is_copied_with_a_note_to_check_the_shape(self):
        result = translate(edited("sweep_straight", 2, lambda d: d.update(twist_deg=90.0)))
        self.assertEqual(verdict_of(result, 2)["verdict"], "translatedWithNote")
        self.assertIn("check the shape", verdict_of(result, 2)["note"])

    def test_a_twist_on_a_bent_flat_path_keeps_the_flat_path(self):
        step = only_sweep(self, translate(edited(PIPE, PIPE_ITEM, lambda d: d.update(twist_deg=-45.0))))
        self.assertEqual((step["twistDeg"], step["path"]["kind"]), (-45.0, "flat"))

    def test_a_twist_on_one_arc_is_a_sweep_and_not_a_revolve(self):
        capture = pipe_along([arc_xy((0, 10), 10, -90, 0)])
        step = only_sweep(self, translate(edited_after(capture, twist_deg=30.0)))
        self.assertEqual([s["kind"] for s in step["path"]["segments"]], ["arc"])

    def test_a_twist_on_a_corners_path(self):
        curves = [line((0, 0, 0), (10, 0, 0)), quarter([10, 5, 0], [0, -1, 0], [1, 0, 0], 5),
                  line((15, 5, 0), (15, 15, 0)), quarter([15, 15, 5], [0, 0, -1], [0, 1, 0], 5),
                  line((15, 20, 5), (15, 20, 20))]
        step = only_sweep(self, translate(edited_after(pipe_along(curves), twist_deg=30.0)))
        self.assertEqual((step["path"]["kind"], step["twistDeg"]), ("corners", 30.0))

    def test_a_twisting_outline_counts_with_its_whole_radius_at_a_bend(self):
        def lifted(data):
            data["profiles"][0]["loops"][0]["curves"][0].update(center=[0.0, 9.0], radius=2.0)
        plain = with_options(PIPE, PIPE_ITEM)
        lifted(sweep_of(plain, PIPE_ITEM))
        self.assertIsNone(translate(plain).refusal)
        twisted = edited_after(plain, twist_deg=10.0)
        self.assertIn("bends in a radius", stopped(translate(twisted))["reason"])

    def test_a_twist_that_follows_a_size_marks_the_outline_sizes(self):
        outline = Motion({"2/p0/l0/radius": Affine(0, {"wire_mm": 0.5}, "Sketch1")})
        capture = edited(PIPE, PIPE_ITEM, lambda d: d.update(twist_deg=45.0))
        capture["items"][PIPE_ITEM]["target_after"]["volume_mm3"] = None
        result = sized(capture, outline)
        self.assertEqual([f["name"] for f in result.loose], ["wire_mm"])
        self.assertEqual(steps_of(result.recipe, "sweep")[0]["sketch"]["outer"]["radius"], {"expr": "0.5 * wire_mm"})

    def test_a_plain_sweep_keeps_its_older_version(self):
        self.assertEqual(translate(load_capture(PIPE)).recipe["version"], 12)

    def test_the_version_of_a_sweep_step(self):
        self.assertEqual(_sweep_version({"kind": "sweep", "path": {"kind": "flat", "closed": True}}), 16)
        self.assertEqual(_sweep_version({"kind": "sweep", "orientation": "fixed", "path": {}}), 16)
        self.assertEqual(_sweep_version({"kind": "sweep", "path": {"kind": "flat"}}), 0)
        self.assertEqual(_sweep_version({"kind": "extrude", "twistDeg": 1}), 0)

    def test_a_twist_over_ten_turns_or_with_a_taper_or_a_parallel_outline_is_left_out(self):
        for label, edit, reason in (
                ("long", dict(twist_deg=3700.0), sweep.TWIST_LONG),
                ("and taper", dict(twist_deg=10.0, taper_deg=1.0), sweep.TWIST_AND_TAPER),
                ("and parallel", dict(twist_deg=10.0, orientation="parallel"), sweep.PARALLEL_AND_SHAPE)):
            with self.subTest(label):
                self.assertEqual(gap_reason(on_plate(lambda d, edit=edit: d.update(**edit))), reason)


def edited_after(capture, **settings):
    """The capture with settings on its sweep (timeline index 2) and its measured volume dropped."""
    sweep_of(capture, 2).update(**settings)
    capture["items"][2]["target_after"]["volume_mm3"] = None
    return capture


class TaperTest(unittest.TestCase):
    """A 20 by 4 rectangle swept 20 mm straight: a recipe taper of 5 degrees narrows each wall by 0.0875 mm per mm."""
    A, B, LENGTH, SLOPE = 20.0, 4.0, 20.0, math.tan(math.radians(5.0))

    def offset(self, slope):
        a, b, n = self.A, self.B, self.LENGTH
        return a * b * n - (a + b) * slope * n ** 2 + 4 * slope ** 2 * n ** 3 / 3

    def scaled(self, slope):
        a, b, n = self.A, self.B, self.LENGTH
        rate = slope * (a + b) / (a * b)
        return a * b * (n - rate * n ** 2 + rate ** 2 * n ** 3 / 3)

    def straight(self, volume, fusion_deg=-5.0):
        """The straight sweep as a 20 by 4 rectangle 20 mm long made with the taper and the volume."""
        def edit(data):
            curve = data["profiles"][0]["loops"][0]["curves"]
            for piece, (start, end) in zip(curve, [((-10, -2), (10, -2)), ((10, -2), (10, 2)), ((10, 2), (-10, 2)),
                                                    ((-10, 2), (-10, -2))]):
                piece.update(start=list(start), end=list(end))
            data["areas"] = [80.0]
            data["path"]["curves"][0].update(end=[0, 0, 20], check={"start": [0, 0, 0], "end": [0, 0, 20]})
            data["taper_deg"] = fusion_deg
        capture = edited("sweep_straight", 2, edit)
        capture["items"][2]["target_after"]["volume_mm3"] = volume
        return capture

    def test_a_taper_whose_volume_fits_the_offset_is_written_with_the_extrude_sign(self):
        result = translate(self.straight(self.offset(self.SLOPE)))
        step = only_sweep(self, result)
        self.assertAlmostEqual(step["taperDeg"], 5.0)
        self.assertEqual(result.recipe["version"], 16)
        self.assertIn("check the shape", verdict_of(result, 2)["note"])

    def test_a_taper_whose_volume_fits_the_opposite_lean_is_written_the_other_way(self):
        step = only_sweep(self, translate(self.straight(self.offset(-self.SLOPE))))
        self.assertAlmostEqual(step["taperDeg"], -5.0)

    def test_a_taper_that_scales_the_outline_is_left_out(self):
        result = translate(self.straight(self.scaled(self.SLOPE)))
        self.assertEqual(stopped(result)["reason"], sweep.SCALED_OUTLINE)

    def test_a_taper_without_a_measured_volume_is_written_as_read(self):
        step = only_sweep(self, translate(self.straight(None)))
        self.assertAlmostEqual(step["taperDeg"], 5.0)

    def test_a_taper_on_a_bent_path_is_a_sweep_step(self):
        step = only_sweep(self, translate(with_options(PIPE, PIPE_ITEM, taper_deg=2.0)))
        self.assertAlmostEqual(step["taperDeg"], -2.0)
        self.assertEqual(step["path"]["kind"], "flat")

    def test_a_taper_on_one_arc_is_a_sweep_and_not_a_revolve(self):
        capture = edited_after(pipe_along([arc_xy((0, 10), 10, -90, 0)]), taper_deg=2.0)
        self.assertEqual([s["kind"] for s in only_sweep(self, translate(capture))["path"]["segments"]], ["arc"])

    def test_an_outline_that_can_grow_past_the_bend_is_refused_for_either_lean(self):
        self.assertIn("bends in a radius", stopped(translate(with_options(PIPE, PIPE_ITEM, taper_deg=10.0)))["reason"])

    def test_a_taper_along_a_free_curve_is_left_out(self):
        samples = [[10 + k, 0.01 * k * k, 0.0] for k in range(21)]
        spline = {"kind": "other", "start": samples[0], "end": samples[-1], "samples": samples, "opposed": False}
        capture = edited_after(pipe_along([line((0, 0, 0), (10, 0, 0)), spline]), taper_deg=2.0)
        self.assertEqual(stopped(translate(capture))["reason"], sweep.TAPER_CURVES)

    def test_a_taper_through_too_many_path_parts_is_left_out(self):
        parts = types.SimpleNamespace(recipe={"kind": "corners"}, curves=[None] * sweep.MAX_TAPER_STATIONS)
        self.assertEqual(sweep._taper_path_refusal(parts).reason, sweep.TAPER_STATIONS)
        parts.curves = parts.curves[:-1]
        self.assertIsNone(sweep._taper_path_refusal(parts))

    def test_a_steep_taper_or_one_with_a_parallel_outline_is_left_out(self):
        for label, edit, reason in (("steep", dict(taper_deg=-50.0), sweep.TAPER_STEEP),
                                    ("parallel", dict(taper_deg=2.0, orientation="parallel"),
                                     sweep.PARALLEL_AND_SHAPE)):
            with self.subTest(label):
                self.assertEqual(gap_reason(on_plate(lambda d, edit=edit: d.update(**edit))), reason)


class ParallelTest(unittest.TestCase):
    def test_a_parallel_outline_along_a_path_that_keeps_rising_is_a_fixed_sweep(self):
        capture = edited_after(pipe_along([arc_xy((0, 10), 10, -90, -30)]), orientation="parallel")
        result = translate(capture)
        step = only_sweep(self, result)
        self.assertEqual(step["orientation"], "fixed")
        self.assertNotIn("twistDeg", step)
        self.assertEqual(result.recipe["version"], 16)
        self.assertNotIn("check the shape", verdict_of(result, 2)["note"] or "")

    def test_a_parallel_outline_along_a_flat_chain_is_a_fixed_sweep(self):
        curves = [line((0, 0, 0), (10, 0, 0)), arc_xy((10, 10), 10, -90, -45), line((17.071068, 2.928932, 0), (30, 15.857864, 0))]
        step = only_sweep(self, translate(edited_after(pipe_along(curves), orientation="parallel")))
        self.assertEqual((step["orientation"], step["path"]["kind"]), ("fixed", "flat"))

    def test_a_parallel_outline_along_a_path_that_turns_back_is_left_out(self):
        for curves in ([arc_xy((0, 10), 10, -90, 30)], None):
            capture = edited_after(pipe_along(curves), orientation="parallel") if curves else with_options(
                PIPE, PIPE_ITEM, orientation="parallel")
            with self.subTest(len(curves or [])):
                self.assertEqual(stopped(translate(capture))["reason"], sweep.KEEPS_DIRECTION)



RIM, RIM_ITEM = "sweep_closed_rim", 2


def reversed_path(data):
    data["path"]["curves"] = [dict(c, start=c["end"], end=c["start"], mid=c.get("mid")) if c["kind"] == "arc"
                              else dict(c, start=c["end"], end=c["start"]) for c in reversed(data["path"]["curves"])]


class ClosedTest(unittest.TestCase):
    """A closed flat path is one sweep step with no end faces; the volume is the area times the length the centre
    travels."""

    def test_a_rim_round_a_rounded_rectangle_is_a_closed_flat_path(self):
        result = translate(load_capture(RIM))
        step = only_sweep(self, result)
        path = step["path"]
        self.assertEqual((path["kind"], path["closed"], path["start"]), ("flat", True, [20.0, 0.0]))
        self.assertEqual(path["segments"][-1]["to"], path["start"])
        self.assertEqual(len(path["segments"]), 9)
        self.assertNotIn("twistDeg", step)
        self.assertEqual(result.recipe["version"], 16)
        self.assertEqual(verdict_of(result, 2)["verdict"], "translated")

    def test_a_rim_drawn_the_other_way_round_has_the_same_volume(self):
        capture = edited(RIM, RIM_ITEM, reversed_path)
        step = only_sweep(self, translate(capture))
        self.assertEqual(step["path"]["segments"][0], {"kind": "line", "to": [5.0, 0.0]})

    def test_a_volume_that_does_not_match_the_rim_is_refused(self):
        capture = edited(RIM, RIM_ITEM, lambda d: None)
        capture["items"][RIM_ITEM]["target_after"]["volume_mm3"] *= 1.1
        self.assertEqual(stopped(translate(capture))["reason"], sweep.NOT_MATCHING)

    def test_a_full_circle_that_twists_is_a_closed_path_and_a_plain_one_stays_a_revolve(self):
        result = translate(edited("sweep_ring", 2, lambda d: d.update(twist_deg=360.0)))
        step = only_sweep(self, result)
        self.assertEqual([s["kind"] for s in step["path"]["segments"]], ["arc", "arc"])
        self.assertEqual((step["path"]["closed"], step["twistDeg"], result.recipe["version"]), (True, 360.0, 16))
        self.assertEqual(len(steps_of(translate(load_capture("sweep_ring")).recipe, "revolve")), 1)

    def test_a_twist_of_whole_turns_is_copied_with_the_note(self):
        result = translate(load_capture("sweep_closed_twist"))
        step = only_sweep(self, result)
        self.assertEqual((step["twistDeg"], step["path"]["closed"]), (360.0, True))
        self.assertIn("check the shape", verdict_of(result, 2)["note"])

    def test_a_twist_along_a_closed_path_stays_a_number_and_its_size_is_dropped(self):
        result = sized(load_capture("sweep_closed_twist"))
        self.assertEqual(only_sweep(self, result)["twistDeg"], 360.0)
        self.assertEqual([(d["name"], "twist" in d["reason"]) for d in result.dropped], [("spin_deg", True)])

    def test_a_twisting_rim_with_its_centre_off_the_path_has_no_volume_to_check(self):
        capture = edited_after(load_capture(RIM), twist_deg=720.0)
        capture["items"][RIM_ITEM]["target_after"]["volume_mm3"] = 1.0
        self.assertEqual(only_sweep(self, translate(capture))["twistDeg"], 720.0)

    def test_a_twist_that_is_not_whole_turns_is_left_out(self):
        for name in (RIM, "sweep_ring"):
            with self.subTest(name):
                result = translate(edited_after(load_capture(name), twist_deg=90.0))
                self.assertEqual(stopped(result)["reason"], sweep.TWIST_CLOSED)

    def test_a_taper_or_a_parallel_outline_along_a_closed_path_is_left_out(self):
        for edit, reason in ((dict(taper_deg=2.0), paths.CLOSED_TAPER),
                             (dict(orientation="parallel"), paths.CLOSED_PARALLEL)):
            for name in (RIM, "sweep_ring"):
                with self.subTest(name, edit=edit):
                    self.assertEqual(stopped(translate(edited_after(load_capture(name), **edit)))["reason"], reason)


if __name__ == "__main__":
    unittest.main()
