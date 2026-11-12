"""Split Body handler (SplitBodyFeature): the piece the walk follows stays, the other side is removed.

The walk reaches a split only when the body it builds comes out of it as one piece and the other pieces stay apart
(split_rules.py). The body before the split and the piece after it are the lineage's (lineage.py): the same body
when it keeps its token, else the body the split made.

- A split by a plane (a construction plane or a flat face) becomes a cut by a box on the far side: a `toolBody` with
  one extrude of a square on the plane, sized from the body's box with a wide margin. Its plane follows sizes like a
  mirror plane (`follow.place_plane`).
- A split by a solid body becomes a cut by that body when the piece lies outside it, or an intersect when it lies
  inside, written by the Combine machinery (`combine.write_tools`). Fusion keeps the tool body.
- A split by anything else (a curved face, a surface body, a sketch curve) stops the copy.

The capture must show that the piece is the whole of its side: it lies on one side of the plane (or inside or outside
the body) and every other piece of the same body on the other side, and the pieces add up to the body's volume.
Anything that cannot be shown stops the copy, since the body after the split would be unknown.
"""
from . import combine as combine_step, follow, lineage, vec
from .capture import same_body
from .repeat_build import round_vec
from .result import Refusal, StepResult
from .tool_placer import ToolMaker
from .values import Quantity

# A piece's box may reach this far (mm) past the plane on the side it does not lie on.
SIDE_TOL_MM = 0.01
# The pieces of a body add up to its volume within this (mm3), or this share of it.
VOLUME_TOL_MM3 = 0.01
VOLUME_RELATIVE = 1e-6
# The box tool reaches this many times the body's half diagonal past the body, plus a fixed margin (mm), so that the
# part still lies inside it when sizes grow it.
BOX_REACH = 4.0
BOX_MARGIN_MM = 100.0


def _stop(reason):
    return Refusal(reason, stops=True)


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _record(records, body):
    return next((r for r in records or () if isinstance(r, dict) and same_body(r, body)), None)


def _side(box, point, normal):
    """+1 or -1 when the box lies on that side of the plane (within SIDE_TOL_MM), else 0."""
    lo, hi = box["min"], box["max"]
    dists = [vec.dot(vec.sub([hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]],
                             point), normal) for i in range(8)]
    if min(dists) >= -SIDE_TOL_MM and max(dists) > SIDE_TOL_MM:
        return 1
    if max(dists) <= SIDE_TOL_MM and min(dists) < -SIDE_TOL_MM:
        return -1
    return 0


def _volumes_add_up(parent, pieces):
    volumes = [parent.get("volume")] + [p.get("volume") for p in pieces]
    if any(not isinstance(v, (int, float)) for v in volumes):
        return False
    whole, parts = volumes[0], sum(volumes[1:])
    return abs(whole - parts) <= max(VOLUME_TOL_MM3, VOLUME_RELATIVE * abs(whole))


def _pieces(item, data, before, kept):
    """`(parent record, kept piece, other pieces)` of the body the walk builds, or a Refusal."""
    parent = _record(data.get("bodies"), before)
    if parent is None:
        return _stop("This split does not list the body it cuts.")
    pieces = [p for p in data.get("pieces") or () if isinstance(p, dict)
              and same_body(lineage.parent_of(item, p) or {}, parent)]
    piece = _record(pieces, kept)
    if piece is None:
        return _stop("The piece of this split that the part comes from was not found.")
    others = [p for p in pieces if p is not piece]
    if not others:
        return _stop("This split leaves the body in one piece, which the copy cannot tell apart from a cut.")
    if not _volumes_add_up(parent, pieces):
        return _stop("The pieces of this split do not add up to the body it cut.")
    return parent, piece, others


def _square(normal):
    """A unit direction square to `normal`."""
    helper = [1.0, 0.0, 0.0] if abs(normal[0]) < 0.9 else [0.0, 1.0, 0.0]
    return vec.unit(vec.cross(normal, helper))


def _box_tool(ctx, item, plane, far, shift, around):
    """The `toolBody` cut that removes everything on the `far` side of `plane` (its point and normal) near the box
    `around`. A sized `shift` moves the plane along its normal."""
    lo, hi = around["min"], around["max"]
    centre = [(a + b) / 2.0 for a, b in zip(lo, hi)]
    reach = BOX_REACH * vec.length(vec.sub(hi, lo)) / 2.0 + BOX_MARGIN_MM
    on_plane = vec.sub(centre, vec.scale(plane["normal"], vec.dot(vec.sub(centre, plane["point"]), plane["normal"])))
    origin = round_vec(on_plane)
    if shift is not None and shift.sized:
        origin = [shift.scaled(c).plus(o).json() if abs(c) > 1e-9 else o for o, c in zip(origin, plane["normal"])]
    side = round(2.0 * reach, 3)
    extrude = {"kind": "extrude",
               "sketch": {"on": {"origin": origin, "normal": round_vec(far), "xDir": round_vec(_square(far))},
                          "outer": {"kind": "rect", "center": [0.0, 0.0], "width": side, "height": side}},
               "combine": "new", "extent": "oneSide", "distance": side}
    inner = StepResult()
    inner.add(extrude, label=item.get("name"))
    held = ctx.child({"name": item.get("name")}, "%st%s_" % (ctx.id_prefix, item["index"]), depth=ctx.depth + 1)
    held.add_steps(item, inner)
    out = StepResult()
    out.add({"kind": "toolBody", "combine": "cut", "features": held.steps}, [ToolMaker(held)])
    return out


def _by_plane(ctx, item, tool, parent, piece, others):
    plane = tool.get("plane") or {}
    point, normal = plane.get("point"), plane.get("normal")
    if not (isinstance(point, list) and isinstance(normal, list) and vec.length(normal) > 1e-9):
        return _stop("The plane of this split could not be read.")
    normal = vec.unit(normal)
    if piece.get("box") is None or any(p.get("box") is None for p in others):
        return _stop("The pieces of this split could not be measured.")
    side = _side(piece["box"], point, normal)
    if not side or any(_side(p["box"], point, normal) != -side for p in others):
        return _stop("This split leaves pieces on both sides of its plane, which is not copied yet.")
    shift = follow.place_plane(ctx, item, plane, normal, "splits along")
    around = parent.get("box") or piece["box"]
    return _box_tool(ctx, item, {"point": point, "normal": normal}, vec.scale(normal, -side), shift, around)


def _by_body(ctx, item, tool, parent, piece, others):
    body = tool.get("body") or {}
    if not tool.get("solid"):
        return _stop("This split cuts along a surface, which is not copied yet.")
    inside = piece.get("inside")
    if inside is None or any(p.get("inside") is not (not inside) for p in others):
        return _stop("The copy could not tell which pieces of this split lie inside its tool body.")
    operation = "intersect" if inside else "cut"
    data = {"tools": [body], "volume_before": parent.get("volume"), "volume_after": piece.get("volume"),
            "intersect_model": "every"}
    out = combine_step.write_tools(ctx, item, data, operation)
    if isinstance(out, Refusal):
        return _stop(out.reason)
    return out


def handle(item, ctx):
    data = _data(item)
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return _stop("What this split cuts with was not read.")
    if not ctx.steps:
        return _stop("The body is split before the copy has a body to split.")
    before, kept = ctx.lineage_at(item["index"])
    found = _pieces(item, data, before, kept)
    if isinstance(found, Refusal):
        return found
    if tool.get("kind") == "plane":
        return _by_plane(ctx, item, tool, *found)
    if tool.get("kind") == "body":
        return _by_body(ctx, item, tool, *found)
    return _stop("This split cuts along a curved surface or a line, which is not copied yet.")

