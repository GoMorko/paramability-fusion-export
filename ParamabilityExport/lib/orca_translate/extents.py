"""Extrude extents of the Orca copy beyond a plain distance: an end on a face or plane ("To"), a start on a face or
plane ("From"), and a taper. `steps.extrude` asks these; each answer is a value to write or a `Skip`. The shared
reader (`design_model/steps/extrude.py`) reads the start, the sides and the planes; this module makes them follow sizes
where Orca can.

Orca's Extrude ends at a distance (blind, symmetric, two sides) or goes through all. Its "up to face" names a face by
Orca's own numbering of the body it rebuilt, which the copy cannot know, so a face or plane becomes a distance:

- To a face or plane (`reach`): a blind side as long as the measured distance from where the extrude starts to that
  plane, plus Fusion's offset from it. When sizes move the plane in a way the copy follows (`plane_move`), the length
  is a formula: the plane's move along the extrude is added to it, so the end stays where Fusion puts it. A plane
  follows what it is built on: an origin plane stays, an offset plane moves with its own distance and with its base,
  and a face follows the end of a copied extrude it lies on (`solid.Prism.ends`). Sizes that may move the plane in any
  other way leave the length a number, and those sizes are marked.
- From a face or plane (`start`): the sketch plane is moved to that plane. Orca cannot move a sketch plane with
  a variable, so the shift is a number and the sizes that move the face are marked.
- Limits (`guard`): Orca variables have no ranges, and past some values Orca builds these extrudes wrong without an
  error: a "To" length at zero or below extrudes the other way, and a taper that shrinks a side of its outline to
  nothing builds a straight extrude. The parameter's line says how far each variable may go; a field whose limit
  cannot be told keeps its number.
- Taper (`taper`): Orca moves the outline in its plane by the length times the tangent of `taper_deg` and lofts the
  two outlines, for a blind extrude of one loop without holes. Its move rounds the corners it pushes outward, and a
  loft between arcs whose ends slide along them twists the wall. So a taper is copied only when Fusion's and Orca's
  walls are the same (`taper_gap`): a full circle, or an outline whose sharp corners all join two lines and point
  away from the move (convex corners when the outline shrinks, inward corners when it grows). Checked live with
  OrcaSlicer 2.5.1: a shrinking rectangle and triangle, and a circle either way, gave the exact volumes; a growing
  rectangle and two arcs meeting at corners did not.
"""
import math

from ..capture_model import gap_hints
from ..capture_model.capture import same_body
from ..geometry import vec
from ..geometry.footprint import arc_span, is_full, polyline
from ..orca_recipe.enums import SketchShape
from ..params.expressions.text import format_number
from ..design_model import refs
from ..design_model.reach import construction_sizes, offset_param, on_part, reach_sizes
from ..design_model.problem import is_problem
from ..design_model.steps import extrude as dm
from . import causes, limits
from ..design_model.values import Quantity
from ..design_model import words as shared
from .skip import Skip
from .solid import Prism

# A plane this close to where the extrude starts (mm) gives it no length.
_SIGN_TOL = 1e-9
# A point this near (mm) to a shape lies on it.
_LENGTH_TOL = 1e-3
# A plane offset this close (mm) to its measured distance from its base has that sign.
_OFFSET_TOL = 1e-5
# A junction of two curves whose directions differ by less than this (radians) is smooth, not a corner.
_SMOOTH = 1e-4
# Orca builds a straight extrude for a taper of 89 degrees or more; steeper than this is not copied.
_TAPER_MAX = 80.0
# An edge or arc of the moved outline at the far end must keep at least this size (mm).
_KEEP = 0.05

_AXES = ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0])


def _label(item):
    return item.get("name") or "the step"


# ---- values ------------------------------------------------------------------------------------------------------

class Reach(Quantity):
    """The length of a side that ends on a face or plane ("To"). Orca extrudes the other way when a variable takes
    it to zero or below, where Fusion stops."""


def change(value):
    """How a value moves from its number now: zero, with the formula `value - number` when sizes move it."""
    if value.text is None:
        return Quantity(0.0)
    return Quantity(0.0, "(%s) - %s" % (value.text, format_number(value.n)), value.reads)


# ---- how a face or plane moves -------------------------------------------------------------------------------------

def plane_move(ctx, item, record, z, what):
    """How the face or plane `record` (a capture TARGET: an extrude's `start`, `side_one` or `side_two`) moves along
    the unit sketch normal `z` when sizes change: a Quantity of zero whose formula is that move (none when it stays), or
    None when sizes may move it in a way the copy cannot follow. Those sizes are then marked; `what` words the reason
    ("reaches to", "starts from")."""
    if ctx.table is None:
        return Quantity(0.0)
    found = _move(ctx, item, record, z)
    if found is not None:
        return found
    names = reach_sizes(ctx.table, ctx.capture.get("items") or [], item, record)
    if not names:
        return Quantity(0.0)
    ctx.doubt(names, "%s %s a face or plane that may move with it, and the Orca copy cannot follow that"
              % (_label(item), what))
    return None


def _move(ctx, item, record, z):
    if record.get("origin"):
        return Quantity(0.0)
    if record.get("assembly"):
        # A face or plane of another component stays where the capture places it; the walk marks the sizes that act
        # on its component (`other_components.mark_refs`).
        return Quantity(0.0)
    if record.get("foreign"):
        return None
    kind = record.get("entity_type")
    if kind == "ConstructionPlane":
        return _plane(ctx, item, record, z)
    if kind == "BRepFace":
        return _face(ctx, item, record, z)
    return None


def _plane_of(record):
    plane = record.get("plane") if isinstance(record.get("plane"), dict) else record
    return plane.get("point"), plane.get("normal")


def _plane(ctx, item, record, z):
    """A construction plane: one made from parameters alone stays (unless a size sets one of them); an offset plane
    moves with its base and with its own distance when one size sets it (`sizes.offset_param`). A record that does
    not say what the plane is built on (an older capture) cannot be followed."""
    if "definition" not in record and "built_on" not in record:
        return None
    # A plane without a token stands for every construction plane.
    own = construction_sizes(ctx.table, "constructionPlane", record.get("token") or "")
    if not _chain_sizes(ctx.table, record) and not on_part(record):
        return Quantity(0.0)
    base = record.get("built_on") or []
    if "offset" not in (record.get("definition") or "").lower() or len(base) != 1:
        return None
    under = _move(ctx, item, base[0], z)
    if under is None:
        return None
    param = offset_param(ctx.table, record)
    if param is None:
        return None if own else under
    point, normal = _plane_of(record)
    base_point = [0.0, 0.0, 0.0] if base[0].get("origin") else (
        base[0].get("face_point") or _plane_of(base[0])[0])
    if not point or not normal or not base_point:
        return None
    distance = float(param["value"]) * 10.0
    measured = vec.dot(vec.sub(point, base_point), vec.unit(normal))
    if abs(distance) <= _OFFSET_TOL:
        return None
    if abs(measured - distance) <= _OFFSET_TOL:
        sign = 1.0
    elif abs(measured + distance) <= _OFFSET_TOL:
        sign = -1.0
    else:
        return None
    own_item = {"name": item.get("name"), "data": {"params": {"plane.offset": {
        "name": param["name"], "expression": param["expression"], "value": distance}}}}
    q = ctx.quantity(own_item, "plane.offset", distance)
    return under.plus(change(q).scaled(sign * vec.dot(vec.unit(normal), z)))


def _chain_sizes(table, record):
    """The ticked sizes behind a construction plane and the construction planes it is built on."""
    found = set()
    pending = [record]
    while pending:
        entry = pending.pop()
        if isinstance(entry, dict) and entry.get("entity_type") == "ConstructionPlane":
            found |= set(construction_sizes(table, "constructionPlane", entry.get("token") or ""))
            pending.extend(entry.get("built_on") or ())
    return found


def _face(ctx, item, record, z):
    """A flat face on an end face of a copied extrude follows that end's length (`solid.Prism.ends`)."""
    point = record.get("face_point")
    if record.get("surface") not in (None, "Plane") or not point:
        return None
    found = _cap(ctx, record, point)
    if found is None:
        return None
    prism, end = found
    k = vec.dot(prism.z, z)
    if abs(abs(k) - 1.0) > 1e-9:
        return None
    if prism.plane_sizes:
        ctx.doubt(prism.plane_sizes, "%s uses a face whose sketch plane moves with it, and Orca cannot move a sketch "
                  "plane with a variable" % _label(item))
    return change(end).scaled(1.0 if k > 0 else -1.0)


def _cap(ctx, record, point):
    """(prism, Quantity of the end) for the end face of a copied extrude that `point` lies on, when no later shape of
    that body touches the point; else None."""
    owner = record.get("body")
    bodies = []
    for body in list(ctx.scopes) + list(ctx.bodies):
        if body in bodies:
            continue
        if owner is None and body is not ctx.scope:
            continue
        if owner is not None and not (body.target and same_body(body.target, owner)):
            continue
        bodies.append(body)
    for body in bodies:
        for _, shape in reversed(body.solid.pieces):
            if isinstance(shape, Prism) and shape.ends is not None:
                end = shape.cap_at(point)
                if end is not None:
                    return shape, shape.ends[end]
            if _touches(shape, point):
                break
    return None


def _touches(shape, point):
    """True when `point` lies in or on `shape`."""
    for axis in _AXES:
        for t0, t1 in shape.span(point, axis):
            if t0 - _LENGTH_TOL <= 0.0 <= t1 + _LENGTH_TOL:
                return True
    return False


# ---- From and To --------------------------------------------------------------------------------------------------

def reader_skip(found, item):
    """The Skip of a Problem of the extrude reader (`dm.start_of`, `dm.read_sides`). A face or plane of another
    component that stays foreign gets the shared sentence of why it cannot be placed, a curved face or one of no known
    place (`refs.why_foreign`, as `ResolvedStep.why_foreign` gives it for the step)."""
    if found.code == dm.FOREIGN:
        why = refs.why_foreign(item)
        if why:
            return Skip(why, found.cause or gap_hints.REFUSED)
    return Skip.of(found)


def start(ctx, item, data, frame):
    """How far along the sketch normal (mm) the extrude starts from its sketch plane (`dm.start_of`), or a Skip. The
    sizes that move a start offset, or the face or plane it starts from, are marked: Orca keeps the sketch plane in
    place."""
    found = dm.start_of(data, frame)
    if is_problem(found):
        return reader_skip(found, item)
    if found.kind == dm.OFFSET and found.shift:
        ctx.doubt(ctx.quantity(item, found.path, found.shift).reads,
                  "%s starts away from its sketch, and Orca cannot move a sketch with a variable" % _label(item))
    if found.kind == dm.FACE:
        move = plane_move(ctx, item, found.target.record, vec.unit(frame["z"]), "starts from")
        if move is not None and move.text is not None:
            ctx.doubt(move.reads, "%s starts from a face or plane that moves with it, and Orca cannot move a sketch "
                      "plane with a variable" % _label(item))
    return found.shift


def reach(ctx, item, side, z):
    """The length of a side that reaches to a face or plane (a `dm.SidePlan` of kind REACH) as a `Reach` that follows
    the plane where the copy can: the measured distance from where the extrude starts to the plane along the unit
    sketch normal `z`, plus Fusion's offset."""
    offset = ctx.quantity(item, side.offset_path, side.offset)
    move = plane_move(ctx, item, side.reach.record, z, "reaches to")
    length = Quantity(abs(side.reach.distance)).plus(offset)
    if move is not None:
        length = length.plus(move.scaled(side.sign))
    return Reach(length.n, length.text, length.reads)


# ---- limits -------------------------------------------------------------------------------------------------------

def guard(ctx, sketch, feature, side, outer):
    """Tell how far the variables of one written extrude may go before Orca builds it wrong without an error: a "To"
    length (`Reach`) must stay above zero, and a tapered outline must keep every side (`taper_gap`). `sketch` is
    the Orca sketch feature, `feature` the Orca extrude, `side` the `steps._Side` it was written from and `outer`
    the outer loop drawn (capture curves). The outline follows the bound `width`, `height` or `radius` of a plain
    rectangle or circle, else it keeps its curves."""
    reaches = (isinstance(side.distance, Reach), isinstance(side.distance2, Reach))
    tapered = bool(feature.taper_deg) or "taper_deg" in feature.expr
    if not (any(reaches) or tapered):
        return
    name, drawn = feature.name, sketch.name
    fields = [(feature, "distance", "%s distance" % name), (feature, "distance2", "%s second side" % name),
              (feature, "taper_deg", "%s taper" % name), (sketch, "width", "%s width" % drawn),
              (sketch, "height", "%s height" % drawn), (sketch, "radius", "%s radius" % drawn)]

    def ok(numbers):
        distance, distance2, taper_deg, width, height, radius = numbers
        if reaches[0] and not distance > _SIGN_TOL or reaches[1] and not distance2 > _SIGN_TOL:
            return False
        if not tapered or not taper_deg:
            return True
        deg = -taper_deg if feature.flip else taper_deg
        if abs(deg) >= _TAPER_MAX or distance <= 0:
            return False
        loop = drawn_loop(sketch, outer, width, height, radius)
        return not isinstance(taper_gap(loop, deg > 0, distance * math.tan(math.radians(abs(deg)))), str)

    limits.guard(ctx, fields, ok, "%s: the Orca copy cannot tell how far this may change before Orca builds the "
                 "extrude wrong" % name)


def drawn_loop(sketch, outer, width, height, radius):
    """The outer loop Orca draws for `sketch` with these sizes: a plain rectangle or circle about its plane's origin,
    else the drawn curves `outer`."""
    if sketch.entities:
        return outer
    if sketch.shape == SketchShape.CIRCLE:
        return [{"kind": "circle", "center": [0.0, 0.0], "radius": radius}]
    hw, hh = width / 2.0, height / 2.0
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return [{"kind": "line", "start": list(corners[n]), "end": list(corners[(n + 1) % 4])} for n in range(4)]


# ---- taper --------------------------------------------------------------------------------------------------------

def taper(ctx, item, path, deg, flip, outline, length):
    """The Orca `taper_deg` of a blind side whose Fusion taper is `deg` (degrees; positive widens the outline going
    away from the sketch), as a Quantity; None for no taper; or a Skip. `flip` says the side runs against the sketch
    normal (Orca then moves the outline the other way for the same angle), `outline` is the `sketches.Outline` and
    `length` the side's length now (mm). A taper whose sign a size could turn keeps its number when the outline has
    sharp corners, since Orca would then round them."""
    if deg is None:
        return Skip(shared.EXTRUDE_UNREADABLE)
    if not deg:
        return None
    if abs(deg) >= _TAPER_MAX:
        return Skip("The taper of this extrude is too steep to copy to Orca.", gap_hints.TAPER_STEEP)
    if outline.holes:
        return Skip("Orca cannot taper an outline with holes, so this extrude is left out.", causes.TAPER_SHAPE)
    found = taper_gap(outline.outer, deg > 0, length * math.tan(math.radians(abs(deg))))
    if isinstance(found, str):
        return Skip(found, causes.TAPER_SHAPE)
    q = ctx.quantity(item, path, float(deg), "angle")
    if q.text is not None and found:
        ctx.doubt(q.reads, "%s: the taper stays a number in Orca, since the other way Orca would round the corners "
                  "of its outline" % _label(item))
        q = Quantity(float(deg))
    return q.scaled(-1.0 if flip else 1.0)


def taper_measured(data, sides, outlines):
    """A Skip when the tapers of an extrude's sides (`steps._Side`: `taper` in Fusion's degrees, `flip`) disagree
    with the walls Fusion measured (`side_leans`, else the end face area of one outline), or cannot be checked; else
    None. The same check as for a recipe (`design_model.steps.extrude.taper_problem`)."""
    if not any(side.taper for side in sides):
        return None
    plan = [dm.SidePlan(dm.DISTANCE, "", -1 if side.flip else 1, Quantity(side.distance.n), side.taper)
            for side in sides]
    found = dm.taper_problem(plan, data, data.get("operation"), outlines)
    return Skip.of(found) if found is not None else None


def _ends(curve):
    """(start, direction at start, end, direction at end) of a line or arc, in the order its points run."""
    if curve["kind"] == "line":
        a, b = curve["start"], curve["end"]
        d = _unit2((b[0] - a[0], b[1] - a[1]))
        return a, d, b, d
    c, r = curve["center"], curve["radius"]
    a0, sweep = arc_span(curve)
    turn = 1.0 if sweep > 0 else -1.0
    a1 = a0 + sweep
    return ((c[0] + r * math.cos(a0), c[1] + r * math.sin(a0)), (-turn * math.sin(a0), turn * math.cos(a0)),
            (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1)), (-turn * math.sin(a1), turn * math.cos(a1)))


def _unit2(d):
    n = math.hypot(d[0], d[1])
    return (d[0] / n, d[1] / n) if n > 0 else (0.0, 0.0)


def _chain(curves):
    """The curves of one closed loop in running order, each `(curve, reversed)`; None when a curve is not a line or
    an arc, or the loop does not close."""
    if any(c.get("kind") not in ("line", "arc") for c in curves):
        return None
    left = list(curves)
    out = [(left.pop(0), False)]
    while left:
        last, back = out[-1]
        here = _ends(last)[0 if back else 2]
        for n, c in enumerate(left):
            ends = _ends(c)
            if math.dist(ends[0], here) <= 1e-5:
                out.append((left.pop(n), False))
                break
            if math.dist(ends[2], here) <= 1e-5:
                out.append((left.pop(n), True))
                break
        else:
            return None
    first, back = out[0]
    last, last_back = out[-1]
    if math.dist(_ends(first)[2 if back else 0], _ends(last)[0 if last_back else 2]) > 1e-5:
        return None
    return out


def _oriented(curve, back):
    """(start, direction at start, end, direction at end) of a curve run forward or backward."""
    a, da, b, db = _ends(curve)
    return (b, (-db[0], -db[1]), a, (-da[0], -da[1])) if back else (a, da, b, db)


def taper_gap(loop, grows, move):
    """Why Orca's taper would not build the walls Fusion builds for the outline `loop` (capture curves) moved by
    `move` mm at the far end (outward when `grows`), as one plain sentence; else the number of sharp corners (0 means
    the outline is smooth, and a taper either way gives the same walls)."""
    if len(loop) == 1 and loop[0].get("kind") == "circle" or (len(loop) == 1 and is_full(loop[0])):
        radius = float(loop[0]["radius"])
        if not grows and radius - move < _KEEP:
            return "The taper of this extrude would shrink its circle to nothing, so it is not copied to Orca."
        return 0
    chain = _chain(loop)
    if chain is None:
        return "Orca can taper only an outline of lines and arcs, so this extrude is left out."
    points = [p for c, back in chain for p in (polyline(c)[::-1] if back else polyline(c))]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2.0
    ccw = 1.0 if area > 0 else -1.0
    runs = [_oriented(c, back) for c, back in chain]
    turns = []
    for n, (curve, _) in enumerate(chain):
        incoming, outgoing = runs[n - 1][3], runs[n][1]
        cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
        dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
        angle = math.atan2(cross, dot) * ccw  # positive at a convex corner
        sharp = abs(angle) > _SMOOTH
        if sharp and (curve["kind"] != "line" or chain[n - 1][0]["kind"] != "line"):
            return ("This tapered outline has a sharp corner at an arc, and Orca's taper twists the wall there, so "
                    "it is not copied to Orca.")
        if sharp and (angle > 0) == grows:
            return ("This tapered outline has corners that Orca would round off, so it is not copied to Orca." if grows
                    else "This tapered outline has inward corners that Orca would round off, so it is not copied to "
                         "Orca.")
        turns.append(angle if sharp else 0.0)
    outward = move if grows else -move
    for n, (curve, back) in enumerate(chain):
        if curve["kind"] == "line":
            kept = math.dist(curve["start"], curve["end"]) + outward * (
                math.tan(turns[n] / 2.0) + math.tan(turns[(n + 1) % len(chain)] / 2.0))
        else:
            convex = (arc_span(curve)[1] > 0) != back
            convex = convex if ccw > 0 else not convex
            kept = float(curve["radius"]) + (outward if convex else -outward)
        if kept < _KEEP:
            return "The taper of this extrude would shrink a side of its outline to nothing, so it is not copied."
    return sum(1 for t in turns if t)
