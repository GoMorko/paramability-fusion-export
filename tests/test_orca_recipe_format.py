"""The Orca recipe archive: value widths, size tags, the feature field list and its defaults."""
import struct
import unittest

from tests import context  # noqa: F401

from lib.orca_recipe.cereal import Reader, RecipeFormatError, ShortRead, Writer
from lib.orca_recipe.enums import BooleanMode, ConstraintType, EntityType, FaceGroup, FeatureType, PointRole
from lib.orca_recipe.feature import (BINDABLE_FIELDS, FIELD_COUNT_V3, FIELD_COUNT_V4, FIELD_NAMES, FIELDS, CadFeature,
                                     feature_refs, read_feature_block, shift_refs, write_feature)
from lib.orca_recipe.sketch import (SketchConstraintDef, SketchEntity, SketchEntityConstraintDef, SketchPlane,
                                    SketchProfile)


def feature_bytes(feature):
    w = Writer()
    write_feature(w, feature)
    return w.getvalue()


class PrimitiveTest(unittest.TestCase):
    def test_widths_and_little_endian(self):
        w = Writer()
        w.bool(True)
        w.i32(-2)
        w.u32(7)
        w.f32(0.5)
        w.f64(1.5)
        w.size(3)
        self.assertEqual(w.getvalue(), b"\x01" + struct.pack("<iIfdQ", -2, 7, 0.5, 1.5, 3))

    def test_a_string_is_a_u64_byte_count_then_utf8(self):
        w = Writer()
        w.string("Bø")
        self.assertEqual(w.getvalue(), struct.pack("<Q", 3) + "Bø".encode("utf-8"))
        self.assertEqual(Reader(w.getvalue()).string(), "Bø")

    def test_vectors_and_eigen_points(self):
        w = Writer()
        w.int_list([1, -1])
        w.vec2((1.0, 2.0))
        w.vec3((3.0, 4.0, 5.0))
        w.vec2_list([(6.0, 7.0)])
        expected = struct.pack("<Qii", 2, 1, -1) + struct.pack("<5d", 1, 2, 3, 4, 5) + struct.pack("<Q2d", 1, 6, 7)
        self.assertEqual(w.getvalue(), expected)
        r = Reader(expected)
        self.assertEqual((r.int_list(), r.vec2(), r.vec3(), r.vec2_list()),
                         ([1, -1], (1.0, 2.0), (3.0, 4.0, 5.0), [(6.0, 7.0)]))
        self.assertTrue(r.at_end())

    def test_a_string_map_is_written_in_key_byte_order(self):
        w = Writer()
        w.string_map({"b": "2", "a": "1"})
        self.assertEqual(w.getvalue(), struct.pack("<QQ", 2, 1) + b"a" + struct.pack("<Q", 1) + b"1"
                         + struct.pack("<Q", 1) + b"b" + struct.pack("<Q", 1) + b"2")

    def test_running_out_raises_a_short_read(self):
        with self.assertRaises(ShortRead):
            Reader(b"\x01\x00").i32()
        with self.assertRaises(ShortRead):
            Reader(struct.pack("<Q", 50) + b"abc").string()
        self.assertTrue(issubclass(ShortRead, RecipeFormatError))


class SketchTypeTest(unittest.TestCase):
    def test_sizes_of_the_sketch_types(self):
        sizes = {}
        for value in (SketchPlane(), SketchProfile(), SketchEntity(), SketchConstraintDef(),
                      SketchEntityConstraintDef()):
            w = Writer()
            value.write(w)
            sizes[type(value).__name__] = len(w.getvalue())
        # plane 4 x 3 doubles; profile size tag + bool; entity int, 3 points, 3 doubles, bool, 2 doubles, size tag;
        # point constraint int, 4 ints, double; entity constraint int, 4 ints, double, 2 ints.
        self.assertEqual(sizes, {"SketchPlane": 96, "SketchProfile": 9, "SketchEntity": 4 + 48 + 24 + 1 + 16 + 8,
                                 "SketchConstraintDef": 28, "SketchEntityConstraintDef": 36})

    def test_sketch_types_read_back(self):
        values = [
            SketchPlane.xz((1.0, 2.0, 3.0)),
            SketchProfile([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], True),
            SketchEntity(EntityType.BSPLINE, (0.0, 0.0), (3.0, 0.0), ctrl=[(0.0, 0.0), (1.0, 1.0), (3.0, 0.0)]),
            SketchConstraintDef(ConstraintType.DISTANCE, 0, 1, value=12.5),
            SketchEntityConstraintDef(ConstraintType.SYMMETRIC, 0, 1, PointRole.P1, PointRole.CENTER, 0.0, 2,
                                      PointRole.P0),
        ]
        for value in values:
            w = Writer()
            value.write(w)
            r = Reader(w.getvalue())
            self.assertEqual(type(value).read(r), value)
            self.assertTrue(r.at_end())

    def test_xz_keeps_orcas_normal(self):
        self.assertEqual(SketchPlane.xz().normal, (0.0, 1.0, 0.0))


class FeatureFieldTest(unittest.TestCase):
    def test_field_list_order_anchors(self):
        self.assertEqual(len(FIELDS), 146)
        self.assertEqual(len(set(FIELD_NAMES)), len(FIELD_NAMES))
        self.assertEqual(FIELD_NAMES[:8], ["type", "name", "enabled", "shape", "plane", "width", "height", "radius"])
        self.assertEqual(FIELD_NAMES[FIELD_NAMES.index("cut_keep_lower") + 1], "brep")
        self.assertEqual(FIELD_NAMES[FIELD_NAMES.index("expr") - 1], "pattern_curve_entity")
        self.assertEqual(FIELD_NAMES[FIELD_NAMES.index("expr") + 1], "mate_kind")
        self.assertEqual((FIELD_COUNT_V3, FIELD_COUNT_V4), (137, 139))
        self.assertEqual(FIELD_NAMES[-1], "revolve_axis_entity")

    def test_defaults(self):
        f = CadFeature()
        self.assertEqual((f.type, f.name, f.enabled, f.width, f.height, f.radius),
                         (FeatureType.SKETCH, "", True, 20.0, 20.0, 10.0))
        self.assertEqual((f.distance, f.mode, f.dressup_size, f.face_group),
                         (10.0, BooleanMode.NEW, 1.0, FaceGroup.ALL))
        self.assertEqual((f.hole_diameter, f.hole_depth, f.hole_through, f.hole_csink_angle), (5.0, 10.0, True, 90.0))
        self.assertEqual((f.pattern_count, f.pattern_spacing, f.revolve_angle), (3, 20.0, 360.0))
        self.assertEqual((f.axis_p2, f.coordsys_x_hint, f.xf_axis),
                         ((0.0, 0.0, 10.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual((f.plane, f.expr, f.entities, f.revolve_axis_entity), (SketchPlane.xy(), {}, [], -1))
        self.assertEqual((f.thread_major_nominal, f.pattern_inclusive, f.text_height), (False, False, 0.0))

    def test_inserting_features_moves_every_index_orca_moves(self):
        # Orca's `for_each_feature_ref` (CadDocument.cpp) visits these fields; each must follow an insert.
        f = CadFeature(sketch_ref=1, sweep_path_ref=4, pattern_curve_sketch=5, rib_sketch_ref=6, mate_cs_a=7,
                       mate_cs_b=2, loft_profile_refs=[1, 4])
        shift_refs(f, 3, 10)
        self.assertEqual(sorted(feature_refs(f)), [1, 1, 2, 14, 14, 15, 16, 17])
        self.assertEqual(feature_refs(CadFeature()), [])

    def test_defaults_are_not_shared_between_features(self):
        a, b = CadFeature(), CadFeature()
        a.expr["width"] = "w"
        a.entities.append(SketchEntity())
        self.assertEqual((b.expr, b.entities), ({}, []))

    def test_a_default_feature_has_the_byte_count_of_its_field_widths(self):
        widths = {"int": 4, "double": 8, "bool": 1}
        kinds = {
            "int": [n for n in FIELD_NAMES if isinstance(getattr(CadFeature(), n), int)
                    and not isinstance(getattr(CadFeature(), n), bool)],
            "double": [n for n in FIELD_NAMES if isinstance(getattr(CadFeature(), n), float)],
            "bool": [n for n in FIELD_NAMES if isinstance(getattr(CadFeature(), n), bool)],
        }
        fixed = sum(widths[k] * len(v) for k, v in kinds.items())
        # Points: 1 vec2 and 8 vec3. Empty containers and strings: one size tag each (profile has a bool too).
        points = 16 + 8 * 24
        tags = 8 * sum(1 for n in FIELD_NAMES if isinstance(getattr(CadFeature(), n), (str, list, dict)))
        self.assertEqual(len(feature_bytes(CadFeature())), fixed + points + tags + 96 + 9)

    def test_unknown_field_names_are_refused(self):
        with self.assertRaises(TypeError):
            CadFeature(widht=3)

    def test_only_bindable_fields_take_a_formula(self):
        f = CadFeature()
        f.bind("distance", "depth * 2")
        self.assertEqual(f.expr, {"distance": "depth * 2"})
        with self.assertRaises(ValueError):
            f.bind("hole_through", "1")
        self.assertIn("thread_diameter", BINDABLE_FIELDS)
        self.assertNotIn("value", BINDABLE_FIELDS)

    def test_feature_reads_back(self):
        f = CadFeature(type=FeatureType.EXTRUDE, name="Boss", sketch_ref=0, distance=12.5, mode=BooleanMode.ADD,
                       expr={"distance": "h"}, dressup_edges=[3, 4], text_string="Hi", revolve_axis_entity=2)
        back = read_feature_block(Reader(feature_bytes(f)))
        self.assertEqual(back, f)
        self.assertEqual((back.stored_fields, back.tail), (None, b""))


class ShortBlockTest(unittest.TestCase):
    def test_a_short_block_keeps_defaults_and_writes_back_short(self):
        full = feature_bytes(CadFeature(name="Old", distance=3.0))
        w = Writer()
        f = CadFeature(name="Old", distance=3.0)
        for field in FIELDS[:FIELD_COUNT_V4]:
            field.kind.write(w, getattr(f, field.name))
        short = w.getvalue()
        self.assertLess(len(short), len(full))
        back = read_feature_block(Reader(short))
        self.assertEqual((back.name, back.distance, back.stored_fields), ("Old", 3.0, FIELD_COUNT_V4))
        self.assertEqual(back.revolve_axis_entity, -1)
        self.assertEqual(feature_bytes(back), short)

    def test_a_changed_field_after_a_short_block_is_written(self):
        back = read_feature_block(Reader(feature_bytes(CadFeature())[:300]))
        cut = back.stored_fields
        back.text_height = 4.0
        out = feature_bytes(back)
        self.assertEqual(read_feature_block(Reader(out)).text_height, 4.0)
        self.assertGreater(len(out), 300)
        self.assertLess(cut, FIELD_NAMES.index("text_height"))

    def test_a_field_cut_in_the_middle_is_kept_as_tail(self):
        data = feature_bytes(CadFeature(name="Cut here"))
        cut = data[:18]  # type, the name's size tag and part of the name
        back = read_feature_block(Reader(cut))
        self.assertEqual((back.stored_fields, back.name, back.tail), (1, "", cut[4:]))
        self.assertEqual(feature_bytes(back), cut)

    def test_bytes_of_a_newer_orca_after_the_known_fields_are_kept(self):
        data = feature_bytes(CadFeature(name="New")) + b"\x01\x02\x03"
        back = read_feature_block(Reader(data))
        self.assertEqual(back.tail, b"\x01\x02\x03")
        self.assertEqual(feature_bytes(back), data)

    def test_an_unknown_enum_number_survives(self):
        w = Writer()
        w.i32(99)
        back = read_feature_block(Reader(w.getvalue()))
        self.assertEqual(back.type, 99)
        self.assertEqual(feature_bytes(back), w.getvalue())


if __name__ == "__main__":
    unittest.main()
