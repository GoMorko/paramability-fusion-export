"""One feature of the recipe (`CadFeature`): every stored field in archive order, with Orca's default.

The order is the format. Orca only appends fields at the end, and a feature block that ends early leaves the
fields after it at their defaults, so a field list here may be shorter than a newer Orca's and still read right.
"""
import copy

from .cereal import ShortRead
from .enums import (AxisType, BooleanMode, CoordSysType, ExtrudeEnd, FaceGroup, FeatureType, PlaneType, SketchShape,
                    enum_value)
from .sketch import (SketchConstraintDef, SketchEntity, SketchEntityConstraintDef, SketchPlane, SketchProfile,
                     read_regions, write_regions)


class _Kind:
    def __init__(self, write, read):
        self.write = write
        self.read = read


def _enum(cls):
    return _Kind(lambda w, v: w.i32(v), lambda r: enum_value(cls, r.i32()))


INT = _Kind(lambda w, v: w.i32(v), lambda r: r.i32())
DOUBLE = _Kind(lambda w, v: w.f64(v), lambda r: r.f64())
BOOL = _Kind(lambda w, v: w.bool(v), lambda r: r.bool())
STRING = _Kind(lambda w, v: w.string(v), lambda r: r.string())
VEC2 = _Kind(lambda w, v: w.vec2(v), lambda r: r.vec2())
VEC3 = _Kind(lambda w, v: w.vec3(v), lambda r: r.vec3())
INT_LIST = _Kind(lambda w, v: w.int_list(v), lambda r: r.int_list())
STRING_MAP = _Kind(lambda w, v: w.string_map(v), lambda r: r.string_map())
PLANE = _Kind(lambda w, v: v.write(w), SketchPlane.read)
PROFILE = _Kind(lambda w, v: v.write(w), SketchProfile.read)
ENTITIES = _Kind(lambda w, v: w.items(v, lambda w2, e: e.write(w2)), lambda r: r.items(SketchEntity.read))
CONSTRAINTS = _Kind(lambda w, v: w.items(v, lambda w2, c: c.write(w2)), lambda r: r.items(SketchConstraintDef.read))
ENTITY_CONSTRAINTS = _Kind(lambda w, v: w.items(v, lambda w2, c: c.write(w2)),
                           lambda r: r.items(SketchEntityConstraintDef.read))
REGIONS = _Kind(write_regions, read_regions)


class Field:
    def __init__(self, name, kind, default):
        self.name = name
        self.kind = kind
        self._default = default

    def default(self):
        return copy.deepcopy(self._default)


_ORIGIN3 = (0.0, 0.0, 0.0)

# (name, kind, default) in the order Orca writes them.
FIELDS = [Field(*f) for f in (
    # What the feature is.
    ("type", _enum(FeatureType), FeatureType.SKETCH),
    ("name", STRING, ""),
    ("enabled", BOOL, True),
    # Sketch: the simple rectangle or circle centred on the plane origin, or entities, or the older profile.
    ("shape", _enum(SketchShape), SketchShape.RECTANGLE),
    ("plane", PLANE, SketchPlane()),
    ("width", DOUBLE, 20.0),
    ("height", DOUBLE, 20.0),
    ("radius", DOUBLE, 10.0),
    ("profile", PROFILE, SketchProfile()),
    ("entities", ENTITIES, []),
    ("constraints", CONSTRAINTS, []),
    ("entity_constraints", ENTITY_CONSTRAINTS, []),
    ("imported_regions", REGIONS, []),
    ("import_offset", VEC2, (0.0, 0.0)),
    ("import_scale_x", DOUBLE, 1.0),
    ("import_scale_y", DOUBLE, 1.0),
    ("import_on_face", BOOL, False),
    ("import_face_body", INT, -1),
    # Extrude (also the profile source and boolean of revolve, sweep and loft).
    ("sketch_ref", INT, -1),
    ("distance", DOUBLE, 10.0),
    ("symmetric", BOOL, False),
    ("mode", _enum(BooleanMode), BooleanMode.NEW),
    ("extrude_end", _enum(ExtrudeEnd), ExtrudeEnd.BLIND),
    ("distance2", DOUBLE, 0.0),
    ("taper_deg", DOUBLE, 0.0),
    ("flip", BOOL, False),
    ("up_to_face", INT, -1),
    ("extrude_src_face", INT, -1),
    ("up_to_point", VEC3, _ORIGIN3),
    ("target_body", INT, -1),
    # Fillet and chamfer.
    ("dressup_size", DOUBLE, 1.0),
    ("face_group", _enum(FaceGroup), FaceGroup.ALL),
    ("dressup_edge", INT, -1),
    # Hole.
    ("hole_diameter", DOUBLE, 5.0),
    ("hole_depth", DOUBLE, 10.0),
    ("hole_through", BOOL, True),
    ("hole_x", DOUBLE, 0.0),
    ("hole_y", DOUBLE, 0.0),
    # Thread.
    ("thread_radius", DOUBLE, 5.0),
    ("thread_pitch", DOUBLE, 2.0),
    ("thread_height", DOUBLE, 10.0),
    ("thread_depth", DOUBLE, 1.0),
    ("thread_internal", BOOL, False),
    ("thread_x", DOUBLE, 0.0),
    ("thread_y", DOUBLE, 0.0),
    # Shell, draft, revolve, sweep, loft.
    ("shell_thickness", DOUBLE, 2.0),
    ("shell_face", INT, -1),
    ("draft_face", INT, -1),
    ("draft_angle", DOUBLE, 5.0),
    ("revolve_angle", DOUBLE, 360.0),
    ("revolve_axis", INT, 0),
    ("sweep_path_ref", INT, -1),
    ("loft_profile_refs", INT_LIST, []),
    ("loft_ruled", BOOL, False),
    # Pattern.
    ("pattern_circular", BOOL, False),
    ("pattern_count", INT, 3),
    ("pattern_spacing", DOUBLE, 20.0),
    ("pattern_dir", INT, 0),
    ("pattern_angle", DOUBLE, 360.0),
    # Datum plane.
    ("plane_base", INT, 0),
    ("plane_offset", DOUBLE, 20.0),
    ("plane_angle_tilt", DOUBLE, 0.0),
    ("plane_axis", INT, 0),
    # Boolean between bodies.
    ("bool_tool_body", INT, -1),
    ("bool_keep_tool", BOOL, False),
    ("bool_tolerance", DOUBLE, 0.0),
    ("bool_target_face", INT, -1),
    ("bool_tool_face", INT, -1),
    # Plane cut.
    ("cut_offset", DOUBLE, 0.0),
    ("cut_flip", BOOL, False),
    ("cut_keep_upper", BOOL, True),
    ("cut_keep_lower", BOOL, False),
    # Imported STEP solid as OCCT BRep text; Orca writes it for Import features only, else empty.
    ("brep", STRING, ""),
    # Datum plane, other methods.
    ("plane_type", _enum(PlaneType), PlaneType.OFFSET),
    ("plane_face_body", INT, -1),
    ("plane_face", INT, -1),
    ("plane_face2_body", INT, -1),
    ("plane_face2", INT, -1),
    ("plane_edge_body", INT, -1),
    ("plane_edge", INT, -1),
    ("plane_edge2_body", INT, -1),
    ("plane_edge2", INT, -1),
    ("plane_u_size", DOUBLE, 60.0),
    ("plane_v_size", DOUBLE, 60.0),
    # Mirror.
    ("mirror_keep_original", BOOL, True),
    # Datum axis.
    ("axis_type", _enum(AxisType), AxisType.TWO_POINTS),
    ("axis_p1", VEC3, _ORIGIN3),
    ("axis_p2", VEC3, (0.0, 0.0, 10.0)),
    ("axis_body", INT, -1),
    ("axis_face", INT, -1),
    ("axis_edge", INT, -1),
    ("axis_plane_a", INT, -1),
    ("axis_plane_b", INT, -1),
    # Datum coordinate system.
    ("coordsys_type", _enum(CoordSysType), CoordSysType.POINT_WORLD),
    ("coordsys_point", VEC3, _ORIGIN3),
    ("coordsys_body", INT, -1),
    ("coordsys_face", INT, -1),
    ("coordsys_edge", INT, -1),
    ("coordsys_x_hint", VEC3, (1.0, 0.0, 0.0)),
    # Helix.
    ("helix_radius", DOUBLE, 10.0),
    ("helix_pitch", DOUBLE, 5.0),
    ("helix_height", DOUBLE, 20.0),
    ("helix_left_handed", BOOL, False),
    ("helix_taper_deg", DOUBLE, 0.0),
    # Transform.
    ("xf_translate", VEC3, _ORIGIN3),
    ("xf_axis", VEC3, (0.0, 0.0, 1.0)),
    ("xf_pivot", VEC3, _ORIGIN3),
    ("xf_angle_deg", DOUBLE, 0.0),
    ("xf_copy", BOOL, False),
    # Thicken a face.
    ("thicken_face", INT, -1),
    ("thicken_thickness", DOUBLE, 2.0),
    ("thicken_flip", BOOL, False),
    # Cut along a face.
    ("cut_face_body", INT, -1),
    ("cut_face", INT, -1),
    # Project edges.
    ("project_source_body", INT, -1),
    ("project_edges", INT_LIST, []),
    ("project_face", INT, -1),
    # Delete faces.
    ("delete_faces", INT_LIST, []),
    # Hole styles.
    ("hole_style", INT, 0),
    ("hole_cbore_diameter", DOUBLE, 0.0),
    ("hole_cbore_depth", DOUBLE, 0.0),
    ("hole_csink_diameter", DOUBLE, 0.0),
    ("hole_csink_angle", DOUBLE, 90.0),
    ("hole_standard", STRING, ""),
    # Rib.
    ("rib_sketch_ref", INT, -1),
    ("rib_entity", INT, -1),
    ("rib_thickness", DOUBLE, 2.0),
    ("rib_depth", DOUBLE, 10.0),
    # Pattern along a curve.
    ("pattern_curve_sketch", INT, -1),
    ("pattern_curve_entity", INT, -1),
    # Variable bindings: field name to formula, evaluated against the document variables on every rebuild.
    ("expr", STRING_MAP, {}),
    # Mate.
    ("mate_kind", INT, 0),
    ("mate_cs_a", INT, -1),
    ("mate_cs_b", INT, -1),
    ("mate_offset", DOUBLE, 0.0),
    ("mate_angle", DOUBLE, 0.0),
    ("mate_flip", BOOL, False),
    # The face a coordinate system was bound to (surface kind, edge count); -1 not recorded.
    ("coordsys_face_kind", INT, -1),
    ("coordsys_face_edges", INT, -1),
    # Appended since the framed layout (v5).
    ("thread_major_nominal", BOOL, False),
    ("pattern_inclusive", BOOL, False),
    ("dressup_edges", INT_LIST, []),
    ("text_string", STRING, ""),
    ("text_font", STRING, ""),
    ("text_height", DOUBLE, 0.0),
    ("revolve_axis_entity", INT, -1),
)]

FIELD_NAMES = [f.name for f in FIELDS]

# The unframed layouts keep the field list they were written with: v4 ends after the coordinate system face,
# v3 two ints earlier, after the mate.
FIELD_COUNT_V4 = FIELD_NAMES.index("coordsys_face_edges") + 1
FIELD_COUNT_V3 = FIELD_NAMES.index("mate_flip") + 1

# The numeric fields a feature formula may drive in Orca 2.5 (`expr` keys). Sketch dimensions are not among them.
BINDABLE_FIELDS = frozenset((
    "bool_tolerance", "cut_offset", "distance", "distance2", "draft_angle", "dressup_size", "height",
    "helix_height", "helix_pitch", "helix_radius", "helix_taper_deg", "hole_cbore_diameter", "hole_cbore_depth",
    "hole_csink_angle", "hole_csink_diameter", "hole_depth", "hole_diameter", "hole_x", "hole_y",
    "import_scale_x", "import_scale_y", "mate_angle", "mate_offset", "pattern_angle", "pattern_spacing",
    "plane_angle_tilt", "plane_offset", "plane_u_size", "plane_v_size", "radius", "revolve_angle", "rib_depth",
    "rib_thickness", "shell_thickness", "taper_deg", "thicken_thickness", "thread_depth", "thread_height",
    "thread_pitch", "thread_radius", "thread_diameter", "thread_x", "thread_y", "width", "xf_angle_deg",
    "pattern_count",
))

# The fields that name another feature by its index in the list, as Orca's `for_each_feature_ref` visits them
# (CadDocument.cpp): one index each, then lists of indexes. Inserting or removing a feature moves the indexes after it.
FEATURE_REF_FIELDS = ("sketch_ref", "sweep_path_ref", "pattern_curve_sketch", "rib_sketch_ref", "mate_cs_a",
                      "mate_cs_b")
FEATURE_REF_LISTS = ("loft_profile_refs",)


def feature_refs(feature):
    """Every index of another feature that `feature` names; -1 (none) is left out."""
    out = [getattr(feature, field) for field in FEATURE_REF_FIELDS]
    out += [n for field in FEATURE_REF_LISTS for n in getattr(feature, field) or ()]
    return [n for n in out if n >= 0]


def shift_refs(feature, at, by):
    """Move each index of another feature that `feature` names, from `at` on, by `by` (features inserted or removed
    at `at`)."""
    for field in FEATURE_REF_FIELDS:
        if getattr(feature, field) >= at:
            setattr(feature, field, getattr(feature, field) + by)
    for field in FEATURE_REF_LISTS:
        if getattr(feature, field):
            setattr(feature, field, [n + by if n >= at else n for n in getattr(feature, field)])


class CadFeature:
    """A feature with every stored field as an attribute, Orca's defaults unless given.

    `stored_fields` is how many leading fields the block it was read from held (None: all this code knows) and
    `tail` the bytes after them that this code does not read: a cut field, or fields of a newer Orca. Both serve
    an exact write back of a read block.
    """

    def __init__(self, **values):
        for f in FIELDS:
            setattr(self, f.name, f.default())
        self.stored_fields = None
        self.tail = b""
        for name, value in values.items():
            if name not in _NAME_SET and name not in ("stored_fields", "tail"):
                raise TypeError("CadFeature has no field %r" % name)
            setattr(self, name, value)

    def values(self):
        return {name: getattr(self, name) for name in FIELD_NAMES}

    def __eq__(self, other):
        return isinstance(other, CadFeature) and self.values() == other.values()

    def __repr__(self):
        changed = {f.name: getattr(self, f.name) for f in FIELDS if getattr(self, f.name) != f.default()}
        return "CadFeature(%s)" % ", ".join("%s=%r" % kv for kv in changed.items())

    def bind(self, field, formula):
        """Drive a numeric field by a formula over the document variables."""
        if field not in BINDABLE_FIELDS:
            raise ValueError("Orca cannot bind %r to a variable" % field)
        self.expr[field] = formula


_NAME_SET = frozenset(FIELD_NAMES)


def _count_to_write(feature, limit):
    """Fields to write: what the block held, more when a field after that was changed from its default."""
    count = limit if feature.stored_fields is None else min(feature.stored_fields, limit)
    for i in range(limit - 1, count - 1, -1):
        if getattr(feature, FIELDS[i].name) != FIELDS[i].default():
            return i + 1
    return count


def write_feature(w, feature, limit=len(FIELDS)):
    """The feature's fields in order, at most `limit` of them, then its unread tail if the count is unchanged."""
    count = _count_to_write(feature, limit)
    for f in FIELDS[:count]:
        f.kind.write(w, getattr(feature, f.name))
    held = len(FIELDS) if feature.stored_fields is None else feature.stored_fields
    if count == held and limit == len(FIELDS):
        w.raw(feature.tail)


def read_feature_block(r):
    """A framed feature block: fields until the bytes end, as Orca does. The rest stays at defaults."""
    feature = CadFeature()
    for i, f in enumerate(FIELDS):
        if r.at_end():
            feature.stored_fields = i
            return feature
        start = r.pos
        try:
            setattr(feature, f.name, f.kind.read(r))
        except ShortRead:
            # Orca keeps the fields read before the one that broke off.
            r.seek(start)
            feature.stored_fields = i
            feature.tail = r.rest()
            return feature
    feature.stored_fields = None
    feature.tail = r.rest()
    return feature


def read_feature_flat(r, count):
    """A feature of an unframed layout: exactly `count` fields, all present."""
    feature = CadFeature()
    for f in FIELDS[:count]:
        setattr(feature, f.name, f.kind.read(r))
    feature.stored_fields = count
    return feature
