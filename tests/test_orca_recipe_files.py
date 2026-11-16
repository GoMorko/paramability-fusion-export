"""Whole Orca recipes and the 3MF around them: layout, round trips, Orca's own sample recipes, the sample script.

The byte check over Orca's sample recipes (`tests/data/cad_recipe_v3.bin`, v4, v5 in the OrcaSlicer repo) reads
them from the folder in ORCA_RECIPE_SAMPLES and skips when it is unset. The samples are not kept in this repo.
"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tests import context  # noqa: F401

from lib.orca_recipe.cereal import RecipeFormatError
from lib.orca_recipe.enums import BooleanMode, FaceGroup, FeatureType
from lib.orca_recipe.feature import FIELD_COUNT_V4, CadFeature
from lib.orca_recipe.recipe import Recipe, deserialize, serialize
from lib.orca_recipe.sketch import SketchEntity, SketchPlane
from lib.orca_recipe.threemf import (MODEL_ENTRY, RECIPE_ENTRY, SETTINGS_ENTRY, MeshObject, read_recipe_bytes,
                                    write_3mf)

SAMPLES = os.environ.get("ORCA_RECIPE_SAMPLES", "")
ROOT = os.path.dirname(context.ADDIN_DIR)


def small_recipe():
    recipe = Recipe(variables={"w": "40", "d": "w / 2"})
    plane = SketchPlane.xy((128.0, 128.0, 0.0))
    s = recipe.add(CadFeature(type=FeatureType.SKETCH, name="S", plane=plane, width=40.0, height=20.0,
                              expr={"width": "w", "height": "d"}))
    recipe.add(CadFeature(type=FeatureType.EXTRUDE, name="E", sketch_ref=s, distance=5.0))
    recipe.add(CadFeature(type=FeatureType.SKETCH, name="Lines", plane=plane,
                          entities=[SketchEntity(p1=(10.0, 0.0)), SketchEntity(p0=(10.0, 0.0), p1=(0.0, 5.0))]))
    recipe.add(CadFeature(type=FeatureType.FILLET, name="F", dressup_size=0.5, face_group=FaceGroup.TOP))
    recipe.modeling_origin = (128.0, 128.0, 0.0)
    recipe.body_names = {0: "Plate"}
    recipe.body_colours = {0: (1.0, 0.5, 0.25, 1.0)}
    recipe.auto_close_loops = False
    return recipe


def same(a, b):
    return (a.version, a.features, a.variables, a.body_names, a.modeling_origin, a.body_colours,
            a.auto_close_loops, a.has_extras) == (b.version, b.features, b.variables, b.body_names,
                                                  b.modeling_origin, b.body_colours, b.auto_close_loops, b.has_extras)


class LayoutTest(unittest.TestCase):
    def test_framed_layout(self):
        recipe = small_recipe()
        data = serialize(recipe)
        version, count, first_len = struct.unpack_from("<III", data)
        self.assertEqual((version, count), (6, 4))
        pos = 8
        for _ in range(count):
            pos += 4 + struct.unpack_from("<I", data, pos)[0]
        blocks = []
        while pos < len(data):
            length = struct.unpack_from("<I", data, pos)[0]
            blocks.append(data[pos + 4:pos + 4 + length])
            pos += 4 + length
        self.assertEqual(pos, len(data))
        self.assertEqual(len(blocks), 3)
        variables, names, extras = blocks
        self.assertEqual(struct.unpack_from("<Q", variables)[0], 2)
        self.assertEqual(names, struct.pack("<QI", 1, 0) + struct.pack("<Q", 5) + b"Plate")
        self.assertEqual(extras, struct.pack("<3dQI4f?", 128.0, 128.0, 0.0, 1, 0, 1.0, 0.5, 0.25, 1.0, False))

    def test_a_new_recipe_writes_empty_names_and_default_extras(self):
        data = serialize(Recipe())
        self.assertEqual(data, struct.pack("<IIIQ", 6, 0, 8, 0) + struct.pack("<IQ", 8, 0)
                         + struct.pack("<I3dQ?", 33, 0.0, 0.0, 0.0, 0, True))

    def test_round_trip_of_our_recipe(self):
        recipe = small_recipe()
        data = serialize(recipe)
        back = deserialize(data)
        self.assertTrue(same(back, recipe))
        self.assertEqual(serialize(back), data)

    def test_v5_stamp_reads_and_writes_the_same_bytes(self):
        recipe = small_recipe()
        recipe.version = 5
        data = serialize(recipe)
        self.assertEqual(struct.unpack_from("<I", data)[0], 5)
        self.assertEqual(serialize(deserialize(data)), data)

    def test_missing_trailing_blocks_stay_missing(self):
        data = serialize(small_recipe())
        recipe = small_recipe()
        recipe.body_names = None
        short = serialize(recipe)
        self.assertLess(len(short), len(data))
        back = deserialize(short)
        self.assertEqual((back.body_names, back.has_extras, back.modeling_origin), (None, False, (0.0, 0.0, 0.0)))
        self.assertEqual(serialize(back), short)

    def test_v4_flat_layout_round_trip(self):
        recipe = small_recipe()
        recipe.version = 4
        data = serialize(recipe)
        self.assertEqual(struct.unpack_from("<IQ", data), (4, 4))
        back = deserialize(data)
        self.assertEqual([f.stored_fields for f in back.features], [FIELD_COUNT_V4] * 4)
        self.assertEqual((back.variables, back.body_names), (recipe.variables, None))
        self.assertEqual(serialize(back), data)

    def test_unknown_versions_and_broken_bytes_are_refused(self):
        with self.assertRaises(RecipeFormatError):
            deserialize(struct.pack("<II", 7, 0))
        with self.assertRaises(RecipeFormatError):
            deserialize(serialize(small_recipe())[:-3])
        recipe = Recipe(version=2)
        with self.assertRaises(RecipeFormatError):
            serialize(recipe)


@unittest.skipUnless(SAMPLES, "set ORCA_RECIPE_SAMPLES to the OrcaSlicer tests/data folder")
class OrcaSampleTest(unittest.TestCase):
    def check(self, version):
        path = os.path.join(SAMPLES, "cad_recipe_v%d.bin" % version)
        with open(path, "rb") as f:
            data = f.read()
        recipe = deserialize(data)
        self.assertEqual(recipe.version, version)
        self.assertGreater(len(recipe.features), 0)
        self.assertEqual(serialize(recipe), data)
        return recipe

    def test_v5_sample_writes_back_identical(self):
        recipe = self.check(5)
        first = recipe.features[0]
        self.assertEqual((first.type, first.name), (FeatureType.SKETCH, "Sketch_Base"))

    def test_v4_sample_writes_back_identical(self):
        self.check(4)

    def test_v3_sample_writes_back_identical(self):
        self.check(3)


class ThreeMfTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def test_published_3mf_holds_meshes_and_the_recipe(self):
        data = serialize(small_recipe())
        cube = MeshObject.placed("Box & co", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)],
                                 [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)], (128, 128, 0))
        out = self.path("a.3mf")
        write_3mf(out, data, [cube])
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            model = zf.read(MODEL_ENTRY).decode("utf-8")
        self.assertIn(RECIPE_ENTRY, names)
        self.assertNotIn(SETTINGS_ENTRY, names)
        self.assertEqual(read_recipe_bytes(out), data)
        self.assertIn('<metadata name="orca_published">1</metadata>', model)
        self.assertIn('<metadata name="orca_published_keys">[]</metadata>', model)
        self.assertIn('name="Box &amp; co"', model)
        self.assertIn('transform="1 0 0 0 1 0 0 0 1 128 128 0"', model)
        self.assertEqual(model.count("<triangle "), 4)

    def test_settings_mode_writes_project_settings_and_no_published_mark(self):
        out = self.path("b.3mf")
        write_3mf(out, serialize(Recipe()), settings={"printer_settings_id": "My printer"})
        with zipfile.ZipFile(out) as zf:
            settings = json.loads(zf.read(SETTINGS_ENTRY))
            model = zf.read(MODEL_ENTRY).decode("utf-8")
        self.assertEqual(settings, {"printer_settings_id": "My printer"})
        self.assertNotIn("orca_published", model)

    def test_a_published_file_needs_a_mesh(self):
        with self.assertRaises(ValueError):
            write_3mf(self.path("c.3mf"), serialize(Recipe()))
        self.assertFalse(os.path.exists(self.path("c.3mf")))

    def test_bad_meshes_are_refused(self):
        with self.assertRaises(ValueError):
            MeshObject("x", [(0, 0, 0)], [(0, 1, 2)])
        with self.assertRaises(ValueError):
            MeshObject("x", [(0, 0, 0)], [], transform=(1, 0, 0))

    def test_sample_script_writes_the_bound_sample(self):
        out = self.path("sample.3mf")
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "write_orca_sample.py"), out],
                       check=True, capture_output=True)
        recipe = deserialize(read_recipe_bytes(out))
        types = [f.type for f in recipe.features]
        self.assertEqual(types, [FeatureType.SKETCH, FeatureType.EXTRUDE, FeatureType.HOLE, FeatureType.FILLET])
        sketch, extrude, hole, fillet = recipe.features
        self.assertEqual(sketch.expr, {"width": "width", "height": "depth"})
        self.assertEqual(hole.expr, {"hole_diameter": "hole_d"})
        self.assertEqual((extrude.sketch_ref, extrude.mode), (0, BooleanMode.NEW))
        self.assertEqual((fillet.face_group, hole.hole_through), (FaceGroup.ALL, True))
        self.assertEqual(sorted(recipe.variables), ["depth", "hole_d", "width"])
        self.assertEqual(recipe.modeling_origin, sketch.plane.origin)


if __name__ == "__main__":
    unittest.main()
