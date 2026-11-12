"""The per state read of measured references: found by token, shown through their occurrence as it sits now, brought
into the target's coordinates as the target sits now."""
import unittest

from tests import context  # noqa: F401
from tests.fakes import FakeMatrix3D, FakeOccurrence, FakeSolid, apply_matrix, turn_z
from tests.test_capture_reader import Coll, Obj, P

from lib.fusion_reader import placement, probe_refs
from lib.fusion_reader.probe_state import read_state
from lib.fusion_reader.read_geometry import ReadContext

TRAY_PLACE = turn_z(90, (100, 50, 0))
LID_PLACE = turn_z(90, (110, 50, 32))
CORNERS = [(0, 0, 0), (40, 0, 0), (0, 20, 0), (0, 0, 10)]


def turned(place, direction):
    moved = apply_matrix(place, direction)
    return tuple(moved[i] - place[0][i] for i in range(3))


def vector(v):
    return Obj(x=v[0], y=v[1], z=v[2])


def plane_geometry(origin, normal):
    return Obj("core::Plane", origin=P(*origin), normal=vector(normal))


class Assembly:
    """A tray (the target) and a lid, both placed in the root. Their places can be changed to mimic a size."""

    def __init__(self):
        self.tray = Obj(entityToken="tray", name="Tray")
        self.lid = Obj(entityToken="lid", name="Lid")
        self.native = FakeSolid(CORNERS, component=self.tray, token="t1")
        self.native.createForAssemblyContext = self.show_tray
        self.tray_at = FakeOccurrence("Tray:1", TRAY_PLACE, component=self.tray)
        self.lid_at = FakeOccurrence("Lid:1", LID_PLACE, component=self.lid)
        self.entities = {"t1": [self.native]}
        self.root = Obj(entityToken="root", name="Root", modelParameters=Coll([]), bRepBodies=Coll([]),
                        allOccurrencesByComponent=lambda c: Coll([o for o in (self.tray_at, self.lid_at)
                                                                  if o.component.entityToken == c.entityToken]))
        self.design = Obj(rootComponent=self.root, findEntityByToken=lambda token: self.entities.get(token, []))
        self.picked = self.show_tray(self.tray_at)

    def show_tray(self, occurrence):
        place = occurrence.transform2.matrix
        return FakeSolid([apply_matrix(place, p) for p in CORNERS], context=occurrence, native=self.native,
                         component=self.tray, token="t1:path")

    def context(self):
        return ReadContext(self.design, self.picked)

    def move(self, occurrence, place):
        occurrence.transform2 = FakeMatrix3D(place)

    def add_plane(self, token="cp1", origin=(0, 0, 4), normal=(1, 0, 0)):
        native = Obj("fusion::ConstructionPlane", entityToken=token, parentComponent=self.lid,
                     geometry=plane_geometry(origin, normal))

        def show(occurrence):
            place = occurrence.transform2.matrix
            return Obj("fusion::ConstructionPlane", entityToken=token + ":path", assemblyContext=occurrence,
                       nativeObject=native, geometry=plane_geometry(apply_matrix(place, origin), turned(place, normal)))
        native.createForAssemblyContext = show
        self.entities[token] = [native]
        return native

    def add_axis(self, token="ax1", origin=(10, 0, 0), direction=(0, 0, 1)):
        def line(o, d):
            return Obj("core::InfiniteLine3D", origin=P(*o), direction=vector(d))
        native = Obj("fusion::ConstructionAxis", entityToken=token, parentComponent=self.lid,
                     geometry=line(origin, direction))

        def show(occurrence):
            place = occurrence.transform2.matrix
            return Obj("fusion::ConstructionAxis", entityToken=token + ":path", assemblyContext=occurrence,
                       nativeObject=native, geometry=line(apply_matrix(place, origin), turned(place, direction)))
        native.createForAssemblyContext = show
        self.entities[token] = [native]
        return native

    def add_point(self, token="pt1", at=(1, 2, 3)):
        native = Obj("fusion::SketchPoint", entityToken=token, worldGeometry=P(*at),
                     parentSketch=Obj(entityToken="sk", parentComponent=self.lid))

        def show(occurrence):
            return Obj("fusion::SketchPoint", entityToken=token + ":path", assemblyContext=occurrence,
                       nativeObject=native, worldGeometry=P(*apply_matrix(occurrence.transform2.matrix, at)))
        native.createForAssemblyContext = show
        self.entities[token] = [native]
        return native


def hint(token, shape, path="Lid:1"):
    return {"token": token, "path": path, "shape": shape}


def read(assembly, wanted):
    return probe_refs.read_refs(assembly.design, assembly.context(), wanted)


class ReadRefsTest(unittest.TestCase):
    def setUp(self):
        self.a = Assembly()
        self.a.add_plane()

    def at_capture(self):
        """The reference as the capture reader records it, in the target's coordinates."""
        proxy = self.a.entities["cp1"][0].createForAssemblyContext(self.a.lid_at)
        return placement.ref_record(proxy, self.a.context(), "plane")

    def test_the_first_read_gives_the_place_the_capture_recorded(self):
        found, unread = read(self.a, {"3.plane": hint("cp1", "plane")})
        record = self.at_capture()
        self.assertEqual(unread, {})
        self.assertEqual(found["3.plane"], {"point": record["point"], "normal": record["normal"]})

    def test_a_lid_that_moves_in_the_assembly_moves_the_plane_in_the_target_frame(self):
        before = read(self.a, {"3.plane": hint("cp1", "plane")})[0]["3.plane"]
        self.a.move(self.a.lid_at, turn_z(90, (120, 50, 32)))
        after = read(self.a, {"3.plane": hint("cp1", "plane")})[0]["3.plane"]
        # The tray is turned 90 degrees, so a step of +10 along the assembly's x is -10 along the tray's y.
        self.assertEqual([round(b - a, 6) for a, b in zip(before["point"], after["point"])], [0, -10, 0])
        self.assertEqual(after["normal"], before["normal"])

    def test_a_tray_that_moves_with_the_lid_leaves_the_plane_where_it_is(self):
        before = read(self.a, {"3.plane": hint("cp1", "plane")})[0]
        self.a.move(self.a.lid_at, turn_z(90, (120, 50, 32)))
        self.a.move(self.a.tray_at, turn_z(90, (110, 50, 0)))
        self.assertEqual(read(self.a, {"3.plane": hint("cp1", "plane")})[0], before)

    def test_a_plane_of_the_root_is_only_brought_into_the_target(self):
        plane = Obj("fusion::ConstructionPlane", entityToken="rp", parentComponent=self.a.root,
                    geometry=plane_geometry((0, 0, 7), (0, 0, 1)))
        self.a.entities["rp"] = [plane]
        found, _ = read(self.a, {"1.plane": hint("rp", "plane", path="")})
        # The tray is turned 90 degrees at (100, 50, 0): the root's origin is at (-50, 100) in the tray's frame.
        self.assertEqual(found["1.plane"], {"point": [-50.0, 100.0, 7.0], "normal": [0.0, 0.0, 1.0]})

    def test_a_face_of_the_part_itself_is_read_in_the_part_s_own_coordinates(self):
        face = Obj("fusion::BRepFace", entityToken="f1", geometry=plane_geometry((5, 5, 10), (0, 0, 1)))
        self.a.entities["f1"] = [face]
        found, _ = read(self.a, {"2.side_one": dict(hint("f1", "plane", path=""), own=True)})
        self.assertEqual(found["2.side_one"], {"point": [5.0, 5.0, 10.0], "normal": [0.0, 0.0, 1.0]})

    def test_an_axis_a_direction_and_a_point_are_read_by_their_shape(self):
        self.a.add_axis()
        self.a.add_point()
        found, unread = read(self.a, {"1.axis": hint("ax1", "axis"), "2.direction_one": hint("ax1", "direction"),
                                      "3.positions.0": hint("pt1", "point")})
        self.assertEqual(unread, {})
        self.assertEqual(set(found["1.axis"]), {"point", "dir"})
        self.assertEqual(set(found["2.direction_one"]), {"dir"})
        self.assertEqual(found["2.direction_one"]["dir"], found["1.axis"]["dir"])
        self.assertEqual(set(found["3.positions.0"]), {"point"})

    def test_a_reference_that_cannot_be_read_is_left_out_with_a_reason(self):
        self.a.add_axis()
        self.a.entities["ax1"][0].createForAssemblyContext = lambda occ: None
        ghost = Obj("fusion::ConstructionPlane", entityToken="gp", parentComponent=Obj(entityToken="ghost"),
                    geometry=plane_geometry((0, 0, 0), (0, 0, 1)))
        self.a.entities["gp"] = [ghost]
        wanted = {"1.plane": hint("gone", "plane"), "2.plane": hint("gp", "plane", path="Ghost:1"),
                  "3.axis": hint("ax1", "axis"), "4.plane": hint("cp1", "axis"), "5.plane": hint("cp1", "plane")}
        found, unread = read(self.a, wanted)
        self.assertEqual(list(found), ["5.plane"])
        self.assertEqual(unread, {"1.plane": probe_refs.NOT_FOUND, "2.plane": probe_refs.NO_OCCURRENCE,
                                  "3.axis": probe_refs.NO_PROXY, "4.plane": probe_refs.NO_GEOMETRY})

    def test_when_the_target_place_cannot_be_read_no_reference_is_read(self):
        self.a.native.createForAssemblyContext = lambda occ: None
        found, unread = read(self.a, {"1.plane": hint("cp1", "plane")})
        self.assertEqual((found, unread), ({}, {"1.plane": probe_refs.NO_TARGET_PLACE}))

class ReadStateTest(unittest.TestCase):
    def test_the_state_holds_the_references_and_the_reasons_for_the_ones_left_out(self):
        a = Assembly()
        a.add_plane()
        state = read_state(a.design, {"refs": {"3.plane": hint("cp1", "plane"), "4.plane": hint("gone", "plane")}},
                           a.context())
        self.assertEqual(list(state["refs"]), ["3.plane"])
        self.assertEqual(state["unread"], {"4.plane": probe_refs.NOT_FOUND})

    def test_reading_changes_nothing_in_the_design(self):
        a = Assembly()
        a.add_plane()
        read_state(a.design, {"refs": {"3.plane": hint("cp1", "plane")}}, a.context())
        self.assertEqual((a.tray_at.transform2.matrix, a.lid_at.transform2.matrix), (TRAY_PLACE, LID_PLACE))


if __name__ == "__main__":
    unittest.main()
