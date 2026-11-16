"""The enums of the recipe. Each is stored as its 4 byte int, so the numbers are the format: never renumber."""
from enum import IntEnum


class FeatureType(IntEnum):
    SKETCH = 0
    EXTRUDE = 1
    FILLET = 2
    CHAMFER = 3
    HOLE = 4
    THREAD = 5
    SHELL = 6
    REVOLVE = 7
    SWEEP = 8
    PATTERN = 9
    PLANE = 10
    LOFT = 11
    DRAFT = 12
    IMPORT = 13
    BOOLEAN = 14
    CUT = 15
    MIRROR = 16
    AXIS = 17
    COORD_SYS = 18
    HELIX = 19
    TRANSFORM = 20
    THICKEN = 21
    PROJECT = 22
    DELETE_FACE = 23
    RIB = 24
    SURFACE_EXTRUDE = 25
    SURFACE_REVOLVE = 26
    THICKEN_SURFACE = 27
    SURFACE_OFFSET = 28
    SURFACE_LOFT = 29
    SURFACE_FILL = 30
    MATE = 31


class SketchShape(IntEnum):
    RECTANGLE = 0
    CIRCLE = 1


class PlaneType(IntEnum):
    OFFSET = 0
    ANGLE = 1
    MIDPLANE = 2
    TANGENT = 3
    TWO_EDGES = 4
    COINCIDENT = 5


class AxisType(IntEnum):
    TWO_POINTS = 0
    FACE_NORMAL = 1
    CYLINDER_CENTERLINE = 2
    PLANE_INTERSECTION = 3
    ALONG_EDGE = 4


class CoordSysType(IntEnum):
    POINT_WORLD = 0
    FACE_AND_DIRECTION = 1


class BooleanMode(IntEnum):
    NEW = 0
    ADD = 1
    CUT = 2
    INTERSECT = 3


class ExtrudeEnd(IntEnum):
    BLIND = 0
    SYMMETRIC = 1
    TWO_SIDED = 2
    THROUGH_ALL = 3
    UP_TO_FACE = 4
    UP_TO_VERTEX = 5


class FaceGroup(IntEnum):
    TOP = 0
    BOTTOM = 1
    LATERAL = 2
    ALL = 3


class EntityType(IntEnum):
    LINE = 0
    ARC = 1
    CIRCLE = 2
    POINT = 3
    ELLIPSE = 4
    ELLIPSE_ARC = 5
    BSPLINE = 6


class ConstraintType(IntEnum):
    FIX = 0
    COINCIDENT = 1
    HORIZONTAL = 2
    VERTICAL = 3
    DISTANCE = 4
    LOCK_X = 5
    LOCK_Y = 6
    EQUAL_LENGTH = 7
    PARALLEL = 8
    PERPENDICULAR = 9
    CONCENTRIC = 10
    TANGENT = 11
    MIDPOINT = 12
    SYMMETRIC = 13
    ANGLE = 14
    RADIUS = 15
    DIAMETER = 16
    POINT_ON_LINE = 17
    POINT_ON_OBJECT = 18
    EQUAL_RADIUS = 19
    COLLINEAR = 20
    DISTANCE_X = 21
    DISTANCE_Y = 22
    SYMMETRIC_ABOUT_Y = 23
    SYMMETRIC_ABOUT_X = 24


class PointRole(IntEnum):
    P0 = 0
    P1 = 1
    CENTER = 2


# Implicit sketch references a constraint may name in place of an entity index.
SKETCH_REF_ORIGIN = -2
SKETCH_REF_AXIS_X = -3
SKETCH_REF_AXIS_Y = -4


def enum_value(cls, number):
    """The member for a stored number, or the bare int when this code does not know it (a newer file)."""
    try:
        return cls(number)
    except ValueError:
        return number
