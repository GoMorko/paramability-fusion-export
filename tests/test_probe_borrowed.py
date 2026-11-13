"""The size probe with a step that uses a sketch of another component (a borrowed sketch)."""
import unittest

from tests import context  # noqa: F401
from tests.probe_helpers import IDENT, capture, extrude, loop, profile, rect_curves, sketch_state, table, size
from tests.test_probe_flow import UNITS, Fusion, number, run
from tests.test_probe_motion import CAPTURE, MODEL, PARAMS, TICKED, W, read_at

from lib.export_plan.probe_flow import SizeProbe, borrowed_sketches, covers_a_sketch, probe_view
from lib.sketch_values.motion import Affine
from lib.translator.sketch import borrowed

LID_FRAME = {"origin": [0, 0, 20], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
PLACE = {"path": "BoxLid:1", "frame": LID_FRAME, "source": "transform2", "checked_points": 3}


def rail(w=32):
    """The borrowed sketch LidRail of BoxLid: a rectangle as wide as the box, 4 mm deep."""
    curves = rect_curves("rl", 0, 0, w, 4)
    return dict(profile("LidRail", "skL", [loop(curves)], frame=LID_FRAME), foreign=True, native_frame=IDENT,
                component={"token": "cLid", "name": "BoxLid"}, placement=PLACE, sketch_params=[])


BORROWING = capture(*CAPTURE["items"], extrude(8, rail()))


class Lid(Fusion):
    """A design that also draws the borrowed sketch. It follows the box width unless `fixed_width`; `shift(sizes)` is
    how far the lid component sits from where it was captured; `edit(out, sizes)` changes a read."""

    def __init__(self, fixed_width=False, shift=None, edit=None):
        super().__init__()
        self.fixed_width, self.shift, self.edit = fixed_width, shift, edit

    def read(self, request):
        self.requests.append(request)
        e = self.store.exprs
        sizes = dict(count=number(e["count"]), cube=number(e["cube"]), off=number(e["off"]),
                     height=number(e["height"]))
        out = read_at(**sizes)
        w = 32 if self.fixed_width else sizes["count"] * sizes["cube"] + 2
        frame = dict(LID_FRAME, origin=[self.shift(sizes) if self.shift else 0.0, 0, 20])
        out["sketches"].update(sketch_state("skL", [{"loops": [loop(rect_curves("rl", 0, 0, w, 4))]}], frame=frame))
        if self.edit:
            self.edit(out, sizes)
        return out


class Rig(unittest.TestCase):
    def setUp(self):
        self.table = table(PARAMS, TICKED, MODEL)
        self.sizes = [size(self.table, n, UNITS[n]) for n in TICKED]

    def probe(self, fusion):
        probe = SizeProbe.start(BORROWING, self.table, fusion.read)
        self.assertIsNotNone(probe)
        run(fusion, probe, self.sizes)
        return probe, probe.finish(probe.read_now(), {"height": "Box height"})


class ViewTests(unittest.TestCase):
    def test_a_borrowed_profile_is_seen_as_an_own_one_with_the_component_in_its_name(self):
        view = probe_view(BORROWING)
        seen = view["items"][-1]["data"]["profiles"][0]
        self.assertEqual(seen["sketch"], "LidRail of BoxLid")
        self.assertFalse(set(seen) & set(borrowed.BORROWED_KEYS))
        self.assertTrue(BORROWING["items"][-1]["data"]["profiles"][0]["foreign"])

    def test_a_profile_without_a_readable_place_is_not_borrowed(self):
        bad = rail()
        bad["placement"] = {"path": "BoxLid:1", "error": "No points."}
        self.assertEqual(borrowed_sketches(capture(extrude(8, bad))), {})
        self.assertFalse(covers_a_sketch(capture(extrude(8, bad))))

    def test_hints_name_the_occurrence_path(self):
        self.assertEqual(borrowed_sketches(BORROWING),
                         {"skL": {"path": "BoxLid:1", "sketch": "LidRail", "component": "BoxLid"}})


class BorrowedProbeTest(Rig):
    def test_the_request_reads_the_borrowed_sketch_with_its_path(self):
        fusion = Lid()
        probe = SizeProbe.start(BORROWING, self.table, fusion.read)
        self.assertIn("skL", probe.request["sketches"])
        self.assertEqual(probe.request["borrowed"], {"skL": {"path": "BoxLid:1"}})
        self.assertEqual(fusion.requests[0]["borrowed"], {"skL": {"path": "BoxLid:1"}})

    def test_a_borrowed_sketch_that_follows_the_width_gets_a_formula(self):
        probe, fixed = self.probe(Lid())
        self.assertEqual(fixed, [])
        self.assertEqual(probe.watch, {})
        value = probe.motion.get("8/p0/l0/width")
        self.assertIsInstance(value, Affine)
        self.assertEqual(value.terms, {W: 1.0})

    def test_a_lid_that_moves_with_a_size_moves_the_values_in_the_sketch_not_the_plane(self):
        probe, _ = self.probe(Lid(shift=lambda s: (s["off"] - 5) / 2))
        self.assertEqual(probe.motion.get("8/p0/l0/center.0").terms.keys() - {W}, {"off"})
        self.assertIsNone(probe.motion.get("8/p0/plane"))

    def test_a_borrowed_sketch_that_is_unread_or_turned_at_a_state_is_stuck_for_the_sizes_of_that_state(self):
        def turn(out, sizes):
            if sizes["off"] != 5:
                out["sketches"]["skL"]["frame"] = dict(LID_FRAME, z=[1, 0, 0])
        for cause, size_name, edit in (
                ("unread", "height", lambda out, s: out["sketches"].pop("skL") if s["height"] != 20 else None),
                ("turns", "off", turn)):
            with self.subTest(cause):
                probe, _ = self.probe(Lid(edit=edit))
                stuck = probe.motion.get("8/p0/l0/width")
                self.assertEqual((stuck.cause, stuck.sketch), (cause, "LidRail of BoxLid"))
                self.assertIn(size_name, stuck.movers)


class WatchedSketchTest(Rig):
    """A borrowed sketch that does not read back as captured is not fitted; the sizes that change it are loose."""

    @staticmethod
    def off_origin(out, sizes):
        out["sketches"]["skL"]["frame"] = dict(LID_FRAME, origin=[0.5, 0, sizes["height"]])

    def test_sizes_that_change_a_watched_sketch_are_loose_with_a_plain_reason(self):
        probe, fixed = self.probe(Lid(fixed_width=True, edit=self.off_origin))
        self.assertEqual(set(probe.watch), {"skL"})
        self.assertEqual([f["param"] for f in fixed], ["height"])
        self.assertIn("Box height may give unexpected results: it changes the sketch LidRail of BoxLid", fixed[0]["reason"])
        self.assertIsNone(probe.motion.get("8/p0/l0/width"))

    def test_a_watched_sketch_that_does_not_change_fixes_nothing(self):
        probe, fixed = self.probe(Lid(fixed_width=True,
                                      edit=lambda out, s: out["sketches"]["skL"].update(frame=dict(LID_FRAME, origin=[0.5, 0, 20]))))
        self.assertEqual((set(probe.watch), fixed), ({"skL"}, []))

    def test_a_watched_sketch_that_is_gone_at_a_row_makes_that_size_loose(self):
        def gone(out, sizes):
            out["sketches"]["skL"]["frame"] = dict(LID_FRAME, origin=[0.5, 0, 20])
            if sizes["cube"] != 10:
                out["sketches"].pop("skL")
        _, fixed = self.probe(Lid(fixed_width=True, edit=gone))
        self.assertEqual([f["param"] for f in fixed], ["cube"])
