"""Thin extrudes as Orca features. Orca has no thin extrude, so the wall is built from plain extrudes.

Which side the wall stands on comes only from what Fusion measured, as the shared layer decides it
(`design_model/steps/thin.py`): the end face area for a closed outline (`closed_side`), the faces the extrude made for
an open line (`line_side`). When that is not certain, the step is left out. Fusion keeps the corners of a wall sharp,
and so does every shape written here.

- One closed rectangle or circle: a tool body of two plain sketches, the outer outline extruded as a new body and the
  inner outline cut through all of it, then a Boolean with the step's operation. On the first body of the part the
  two extrudes go straight into the part. The width, height or radius of each outline is the drawn size plus or minus
  the thickness (by the side of the wall), so both follow their variables, and the length follows.
- One straight line with the wall centred on it: an Orca rectangle centred on the line, as long as the line and as
  wide as the wall. The length and the thickness follow.
- Any other open line of straight lines, or of lines and arcs that meet tangent at each arc (`thin_arc.py`): the
  outline of the wall (`thin.wall_curves`) drawn with numbers, lines and arcs. The line and the thickness keep their
  numbers, and the sizes that move them are marked. A line with arcs is copied only when the part's volume changed by
  the outline's area times the length (`thin_arc.size_problem`).

Several outlines, outlines with holes, other closed outlines, lines with other curves or with a corner next to an
arc, two ways, To a face or through all and a taper are left out with their reasons.
"""
import math

from ..capture_model import gap_hints
from ..capture_model.capture import same_body
from ..design_model import reach, roles
from ..design_model.problem import is_problem
from ..design_model.steps import thin as facts
from ..design_model.steps import thin_arc
from ..design_model.values import Quantity
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, ExtrudeEnd, FeatureType, SketchShape
from . import causes, extents, limits, tools
from .context import Body
from .sketch_sizes import profile_sizes, sketch_doubts, sketch_formulas
from .sketches import Outline, SketchOut, circle_of, outline_sketch, outlines_of, rectangle_of
from .skip import Skip
from .solid import ADD, CUT, INTERSECT, Prism, Solid
from .steps import extrude_sides, misses_reason

_MODES = {"join": BooleanMode.ADD, "cut": BooleanMode.CUT, "intersect": BooleanMode.INTERSECT}
_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}
# The two outlines of a closed wall, as moves of the drawn outline outward by a share of the thickness.
_OFFSETS = {"inside": (0.0, -1.0), "outside": (1.0, 0.0), "middle": (0.5, -0.5)}
# A wall thinner than this (mm) between the outer and the inner outline is no wall.
_GAP = 1e-6

_SHAPE = ("A thin extrude is copied to Orca only for one rectangle, one circle or a line of lines and arcs, so this "
          "one is left out.")
_ROUNDED = ("The wall of this thin extrude has rounded corners in Fusion, and the Orca copy builds sharp ones, so it "
            "is left out.")
_UNREAD = "The outline of this thin extrude could not be read."


def _label(item):
    return item.get("name") or "the step"


def extrude(ctx, step):
    """The Orca features of a thin extrude (`step`, a `design.ResolvedStep`), or a Skip."""
    item, data = step.brought, step.brought_data
    operation = data.get("operation")
    wall = facts.wall_of(data)
    if is_problem(wall):
        return Skip.of(wall)
    if operation not in _SOLID_MODES:
        return Skip("This kind of extrude is not copied.")
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    if operation == "cut" and roles.new_bodies(item, [ctx.target]):
        return Skip("This cut splits the part into pieces, which is not copied to Orca yet.")
    profiles = data.get("profiles") or []
    if facts.is_line(profiles):
        return _line(ctx, item, data, wall)
    return _closed(ctx, item, data, wall, profiles)


def _frame_at(frame, shift):
    return dict(frame, origin=vec.add(frame["origin"], vec.scale(vec.unit(frame["z"]), shift)))


def _one_side(ctx, item, data, frame):
    """`(shift, side)`: where the extrude starts along the sketch normal and its one `steps` side, or a Skip."""
    shift = extents.start(ctx, item, data, frame)
    if isinstance(shift, Skip):
        return shift
    sides = extrude_sides(ctx, item, data, frame, shift)
    if isinstance(sides, Skip):
        return sides
    if len(sides) != 1 or sides[0].end not in (ExtrudeEnd.BLIND, ExtrudeEnd.SYMMETRIC) or sides[0].through:
        return Skip("A thin extrude is copied to Orca only with a distance one way or symmetric.")
    return shift, sides[0]


def _plane_doubts(ctx, item, profile):
    ctx.doubt(tuple(reach.sketch_plane_sizes(ctx.table, ctx.capture.get("items") or [], item, profile)),
              "%s: its sketch sits on a plane or face that moves with it, and Orca cannot move a sketch plane with a "
              "variable" % _label(item))


def _extrude(ctx, made, name, side, mode):
    """Write the Orca sketch `made` (a SketchOut whose bound fields hold `Quantity`s) and its extrude."""
    sketch_ref = ctx.add(made.feature)
    for field, value in made.bound.items():
        ctx.bind(made.feature, field, value, "%s %s" % (made.feature.name, field))
    feature = tools.feature(FeatureType.EXTRUDE, name, sketch_ref=sketch_ref, mode=mode)
    if mode == BooleanMode.CUT and side is None:
        feature.extrude_end, feature.flip = ExtrudeEnd.THROUGH_ALL, False
    else:
        feature.extrude_end, feature.flip = side.end, side.flip
        feature.symmetric = side.end == ExtrudeEnd.SYMMETRIC
        ctx.bind(feature, "distance", side.distance, "%s distance" % name)
    ctx.add(feature)
    return [made.feature, feature]


def _heights(side):
    low, high = side.ends()
    return low.n, high.n


# ---- a closed rectangle or circle --------------------------------------------------------------------------------

def _closed(ctx, item, data, wall, profiles):
    if any(p.get("kind") == "other" and "loops" not in p for p in profiles):
        return Skip("The open line of this thin extrude could not be read, so it is not copied.",
                    gap_hints.THIN_OUTLINE)
    if len(profiles) > 1:
        return Skip("A thin extrude of several outlines is not copied to Orca yet.", gap_hints.THIN_OUTLINE)
    profile = profiles[0]
    if profile.get("face") or profile.get("text") or profile.get("foreign") or not isinstance(
            profile.get("frame"), dict):
        return Skip(_SHAPE, causes.THIN_SHAPE)
    outline = outlines_of(profile)
    if outline is None:
        return Skip(_UNREAD)
    if outline.holes:
        return Skip("A thin extrude of an outline with holes is not copied to Orca yet.", gap_hints.THIN_OUTLINE)
    if rectangle_of(outline.outer) is None and circle_of(outline.outer) is None:
        return Skip(_SHAPE, causes.THIN_SHAPE)
    decided = facts.closed_side(outline.outer, wall, data.get("end_area"))
    if is_problem(decided):
        return Skip.of(decided)
    side_name, _ = decided
    if not facts.area_fits(outline.outer, side_name, wall["thickness"], facts.SHARP, data.get("end_area")):
        return Skip(_ROUNDED)
    found = _one_side(ctx, item, data, profile["frame"])
    if isinstance(found, Skip):
        return found
    shift, side = found
    frame = _frame_at(profile["frame"], shift)
    name = _label(item)
    base = outline_sketch(outline, frame, ctx.place, sketch_formulas(ctx, profile), name + " sketch")
    if base is None:
        return Skip(_UNREAD)
    if base.moves:
        base.notes.append("%s keeps its numbers: Fusion moves it as it changes, and Orca draws it about its centre"
                          % base.feature.name)
        base.bound = {}
    thickness = ctx.quantity(item, "thin.thickness", wall["thickness"])
    outer_share, inner_share = _OFFSETS[side_name]
    outer = _moved(base, outline.outer, thickness.scaled(outer_share) if outer_share else Quantity(0.0),
                   name + " outer sketch")
    inner = _moved(base, outline.outer, thickness.scaled(inner_share) if inner_share else Quantity(0.0),
                   name + " inner sketch")
    low, high = _heights(side)
    walls = Solid([(ADD, Prism(frame, [outer[1]], low, high)), (CUT, Prism(frame, [inner[1]], -math.inf, math.inf))])
    if _must_meet(data) and not ctx.solid.meets(walls):
        return Skip(*misses_reason(ctx, "cut" if data["operation"] == "cut" else "intersect"))
    _plane_doubts(ctx, item, profile)
    sketch_doubts(ctx, item, [(profile, outline)], [(base, Outline(outline.outer, []), profile)])

    mode = _MODES.get(data["operation"], BooleanMode.ADD)
    out = []
    if ctx.has_body:
        tool = ctx.push(Body(None, name + " wall"))
        try:
            out += _wall(ctx, name, outer[0], inner[0], side, walls)
        finally:
            ctx.pop()
        out.append(tools.boolean(ctx, tool, mode, name))
    else:
        out += _wall(ctx, name, outer[0], inner[0], side, walls)
    _guard(ctx, item, outer[0], inner[0])
    return out


def _must_meet(data):
    """True when the step must meet the part: Orca stops its rebuild on a cut that removes nothing."""
    return data.get("operation") in ("cut", "intersect")


def _wall(ctx, name, outer, inner, side, walls):
    """The outer outline as a new body and the inner outline cut through all of it, on the innermost body."""
    out = _extrude(ctx, outer, name, side, BooleanMode.NEW)
    ctx.has_body = True
    out += _extrude(ctx, inner, name + " inside", None, BooleanMode.CUT)
    for mode, shape in walls.pieces:
        ctx.solid.add(mode, shape)
    return out


def _moved(base, curves, by, sketch_name):
    """`(SketchOut, loop)`: the plain rectangle or circle of `base` moved outward by the Quantity `by` (inward when
    below zero), its sizes as `Quantity`s, and the moved loop as capture curves in the sketch plane."""
    drawn = base.feature
    made = SketchOut(tools.feature(FeatureType.SKETCH, sketch_name, shape=drawn.shape, plane=drawn.plane),
                     base.shape)
    if drawn.shape == SketchShape.CIRCLE:
        centre, radius = circle_of(curves)
        made.bound["radius"] = _size(base, "radius", radius).plus(by)
        return made, [{"kind": "circle", "center": list(centre), "radius": radius + by.n}]
    centre, (ux, uy), width, height = rectangle_of(curves)
    made.bound["width"] = _size(base, "width", width).plus(by.scaled(2.0))
    made.bound["height"] = _size(base, "height", height).plus(by.scaled(2.0))
    hw, hh = width / 2.0 + by.n, height / 2.0 + by.n
    corners = [(centre[0] + a * ux - b * uy, centre[1] + a * uy + b * ux)
               for a, b in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
    ring = zip(corners, corners[1:] + corners[:1])
    return made, [{"kind": "line", "start": list(a), "end": list(b)} for a, b in ring]


def _size(base, field, number):
    """The drawn size `field` of `base` as a Quantity: its formula when the sketch gives one, else its number."""
    found = base.bound.get(field)
    return Quantity(number, found[0], found[1]) if found else Quantity(number)


def _guard(ctx, item, outer, inner):
    """Tell how far the variables may go while the inner outline stays inside the outer one and above zero: past
    that, Orca builds no wall or a solid block without an error."""
    fields = [(sketch, field, "%s %s" % (sketch.name, field)) for field in ("width", "height", "radius")
              for sketch in (outer.feature, inner.feature) if field in sketch.expr]
    if not fields:
        return
    keys = [(id(f), n) for f, n, _ in fields]
    pairs = [((id(outer.feature), n), (id(inner.feature), n)) for n in ("width", "height", "radius")]

    def ok(numbers):
        values = dict(zip(keys, numbers))
        return limits.stop(all(values[a] - values[b] > _GAP for a, b in pairs if a in values and b in values),
                           limits.SHAPE_ZERO)

    limits.guard(ctx, fields, ok, "%s: the Orca copy cannot tell how far this may change before the wall is gone"
                 % _label(item))


# ---- an open line ---------------------------------------------------------------------------------------------

def _line(ctx, item, data, wall):
    line = facts.line_of(data)
    if is_problem(line):
        return Skip.of(line)
    problem = facts.shape_problem(line, 0.0, 0.0)
    if problem:
        return Skip("The wall of this thin extrude does not follow its line: %s." % problem, gap_hints.THIN_OUTLINE)
    found = _one_side(ctx, item, data, line.frame)
    if isinstance(found, Skip):
        return found
    shift, side = found
    frame = _frame_at(line.frame, shift)
    thickness = wall["thickness"]
    if wall.get("decided") in facts.SWAPPED:
        # A step written as a thin extrude (a rib or web) whose side its own handler found from what Fusion made.
        side_name = wall["decided"]
    else:
        side_name = facts.line_side(line, wall["location"], thickness, data.get("wall_faces"), frame["origin"],
                                    side.distance.n, side.end == ExtrudeEnd.SYMMETRIC, -1 if side.flip else 1,
                                    faces_of_part(ctx, data))
    if is_problem(side_name):
        return Skip.of(side_name)
    problem = facts.shape_problem(line, *facts.reaches(side_name, thickness))
    if problem:
        return Skip("The wall of this thin extrude does not follow its line: %s." % problem, gap_hints.THIN_OUTLINE)
    name = _label(item)
    loop = facts.wall_curves(line, side_name, thickness)
    if line.curved:
        found = thin_arc.size_problem(item, data, loop, side.distance.n)
        if found is not None:
            return Skip.of(found)
    low, high = _heights(side)
    shape = Prism(frame, [loop], low, high)
    if _must_meet(data) and not ctx.solid.meets(shape):
        return Skip(*misses_reason(ctx, "cut" if data["operation"] == "cut" else "intersect"))
    path = line.path
    _plane_doubts(ctx, item, path)
    drawn = [{"kind": "line", "start": list(a), "end": list(b)} for a, b in zip(line.points, line.points[1:])]
    if side_name == "middle" and not line.curved and len(line.points) == 2:
        made = _centred(ctx, item, line, frame, thickness, name + " sketch")
        sketch_doubts(ctx, item, [(path, Outline(drawn, []))], [(_formulas_view(made), Outline(drawn, []), path)])
    else:
        made = outline_sketch(Outline(loop, []), frame, ctx.place, None, name + " sketch")
        if made is None:
            return Skip(_UNREAD)
        ctx.doubt(ctx.quantity(item, "thin.thickness", thickness).reads,
                  "%s: Orca draws the wall along its line with this thickness as a number" % name)
        ctx.doubt(profile_sizes(ctx, path), "%s: Orca draws the wall along its line as it is now, so its line keeps "
                  "its place and length" % name)
    mode = _MODES.get(data["operation"], BooleanMode.ADD) if ctx.has_body else BooleanMode.NEW
    out = _extrude(ctx, made, name, side, mode)
    ctx.has_body = True
    ctx.solid.add(_SOLID_MODES[data["operation"]], shape)
    if made.bound:
        limits.guard(ctx, [(made.feature, f, "%s %s" % (made.feature.name, f)) for f in made.bound], lambda n: True,
                     "%s: the Orca copy cannot tell how far this may change before the wall is gone" % name)
    return out


def faces_of_part(ctx, data):
    """The faces of the part before the step (`target_faces_before`) when they are the faces of the body the copy
    builds, else None: while a tool body is built, a face of the part proves nothing about a face of the tool."""
    body = data.get("target_faces_body")
    if len(ctx.scopes) > 1 or not isinstance(body, dict) or not same_body(body, ctx.target):
        return None
    return data.get("target_faces_before")


def _centred(ctx, item, line, frame, thickness, sketch_name):
    """A SketchOut of the Orca rectangle centred on the one straight line of `line`, as long as the line and
    `thickness` wide; its length follows the sketch when the line keeps its middle and its direction, and its width
    follows the thickness. Bound fields hold `Quantity`s."""
    a, b = line.points
    length = math.dist(a, b)
    u = [(b[0] - a[0]) / length, (b[1] - a[1]) / length]
    middle = [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
    x3 = [frame["x"][i] * u[0] + frame["y"][i] * u[1] for i in range(3)]
    y3 = [-frame["x"][i] * u[1] + frame["y"][i] * u[0] for i in range(3)]
    origin = [frame["origin"][i] + frame["x"][i] * middle[0] + frame["y"][i] * middle[1] for i in range(3)]
    feature = tools.feature(FeatureType.SKETCH, sketch_name, shape=SketchShape.RECTANGLE,
                            plane=ctx.place.plane(origin, x3, y3, frame["z"]), width=length, height=thickness)
    made = SketchOut(feature, "rectangle")
    made.bound["height"] = ctx.quantity(item, "thin.thickness", thickness)
    made.bound["width"] = Quantity(length)
    formulas = sketch_formulas(ctx, line.path)
    ends = [formulas.point(tuple(p)) for p in (a, b)] if formulas is not None else [None]
    if any(end is None for end in ends):
        if formulas is not None and formulas.why:
            made.notes.append("%s keeps its length: %s." % (sketch_name, formulas.why))
        return _sized(made)
    (ax, ay), (bx, by) = ends
    dx, dy = bx - ax, by - ay
    across = formulas.over_sizes(dx.scaled(-u[1]) + dy.scaled(u[0]))
    if across is None or not across.is_constant:
        made.notes.append("%s keeps its length: its line turns when the sizes change." % sketch_name)
        return _sized(made)
    moves = {}
    for expr in ((ax + bx).scaled(0.5), (ay + by).scaled(0.5)):
        over = formulas.over_sizes(expr)
        if over is None:
            made.notes.append("%s keeps its length: the copy cannot work out the middle of its line." % sketch_name)
            return _sized(made)
        if not over.is_constant:
            moves.update(dict.fromkeys(formulas.free_reads(over)))
    if moves:
        made.moves = tuple(moves)
        return _sized(made)
    found = formulas.sized(dx.scaled(u[0]) + dy.scaled(u[1]), length)
    if found is not None:
        made.bound["width"] = Quantity(length, found[0], found[1])
    return _sized(made)


def _formulas_view(made):
    """`made` as `sketch_sizes.sketch_doubts` reads it: each bound field as (formula, Fusion names it reads)."""
    view = SketchOut(made.feature, made.shape)
    view.bound = {field: (q.text, q.reads) for field, q in made.bound.items()}
    view.notes, view.moves = made.notes, made.moves
    return view


def _sized(made):
    """`made` with only the bound fields that follow sizes."""
    made.bound = {field: q for field, q in made.bound.items() if q.sized}
    return made
