"""STL bytes and Fusion's mesh lists read into one shared vertex list (`geometry.mesh`)."""
import struct
import unittest

from tests import context  # noqa: F401

from lib.geometry import mesh

BOX = {"min": [0.0, 0.0, 0.0], "max": [40.0, 20.0, 10.0]}


def corners_of(vertices, triangles):
    return [tuple(vertices[i] for i in t) for t in triangles]


def binary_stl(corners):
    out = bytearray(b"\0" * 80) + struct.pack("<I", len(corners))
    for tri in corners:
        out += struct.pack("<3f", 0, 0, 0)
        for p in tri:
            out += struct.pack("<3f", *p)
        out += b"\0\0"
    return bytes(out)


def ascii_stl(corners):
    lines = ["solid part"]
    for tri in corners:
        lines += ["  facet normal 0 0 0", "    outer loop"]
        lines += ["      vertex %r %r %r" % p for p in tri]
        lines += ["    endloop", "  endfacet"]
    return ("\n".join(lines + ["endsolid part"]) + "\n").encode("ascii")


class MeshTest(unittest.TestCase):
    def test_a_box_mesh_is_closed_and_faces_out(self):
        vertices, triangles = mesh.box_mesh(BOX)
        self.assertEqual((len(vertices), len(triangles)), (8, 12))
        self.assertAlmostEqual(mesh.volume(vertices, triangles), 8000.0)
        self.assertEqual(mesh.bounds(vertices), BOX)

    def test_binary_and_text_stl_read_to_the_same_shared_mesh(self):
        corners = corners_of(*mesh.box_mesh(BOX))
        for data in (binary_stl(corners), ascii_stl(corners)):
            vertices, triangles = mesh.parse_stl(data)
            self.assertEqual((len(vertices), len(triangles)), (8, 12))
            self.assertAlmostEqual(mesh.volume(vertices, triangles), 8000.0, places=3)

    def test_a_binary_stl_whose_header_starts_with_solid_is_still_binary(self):
        corners = corners_of(*mesh.box_mesh(BOX))
        data = b"solid made by a tool" + binary_stl(corners)[20:]
        self.assertEqual(len(mesh.parse_stl(data)[1]), 12)

    def test_fusion_mesh_lists_in_cm_become_mm_with_seams_shared(self):
        coordinates = [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]
        vertices, triangles = mesh.from_arrays(coordinates, [0, 1, 2, 3, 4, 5], 10.0)
        self.assertEqual(len(vertices), 4)
        self.assertEqual(mesh.bounds(vertices), {"min": [0, 0, 0], "max": [10.0, 10.0, 0]})

    def test_a_triangle_without_area_is_dropped(self):
        vertices, triangles = mesh.weld([((0, 0, 0), (1, 0, 0), (1, 0, 0)), ((0, 0, 0), (1, 0, 0), (0, 1, 0))])
        self.assertEqual(len(triangles), 1)

    def test_bytes_that_are_no_mesh_are_refused(self):
        for data in (b"", b"hello", b"solid x\nendsolid x\n"):
            with self.assertRaises(mesh.MeshError):
                mesh.parse_stl(data)
        with self.assertRaises(mesh.MeshError):
            mesh.from_arrays([0, 0, 0], [0, 1, 2])


def _adsk_modules():
    """`adsk`, `adsk.core` and `adsk.fusion` for the reader module, only the names it reads, to patch into
    `sys.modules` for one test (other tests read the absence of `adsk.fusion`)."""
    import types
    adsk, core, fusion = (types.ModuleType(n) for n in ("adsk", "adsk.core", "adsk.fusion"))
    adsk.core, adsk.fusion = core, fusion
    fusion.TriangleMeshQualityOptions = types.SimpleNamespace(HighQualityTriangleMesh=1)
    return {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion}


class _Point:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Box:
    def __init__(self, lo, hi):
        self.minPoint, self.maxPoint = _Point(*lo), _Point(*hi)


class _Matrix:
    def __init__(self, offset):
        self.offset = offset

    def getCell(self, row, column):
        return self.offset[row] if column == 3 else (1.0 if row == column else 0.0)


class _Body:
    """A body of a component moved 5 cm along x: Fusion's mesh comes at the component's origin, its box in the
    root."""

    def __init__(self, placed_mesh=False):
        corners = corners_of(*mesh.box_mesh({"min": [0, 0, 0], "max": [4, 2, 1]}))
        offset = 5.0 if placed_mesh else 0.0
        nodes = [c + (offset if i % 3 == 0 else 0.0) for tri in corners for p in tri for i, c in enumerate(p)]
        found = type("Mesh", (), {"nodeCoordinatesAsDouble": nodes, "nodeIndices": list(range(len(nodes) // 3))})()
        calculator = type("Calc", (), {"setQuality": lambda self, q: None, "calculate": lambda self: found})()
        self.meshManager = type("Manager", (), {"createMeshCalculator": lambda self: calculator})()
        self.boundingBox = _Box((5, 0, 0), (9, 2, 1))
        self.assemblyContext = type("Occurrence", (), {"transform2": _Matrix((5.0, 0.0, 0.0))})()


class BodyMeshTest(unittest.TestCase):
    def test_a_mesh_at_the_component_origin_is_moved_into_the_root_in_mm(self):
        import importlib
        import sys
        from unittest import mock
        with mock.patch.dict(sys.modules, _adsk_modules()):
            sys.modules.pop("lib.fusion_reader.body_mesh", None)
            read_body_mesh = importlib.import_module("lib.fusion_reader.body_mesh").read_body_mesh
            for placed in (False, True):
                vertices, triangles = read_body_mesh(None, _Body(placed))
                self.assertEqual(mesh.bounds(vertices), {"min": [50.0, 0.0, 0.0], "max": [90.0, 20.0, 10.0]})
                self.assertEqual(len(triangles), 12)


if __name__ == "__main__":
    unittest.main()
