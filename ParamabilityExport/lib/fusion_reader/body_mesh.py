"""A triangle mesh of one body as the design is now, in root coordinates and mm, for the Orca output.

Fusion's mesh calculator gives the mesh in cm. For a body inside a component it is checked against the box of the
picked body (root coordinates); when it lies at the component's own origin instead, the occurrence's transform moves
it. When the calculator gives nothing that fits, the body is written as an STL file and read back (`geometry.mesh`).
"""
import os
import tempfile

import adsk.core
import adsk.fusion

from ..design_edit.errors import StepExportError
from ..geometry import mesh as meshes
from ..package.units import cm_to_mm

# How far (mm) the mesh box may be from the body's box: a mesh of a curved face lies a little inside it.
BOX_TOLERANCE_MM = 0.2


def _box_mm(body):
    box = body.boundingBox
    return {"min": [cm_to_mm(box.minPoint.x), cm_to_mm(box.minPoint.y), cm_to_mm(box.minPoint.z)],
            "max": [cm_to_mm(box.maxPoint.x), cm_to_mm(box.maxPoint.y), cm_to_mm(box.maxPoint.z)]}


def _fits(vertices, box):
    found = meshes.bounds(vertices)
    if found is None:
        return False
    return max(abs(found[k][i] - box[k][i]) for k in ("min", "max") for i in range(3)) <= BOX_TOLERANCE_MM


def _calculated(body):
    calculator = body.meshManager.createMeshCalculator()
    calculator.setQuality(adsk.fusion.TriangleMeshQualityOptions.HighQualityTriangleMesh)
    found = calculator.calculate()
    return meshes.from_arrays(list(found.nodeCoordinatesAsDouble), list(found.nodeIndices), cm_to_mm(1.0))


def _placed(vertices, body):
    """The vertices through the transform of the occurrence the body is seen through, or None without one."""
    context = getattr(body, "assemblyContext", None)
    if context is None:
        return None
    matrix = context.transform2
    rows = [[matrix.getCell(i, j) for j in range(4)] for i in range(3)]
    return [tuple(sum(rows[i][k] * v[k] for k in range(3)) + cm_to_mm(rows[i][3]) for i in range(3))
            for v in vertices]


def _from_stl(design, body):
    with tempfile.TemporaryDirectory(prefix="paramability_mesh_", ignore_cleanup_errors=True) as tmp:
        path = os.path.join(tmp, "part.stl")
        manager = design.exportManager
        options = manager.createSTLExportOptions(body, path)
        options.isBinaryFormat = True
        try:
            options.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
        except Exception:
            pass
        try:
            options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        except Exception:
            pass
        if not manager.execute(options):
            return None
        with open(path, "rb") as f:
            return meshes.parse_stl(f.read())


def read_body_mesh(design, body):
    """`(vertices, triangles)` of the picked body (an occurrence proxy for a body in a component), root coordinates,
    mm. Raises StepExportError when Fusion gives no mesh that fits the body's box."""
    try:
        box = _box_mm(body)
    except Exception:
        box = None
    tries = []
    try:
        vertices, triangles = _calculated(body)
        tries.append((vertices, triangles))
        placed = _placed(vertices, body)
        if placed is not None:
            tries.append((placed, triangles))
    except Exception:
        pass
    for vertices, triangles in tries:
        if triangles and (box is None or _fits(vertices, box)):
            return vertices, triangles
    try:
        found = _from_stl(design, body)
    except Exception:
        found = None
    if found is not None:
        vertices, triangles = found
        for factor in (1.0, 10.0, 25.4, 0.1):
            scaled = [tuple(c * factor for c in v) for v in vertices]
            if triangles and (box is None or _fits(scaled, box)):
                return scaled, triangles
    raise StepExportError("Fusion could not give the shape of the part as a mesh.")
