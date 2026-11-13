"""Sizes a written sweep cannot follow, marked as doubts: the path sketch's place, its edges, the outline plane and
an outline that can outgrow a bend."""
import math

from ...geometry import vec
from ..sketch import loops, sketch_motion
from . import sweep_reach
from ..result import Refusal
from ..sizes import construction_sizes, placement_sizes, sketch_sizes


def mark_path(ctx, item, path):
    """The path is written as measured: the sizes behind its sketch (or, for edges, behind the steps written so far)
    stay free with a warning."""
    name = item.get("name", "a sweep")
    if ctx.table is None:
        return
    if path.get("kind") == "edges":
        _mark_edges(ctx, name, path)
        return
    sketch = path.get("sketch") or ""
    names = sketch_sizes(ctx.table, sketch) if sketch else ()
    if names:
        ctx.doubt(names, "%s copies its path from %s as measured" % (name, sketch))
    mark_sketch_place(ctx, name, path)


def _mark_edges(ctx, name, path):
    """Edges of the part move with the steps written so far; edges of another body of the component may move with any
    size."""
    if any(edge.get("body") and not ctx.is_target(edge["body"]) for edge in path.get("edges") or []):
        ctx.doubt(ctx.table.ticked, "%s follows edges of another body, which the copy keeps as measured" % name)
    elif ctx.written_reads:
        ctx.doubt(ctx.written_reads, "%s follows edges of the part, which the copy keeps as measured" % name)


def mark_sketch_place(ctx, name, path, plane_follows=False):
    """A path sketch sits on a plane or face and may hold projected curves: sizes that move those move the path in
    Fusion, not in the copy. A plane that follows sizes (`plane_follows`) is no reason, except for the sizes that may
    move it and were not tried (`sketch_motion.placement_doubts`)."""
    reference = path.get("reference")
    kind = reference.get("kind") if isinstance(reference, dict) else None
    item = ctx.current or {}
    if kind == "constructionPlane" and plane_follows:
        sketch_motion.placement_doubts(ctx, item, path)
    elif kind == "constructionPlane":
        names = list(construction_sizes(ctx.table, "constructionPlane", reference.get("token") or ""))
        names += [n for n in placement_sizes(ctx.table, ctx.timeline, path, item.get("index")) if n not in names]
        if names:
            ctx.doubt(names, "%s copies its path from a sketch on a construction plane, as measured" % name)
    elif kind in ("face", "other") or path.get("projected") or ("reference" in path and reference is None):
        if ctx.written_reads:
            ctx.doubt(ctx.written_reads, "%s copies its path from a sketch on or projected from the part, as measured"
                      % name)


def drawn_outline(ctx, item, profile):
    """The `sketch_motion.Outline` of the sweep's outline, or None when sketch values do not follow sizes."""
    outcome = loops.profile_loops(profile)
    if isinstance(outcome, Refusal):
        return None
    return sketch_motion.outline(ctx, item, profile, outcome[0], outcome[1], [(sketch_motion.profile_number(profile), profile)])


def keep_path_on_plane(ctx, item, profile):
    """The path is written as numbers and starts on the plane the outline had when it was captured: a size that moves
    that plane is marked, whichever form the sweep is written in."""
    drawn = drawn_outline(ctx, item, profile)
    if drawn is None:
        return
    shift = drawn.plane_shift(ctx)
    if shift.sized:
        ctx.doubt(shift.reads, "%s starts its path on the plane of its outline, which the copy cannot move with it"
                  % item.get("name", "a sweep"))


def keep_outline_in_bends(ctx, item, profile, found, outer, growth):
    """A larger outline can reach past the tightest bend of the path, which the app refuses: mark the sizes behind
    the outline that can do so. `growth` is how far a taper can lean the walls out by the path's end."""
    if ctx.table is None or found.tightest == math.inf:
        return
    frame = profile["frame"]
    offset = vec.sub(found.start, frame["origin"])
    names = sweep_reach.outgrown_reads(ctx.table, outer, [vec.dot(offset, frame["x"]), vec.dot(offset, frame["y"])],
                                       found.tightest - growth * found.length)
    if names:
        ctx.doubt(names, "it can make the outline of %s reach past the tightest bend of its path"
                  % item.get("name", "a sweep"))
