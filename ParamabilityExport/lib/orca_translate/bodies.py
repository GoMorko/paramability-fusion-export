"""Split Body and Move steps as Orca Cut and Transform features.

Split Body: the part keeps one piece of the split and the other pieces go their own way, so only the removal of the
far side is copied.
- By a plane (a construction plane or a flat face): Orca's Cut by that plane, keeping the side the part lies on
  (`cut_keep_upper` or `cut_keep_lower`). The capture must show the part's piece on one side and every other piece
  of the same body on the other.
- By a solid body: that body is written as a tool (`tools.build`) and the part keeps what lies inside it (an
  intersect) or outside it (a cut), as the capture's `inside` answers say (`split_inside.resolve`).
- Anything else (a curved face, a sketch curve) is left out.
A split is left out too when a later step changes another of its pieces together with the part (`roles.used_later`):
the copy keeps only the part's piece, so what that step brings back would be missing. For a tool body only the steps
before the item that takes the tool count.

Move: the body's first vertices before and after the step give the rigid move (`move.fit`). Orca's Transform turns
about an axis, then moves. A Move that turns about an axis writes that axis and binds `xf_angle_deg` to the angle;
any other move is written as its measured turn and shift. Orca cannot tie a move distance to a variable, so such
sizes keep their numbers.
"""
import math

from ..capture_model import gap_hints, lineage
from ..capture_model.capture import same_body
from ..design_model import roles
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, FeatureType
from ..translator.bodies.move import fit
from ..translator.bodies.split_inside import resolve as inside_of
from . import causes
from .solid import INTERSECT, HalfSpace
from .steps import Skip
from .tools import Pass, boolean, build, data_of, feature, label

# A piece's box may reach this far (mm) past the plane on the side it does not lie on.
SIDE_TOL_MM = 0.01
# A Move that carries the part less than this (mm, and the same in turn) leaves it where it is.
NO_MOVE_MM = 1e-9


def _record(records, body):
    return next((r for r in records or () if isinstance(r, dict) and same_body(r, body)), None)


def _pieces(ctx, item, data):
    """`(parent record, kept piece, other pieces)` of the body the copy builds, or a Skip."""
    chain = lineage.of(ctx.capture)
    before, kept = lineage.at(chain, ctx.capture["target"], item["index"])
    if len(ctx.scopes) > 1:
        before = kept = ctx.target
    parent = _record(data.get("bodies"), before)
    if parent is None:
        return Skip("This split does not list the body it cuts.")
    pieces = [p for p in data.get("pieces") or () if isinstance(p, dict)
              and same_body(lineage.parent_of(item, p) or {}, parent)]
    piece = _record(pieces, kept)
    if piece is None:
        return Skip("The piece of this split that the part comes from was not found.")
    others = [p for p in pieces if p is not piece]
    if not others:
        return Skip("This split leaves the body in one piece.")
    return parent, piece, others


def _used_later(ctx, item, parent, piece):
    """A Skip when a later step changes another piece of the split `item` together with the body the copy builds,
    else None."""
    timeline = ctx.capture["items"]
    if len(ctx.scopes) > 1:
        anchor = (ctx.scope.anchor or {}).get("index")
        timeline = [i for i in timeline if anchor is None or i.get("index", 0) < anchor]
        target, chain = ctx.target, ()
    else:
        target, chain = ctx.capture["target"], lineage.of(ctx.capture)
    for body in roles.other_pieces(item, parent, piece):
        later = roles.used_later(timeline, item, body, target, chain)
        if later is not None:
            return Skip("%s later changes %s, another piece of this split, together with the part. The Orca copy "
                        "keeps only the part's piece, so this split is left out."
                        % (later.get("name") or "A step", body.get("name") or "a body"), causes.PIECE_USED_LATER)
    return None


def split(ctx, item):
    data = data_of(item)
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return Skip("What this split cuts with was not read.")
    if not ctx.has_body:
        return Skip("The part this split cuts is not in the copy.", gap_hints.AFTER_GAP)
    found = _pieces(ctx, item, data)
    if isinstance(found, Skip):
        return found
    parent, piece, others = found
    later = _used_later(ctx, item, parent, piece)
    if later is not None:
        return later
    if tool.get("kind") == "plane":
        return _by_plane(ctx, item, tool, piece, others)
    if tool.get("kind") == "body":
        return _by_body(ctx, item, tool, piece, others)
    return Skip("This split cuts along a curved surface or a line, which is not copied to Orca yet.")


def _by_plane(ctx, item, tool, piece, others):
    plane = tool.get("plane") or {}
    if plane.get("foreign"):
        return Skip("The plane of this split belongs to another component and could not be brought into the part's "
                    "place, which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    point, normal = plane.get("point"), plane.get("normal")
    if not (isinstance(point, (list, tuple)) and isinstance(normal, (list, tuple)) and vec.length(normal) > 1e-9):
        return Skip("The plane of this split could not be read.")
    normal = vec.unit(normal)
    if piece.get("box") is None or any(p.get("box") is None for p in others):
        return Skip("The pieces of this split could not be measured.")
    side = vec.box_side(piece["box"], point, normal, SIDE_TOL_MM)
    sides = [vec.box_side(p["box"], point, normal, SIDE_TOL_MM) for p in others]
    if not side or any(s != -side for s in sides):
        return Skip("This split leaves pieces on both sides of its plane, which is not copied to Orca yet.",
                    causes.SPLIT_SIDES)
    x_axis = vec.unit(vec.cross(normal, [1.0, 0.0, 0.0] if abs(normal[0]) < 0.9 else [0.0, 1.0, 0.0]))
    made = feature(FeatureType.CUT, label(item), plane=ctx.place.plane(point, x_axis, vec.cross(normal, x_axis),
                                                                       normal),
                   cut_keep_upper=side > 0, cut_keep_lower=side < 0, target_body=ctx.scope.index)
    ctx.add(made)
    ctx.solid.add(INTERSECT, HalfSpace(point, vec.scale(normal, float(side))))
    return [made]


def _by_body(ctx, item, tool, piece, others):
    body = tool.get("body") or {}
    if not tool.get("solid"):
        return Skip("This split cuts along a surface, which is not copied to Orca yet.")
    inside = inside_of(body, piece, others)
    if inside is None:
        return Skip("The copy could not tell which pieces of this split lie inside its tool body.")
    start = len(ctx.features)
    mark = ctx.checkpoint()
    made = build(ctx, body, item)
    if isinstance(made, Skip):
        ctx.rollback(mark)
        return made
    boolean(ctx, made, BooleanMode.INTERSECT if inside else BooleanMode.CUT, label(item))
    return ctx.features[start:]


# ---- move ------------------------------------------------------------------------------------------------------

def _axis_angle(rows):
    """`(unit axis, degrees)` of a turn (0 to 180 degrees), or None when it turns nothing."""
    trace = rows[0][0] + rows[1][1] + rows[2][2]
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) / 2.0)))
    if angle < 1e-9:
        return None
    skew = [rows[2][1] - rows[1][2], rows[0][2] - rows[2][0], rows[1][0] - rows[0][1]]
    if vec.length(skew) > 1e-6:
        return vec.unit(skew), math.degrees(angle)
    # A half turn: the axis is the longest column of (rows + I) / 2.
    columns = [[(rows[i][j] + (1.0 if i == j else 0.0)) / 2.0 for i in range(3)] for j in range(3)]
    return vec.unit(max(columns, key=vec.length)), 180.0


def _turns_like(rows, offset, point, axis, degrees):
    """True when the turn about the line through `point` along `axis` is the measured move."""
    for p in ([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
        moved = [sum(rows[i][k] * p[k] for k in range(3)) + offset[i] for i in range(3)]
        if not vec.close(vec.rotate(p, axis, degrees, point), moved, 1e-4):
            return False
    return True


def move(ctx, item):
    data = data_of(item)
    if data.get("input_kind") != "bodies":
        return Skip("A Move of faces is not copied to Orca yet.")
    bodies = data.get("bodies") or []
    at = next((n for n, b in enumerate(bodies) if isinstance(b, dict) and same_body(b, ctx.target)), None)
    if at is None:
        return Pass("It moves another body; this part stays where it is.")
    if not ctx.has_body:
        return Skip("The part this Move carries is not in the copy.", gap_hints.AFTER_GAP)
    before, after = data.get("points_before") or [], data.get("points_after") or []
    motion = fit(before[at] or [], after[at] or []) if at < len(before) and at < len(after) else None
    if motion is None:
        return Skip("The points of the part before and after this Move do not show a turn and a shift.")
    rows = [list(row) for row in motion.rows]
    offset = [q.n for q in motion.shift]
    turn = _axis_angle(rows)
    if turn is None and vec.length(offset) <= NO_MOVE_MM:
        return Pass("It leaves this part where it is.")
    name = label(item)
    made = feature(FeatureType.TRANSFORM, name, target_body=ctx.scope.index)
    used = set()
    axis = data.get("axis") or {}
    angle = data.get("angle_deg")
    if data.get("move_type") == "rotate" and isinstance(angle, (int, float)) and turn is not None \
            and isinstance(axis.get("point"), (list, tuple)) and isinstance(axis.get("dir"), (list, tuple)):
        point, direction = [float(c) for c in axis["point"]], vec.unit(axis["dir"])
        sign = next((s for s in (1.0, -1.0) if _turns_like(rows, offset, point, direction, s * float(angle))), None)
        if sign is None:
            return Skip("The turn this Move names does not match how the part moved.", causes.MOVE_MISMATCH)
        # Orca turns by a positive angle: a negative one turns about the reversed axis, and its formula is negated
        # so that it gives the same turn at every value.
        flip = math.copysign(1.0, float(angle))
        made.xf_pivot, made.xf_axis = ctx.place.point(point), ctx.place.direction(vec.scale(direction, sign * flip))
        ctx.bind(made, "xf_angle_deg", ctx.quantity(item, "angle_deg", float(angle), "angle").scaled(flip),
                 "%s angle" % name)
        used.add("angle_deg")
    else:
        origin = [0.0, 0.0, 0.0]
        made.xf_pivot, made.xf_translate = ctx.place.point(origin), ctx.place.direction(offset)
        if turn is not None:
            made.xf_axis, made.xf_angle_deg = ctx.place.direction(turn[0]), turn[1]
    for path, found in (data.get("params") or {}).items():
        if path not in used and isinstance(found, dict) and found.get("name"):
            ctx.doubt(ctx.depends([found["name"]]), "%s: Orca cannot tie how far a Move carries the part to a "
                      "variable" % name)
    ctx.add(made)
    ctx.solid.moved(rows, offset)
    return [made]


HANDLERS = {"SplitBodyFeature": split, "MoveFeature": move}
