"""Thin extrudes of an open line: a wall along a chain of straight sketch lines, with square ends and sharp corners.

The recipe writes it as an extrude whose outline is an `open` loop, with `thin` set to `ends: square` and
`corners: sharp` (recipe version 17). The loop runs from the first point of the line to its last, so it keeps the
direction of the line. The app puts an `inside` wall on the left of that direction (seen from the front of the
sketch, along its normal), an `outside` wall on the right, and a `middle` wall half on each side.

The shared layer (`design_model/steps/thin.py`) reads the line (`line_of`: lines of one sketch that run one after the
other along the path), its shape (`line_problem`, `band`) and the side of the wall from the faces Fusion made
(`line_side`). This module writes the loop, the `thin` record and the placer.

A line with arcs (`thin_arc.py`) is written as a plain extrude of the closed outline of its wall, lines and arcs,
with numbers (`ArcWall`): the line keeps its place and shape and the wall its thickness, and the sizes that move them
are marked. The wall is copied only when the part's volume changed by the outline's area times the length.

The line at other sizes. Its points follow the probe's values for the path (`sketch_values.keys.path`). The wall
must keep its shape over the size ranges (`keep_line_valid`): each line longer than what its corners take from it,
no corner sharper than `thin.MAX_TURN_DEG`, and no two lines that do not meet nearer than twice the farthest the wall
reaches from its line. The ranges are cut where it stops, or the sizes are marked.
"""
from ...capture_model import gap_hints
from ...design_model.problem import is_problem
from ...design_model.reach import sketch_sizes
from ...design_model.loops import loop_of
from ...design_model.steps import thin, thin_arc
from ...design_model.steps.thin import SWAPPED, band, band_profile, is_line, line_problem, reaches
from ...geometry import vec
from ...package.numbers import round9
from ...sketch_values import keys
from .. import values
from ..ranges import kept_ranges, range_check
from ..result import Refusal
from ..sketch import sketch_motion
from ..sketch.written_loops import curves_at, value, written_reads

_FAILURES = (ArithmeticError, ValueError, KeyError, TypeError)

FOLDS = "the wall of %s would fold or its line cross itself"


def open_loop(points):
    """The recipe's `open` loop through `points`."""
    return {"kind": "open", "start": [round9(c) for c in points[0]],
            "segments": [{"kind": "line", "to": [round9(c) for c in p]} for p in points[1:]]}


def outline(ctx, item, line):
    """`(loop, drawn)`: the written loop as numbers and its `sketch_motion.Outline` when the line follows sizes, else
    None. A line the probe did not follow keeps its numbers, and the sizes of its sketch are marked. A line with arcs
    has no open loop (None): its wall is written as a closed outline (`ArcWall`), with numbers."""
    if line.curved:
        names = sketch_sizes(ctx.table, line.sketch) if line.sketch and ctx.table is not None else ()
        if names:
            ctx.doubt(names, "%s copies its line with arcs from %s as measured" % (
                item.get("name", "a thin extrude"), line.sketch))
        sketch_motion.placement_doubts(ctx, item, line.path)
        return None, None
    loop = open_loop(line.points)
    if not sketch_motion.active(ctx):
        sketch_motion.placement_doubts(ctx, item, line.path)
        return loop, None
    index = item.get("index")
    if keys.path(index) not in ctx.motion.curves:
        names = sketch_sizes(ctx.table, line.sketch) if line.sketch else ()
        if names:
            ctx.doubt(names, "%s copies its line from %s as measured" % (item.get("name", "a thin extrude"),
                                                                         line.sketch))
        sketch_motion.placement_doubts(ctx, item, line.path)
        return loop, None

    def raw(number, name, point):
        prefix = keys.path_curve(index, number)
        return [sketch_motion.raw(ctx, "%s%s.%d" % (prefix, name, c), float(point[c]), line.sketch) for c in range(2)]

    raw_loop = {"kind": "open", "start": raw(0, "start", line.points[0]),
                "segments": [{"kind": "line", "to": raw(n, "end", p)} for n, p in enumerate(line.points[1:])]}
    frame = line.frame
    plane = sketch_motion.raw(ctx, keys.path_plane(index), vec.dot(frame["origin"], frame["z"]), line.sketch)
    sketch_motion.placement_doubts(ctx, item, line.path, plane)
    return loop, sketch_motion.Outline(ctx, frame, [loop], [raw_loop], plane, line.sketch)


def _refusal(problem):
    return Refusal(problem.words, cause=problem.cause)


def line_of(data):
    """The `thin.Line` of a thin extrude's path record, or a Refusal."""
    found = thin.line_of(data)
    return _refusal(found) if is_problem(found) else found


def decide(line, location, thickness, faces, start, entry, before=None):
    """The side of the wall in the line's own sketch frame (`thin.line_side`), or a Refusal. `entry` is the extrude's
    planned `RecipeSide`."""
    found = thin.line_side(line, location, thickness, faces, start, entry.distance, entry.extent == "symmetric",
                           entry.sign, before)
    return _refusal(found) if is_problem(found) else found


class LineWall:
    """The wall of a thin extrude of an open line: `side` in the line's own sketch frame, `thickness` a Quantity, and
    `profile` the closed outline of the wall at the measured sizes (for the material placer)."""

    def __init__(self, side, thickness, profile):
        self.side, self.thickness, self.profile = side, thickness, profile

    def written(self, reverse):
        """The recipe's `thin`. A reversed placement mirrors the loop, so the left of the line becomes its right."""
        return {"thickness": self.thickness.json(), "side": SWAPPED[self.side] if reverse else self.side,
                "ends": "square", "corners": "sharp"}


def faces_of_built_body(ctx, data):
    """The faces of the body before the step (`target_faces_before`) when they are the faces of the body this walk
    builds (`target_faces_body`), else None: in the walk of a tool body the reader's target is another body, and a
    face of that body proves nothing about a face of the tool."""
    body = data.get("target_faces_body")
    return data.get("target_faces_before") if isinstance(body, dict) and ctx.is_target(body) else None


def wall_step(ctx, item, data, wall, line, drawn, start, entry):
    """The `LineWall` of a thin extrude of an open line, or a Refusal: the side from the measured faces (`decide`, or
    `thin_wall.decided` when the step that was written as this extrude found it), the thickness that follows its
    parameter, and the line's shape kept over the size ranges."""
    thickness = wall["thickness"]
    if line.curved:
        return arc_wall(ctx, item, data, wall, line, start, entry)
    # The line alone first: a line that turns back on itself has no wall to compare the faces with.
    problem = line_problem(line.points, 0.0, 0.0)
    side = None
    if not problem and wall.get("decided") in SWAPPED:
        # A step written as a thin extrude (a rib or web) whose side its own handler found from what Fusion made.
        side = wall["decided"]
    elif not problem:
        side = decide(line, wall["location"], thickness, data.get("wall_faces"), start, entry,
                      faces_of_built_body(ctx, data))
    if isinstance(side, Refusal):
        return side
    problem = problem or line_problem(line.points, *reaches(side, thickness))
    if problem:
        return Refusal("The wall of this thin extrude does not follow its line: %s." % problem,
                       cause=gap_hints.THIN_OUTLINE)
    thickness_q = values.quantity(ctx, item, "thin.thickness", thickness, absolute=True)
    if drawn is not None:
        keep_line_valid(ctx, item, drawn.preview()[0], thickness_q, side)
    return LineWall(side, thickness_q, band_profile(line.frame, band(line.points, *reaches(side, thickness))))


class ArcWall:
    """The wall of a thin extrude along a line with arcs: `loop` the recipe loop of its closed outline and `profile`
    that outline as a capture profile (for the material placer), both as measured."""

    def __init__(self, loop, profile):
        self.loop, self.profile = loop, profile


def _shape_refusal(problem):
    return Refusal("The wall of this thin extrude does not follow its line: %s." % problem,
                   cause=gap_hints.THIN_OUTLINE)


def arc_wall(ctx, item, data, wall, line, start, entry):
    """The `ArcWall` of a thin extrude along a line with arcs, or a Refusal: the side from the measured faces
    (`decide`), the band kept in shape (`thin_arc.problem`), and the part's volume changed by the band's area times
    the length (`thin_arc.size_problem`). The thickness keeps its number, so its sizes are marked."""
    thickness = wall["thickness"]
    problem = thin.shape_problem(line, 0.0, 0.0)
    if problem:
        return _shape_refusal(problem)
    side = decide(line, wall["location"], thickness, data.get("wall_faces"), start, entry,
                  faces_of_built_body(ctx, data))
    if isinstance(side, Refusal):
        return side
    problem = thin.shape_problem(line, *reaches(side, thickness))
    if problem:
        return _shape_refusal(problem)
    curves = thin.wall_curves(line, side, thickness)
    found = thin_arc.size_problem(item, data, curves, entry.distance)
    if found is not None:
        return _refusal(found)
    loop = loop_of(curves, line.sketch)
    if is_problem(loop):
        return Refusal(loop.words, cause=gap_hints.THIN_OUTLINE)
    names = values.quantity(ctx, item, "thin.thickness", thickness, absolute=True).reads
    if names:
        ctx.doubt(names, "%s keeps the thickness of its wall along a line with arcs as measured"
                  % item.get("name", "a thin extrude"))
    return ArcWall(loop, thin_arc.profile(line.frame, curves))


def keep_line_valid(ctx, item, loop, thickness_q, side):
    """Cut the ranges of the sizes that move the written `loop` or the wall thickness so the wall keeps its shape
    (`line_problem`) at every size setting tested: the corners and middles of the ranges, and inner settings for a
    formula that is more than sums and products. The sizes are marked when no cut keeps it."""
    reads = [n for n in dict.fromkeys(written_reads(loop) + tuple(thickness_q.reads)) if n not in ctx.doubted()]
    if ctx.table is None or not reads:
        return
    thickness = thickness_q.json()
    inner = any(range_check.needs_inner(text) for text in _formulas([loop, thickness]))

    def shaped(env):
        lines = curves_at(loop, env)
        points = [lines[0]["start"]] + [c["end"] for c in lines]
        return line_problem(points, *reaches(side, value(thickness, env))) is None

    def holds(bounds, only=None):
        if only is not None:
            settings = [{only[0]: bounds[only[0]][only[1]]}]
        else:
            settings = range_check.corners(ctx.table, reads, bounds) + range_check.middles(ctx.table, reads, bounds)
            if inner:
                settings += range_check.inner_settings(ctx.table, reads, bounds)
        try:
            return all(shaped(range_check.recipe_size_values(ctx.table, setting)) for setting in settings)
        except _FAILURES:
            return False

    found = kept_ranges.holding_ranges_where(ctx.table, reads, holds)
    why = FOLDS % item.get("name", "a thin extrude")
    if found is None:
        ctx.doubt(reads, "at other values " + why)
    elif found:
        ctx.cut(found, why)


def _formulas(node, out=None):
    """The formula texts of the written values in `node`."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("expr"), str):
            out.append(node["expr"])
        for item in node.values():
            _formulas(item, out)
    elif isinstance(node, list):
        for item in node:
            _formulas(item, out)
    return out
