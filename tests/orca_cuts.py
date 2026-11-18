"""Captures of extrudes whose outlines follow user parameters through their sketch graphs, for the tests of outlines
built from plane cuts and the live check (`scripts/orca_live_check.py write <file>` with a capture these write), and
`Section`: the Orca recipe read in Python, as the cross section of each body on the sketch plane.

Each shape draws its sketch at given values with hand worked corners, so the outline the tests expect at other
values does not come from the sketch solver. Target boxes and volumes are worked out from the corners."""
import math

from tests.derived_fixtures import dimension
from tests.orca_extents import B1, UP, capture, extrude, profile, side, sketch_item
from tests.probe_helpers import user
from tests.sketch_solve_helpers import L, P, Sketch

from lib.orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from lib.orca_translate import halfplanes
from lib.orca_translate.formulas import orca_value, variable_values


def lines(points):
    return [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(points, points[1:] + points[:1])]


def _cos(a):
    return math.cos(math.radians(a))


def _sin(a):
    return math.sin(math.radians(a))


class Shape:
    """An outline drawn from user parameters. `values` are the parameters now (`t` the extrude length, angles named
    in `angles`); `draw(sketch, values)` adds the graph and gives the corner point ids in loop order."""

    def __init__(self, values, draw, angles=()):
        self.values, self.draw, self.angles = dict(values), draw, tuple(angles)

    def sketch(self, values=None):
        """(graph record, corners in loop order) at `values`."""
        s = Sketch()
        ids = self.draw(s, dict(self.values, **(values or {})))
        record = s.record()
        for number, entity in enumerate(record["curves"]):
            entity["token"] = "e%d" % number
        return record, [tuple(s.points[i]["xy"]) for i in ids]

    def corners(self, values=None):
        return self.sketch(values)[1]


def _horizontal(s, a, b):
    line = s.line(a, b)
    s.con("horizontal", L(line))
    return line


def _vertical(s, a, b):
    line = s.line(a, b)
    s.con("vertical", L(line))
    return line


def _ell(s, v):
    """An L: a bar `leg_a` along x and a leg `leg_b` up y, both `wall` thick, its outer corner at the origin."""
    a, b, w = v["leg_a"], v["leg_b"], v["wall"]
    ids = [0] + [s.point(x, y) for x, y in ((a, 0), (a, w), (w, w), (w, b), (0, b))]
    for k in range(6):
        (_horizontal if k % 2 == 0 else _vertical)(s, ids[k], ids[(k + 1) % 6])
    dimension(s, "linear", [P(0), P(ids[1])], a, "d1", "leg_a", "horizontal")
    dimension(s, "linear", [P(0), P(ids[5])], b, "d2", "leg_b", "vertical")
    dimension(s, "linear", [P(ids[1]), P(ids[2])], w, "d3", "wall", "vertical")
    dimension(s, "linear", [P(ids[5]), P(ids[4])], w, "d4", "wall", "horizontal")
    return ids


def _u(s, v):
    """A U: `width` wide and `high` tall, its walls `wall` thick, its base `base` thick, open at the top."""
    a, h, w, b = v["width"], v["high"], v["wall"], v["base"]
    corners = ((a, 0), (a, h), (a - w, h), (a - w, b), (w, b), (w, h), (0, h))
    ids = [0] + [s.point(x, y) for x, y in corners]
    for k in range(8):
        (_horizontal if k % 2 == 0 else _vertical)(s, ids[k], ids[(k + 1) % 8])
    dimension(s, "linear", [P(0), P(ids[1])], a, "d1", "width", "horizontal")
    dimension(s, "linear", [P(0), P(ids[7])], h, "d2", "high", "vertical")
    dimension(s, "linear", [P(ids[1]), P(ids[2])], h, "d3", "high", "vertical")
    dimension(s, "linear", [P(ids[3]), P(ids[2])], w, "d4", "wall", "horizontal")
    dimension(s, "linear", [P(ids[7]), P(ids[6])], w, "d5", "wall", "horizontal")
    dimension(s, "linear", [P(0), P(ids[5])], b, "d6", "base", "vertical")
    return ids


def _trapezoid(s, v):
    """A trapezoid: a base `base` along x from the origin, a top `high` above it, both sides at `ang` to the base."""
    a, h, ang = v["base"], v["high"], v["ang"]
    run = h / math.tan(math.radians(ang))
    ids = [0] + [s.point(x, y) for x, y in ((a, 0), (a - run, h), (run, h))]
    bottom = _horizontal(s, ids[0], ids[1])
    right = s.line(ids[1], ids[2])
    _horizontal(s, ids[2], ids[3])
    left = s.line(ids[3], ids[0])
    dimension(s, "linear", [P(0), P(ids[1])], a, "d1", "base", "horizontal")
    dimension(s, "linear", [P(0), P(ids[3])], h, "d2", "high", "vertical")
    dimension(s, "angular", [L(bottom), L(left)], ang, "d3", "ang")
    dimension(s, "angular", [L(bottom), L(right)], ang, "d4", "ang")
    return ids


def _angled(s, v):
    """Two legs `wall` thick that meet at `ang`: one `leg_a` along x, one `leg_b` along the direction at `ang`, their
    outer corner at the origin. The inner sides are tied to the outer ones by distance dimensions only."""
    a, b, w, ang = v["leg_a"], v["leg_b"], v["wall"], v["ang"]
    e, n = (_cos(ang), _sin(ang)), (_sin(ang), -_cos(ang))
    inner = w / math.tan(math.radians(ang) / 2.0)
    corners = ((a, 0), (a, w), (inner, w), (b * e[0] + w * n[0], b * e[1] + w * n[1]), (b * e[0], b * e[1]))
    ids = [0] + [s.point(x, y) for x, y in corners]
    bottom = _horizontal(s, ids[0], ids[1])
    _vertical(s, ids[1], ids[2])
    _horizontal(s, ids[2], ids[3])
    leg_in = s.line(ids[3], ids[4])
    cap = s.line(ids[4], ids[5])
    leg_out = s.line(ids[5], ids[0])
    s.con("perpendicular", L(cap), L(leg_out))
    dimension(s, "linear", [P(0), P(ids[1])], a, "d1", "leg_a", "horizontal")
    dimension(s, "angular", [L(bottom), L(leg_out)], ang, "d2", "ang")
    dimension(s, "linear", [L(leg_out)], b, "d3", "leg_b", "aligned")
    dimension(s, "linear", [P(ids[1]), P(ids[2])], w, "d4", "wall", "vertical")
    dimension(s, "offset", [L(leg_out), L(leg_in)], w, "d5", "wall")
    return ids


def _window(s, v):
    """A window `wide` by `tall` whose lower left corner sits at (`wx`, `wy`)."""
    x, y, a, b = v["wx"], v["wy"], v["wide"], v["tall"]
    ids = [s.point(x, y), s.point(x + a, y), s.point(x + a, y + b), s.point(x, y + b)]
    for k in range(4):
        (_horizontal if k % 2 == 0 else _vertical)(s, ids[k], ids[(k + 1) % 4])
    dimension(s, "linear", [P(0), P(ids[0])], x, "d1", "wx", "horizontal")
    dimension(s, "linear", [P(0), P(ids[0])], y, "d2", "wy", "vertical")
    dimension(s, "linear", [P(ids[0]), P(ids[1])], a, "d3", "wide", "horizontal")
    dimension(s, "linear", [P(ids[1]), P(ids[2])], b, "d4", "tall", "vertical")
    return ids


def _ell_with_hole(s, v):
    """The L, with a triangle hole in its bar placed from the bar's end corner (`leg_a`, 0) by plain numbers."""
    ids = _ell(s, v)
    a, b, c = (s.point(x, y) for x, y in ell_hole(v))
    _horizontal(s, a, b)
    s.line(b, c)
    s.line(c, a)
    dimension(s, "linear", [P(ids[1]), P(a)], 12.0, "d11", "12 mm", "horizontal")
    dimension(s, "linear", [P(ids[1]), P(a)], 2.0, "d12", "2 mm", "vertical")
    dimension(s, "linear", [P(a), P(b)], 8.0, "d13", "8 mm", "horizontal")
    dimension(s, "linear", [P(a), P(c)], 4.0, "d14", "4 mm", "horizontal")
    dimension(s, "linear", [P(a), P(c)], 4.0, "d15", "4 mm", "vertical")
    return ids


def ell_hole(values):
    """The corners of the triangle hole of `ELL_HOLE` at `values`."""
    a = values["leg_a"]
    return [(a - 12.0, 2.0), (a - 4.0, 2.0), (a - 8.0, 6.0)]


ELL = Shape({"leg_a": 40.0, "leg_b": 30.0, "wall": 8.0, "t": 10.0}, _ell)
U = Shape({"width": 50.0, "high": 30.0, "wall": 6.0, "base": 8.0, "t": 10.0}, _u)
TRAPEZOID = Shape({"base": 40.0, "high": 20.0, "ang": 70.0, "t": 10.0}, _trapezoid, angles=("ang",))
ANGLED = Shape({"leg_a": 40.0, "leg_b": 30.0, "wall": 8.0, "ang": 120.0, "t": 10.0}, _angled, angles=("ang",))
ELL_HOLE = Shape(ELL.values, _ell_with_hole)
WINDOW = Shape({"wx": 10.0, "wy": 6.0, "wide": 20.0, "tall": 12.0}, _window)
# The plate the window is cut through: 60 by 40, its lower left corner at the origin, 10 tall, drawn with numbers.
PLATE = [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0)]


def _parameters(shape, record):
    users = [user(n, "%g %s" % (x, "deg" if n in shape.angles else "mm"), x, "deg" if n in shape.angles else "mm")
             for n, x in shape.values.items()]
    for found in users:
        if found["name"] in shape.angles:
            found["kind"] = "angle"
    models = []
    for d in record["dimensions"]:
        deg = d["type"] == "angular"
        models.append({"name": d["param"], "expression": d["expression"], "unit": "deg" if deg else "mm",
                       "value": math.radians(d["value"]) if deg else d["value"] / 10.0, "kind": "derived",
                       "role": "", "dependency_parameters": [],
                       "created_by": {"kind": "sketchDimension", "token": "", "name": d["param"],
                                      "sketch": "Sketch1", "component": "c"}})
    if "t" in shape.values:
        models.append({"name": "d0", "expression": "t", "unit": "mm", "value": shape.values["t"] / 10.0,
                       "kind": "derived", "role": "", "dependency_parameters": [],
                       "created_by": {"kind": "feature", "token": "tok_d0", "name": ""}})
    return users, models


def _box(points, low, high):
    return ((min(p[0] for p in points), min(p[1] for p in points), low),
            (max(p[0] for p in points), max(p[1] for p in points), high))


# The second side of a two sided extrude (mm), a plain number.
OTHER_SIDE = 4.0


def heights(extent, t):
    """The heights along the sketch normal an extrude `t` long covers: "one" side, "flip" (the other way),
    "symmetric" or "two" sides (`OTHER_SIDE` on the other side)."""
    return {"one": (0.0, t), "flip": (-t, 0.0), "symmetric": (-t / 2.0, t / 2.0), "two": (-OTHER_SIDE, t)}[extent]


def _extent(extent, t, taper):
    """The extrude record fields for an `extent` of `heights`, `t` following the user parameter `t`."""
    length = {"name": "d0", "expression": "t", "value": t}
    if extent == "symmetric":
        return {"extent": "symmetric", "symmetric": {"distance": t, "full_length": True, "taper_deg": 0.0},
                "params": {"symmetric.distance": length}}
    found = {"side_one": side(t, taper), "end_offset": -t if extent == "flip" else t,
             "params": {"side_one.distance": length}}
    if extent == "two":
        found.update(extent="two", side_two=side(OTHER_SIDE))
    return found


def outline_capture(shape, taper=0.0, frame=UP, extent="one"):
    """One extrude of the shape's outline, `t` long, as a new body (tapered by `taper` degrees when given), its
    sketch on `frame`, its `extent` one of `heights`. The box is worked out for the XY plane only."""
    record, corners = shape.sketch()
    t = shape.values["t"]
    users, models = _parameters(shape, record)
    leans = {"side_leans": [math.sin(math.radians(-taper))] * len(corners)} if taper else {}
    items = [sketch_item(0, "Sketch1"),
             extrude(1, "Extrude1", [profile("Sketch1", frame, lines(corners))], target_box_before=None,
                     **_extent(extent, t, taper), **leans)]
    # The volume and box of a tapered extrude are not worked out: such a capture is for the translation only.
    found = capture(items, _box(corners, *heights(extent, t)), abs(halfplanes.area(corners)) * t, users, models)
    found["sketch_graphs"] = [record]
    return found


# The plate the outline joins or intersects: `PLATE`, from the sketch plane up this high, drawn with numbers.
PLATE_HEIGHT = 6.0


def onto_plate_capture(shape, operation):
    """The plate, then the shape's outline extruded `t` up from the same plane with `operation`: join, cut or
    intersect."""
    record, corners = shape.sketch()
    users, models = _parameters(shape, record)
    t = shape.values["t"]
    plate = {"min": [0.0, 0.0, 0.0], "max": [60.0, 40.0, PLATE_HEIGHT]}
    items = [sketch_item(0, "Sketch0"),
             extrude(1, "Plate", [profile("Sketch0", UP, lines(PLATE))], side_one=side(PLATE_HEIGHT),
                     end_offset=PLATE_HEIGHT, target_box_before=None),
             sketch_item(2, "Sketch1"),
             extrude(3, "Extrude1", [profile("Sketch1", UP, lines(corners))], operation=operation,
                     target_box_before=plate, **_extent("one", t, 0.0))]
    area = abs(halfplanes.area(corners))
    if operation == "join":
        box, volume = ((0.0, 0.0, 0.0), (60.0, 40.0, max(t, PLATE_HEIGHT))), 2400.0 * PLATE_HEIGHT + area * max(
            0.0, t - PLATE_HEIGHT)
    elif operation == "cut":
        box, volume = ((0.0, 0.0, 0.0), (60.0, 40.0, PLATE_HEIGHT)), 2400.0 * PLATE_HEIGHT - area * min(
            t, PLATE_HEIGHT)
    else:
        box, volume = _box(corners, 0.0, min(t, PLATE_HEIGHT)), area * min(t, PLATE_HEIGHT)
    found = capture(items, box, volume, users, models)
    found["sketch_graphs"] = [record]
    return found


def holed_capture(shape=ELL_HOLE, hole=ell_hole):
    """`outline_capture` of the shape with a hole in its outline: `hole(values)` gives its corners."""
    found = outline_capture(shape)
    found["items"][1]["data"]["profiles"][0]["loops"].append({"outer": False, "curves": lines(hole(shape.values))})
    return found


def window_capture(shape=WINDOW):
    """The plate, then the shape's outline cut through it from its sketch on the XY plane."""
    record, corners = shape.sketch()
    users, models = _parameters(shape, record)
    through = {"kind": "throughAll", "positive": True, "taper_deg": 0.0}
    box = {"min": [0.0, 0.0, 0.0], "max": [60.0, 40.0, 10.0]}
    items = [sketch_item(0, "Sketch0"),
             extrude(1, "Plate", [profile("Sketch0", UP, lines(PLATE))], side_one=side(10.0), end_offset=10.0,
                     target_box_before=None),
             sketch_item(2, "Sketch1"),
             extrude(3, "Window", [profile("Sketch1", UP, lines(corners))], operation="cut", side_one=through,
                     end_offset=None, target_box_before=box)]
    volume = (2400.0 - abs(halfplanes.area(corners))) * 10.0
    found = capture(items, ((0.0, 0.0, 0.0), (60.0, 40.0, 10.0)), volume, users, models)
    found["sketch_graphs"] = [record]
    return found


def projected_window_capture():
    """The window cut through the plate, its lower left corner a point projected from the part (no dimension places
    it), and the plate `thick` tall: the capture does not tell whether `thick` moves the projected point."""
    found = window_capture()
    record = found["sketch_graphs"][0]
    record["dimensions"] = [d for d in record["dimensions"] if d["expression"] not in ("wx", "wy")]
    corner = record["points"][1]
    corner["reference"] = {"source": "own", "component": "c", "token": "projected"}
    found["parameters"]["user"] = [u for u in found["parameters"]["user"] if u["name"] not in ("wx", "wy")]
    found["parameters"]["user"].append(user("thick", "10 mm", 10.0))
    found["parameters"]["model"] = [m for m in found["parameters"]["model"] if m["expression"] not in ("wx", "wy")]
    found["parameters"]["model"].append(
        {"name": "d9", "expression": "thick", "unit": "mm", "value": 1.0, "kind": "derived", "role": "",
         "dependency_parameters": [], "created_by": {"kind": "feature", "token": "tok_d9", "name": ""}})
    found["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d9", "expression": "thick", "value": 10.0}}
    return found


def window_pattern_capture(copies=2, spacing=30.0):
    """The window cut through the plate, at (5, 6), then repeated `copies` times `spacing` apart along x by a
    rectangular pattern of features."""
    found = window_capture(Shape(dict(WINDOW.values, wx=5.0), WINDOW.draw))
    elements = [{"id": k, "suppressed": False,
                 "frame": {"origin": [k * spacing, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}}
                for k in range(copies)]
    data = {"entity_type": "features", "sources": [3], "direction_one": [1, 0, 0], "quantity_one": copies,
            "distance_one": spacing, "direction_two": None, "quantity_two": 1, "distance_two": 0.0,
            "distance_type": "spacing", "symmetric_one": False, "symmetric_two": False, "elements": elements,
            "suppressed_ids": []}
    found["items"].append({"index": 4, "name": "Pattern1", "type": "RectangularPatternFeature", "suppressed": False,
                           "health": "ok", "in_target_component": True, "bodies_after": [dict(B1)], "data": data})
    found["target"]["volume_mm3"] = (2400.0 - copies * 240.0) * 10.0
    return found


# ---- the recipe read in Python -----------------------------------------------------------------------------------

def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _turned(p, axis, pivot, deg):
    """`p` turned about the line through `pivot` along the unit `axis` by `deg` degrees (right hand)."""
    v = _sub(p, pivot)
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    along = _dot(axis, v)
    cross = [axis[1] * v[2] - axis[2] * v[1], axis[2] * v[0] - axis[0] * v[2], axis[0] * v[1] - axis[1] * v[0]]
    return [pivot[i] + v[i] * c + cross[i] * s + axis[i] * along * (1 - c) for i in range(3)]


class Section:
    """Every body the recipe builds at the variable values `changed` (Orca variable to number; the others keep their
    formulas): `bodies` is Orca's list of bodies, each a test `inside(point)` of a world point. An extrude covers its
    outline between the heights along its sketch plane's normal that its end gives (as `steps._Side.ends` writes
    them: one side from the plane, `flip` the other way; symmetric about the plane; two sides; through all).
    Reads the features the outline cuts and corner tools write: sketches (rectangles, circles, lines), extrudes,
    cuts, transforms, Booleans, patterns along a line, holes through all, and sketches of imported regions (text)."""

    def __init__(self, recipe, changed=None):
        variables = dict(recipe.variables)
        variables.update({k: repr(float(v)) for k, v in (changed or {}).items()})
        self.values = variable_values(variables)
        self.bodies = []
        sketches = {}
        for at, f in enumerate(recipe.features):
            if f.type == FeatureType.SKETCH:
                sketches[at] = self._region(f)
            elif f.type == FeatureType.EXTRUDE:
                self._extrude(f, sketches[f.sketch_ref], recipe.features[f.sketch_ref].plane)
            elif f.type == FeatureType.CUT:
                self._cut(f)
            elif f.type == FeatureType.TRANSFORM:
                self._turn(f)
            elif f.type == FeatureType.BOOLEAN:
                self._boolean(f)
            elif f.type == FeatureType.PATTERN and not f.pattern_circular:
                self._pattern(f)
            elif f.type == FeatureType.HOLE and f.hole_through and f.hole_style == 0:
                self._hole(f)
            else:
                raise ValueError("Section does not read %s" % f.type)

    def _number(self, f, field):
        text = f.expr.get(field)
        return orca_value(text, self.values) if text else float(getattr(f, field))

    def _region(self, f):
        plane = f.plane
        origin, x, y = list(plane.origin), list(plane.x_axis), list(plane.y_axis)
        if f.imported_regions:
            # Imported regions (text): inside a region's outer loop and outside its holes.
            def in_regions(p):
                d = _sub(p, origin)
                uv = (_dot(d, x), _dot(d, y))
                return any(halfplanes.in_polygon(region[0], uv)
                           and not any(halfplanes.in_polygon(hole, uv) for hole in region[1:])
                           for region in f.imported_regions)
            return in_regions
        if f.entities:
            loop = [tuple(e.p0) for e in f.entities]

            def inside(p):
                d = _sub(p, origin)
                return halfplanes.in_polygon(loop, (_dot(d, x), _dot(d, y)))
            return inside
        if f.shape == SketchShape.CIRCLE:
            radius = self._number(f, "radius")

            def in_circle(p):
                d = _sub(p, origin)
                return _dot(d, x) ** 2 + _dot(d, y) ** 2 < radius * radius
            return in_circle
        if f.shape != SketchShape.RECTANGLE:
            raise ValueError("Section reads rectangles, circles and lines only")
        hw, hh = self._number(f, "width") / 2.0, self._number(f, "height") / 2.0

        def inside(p):
            d = _sub(p, origin)
            return abs(_dot(d, x)) < hw and abs(_dot(d, y)) < hh
        return inside

    def _index(self, f, field="target_body"):
        at = getattr(f, field)
        return len(self.bodies) - 1 if at == -1 else at

    def _heights(self, f):
        if f.extrude_end == ExtrudeEnd.THROUGH_ALL:
            return -math.inf, math.inf
        d = self._number(f, "distance")
        if f.extrude_end == ExtrudeEnd.SYMMETRIC:
            return -d / 2.0, d / 2.0
        if f.extrude_end == ExtrudeEnd.TWO_SIDED:
            return -self._number(f, "distance2"), d
        return (-d, 0.0) if f.flip else (0.0, d)

    def _extrude(self, f, region, plane):
        low, high = self._heights(f)
        origin, normal = list(plane.origin), list(plane.normal)

        def solid(p):
            return low < _dot(_sub(p, origin), normal) < high and region(p)
        if f.mode == BooleanMode.NEW:
            self.bodies.append(solid)
            return
        self._combine(self._index(f), solid, f.mode)

    def _combine(self, at, tool, mode):
        body = self.bodies[at]
        if mode == BooleanMode.ADD:
            self.bodies[at] = lambda p: body(p) or tool(p)
        elif mode == BooleanMode.CUT:
            self.bodies[at] = lambda p: body(p) and not tool(p)
        else:
            self.bodies[at] = lambda p: body(p) and tool(p)

    def _cut(self, f):
        at = self._index(f)
        body, offset = self.bodies[at], self._number(f, "cut_offset")
        origin, normal = list(f.plane.origin), list(f.plane.normal)
        upper = f.cut_keep_upper

        def kept(p):
            gap = _dot(_sub(p, origin), normal) - offset
            return body(p) and (gap > 0 if upper else gap < 0)
        self.bodies[at] = kept

    def _turn(self, f):
        at = self._index(f)
        body, deg = self.bodies[at], self._number(f, "xf_angle_deg")
        axis, pivot = list(f.xf_axis), list(f.xf_pivot)
        self.bodies[at] = lambda p: body(_turned(p, axis, pivot, -deg))

    def _hole(self, f):
        """A plain hole through all: Orca cuts a cylinder through its plane's place, both ways."""
        at = self._index(f)
        body, radius = self.bodies[at], self._number(f, "hole_diameter") / 2.0
        plane = f.plane
        hx, hy = self._number(f, "hole_x"), self._number(f, "hole_y")
        centre = [plane.origin[i] + plane.x_axis[i] * hx + plane.y_axis[i] * hy for i in range(3)]
        axis = list(plane.normal)

        def kept(p):
            d = _sub(p, centre)
            along = _dot(d, axis)
            return body(p) and _dot(d, d) - along * along >= radius * radius
        self.bodies[at] = kept

    def _pattern(self, f):
        at = self._index(f)
        body, count, spacing = self.bodies[at], int(round(self._number(f, "pattern_count"))), \
            self._number(f, "pattern_spacing")
        step = list(f.plane.x_axis)
        self.bodies[at] = lambda p: any(body([p[i] - k * spacing * step[i] for i in range(3)]) for k in range(count))

    def _boolean(self, f):
        target, tool = self._index(f), self._index(f, "bool_tool_body")
        self._combine(target, self.bodies[tool], f.mode)
        del self.bodies[tool]


def cell_points(polygon, others=()):
    """2D points in every cell of the lines through the polygon's edges (and of `others`, more polygons)."""
    out = list(halfplanes.samples(polygon))
    for extra in others:
        out += halfplanes.samples(extra)
    return out
