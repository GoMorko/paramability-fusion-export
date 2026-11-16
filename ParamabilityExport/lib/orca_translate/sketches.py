"""Sketch outlines of the capture as Orca sketch features.

One outline (an outer loop with its holes) becomes one Orca sketch:
- one rectangle: the simple rectangle (`SketchShape.RECTANGLE`), centred on its plane's origin, so the plane origin
  moves to the rectangle's centre and its x axis runs along a side; `width` and `height` may follow variables;
- one circle: the simple circle (`SketchShape.CIRCLE`) on a plane at its centre; `radius` may follow variables;
- anything else of lines, arcs, circles and splines (`splines`): entities at their current values. Orca cannot tie
  sketch dimensions to variables yet, so such an outline keeps its numbers.

Which variables a rectangle or circle follows comes from the sketch's own dimensions (`capture.sketch_graphs`),
worked out as formulas by `sketch_solve`: a side length is the difference of two corners, each a formula of the
sketch's dimensions, and each dimension a formula of the sizes. A sketch without a graph, or one whose corners have
no formula, keeps its numbers, and the sizes that move it are reported.
"""
import math

from ..design_model.dimension_sizes import dimension_formulas, leaf_values, moving_sizes, override_sets, size_env
from ..orca_recipe.enums import EntityType, FeatureType, SketchShape
from ..orca_recipe.feature import CadFeature
from ..orca_recipe.sketch import SketchEntity
from ..sketch_solve.constants import constants_of
from ..sketch_solve.solve import solve_sketch
from ..sketch_values.expr import ExprDomainError
from . import splines

# Whether Fusion keeps two lines parallel when only a driving distance dimension ties them (hand test OR18). Until
# that is seen in Fusion, the sizes whose formulas rest on it follow only partly (`SketchFormulas.unconfirmed`).
DISTANCE_KEEPS_PARALLEL = False
UNCONFIRMED = ("%s: the copy takes two lines that only a distance dimension ties to stay parallel when sizes change, "
               "which is not confirmed in Fusion yet")

# Two sketch points closer than this (mm) are one point.
POINT_TOL = 1e-4
# A side length formula must give the drawn length within this (mm).
LENGTH_TOL = 1e-6


class Outline:
    """One outline: `outer` (a list of capture curves) and `holes` (lists of curves), in sketch 2D mm."""

    def __init__(self, outer, holes):
        self.outer = list(outer)
        self.holes = [list(h) for h in holes]


class SketchOut:
    """What one outline became: the Orca sketch `feature`, its `shape` ("rectangle", "circle" or "outline") and the
    fields that follow sizes (`bound`: field to (app formula, Fusion names it reads)). `notes` are plain sentences
    for the verdict; `moves` says the outline also moves with sizes in a way Orca cannot follow (its centre). A circle
    keeps its centre's sketch coordinates (`at`) and their leaf formulas (`centre`, each None when it has none), and
    `drill` is set when it is written as an Orca hole instead (`drilled`). `source` holds the outline and the
    sketch's formulas once an extrude writes it, for corner tools (`corner_hosts`)."""

    def __init__(self, feature, shape):
        self.feature = feature
        self.shape = shape
        self.bound = {}
        self.notes = []
        self.moves = ()
        self.at = self.centre = self.drill = self.source = None


def outlines_of(profile):
    """The outlines of a profile record: one per outer loop, with every hole loop of the record. A record holds one
    outer loop (Fusion lists a profile per region), so this is one outline, or None when the record has no outer
    loop or several."""
    loops = profile.get("loops") or []
    outer = [loop for loop in loops if loop.get("outer")]
    if len(outer) != 1:
        return None
    return Outline(outer[0].get("curves") or [], [loop.get("curves") or [] for loop in loops if not loop.get("outer")])


# ---- the shape of an outline ----------------------------------------------------------------------------------

def _same(a, b, tol=POINT_TOL):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def rectangle_of(curves):
    """`(centre, u, width, height)` of a loop of four lines that make a rectangle, else None. `u` is the unit side
    direction closest to the sketch x axis (pointing towards +x, or +y for a side along y); `width` runs along `u`,
    `height` along `u` turned 90 degrees counter clockwise."""
    if len(curves) != 4 or any(c.get("kind") != "line" for c in curves):
        return None
    corners = []
    for c in curves:
        for key in ("start", "end"):
            p = tuple(float(v) for v in c[key])
            if not any(_same(p, q) for q in corners):
                corners.append(p)
    if len(corners) != 4:
        return None
    centre = (sum(p[0] for p in corners) / 4.0, sum(p[1] for p in corners) / 4.0)
    sides = []
    for c in curves:
        dx, dy = c["end"][0] - c["start"][0], c["end"][1] - c["start"][1]
        length = math.hypot(dx, dy)
        if length <= POINT_TOL:
            return None
        sides.append((dx / length, dy / length, length))
    ux, uy, _ = max(sides, key=lambda s: abs(s[0]))
    if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0):
        ux, uy = -ux, -uy
    vx, vy = -uy, ux
    half_w = half_h = None
    for p in corners:
        a = (p[0] - centre[0]) * ux + (p[1] - centre[1]) * uy
        b = (p[0] - centre[0]) * vx + (p[1] - centre[1]) * vy
        if half_w is None:
            half_w, half_h = abs(a), abs(b)
        if abs(abs(a) - half_w) > POINT_TOL or abs(abs(b) - half_h) > POINT_TOL:
            return None
    signs = {(a > 0, b > 0) for a, b in (((p[0] - centre[0]) * ux + (p[1] - centre[1]) * uy,
                                            (p[0] - centre[0]) * vx + (p[1] - centre[1]) * vy) for p in corners)}
    if len(signs) != 4 or half_w <= POINT_TOL or half_h <= POINT_TOL:
        return None
    return centre, (ux, uy), 2.0 * half_w, 2.0 * half_h


def circle_of(curves):
    """`(centre, radius)` of a loop that is one circle, else None."""
    if len(curves) != 1 or curves[0].get("kind") != "circle":
        return None
    c = curves[0]
    return (float(c["center"][0]), float(c["center"][1])), float(c["radius"])


def _arc_entity(c):
    """An Orca arc through the capture arc's start, middle and end. Orca draws an arc through its two ends and the
    point at the middle of its start and end angles, so the end angle is set on the side that holds `mid`."""
    cx, cy = float(c["center"][0]), float(c["center"][1])
    start, end, mid = c["start"], c["end"], c.get("mid")
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    sweep = (a1 - a0) % (2 * math.pi)
    if isinstance(mid, (list, tuple)):
        am = math.atan2(mid[1] - cy, mid[0] - cx)
        if (am - a0) % (2 * math.pi) > sweep + 1e-9:
            sweep -= 2 * math.pi  # the arc runs clockwise from its start
    return SketchEntity(type=EntityType.ARC, p0=(float(start[0]), float(start[1])), p1=(float(end[0]), float(end[1])),
                        center=(cx, cy), radius=float(c["radius"]), start_angle=a0, end_angle=a0 + sweep)


def entities_of(loops):
    """Orca entities for capture curves (lines, arcs, circles, and splines Orca draws exactly: `splines`), or None
    when a curve is of another kind."""
    out = []
    for curves in loops:
        for c in curves:
            kind = c.get("kind")
            if kind == "line":
                out.append(SketchEntity(type=EntityType.LINE, p0=tuple(float(v) for v in c["start"]),
                                        p1=tuple(float(v) for v in c["end"])))
            elif kind == "arc" and isinstance(c.get("center"), (list, tuple)):
                out.append(_arc_entity(c))
            elif kind == "circle":
                centre = tuple(float(v) for v in c["center"])
                out.append(SketchEntity(type=EntityType.CIRCLE, center=centre, p0=centre, radius=float(c["radius"])))
            elif kind == "other" and c.get("nurbs"):
                drawn = splines.entities(c)
                if drawn is None:
                    return None
                out += drawn
            else:
                return None
    return out


# ---- formulas of a sketch -------------------------------------------------------------------------------------

class SketchFormulas:
    """The point and radius formulas of one sketch over the sizes, from its graph record. Each `*_expr` gives an
    `Expr` over size names, or None with `why` set."""

    def __init__(self, table, record):
        self.table = table
        self.record = record
        self.formulas = dimension_formulas(table, record)
        settings = [leaf_values(self.formulas, size_env(table, o))
                    for o in override_sets(moving_sizes(table, self.formulas))]
        self.solution = solve_sketch(record, settings or None, constants_of(record, False), extended=True)
        self.points = {p["id"]: tuple(p["xy"]) for p in record.get("points") or []
                       if isinstance(p, dict) and isinstance(p.get("id"), int) and p.get("xy")}
        self.curves = [c for c in record.get("curves") or [] if isinstance(c, dict)]
        self.why = ""
        self.unconfirmed = ()
        if self.solution.parallel_by_distance and not DISTANCE_KEEPS_PARALLEL:
            plain = solve_sketch(record, settings or None, constants_of(record, False), extended=True,
                                 distance_parallel=False)
            self.unconfirmed = self._resting(plain)

    def _resting(self, plain):
        """Fusion names of the free sizes read by the formulas (corners, radii, line directions) that the solution
        gives only with a distance dimension keeping its two lines parallel: those `plain`, the solution without
        that rule, leaves open."""
        found = []
        for pid, pair in self.solution.points.items():
            other = plain.points.get(pid)
            found += [v.expr for k, v in enumerate(pair) if v.derived and not (other and other[k].derived)]
        for table, other in ((self.solution.radii, plain.radii), (self.solution.directions, plain.directions)):
            for key, value in table.items():
                if value.derived and not (other.get(key) is not None and other[key].derived):
                    found.append(value.expr)
        out = {}
        for expr in found:
            over = self.over_sizes(expr)
            # A formula Orca cannot write keeps its number, and its sizes get their reason where it is used.
            if over is not None:
                out.update(dict.fromkeys(self.free_reads(over)))
        self.why = ""
        return tuple(out)

    def reads(self):
        """Fusion names of the free sizes the sketch's dimensions read."""
        out = {}
        for formula in self.formulas.values():
            out.update(dict.fromkeys(formula.reads))
        return tuple(out)

    def over_sizes(self, expr):
        """The leaf formula `expr` written over size names: each dimension by its formula, every other leaf (a
        measured input, a dimension that reads no size) by its number. None when a dimension it reads follows sizes
        but its formula cannot be written."""
        leaves = self.solution.leaves
        mapping = {}
        for name in expr.names():
            leaf = leaves.get(name)
            found = self.formulas.get(name)
            if found is not None and found.usable and found.expr is not None:
                mapping[name] = found.expr
            elif found is not None and found.reads:
                self.why = "a dimension of %s reads %s in a way Orca cannot write" % (
                    self.record.get("sketch") or "the sketch", ", ".join(found.reads))
                return None
            elif leaf is not None:
                mapping[name] = leaf.value
            else:
                self.why = "the sketch formula reads %s, which is unknown" % name
                return None
        return expr.substitute(mapping)

    def _line_point(self, xy):
        """The id of the graph point at `xy` that ends a line drawn in the sketch, else of any point there."""
        ends = {pid for c in self.curves if c.get("kind") == "line" and not c.get("construction")
                for pid in c.get("points") or []}
        found = [pid for pid, p in self.points.items() if _same(p, xy)]
        on_lines = [pid for pid in found if pid in ends]
        return (on_lines or found or [None])[0]

    def point(self, xy):
        """`(x, y)` leaf formulas of the graph point at `xy`, or None with `why` set."""
        pid = self._line_point(xy)
        if pid is None:
            self.why = "its corners are not in the sketch record"
            return None
        pair = self.solution.points.get(pid)
        if pair is None or not all(v.derived for v in pair):
            reason = next((v.reason for v in pair or () if not v.derived), "") if pair else ""
            self.why = "its points have no formula%s" % (" (%s)" % reason if reason else "")
            return None
        return pair[0].expr, pair[1].expr

    def line_angle(self, a, b):
        """The leaf formula (degrees) of the direction from `a` to `b` along a line drawn in the sketch through both
        points, or None with `why` set. The line's direction comes from the solver (`Solution.directions`)."""
        for c in self.curves:
            ends = c.get("points") or []
            if c.get("kind") != "line" or c.get("construction") or len(ends) != 2 or not all(
                    pid in self.points for pid in ends):
                continue
            p, q = self.points[ends[0]], self.points[ends[1]]
            if not (_on_line(a, p, q) and _on_line(b, p, q)):
                continue
            found = self.solution.directions.get(c.get("id"))
            if found is None or not found.derived:
                self.why = "no dimension or constraint sets the angle of one of its sides"
                return None
            along = (q[0] - p[0]) * (b[0] - a[0]) + (q[1] - p[1]) * (b[1] - a[1])
            return found.expr if along > 0 else found.expr + 180.0
        self.why = "a side of the outline is not a line of the sketch record"
        return None

    def follows_projection(self, outline):
        """True when a corner or centre of the outline has a formula that reads a measured input: a point placed by
        geometry projected into the sketch, which sizes read before the sketch may move in ways the capture does not
        tell, and which `over_sizes` writes as its number now."""
        for curve in [c for loop in [outline.outer] + outline.holes for c in loop]:
            for key in ("start", "end", "center"):
                xy = curve.get(key)
                if not isinstance(xy, (list, tuple)):
                    continue
                pair = self.solution.points.get(self._line_point(tuple(xy)))
                if pair is not None and any(v.derived and reads_input(v.expr) for v in pair):
                    return True
        return False

    def outline_sizes(self, outline):
        """Fusion names of the free sizes that move the ends and centres of the curves of an outline, or the radius
        of a circle in it; None when one of them has no formula (then any size of the sketch may move it). Leaves
        `why` as it was."""
        why, exprs = self.why, []
        for curve in [c for loop in [outline.outer] + outline.holes for c in loop]:
            kind = curve.get("kind")
            if kind not in ("line", "arc", "circle"):
                exprs = None
                break
            keys = ("center",) if kind == "circle" else ("start", "end") + (("center",) if kind == "arc" else ())
            pairs = [self.solution.points.get(self._line_point(tuple(curve[k])))
                     if isinstance(curve.get(k), (list, tuple)) else None for k in keys]
            if any(pair is None or not all(v.derived for v in pair) for pair in pairs):
                exprs = None
                break
            exprs += [v.expr for pair in pairs for v in pair]
            if kind == "circle":
                found = self.circle(tuple(curve["center"]), float(curve.get("radius") or 0.0))
                if found is None:
                    exprs = None
                    break
                exprs.append(found[2])
        out = {} if exprs is not None else None
        for expr in exprs or ():
            over = self.over_sizes(expr)
            if over is None:
                out = None
                break
            out.update(dict.fromkeys(self.free_reads(over)))
        self.why = why
        return None if out is None else tuple(out)

    def free_reads(self, expr):
        """Fusion names of the free sizes a formula over size names reads."""
        return _free_reads(self.table, expr.names())

    def circle(self, centre, radius):
        """`(centre x, centre y, radius)` leaf formulas of the graph circle at `centre` with `radius`, or None."""
        for c in self.curves:
            if c.get("kind") != "circle" or c.get("construction") or not isinstance(c.get("radius"), (int, float)):
                continue
            pid = c.get("center")
            if pid in self.points and _same(self.points[pid], centre) and abs(c["radius"] - radius) <= POINT_TOL:
                found = self.solution.radii.get(c["id"])
                pair = self.solution.points.get(pid)
                if found is None or not found.derived:
                    self.why = "its radius has no formula%s" % (" (%s)" % found.reason if found else "")
                    return None
                ok = pair is not None and all(v.derived for v in pair)
                return (pair[0].expr if ok else None), (pair[1].expr if ok else None), found.expr
        self.why = "the circle is not in the sketch record"
        return None

    def sized(self, expr, value):
        """`(app formula, Fusion names it reads)` of a leaf formula over sizes that gives `value` now, or None (no
        formula, or the sizes do not move it). Sets `why` when it cannot be written."""
        over = self.over_sizes(expr)
        if over is None:
            return None
        if over.is_constant:
            return None
        env = size_env(self.table, {})
        try:
            now = over.value(env)
        except (ExprDomainError, KeyError):
            self.why = "its formula cannot be worked out"
            return None
        if abs(now - value) > LENGTH_TOL * max(1.0, abs(value)):
            self.why = "its formula gives %s, not the drawn %s" % (_short(now), _short(value))
            return None
        reads = _free_reads(self.table, over.names())
        return over.text(), reads


def reads_input(expr):
    """True when a leaf formula reads a measured input (`sketch_solve.solve.input_name`: a name that starts with
    `@`), the place of a projected entity."""
    return any(name.startswith("@") for name in expr.names())


def _on_line(x, p, q, tol=POINT_TOL):
    """True when `x` lies on the segment from `p` to `q`."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length = math.hypot(dx, dy)
    if length <= tol or abs(dx * (x[1] - p[1]) - dy * (x[0] - p[0])) / length > tol:
        return False
    along = (dx * (x[0] - p[0]) + dy * (x[1] - p[1])) / length
    return -tol <= along <= length + tol


def _short(value):
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _free_reads(table, size_names):
    """Fusion names of the free sizes behind recipe size names."""
    out = {}
    for e in table.entries:
        if e.size_name in size_names:
            if e.state == "free":
                out[e.name] = None
            else:
                out.update(dict.fromkeys(e.reads))
    return tuple(out)


def graph_for(capture, profile):
    """The sketch graph record of a profile's sketch (by token, else by name), or None. An outline of another
    component's sketch (`borrowed`, or still `foreign`) has none: it is written as numbers where the capture places
    it, and its sketch may share its name with one of the part's own."""
    if profile.get("borrowed") or profile.get("foreign"):
        return None
    token, name = profile.get("sketch_token"), profile.get("sketch")
    graphs = [g for g in capture.get("sketch_graphs") or [] if isinstance(g, dict) and not g.get("error")
              and not g.get("cut")]
    found = [g for g in graphs if token and g.get("token") == token] or \
        [g for g in graphs if not token and name and g.get("sketch") == name]
    return found[0] if found else None


# ---- the Orca sketch of one outline ---------------------------------------------------------------------------

def _rectangle(outline, frame, place, formulas, name):
    found = rectangle_of(outline.outer)
    centre, (ux, uy), width, height = found
    x3 = [frame["x"][i] * ux + frame["y"][i] * uy for i in range(3)]
    y3 = [-frame["x"][i] * uy + frame["y"][i] * ux for i in range(3)]
    origin = [frame["origin"][i] + frame["x"][i] * centre[0] + frame["y"][i] * centre[1] for i in range(3)]
    plane = place.plane(origin, x3, y3, frame["z"])
    out = SketchOut(CadFeature(type=FeatureType.SKETCH, name=name, shape=SketchShape.RECTANGLE, plane=plane,
                               width=width, height=height), "rectangle")
    if formulas is None:
        return out
    hw, hh = width / 2.0, height / 2.0
    vx, vy = -uy, ux
    corner = {}
    for key, (a, b) in (("a", (-hw, -hh)), ("b", (hw, -hh)), ("d", (-hw, hh))):
        xy = (centre[0] + a * ux + b * vx, centre[1] + a * uy + b * vy)
        corner[key] = formulas.point(xy)
        if corner[key] is None:
            out.notes.append("%s keeps its numbers: %s." % (name, formulas.why))
            return out
    (ax, ay), (bx, by), (dx, dy) = corner["a"], corner["b"], corner["d"]
    if not _keeps_turn(formulas, (ax, ay), (bx, by), (dx, dy), (ux, uy)):
        out.notes.append("%s keeps its numbers: it turns when the sizes change." % name)
        return out
    for field, expr, value in (("width", (bx - ax).scaled(ux) + (by - ay).scaled(uy), width),
                               ("height", (dx - ax).scaled(vx) + (dy - ay).scaled(vy), height)):
        made = formulas.sized(expr, value)
        if made is not None:
            out.bound[field] = made
        elif formulas.why:
            out.notes.append("%s %s keeps its number: %s." % (name, field, formulas.why))
            formulas.why = ""
    out.moves = _moving(formulas, ((bx + dx).scaled(0.5), (by + dy).scaled(0.5)))
    return out


def _keeps_turn(formulas, a, b, d, u):
    """True when the sides from corner `a` to `b` and to `d` stay along `u` and across it at the solver's size
    settings (the sides keep their direction)."""
    ux, uy = u
    leaves = {n: leaf.value for n, leaf in formulas.solution.leaves.items()}
    for setting in formulas.solution.settings or []:
        env = dict(leaves, **setting)
        try:
            ab = (b[0].value(env) - a[0].value(env), b[1].value(env) - a[1].value(env))
            ad = (d[0].value(env) - a[0].value(env), d[1].value(env) - a[1].value(env))
        except (ExprDomainError, KeyError):
            return False
        if abs(ab[0] * -uy + ab[1] * ux) > LENGTH_TOL * 10 or abs(ad[0] * ux + ad[1] * uy) > LENGTH_TOL * 10:
            return False
    return True


def _moving(formulas, exprs):
    """Fusion names of the sizes that move a point given by leaf formulas (its place, not its size)."""
    out = {}
    for expr in exprs:
        if expr is None:
            continue
        over = formulas.over_sizes(expr)
        if over is not None and not over.is_constant:
            out.update(dict.fromkeys(_free_reads(formulas.table, over.names())))
    formulas.why = ""
    return tuple(out)


def _circle(outline, frame, place, formulas, name):
    centre, radius = circle_of(outline.outer)
    origin = [frame["origin"][i] + frame["x"][i] * centre[0] + frame["y"][i] * centre[1] for i in range(3)]
    plane = place.plane(origin, frame["x"], frame["y"], frame["z"])
    out = SketchOut(CadFeature(type=FeatureType.SKETCH, name=name, shape=SketchShape.CIRCLE, plane=plane,
                               radius=radius), "circle")
    if formulas is None:
        return out
    found = formulas.circle(centre, radius)
    if found is None:
        out.notes.append("%s keeps its numbers: %s." % (name, formulas.why))
        return out
    cx, cy, r = found
    out.at, out.centre = centre, (cx, cy)
    made = formulas.sized(r, radius)
    if made is not None:
        out.bound["radius"] = made
    elif formulas.why:
        out.notes.append("%s radius keeps its number: %s." % (name, formulas.why))
    out.moves = _moving(formulas, (cx, cy))
    return out


def outline_sketch(outline, frame, place, formulas, name):
    """The Orca sketch of one outline (`SketchOut`), or None when a curve cannot be written. `frame` is the sketch
    frame in capture coordinates (already moved for a start offset); `formulas` the sketch's `SketchFormulas` or
    None when its dimensions are not known."""
    if not outline.holes and rectangle_of(outline.outer) is not None:
        return _rectangle(outline, frame, place, formulas, name)
    if not outline.holes and circle_of(outline.outer) is not None:
        return _circle(outline, frame, place, formulas, name)
    entities = entities_of([outline.outer] + outline.holes)
    if entities is None:
        return None
    plane = place.plane(frame["origin"], frame["x"], frame["y"], frame["z"])
    return SketchOut(CadFeature(type=FeatureType.SKETCH, name=name, plane=plane, entities=entities), "outline")
