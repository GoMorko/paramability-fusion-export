"""Triangle meshes as plain lists: STL text and bytes read into vertices and triangles, vertices shared at seams,
boxes and volumes. Vertices are (x, y, z) tuples, triangles (a, b, c) vertex indices."""
import math
import re
import struct

# Vertices closer than this (in the mesh's unit) are one vertex.
WELD_TOL = 1e-6

_ASCII_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


class MeshError(ValueError):
    """The bytes are not a mesh this module can read."""


def parse_stl(data):
    """`(vertices, triangles)` of an STL file's bytes, binary or text, with shared vertices (`weld`)."""
    data = bytes(data)
    corners = _binary_corners(data)
    if corners is None:
        corners = _ascii_corners(data)
    if not corners:
        raise MeshError("The STL file holds no triangles.")
    return weld(corners)


def _binary_corners(data):
    """The corner triples of a binary STL, or None when the bytes are not one."""
    if len(data) < 84:
        return None
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        return None
    out = []
    for i in range(count):
        values = struct.unpack_from("<12f", data, 84 + 50 * i)
        out.append((values[3:6], values[6:9], values[9:12]))
    return out


def _ascii_corners(data):
    if not data.lstrip().lower().startswith(b"solid"):
        raise MeshError("The file is not an STL file.")
    points = []
    for match in _ASCII_VERTEX.finditer(data):
        try:
            points.append(tuple(float(v) for v in match.groups()))
        except ValueError:
            raise MeshError("A vertex of the STL file is not a number.")
    if len(points) % 3:
        raise MeshError("The STL file has a triangle with a missing corner.")
    return [tuple(points[i:i + 3]) for i in range(0, len(points), 3)]


def weld(corners, tol=WELD_TOL):
    """`(vertices, triangles)` from corner triples: corners within `tol` share a vertex, and triangles that lose a
    corner that way (no area) are dropped."""
    vertices, triangles, index = [], [], {}
    scale = 1.0 / tol
    for tri in corners:
        ids = []
        for p in tri:
            p = tuple(float(c) for c in p)
            if not all(math.isfinite(c) for c in p):
                raise MeshError("A vertex of the mesh is not a finite number.")
            key = tuple(int(round(c * scale)) for c in p)
            if key not in index:
                index[key] = len(vertices)
                vertices.append(p)
            ids.append(index[key])
        if len(set(ids)) == 3:
            triangles.append(tuple(ids))
    return vertices, triangles


def from_arrays(coordinates, indices, factor=1.0):
    """`(vertices, triangles)` from flat lists, x y z per node and three node indices per triangle (Fusion's
    `TriangleMesh.nodeCoordinatesAsDouble` and `nodeIndices`), each coordinate times `factor`, vertices shared."""
    if len(coordinates) % 3 or len(indices) % 3:
        raise MeshError("The mesh lists are not whole points and triangles.")
    nodes = [tuple(coordinates[i + k] * factor for k in range(3)) for i in range(0, len(coordinates), 3)]
    try:
        corners = [tuple(nodes[indices[i + k]] for k in range(3)) for i in range(0, len(indices), 3)]
    except IndexError:
        raise MeshError("A triangle names a point the mesh does not have.")
    return weld(corners)


def bounds(vertices):
    """`{min, max}` of the vertices, or None when there are none."""
    if not vertices:
        return None
    return {"min": [min(v[i] for v in vertices) for i in range(3)], "max": [max(v[i] for v in vertices) for i in range(3)]}


def volume(vertices, triangles):
    """The volume a closed, outward facing mesh holds (the divergence sum)."""
    total = 0.0
    for a, b, c in triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = vertices[a], vertices[b], vertices[c]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6.0


def box_mesh(box):
    """A closed mesh of a box `{min, max}`, faces outward."""
    lo, hi = box["min"], box["max"]
    vertices = [(x, y, z) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    triangles = []
    for a, b, c, d in quads:
        triangles += [(a, b, c), (a, c, d)]
    return vertices, triangles


def moved(vertices, move_point):
    """The vertices through a function of a point."""
    return [tuple(move_point(v)) for v in vertices]
