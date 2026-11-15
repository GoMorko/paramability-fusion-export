"""A flat face a step uses as its outline, read again by the size probe before that step (keys `<item>/face`): the
outline follows the sizes that move the face, and only a size the copy cannot follow, or that was not tried, is
marked (lib/translator/sketch/face_outline.py, lib/probe/match.py, lib/fusion_reader/read_face.py)."""
import tempfile
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeMarkerTimeline, FakePort, FakeStore
from tests.probe_helpers import size
from tests.test_capture_reader import Obj
from tests.test_capture_reader_offset import plane_face, side, with_outline
from tests.test_translate_emboss import LID, circle, emboss_data, top_face, trimmed_by
from tests.test_translate_emboss import square as lid_square
from tests.test_translate_face_outline import TALLER, UP, face, face_extrude, on_tray, square
from tests.test_translate_follow import at, loose_names, tray
from tests.test_translate_sized import CUBE, H, TICKED, table_of
from tests.translator_helpers import load_capture, steps_of

from lib.design_edit.marker import MARKER_LOST
from lib.export_plan.pipeline import MarkerNotHeld, ProbeRun
from lib.export_plan.probe_flow import SizeProbe
from lib.fusion_reader.read_face import read_faces
from lib.params import size_table
from lib.probe import build
from lib.sketch_values.motion import Motion
from lib.translator import translate

ON_TOP = {"const": 0, "terms": {"FilterBox_height_mm": 1}}


def tray_face(made_by=None):
    """The tray's base block and a join extrude from its 80 x 60 top face (item 2)."""
    return on_tray(face(UP, square((0, 0), (80, 60)), [40, 30, 32], made_by))


def followed(key, values=None, token="f9", **extra):
    """A motion file in which the probe read the face `key` (its token `token`) at every try."""
    return Motion.from_json(dict({"values": values or {}, "faces": {key: token}}, **extra))


def run(capture, motion):
    table = table_of(capture, TICKED)
    return translate(capture, size_table=table, motion=motion), table


class FollowedFaceTest(unittest.TestCase):
    def test_the_outline_follows_the_measured_face_and_marks_nothing(self):
        result, table = run(tray_face(), followed("2/face", {"2/face/plane": ON_TOP}))
        self.assertIsNone(result.refusal)
        self.assertEqual(loose_names(result), [])
        top = steps_of(result.recipe, "extrude")[1]
        self.assertEqual(at(result.recipe, table, top["sketch"]["on"]["origin"][2], TALLER), 77.0)

    def test_only_a_size_the_face_cannot_follow_or_that_was_not_tried_is_marked(self):
        stuck = {"2/face/l0/width": {"stuck": [CUBE], "cause": "curve", "sketch": "the face Extrude2 starts on"}}
        for label, motion, name in (("no formula", followed("2/face", stuck), CUBE),
                                    ("not tried", followed("2/face", untried=[H]), H)):
            with self.subTest(label):
                result = run(tray_face(), motion)[0]
                self.assertEqual(([f["name"] for f in result.loose], result.fixed), ([name], []))

    def test_a_later_step_that_leaves_the_measured_face_alone_marks_nothing(self):
        made = face(UP, square((0, 0), (80, 60)), [40, 30, 32], {"index": 1, "name": "Extrude1", "which": "end"})
        pocket = face_extrude(2, dict(load_capture("filter_tray_sized")["items"][1]["data"]["profiles"][0],
                                      loops=square((10, 10), (20, 20))), distance=12.0, operation="cut",
                              params={"side_one.distance": {"name": "d9", "expression": "pipe_d_mm", "value": 12.0}})

        def edit(capture):
            capture["items"] += [pocket, dict(face_extrude(3, made), name="Extrude3")]
        result, _ = run(tray(edit, keep=[0, 1]), followed("3/face", {"3/face/plane": ON_TOP}))
        self.assertIsNone(result.refusal)
        self.assertEqual(loose_names(result), [])

    def test_beside_sketch_outlines_only_the_sizes_that_move_the_face_are_marked(self):
        made = face(UP, square((40, 30), (50, 40)), [45, 35, 32])
        sketch = dict(load_capture("filter_tray_sized")["items"][1]["data"]["profiles"][0], frame=UP,
                      loops=square((10, 10), (20, 20)))
        capture = on_tray(made)
        capture["items"][-1]["data"]["profiles"] = [made, sketch]
        result, _ = run(capture, followed("2/face", {"2/face/l0/width": {"const": 10, "terms": {"wall_mm": 0}},
                                                     "2/face/l0/center.0": {"const": 43, "terms": {CUBE: 0.1}}}))
        self.assertIsNone(result.refusal)
        self.assertEqual(loose_names(result), [CUBE])

    def test_a_face_plane_that_moves_along_a_curve_follows_its_formula(self):
        moved = {"const": 2, "sum": [{"k": 1, "of": [["", H, 1], ["", CUBE, 1]]}]}
        result, table = run(tray_face(), followed("2/face", {"2/face/plane": moved}))
        self.assertEqual(loose_names(result), [])
        top = steps_of(result.recipe, "extrude")[1]
        self.assertAlmostEqual(at(result.recipe, table, top["sketch"]["on"]["origin"][2], TALLER), 77.0, places=6)

    def test_a_trimmed_emboss_limits_itself_to_the_measured_face(self):
        capture = load_capture(LID)
        trimmed_by(top_face(lid_square([0, 0], [60, 40])), 280.0)(emboss_data(capture))
        params = capture["parameters"]
        table = size_table.build(params["user"], ["lid_mm", "raise_mm"], params["model"], "mm")
        motion = followed("3/face", {"3/face/plane": {"const": 0, "terms": {"lid_mm": 1}}}, token="f1")
        result = translate(capture, size_table=table, motion=motion)
        self.assertIsNone(result.refusal)
        self.assertEqual(steps_of(result.recipe, "extrude")[1]["within"]["on"]["origin"][2], {"expr": "lid_mm"})
        self.assertEqual(result.loose, [])


    def test_a_hole_of_the_followed_face_that_would_leave_it_cuts_the_range_before_that(self):
        # The hole is 30 mm above the face's lower edge; the face's upper edge is 10 * lid_mm up, so the hole fits
        # only from a lid of 3.3 mm.
        capture = load_capture(LID)
        face = top_face(lid_square([0, 0], [60, 40]) + [circle([30, 30], 3)],
                        {"index": 1, "name": "Extrude1", "which": "end"})
        trimmed_by(face, 280.0)(emboss_data(capture))
        params = capture["parameters"]
        table = size_table.build(params["user"], ["lid_mm", "raise_mm"], params["model"], "mm")
        motion = followed("3/face", {"3/face/plane": {"const": 0, "terms": {"lid_mm": 1}},
                                     "3/face/l0/center.1": {"const": 0, "terms": {"lid_mm": 5}},
                                     "3/face/l0/height": {"const": 0, "terms": {"lid_mm": 10}}}, token="f1")
        result = translate(capture, size_table=table, motion=motion)
        self.assertIsNone(result.refusal)
        size = result.recipe["sizes"]["lid_mm"]
        self.assertEqual((size["min"], size["max"]), (3.31, 8.0))
        self.assertIn("hole reach its edge", result.cuts[0]["reason"])


def face_read(height, holed=False, back=False):
    """The tray's top face as the reader gives it at `height`: its frame turned a quarter about the normal and set
    apart, its edges from another corner and the other way round. `holed` adds a round hole; `back` reads it facing
    down, as when the body under it lies on its other side."""
    origin = (5, 5)
    frame = {"origin": [origin[0], origin[1], height], "x": [0, 1, 0], "y": [1, 0, 0] if back else [-1, 0, 0],
             "z": [0, 0, -1] if back else [0, 0, 1]}
    local = [[y - origin[1], origin[0] - x] for x, y in [(80, 0), (0, 0), (0, 60), (80, 60)]]
    loops = [{"outer": True, "curves": [{"kind": "line", "start": local[n], "end": local[(n + 1) % 4]}
                                        for n in range(4)]}]
    if holed:
        loops.append({"outer": False, "curves": [{"kind": "circle", "center": [10, -20], "radius": 3}]})
    return {"frame": frame, "loops": loops}


def tray_read(values, holed_above=None, back_above=None):
    h, cube = values.get(H, 1.5), values.get(CUBE, 20.0)
    top = h * cube + 2
    holed = holed_above is not None and h > holed_above
    back = back_above is not None and h > back_above
    return {"sketches": {}, "points": {}, "lines": {}, "params": {}, "box": {"min": [0, 0, 0], "max": [80, 60, top]},
            "faces": {"2/face": face_read(top, holed=holed, back=back)}}


class ProbeTest(unittest.TestCase):
    def test_the_probe_reads_the_face_before_its_step_and_tries_the_sizes_that_may_move_it(self):
        capture = tray_face()
        table = table_of(capture, [H, CUBE])
        probe = SizeProbe.start(capture, table, lambda request: tray_read({}))
        self.assertEqual(probe.request["faces"], {"2/face": {"token": "f9", "before": 2}})
        rows = probe.probe_rows([size(table, H, "count"), size(table, CUBE)])
        probe.add_states([(r["state"], {"name": r["name"]}, tray_read(r["state"])) for r in rows])
        probe.finish(tray_read({}), {})
        result = translate(capture, size_table=table, motion=probe.motion)
        self.assertEqual(loose_names(result), [])
        top = steps_of(result.recipe, "extrude")[1]
        self.assertEqual(at(result.recipe, table, top["sketch"]["on"]["origin"][2], TALLER), 77.0)

    def test_a_face_is_read_again_only_while_a_size_that_may_change_it_is_set(self):
        capture = tray_face()
        table = table_of(capture, [H, CUBE, "wall_mm"])
        asked = []

        def read(request):
            asked.append(set(request.get("faces") or ()))
            return tray_read({})
        probe = SizeProbe.start(capture, table, read)
        for values, faces in (({H: 2.0}, {"2/face"}), ({"wall_mm": 3.0}, set()), ({}, set())):
            with self.subTest(values):
                state = probe.read_now(values)
                self.assertEqual((asked[-1], state["faces"]), (faces, tray_read({})["faces"]))

    def test_a_face_that_changes_outline_or_turns_over_at_a_value_cuts_the_range_there(self):
        capture = tray_face()
        table = table_of(capture, [H, CUBE])
        tries = [{}, {H: 1.125}, {H: 1.875}, {H: 2.5}, {CUBE: 15.0}, {CUBE: 25.0}, {H: 2.5, CUBE: 25.0}]
        for label, change in (("hole", {"holed_above": 2.0}), ("other way", {"back_above": 2.0})):
            with self.subTest(label):
                states = [{"values": v, "built": True, "read": tray_read(v, **change), "e0": not v} for v in tries]
                motion = build.build(capture, table, states, after=tray_read({}))
                result = translate(capture, size_table=table, motion=motion)
                self.assertEqual(loose_names(result), [])
                cut = next(c for c in result.cuts if c["name"] == H)
                self.assertEqual(cut["max"], 1.875)


class ParkStore(FakeStore):
    """A store whose marker is held at `HELD`, counting how often Fusion rebuilds the items after the outline face's
    step (`tail_builds`). A change or a recompute rebuilds them: at once with the marker held, or as the marker goes
    back there from an earlier place. `homes` false keeps the marker where a read left it."""

    HELD = 10

    def __init__(self, expressions, homes=True):
        super().__init__(expressions)
        self.at, self.tail_builds, self.homes = self.HELD, 0, homes

    def _rebuilt(self):
        if self.homes:
            self.tail_builds += 1
            self.at = self.HELD

    def set_expressions(self, expressions):
        self.exprs.update(expressions)
        self._rebuilt()
        return True

    def recompute(self):
        self.recomputes += 1
        self._rebuilt()
        return True

    def keep_marker(self):
        if self.at != self.HELD:
            self._rebuilt()
        return self.at == self.HELD

    def marker_holds(self):
        return self.at >= self.HELD


def face_reader(store):
    """A read that moves the marker to the face's step and back, as `read_faces` does, unless asked to `park` it."""
    def read(request):
        if request.get("faces"):
            store.at = 2
            if not request.get("park"):
                store.keep_marker()
        return tray_read({})
    return read


class ParkedFaceReadTest(unittest.TestCase):
    def run_rows(self, store):
        capture = tray_face()
        table = table_of(capture, [H, CUBE])
        probe = SizeProbe.start(capture, table, face_reader(store))
        store.tail_builds = 0  # the first read is not a try
        run = ProbeRun(FakePort(capture, store), tempfile.gettempdir(), probe)
        rows = probe.probe_rows([size(table, H, "count"), size(table, CUBE)])
        run.run_rows(rows)
        return rows

    def test_a_row_that_reads_a_face_rebuilds_the_later_items_once_with_its_values_and_once_with_them_back(self):
        store = ParkStore({p["name"]: p["expression"] for p in tray_face()["parameters"]["user"]})
        rows = self.run_rows(store)
        self.assertEqual(len(rows), 4)
        # The baseline, then per row the change and the change back; the face read adds none.
        self.assertEqual(store.tail_builds, 1 + 2 * len(rows))
        self.assertEqual(store.at, ParkStore.HELD)

    def test_a_marker_that_does_not_go_back_after_a_face_read_stops_the_probe(self):
        store = ParkStore({p["name"]: p["expression"] for p in tray_face()["parameters"]["user"]}, homes=False)
        with self.assertRaises(MarkerNotHeld):
            self.run_rows(store)


class ReadFacesTest(unittest.TestCase):
    def test_each_face_is_read_with_the_marker_before_its_step_and_the_marker_goes_back(self):
        timeline = FakeMarkerTimeline([Obj() for _ in range(4)], marker=3)
        top = with_outline(plane_face(10), [side((0, -1, 0)), side((1, 0, 0)), side((0, 1, 0)), side((-1, 0, 0))])
        design = Obj(timeline=timeline,
                     findEntityByToken=lambda token: [top] if timeline.markerPosition == 2 else [])
        found, unread = read_faces(design, None, {"2/face": {"token": "top", "before": 2},
                                                  "4/face": {"token": "top", "before": 4}})
        self.assertEqual(found["2/face"]["frame"]["origin"], [0, 0, 10])
        self.assertEqual(len(found["2/face"]["loops"][0]["curves"]), 4)
        self.assertEqual(list(unread), ["4/face"])
        self.assertEqual((timeline.markerPosition, timeline.visited), (3, [2, 3]))

    def test_a_read_asked_to_stay_leaves_the_marker_before_the_step(self):
        timeline = FakeMarkerTimeline([Obj() for _ in range(4)], marker=3)
        top = with_outline(plane_face(10), [side((0, -1, 0)), side((1, 0, 0)), side((0, 1, 0)), side((-1, 0, 0))])
        design = Obj(timeline=timeline, findEntityByToken=lambda token: [top])
        found, unread = read_faces(design, None, {"2/face": {"token": "top", "before": 2}}, stay=True)
        self.assertEqual((list(found), unread), (["2/face"], {}))
        self.assertEqual((timeline.markerPosition, timeline.visited), (2, [2]))

    def test_a_marker_that_does_not_go_back_leaves_every_face_unread_and_says_so(self):
        timeline = FakeMarkerTimeline([Obj() for _ in range(4)], marker=3, moves_allowed=1)
        top = with_outline(plane_face(10), [side((0, -1, 0)), side((1, 0, 0)), side((0, 1, 0)), side((-1, 0, 0))])
        design = Obj(timeline=timeline, findEntityByToken=lambda token: [top])
        found, unread = read_faces(design, None, {"2/face": {"token": "top", "before": 2}})
        self.assertEqual((found, sorted(unread)), ({}, ["2/face", MARKER_LOST]))


if __name__ == "__main__":
    unittest.main()
