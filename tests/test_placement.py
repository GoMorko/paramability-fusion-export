import unittest

from tests import context  # noqa: F401
from tests.fakes import (FakeMatrix3D, FakeOccurrence, FakeSolid, apply_matrix, compose_matrices, turn_x, turn_z)

from lib.fusion_reader.placement import occurrence_path, read_placement

POINTS = [(0, 0, 0), (40, 0, 0), (0, 20, 0), (0, 0, 10)]


class _ByToken:
    """Fusion objects of one entity are equal; the fakes say so by their token."""

    def __eq__(self, other):
        return getattr(other, "entityToken", None) == self.entityToken

    def __hash__(self):
        return hash(self.entityToken)


class Comp(_ByToken):
    def __init__(self, token):
        self.entityToken = token


class Root(_ByToken):
    entityToken = "root"

    def __init__(self, uses=1):
        self.uses = uses

    def allOccurrencesByComponent(self, component):
        return type("Found", (), {"count": self.uses})()


def moved(place):
    """(proxy body, native body) for one occurrence at `place` (a matrix) directly under the root."""
    native = FakeSolid(POINTS, component=Comp("tray"))
    occurrence = FakeOccurrence("Tray:1", place)
    return FakeSolid([apply_matrix(place, p) for p in POINTS], context=occurrence, native=native,
                     component=native.parentComponent), occurrence


def nested(box_place, tray_place, transform2_is_to_root):
    """Tray inside Box. The proxy occurrence reports a transform2 to the root or only to its parent."""
    native = FakeSolid(POINTS, component=Comp("tray"))
    box = FakeOccurrence("Box:1", box_place)
    full = compose_matrices(box_place, tray_place)
    tray_native = FakeOccurrence("Tray:2", tray_place)
    tray = FakeOccurrence("Tray:2", full if transform2_is_to_root else tray_place, parent=box, native=tray_native)
    return FakeSolid([apply_matrix(full, p) for p in POINTS], context=tray, native=native, component=native.parentComponent)


class RootBodyTest(unittest.TestCase):
    def test_a_root_body_has_no_placement(self):
        body = FakeSolid(POINTS, component=Comp("root"))
        self.assertIsNone(read_placement(body, Root()))
        self.assertEqual(occurrence_path(body), [])

    def test_a_native_body_of_another_component_cannot_be_placed(self):
        placement = read_placement(FakeSolid(POINTS, component=Comp("tray")), Root())
        self.assertIn("error", placement)
        self.assertNotIn("frame", placement)


class FrameTest(unittest.TestCase):
    def test_a_moved_and_turned_occurrence_gives_its_own_frame(self):
        proxy, _ = moved(turn_z(90, origin=(100, 50, 0)))
        placement = read_placement(proxy, Root(uses=2))
        self.assertEqual(placement["source"], "transform2")
        self.assertEqual(placement["frame"], {"origin": [100, 50, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]})
        self.assertEqual((placement["path"], placement["checked_points"], placement["uses"], placement["linked"]),
                         ("Tray:1", 3, 2, False))
        self.assertNotIn("error", placement)

    def test_nested_with_a_transform_to_the_root_uses_the_direct_candidate(self):
        proxy = nested(turn_z(90, (100, 50, 0)), turn_x(90, (5, 0, 0)), transform2_is_to_root=True)
        placement = read_placement(proxy, Root())
        self.assertEqual((placement["source"], placement["path"]), ("transform2", "Box:1+Tray:2"))

    def test_nested_with_a_transform_to_the_parent_falls_to_the_path_product(self):
        box, tray = turn_z(90, (100, 50, 0)), turn_x(90, (5, 0, 0))
        placement = read_placement(nested(box, tray, transform2_is_to_root=False), Root())
        self.assertEqual(placement["source"], "path_transform2")
        full = compose_matrices(box, tray)
        for got, want in zip(placement["frame"]["origin"], full[0]):
            self.assertAlmostEqual(got, want, places=6)
        self.assertEqual(placement["frame"]["z"], [round(c, 9) + 0.0 for c in full[3]])

    def test_a_frame_that_misses_the_proxy_vertices_is_an_error_without_a_frame(self):
        proxy, occurrence = moved(turn_z(0, (100, 0, 0)))
        occurrence.transform2 = FakeMatrix3D(turn_z(0, (101, 0, 0)))
        placement = read_placement(proxy, Root())
        self.assertIn("does not match", placement["error"])
        self.assertNotIn("frame", placement)
        self.assertEqual((placement["path"], placement["uses"], placement["linked"]), ("Tray:1", 1, False))

    def test_a_scaled_or_mirrored_transform_is_refused_before_the_point_check(self):
        scaled = ((0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2))
        mirrored = ((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, 1))
        for matrix in (scaled, mirrored):
            proxy, _ = moved(matrix)
            self.assertIn("scaled or mirrored", read_placement(proxy, Root())["error"])

    def test_the_retired_transform_member_is_used_when_transform2_is_missing(self):
        proxy, occurrence = moved(turn_z(0, (30, 0, 0)))
        occurrence.transform, occurrence.transform2 = occurrence.transform2, None
        placement = read_placement(proxy, Root())
        self.assertEqual((placement["source"], placement["frame"]["origin"]), ("transform", [30, 0, 0]))

    def test_axis_noise_from_many_turns_is_still_a_rotation(self):
        noisy = ((100, 0, 0), (1 + 1e-8, 1e-8, 0), (-1e-8, 1, 0), (0, 0, 1))
        proxy, _ = moved(noisy)
        self.assertNotIn("error", read_placement(proxy, Root()))

    def test_a_body_with_many_vertices_gives_only_the_points_checked(self):
        many = POINTS + [(n, 2 * n, 3) for n in range(1, 400)]
        native = FakeSolid(many, component=Comp("tray"))
        place = turn_z(90, (100, 50, 0))
        proxy = FakeSolid([apply_matrix(place, p) for p in many], context=FakeOccurrence("Tray:1", place),
                          native=native, component=native.parentComponent)
        fetched = []
        for each in (native, proxy):
            item = each.vertices.item
            each.vertices.item = lambda i, item=item: fetched.append(i) or item(i)
        self.assertEqual(read_placement(proxy, Root())["checked_points"], 3)
        self.assertEqual(fetched, [0, 1, 2, 0, 1, 2])

    def test_few_vertices_add_face_points(self):
        place = turn_z(90, (10, 0, 0))
        native = FakeSolid([(0, 0, 0)], faces=[(5, 5, 5), (1, 2, 3)], component=Comp("c"))
        occurrence = FakeOccurrence("C:1", place)
        proxy = FakeSolid([apply_matrix(place, (0, 0, 0))], faces=[apply_matrix(place, p) for p in ((5, 5, 5), (1, 2, 3))],
                          context=occurrence, native=native)
        self.assertEqual(read_placement(proxy, Root())["checked_points"], 3)

    def test_linked_component_on_any_occurrence_of_the_path(self):
        proxy = nested(turn_z(0, (1, 0, 0)), turn_z(0), True)
        proxy.assemblyContext.assemblyContext.isReferencedComponent = True
        self.assertTrue(read_placement(proxy, Root())["linked"])


if __name__ == "__main__":
    unittest.main()
