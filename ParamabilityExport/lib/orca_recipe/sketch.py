"""The sketch values a feature carries: its plane, entities, the older point profile and the constraints.

Each type lists its fields in archive order with Orca's defaults. Points are (x, y) tuples in plane millimetres,
3D vectors (x, y, z) tuples. Angles of arcs and ellipses are radians.
"""
from dataclasses import dataclass, field

from .enums import ConstraintType, EntityType, PointRole, enum_value


@dataclass
class SketchPlane:
    """A plane frame in world millimetres. The base planes pass through the world origin."""

    origin: tuple = (0.0, 0.0, 0.0)
    normal: tuple = (0.0, 0.0, 1.0)
    x_axis: tuple = (1.0, 0.0, 0.0)
    y_axis: tuple = (0.0, 1.0, 0.0)

    @classmethod
    def xy(cls, origin=(0.0, 0.0, 0.0)):
        return cls(tuple(origin), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))

    @classmethod
    def xz(cls, origin=(0.0, 0.0, 0.0)):
        # Orca keeps +Y as this plane's normal although x cross y is -Y; extrude directions depend on it.
        return cls(tuple(origin), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))

    @classmethod
    def yz(cls, origin=(0.0, 0.0, 0.0)):
        return cls(tuple(origin), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

    def write(self, w):
        w.vec3(self.origin)
        w.vec3(self.normal)
        w.vec3(self.x_axis)
        w.vec3(self.y_axis)

    @classmethod
    def read(cls, r):
        return cls(r.vec3(), r.vec3(), r.vec3(), r.vec3())


@dataclass
class SketchEntity:
    """One curve of a sketch.

    Line: p0 to p1. Arc: center, radius, start and end angle (p0, p1 its ends). Circle and Point: center (Point
    also p0). Ellipse and its arc: center, radius (semi major), rminor, rotation, start and end angle. BSpline:
    ctrl holds the poles, p0 and p1 the first and last. A construction entity helps the solver and builds nothing.
    """

    type: int = EntityType.LINE
    p0: tuple = (0.0, 0.0)
    p1: tuple = (0.0, 0.0)
    center: tuple = (0.0, 0.0)
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    construction: bool = False
    rminor: float = 0.0
    rotation: float = 0.0
    ctrl: list = field(default_factory=list)

    def write(self, w):
        w.i32(self.type)
        w.vec2(self.p0)
        w.vec2(self.p1)
        w.vec2(self.center)
        w.f64(self.radius)
        w.f64(self.start_angle)
        w.f64(self.end_angle)
        w.bool(self.construction)
        w.f64(self.rminor)
        w.f64(self.rotation)
        w.vec2_list(self.ctrl)

    @classmethod
    def read(cls, r):
        return cls(enum_value(EntityType, r.i32()), r.vec2(), r.vec2(), r.vec2(), r.f64(), r.f64(), r.f64(),
                   r.bool(), r.f64(), r.f64(), r.vec2_list())


@dataclass
class SketchProfile:
    """The older single polyline sketch: points in order, closed or open."""

    points: list = field(default_factory=list)
    closed: bool = False

    def write(self, w):
        w.vec2_list(self.points)
        w.bool(self.closed)

    @classmethod
    def read(cls, r):
        return cls(r.vec2_list(), r.bool())


@dataclass
class SketchConstraintDef:
    """A constraint on profile points a, b, c, d (indices; -1 unused). value is the dimension, if any."""

    type: int = ConstraintType.COINCIDENT
    a: int = -1
    b: int = -1
    c: int = -1
    d: int = -1
    value: float = 0.0

    def write(self, w):
        w.i32(self.type)
        for v in (self.a, self.b, self.c, self.d):
            w.i32(v)
        w.f64(self.value)

    @classmethod
    def read(cls, r):
        return cls(enum_value(ConstraintType, r.i32()), r.i32(), r.i32(), r.i32(), r.i32(), r.f64())


@dataclass
class SketchEntityConstraintDef:
    """A constraint on entities ea, eb (and ec, the axis of a symmetry), each with the point role it names.

    An entity index may also be one of the implicit references (SKETCH_REF_ORIGIN, _AXIS_X, _AXIS_Y). value is
    the dimension; Orca cannot bind it to a variable.
    """

    type: int = ConstraintType.COINCIDENT
    ea: int = -1
    eb: int = -1
    ra: int = PointRole.P0
    rb: int = PointRole.P0
    value: float = 0.0
    ec: int = -1
    rc: int = PointRole.P0

    def write(self, w):
        w.i32(self.type)
        w.i32(self.ea)
        w.i32(self.eb)
        w.i32(self.ra)
        w.i32(self.rb)
        w.f64(self.value)
        w.i32(self.ec)
        w.i32(self.rc)

    @classmethod
    def read(cls, r):
        return cls(enum_value(ConstraintType, r.i32()), r.i32(), r.i32(), enum_value(PointRole, r.i32()),
                   enum_value(PointRole, r.i32()), r.f64(), r.i32(), enum_value(PointRole, r.i32()))


def write_regions(w, regions):
    """Imported text or SVG art: regions, each a list of loops (outer first, then holes), each a list of points."""
    w.size(len(regions))
    for region in regions:
        w.size(len(region))
        for loop in region:
            w.vec2_list(loop)


def read_regions(r):
    return [[r.vec2_list() for _ in range(r.size())] for _ in range(r.size())]
