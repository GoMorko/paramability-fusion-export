"""Writes a hand made OrcaSlicer 2.5 project with a Design tab recipe, to check the format in Orca.

The part: a rectangle sketch, an extrude, a through hole in the middle and a fillet on all edges. The variables
`width`, `depth` and `hole_d` drive the sketch width and height and the hole diameter. The plate gets a mesh of the
same block with its hole (without the fillet); Orca rebuilds the Design body from the recipe.
Usage:
python3 scripts/write_orca_sample.py [output .3mf] [--origin X,Y,Z] [--settings project_settings.json]

`--origin` is the Design tab's modeling origin, the bed centre of the printer (default 128,128,0, a 256 mm bed).
`--settings` writes those project settings instead of keeping the person's presets (see lib/orca_recipe/threemf.py).
"""
import argparse
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))

from lib.orca_recipe.enums import BooleanMode, FaceGroup, FeatureType, SketchShape  # noqa: E402
from lib.orca_recipe.feature import CadFeature  # noqa: E402
from lib.orca_recipe.recipe import Recipe, serialize  # noqa: E402
from lib.orca_recipe.sketch import SketchPlane  # noqa: E402
from lib.orca_recipe.threemf import MeshObject, write_3mf  # noqa: E402

WIDTH = 40.0
DEPTH = 30.0
HOLE_D = 8.0
THICKNESS = 10.0
FILLET = 1.0


def sample_recipe(origin):
    recipe = Recipe(variables={"width": "%g" % WIDTH, "depth": "%g" % DEPTH, "hole_d": "%g" % HOLE_D})
    recipe.modeling_origin = tuple(origin)
    plane = SketchPlane.xy(origin)
    sketch = recipe.add(CadFeature(type=FeatureType.SKETCH, name="Base sketch", shape=SketchShape.RECTANGLE,
                                   plane=plane, width=WIDTH, height=DEPTH))
    recipe.features[sketch].bind("width", "width")
    recipe.features[sketch].bind("height", "depth")
    recipe.add(CadFeature(type=FeatureType.EXTRUDE, name="Block", sketch_ref=sketch, distance=THICKNESS,
                          mode=BooleanMode.NEW))
    hole = recipe.add(CadFeature(type=FeatureType.HOLE, name="Through hole", plane=plane, hole_diameter=HOLE_D,
                                 hole_through=True, hole_x=0.0, hole_y=0.0))
    recipe.features[hole].bind("hole_diameter", "hole_d")
    recipe.add(CadFeature(type=FeatureType.FILLET, name="Round all edges", dressup_size=FILLET,
                          face_group=FaceGroup.ALL))
    return recipe


def block_with_hole(width, depth, height, hole_d, segments=48):
    """A closed mesh of a block centred on x, y = 0 from z = 0 to height, with a round hole through its middle."""
    hw, hd, r = width / 2.0, depth / 2.0, hole_d / 2.0
    angles = {round(2 * math.pi * i / segments, 12) for i in range(segments)}
    angles |= {round(math.atan2(sy * hd, sx * hw) % (2 * math.pi), 12) for sx in (-1, 1) for sy in (-1, 1)}
    angles = sorted(angles)
    vertices = []
    rings = {}
    for z in (0.0, height):
        inner, outer = [], []
        for a in angles:
            c, s = math.cos(a), math.sin(a)
            t = min(hw / abs(c) if abs(c) > 1e-12 else math.inf, hd / abs(s) if abs(s) > 1e-12 else math.inf)
            inner.append(len(vertices))
            vertices.append((r * c, r * s, z))
            outer.append(len(vertices))
            vertices.append((t * c, t * s, z))
        rings[z] = (inner, outer)
    (bi, bo), (ti, to) = rings[0.0], rings[height]
    triangles = []
    n = len(angles)
    for i in range(n):
        j = (i + 1) % n
        triangles += [(ti[i], to[i], to[j]), (ti[i], to[j], ti[j])]  # top, facing up
        triangles += [(bi[i], bo[j], bo[i]), (bi[i], bi[j], bo[j])]  # bottom, facing down
        triangles += [(bo[i], bo[j], to[j]), (bo[i], to[j], to[i])]  # outer wall, facing out
        triangles += [(bi[i], ti[i], ti[j]), (bi[i], ti[j], bi[j])]  # hole wall, facing the axis
    return vertices, triangles


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out", nargs="?", default="orca_design_sample.3mf")
    parser.add_argument("--origin", default="128,128,0")
    parser.add_argument("--settings", default=None)
    args = parser.parse_args(argv)
    origin = tuple(float(c) for c in args.origin.split(","))
    if len(origin) != 3:
        parser.error("--origin needs X,Y,Z")
    settings = None
    if args.settings:
        with open(args.settings, encoding="utf-8") as f:
            settings = json.load(f)

    recipe = sample_recipe(origin)
    vertices, triangles = block_with_hole(WIDTH, DEPTH, THICKNESS, HOLE_D)
    plate = MeshObject.placed("Design sample", vertices, triangles, origin)
    write_3mf(args.out, serialize(recipe), [plate], settings=settings)
    print("wrote %s: %d features, variables %s" % (args.out, len(recipe.features), recipe.variables))


if __name__ == "__main__":
    main()
