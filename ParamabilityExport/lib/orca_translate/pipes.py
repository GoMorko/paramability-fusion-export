"""Pipe steps as Orca features: a circle, or a ring for a hollow pipe, carried along a path.

Fusion builds a pipe as a sweep of a section it draws itself: a circle (less a circle of the wall for a hollow pipe)
at the start of the path, square to the path and centred on it (`design_model.steps.pipe`). The copy plans and checks
the path as for a sweep with that outline (`sweeps.plan_path`: lines, arcs and splines in one plane that meet
smoothly, no sharp corner, a new body's measured volume and end face). Every path, also a line, one arc or a full
circle, is written as an Orca Sweep, so that the circle's `radius` can follow the pipe's size:
- a sketch of one circle (`SketchShape.CIRCLE`) on the plane square to the path at its start, centred on it, with
  `radius` half the section size;
- a sketch of the path from its start, in order. Orca starts the wire of an open path at the free end of the first
  entity, and of a closed path at the start of the first entity. A full circle is two half arcs from the start;
- a Sweep of the circle along the path. Orca's sweep (`SketchEngine::make_sweep`, OCCT `BRepOffsetAPI_MakePipe` of
  the circle's face) closes each end with the section carried there. The section starts square to the path, so each
  end is square to the path, as Fusion ends a pipe along an open path.

Orca's sweep takes one closed loop, so a hollow pipe is two sweeps: the outer circle, and the circle of the hole
(`radius` half the size less the wall) cut out of it. On a part that already holds material the two are a tool body
(`Context.push`) and a Boolean with the step's operation (`tools.boolean`), so the hole cuts nothing else.

The parameter's line tells how far the size and the wall may go: the hole must stay open (the wall thinner than the
radius), and the pipe must stay clear of the centre of the tightest bend and of the other parts of the path, or Orca's
sweep runs into itself (`limits.guard`). A cut or intersect must meet the part (`solid.meets`). The path keeps its
numbers, and the sizes that move it, with its start where the section sits, are marked (`sweeps.mark_path`).

Left out: a square or triangle section (the capture does not say which way it turns about the path), a pipe over part
of its path, and what the checks of a sweep leave out, with the words of a sweep said of a pipe.
"""
import dataclasses
import math
import re

from ..capture_model import gap_hints
from ..design_model.paths import curves as path_curves
from ..design_model.paths.checks import bend_problem, overlap_problem, reach_problem
from ..design_model.paths.closed import half_circles
from ..design_model.problem import is_problem
from ..design_model.steps import pipe as facts
from ..design_model.steps.sweep import profile_points
from ..geometry import vec
from ..orca_recipe.enums import BooleanMode, FeatureType, SketchShape
from . import causes, limits, steps, sweep_splines, sweeps
from .context import Body
from .sketches import entities_of
from .skip import Skip
from .solid import ADD, CUT, INTERSECT, Solid
from .tools import OPERATIONS, boolean, feature, label

_SOLID_MODES = {"newBody": ADD, "join": ADD, "cut": CUT, "intersect": INTERSECT}
# A path sketch's own normal is taken for a straight path when it is this square to the line (the cosine).
_SQUARE = 1e-6

OLD_EXPORT = "This pipe was captured without its details. Export again with this version of the add-in to copy it."
NEW_COMPONENT = "This pipe makes a new component, which is not copied."
OTHER_OPERATION = "This pipe combines with the part in a way that is not copied yet."
_FREE_CURVE = ("The path of this pipe has a free curve (a spline) the Orca copy cannot draw exactly, so it is left "
               "out.")
_SWEEP_WORDS = re.compile(r"\b([Ss])weep(s?)\b")


def _as_pipe(skip):
    """A Skip of the sweep checks with the step named as a pipe."""
    skip.reason = _SWEEP_WORDS.sub(lambda m: ("P" if m.group(1) == "S" else "p") + "ipe" + m.group(2), skip.reason)
    return skip


@dataclasses.dataclass
class _Route:
    """The path as the copy writes it: `found` (the `PathPlan`, its curves in order from the start; a full circle as
    two half arcs), `normal` (of the path's plane), `frame` (that plane at the start, x along the path), the Orca
    `entities` of the path sketch and the radius of the tightest bend (`tightest`, infinity for a line)."""

    found: object
    normal: list
    frame: dict
    entities: list
    tightest: float


def pipe(ctx, step):
    """The Orca features of a pipe, or a Skip."""
    item, data = step.brought, step.brought_data
    if "section" not in data:
        return Skip(OLD_EXPORT, gap_hints.OLD_EXPORT)
    operation = data.get("operation")
    if operation == "newComponent":
        return Skip(NEW_COMPONENT, gap_hints.NEW_COMPONENT)
    if operation not in _SOLID_MODES:
        return Skip(OTHER_OPERATION)
    if not ctx.has_body and operation in ("cut", "intersect"):
        return Skip("The part this %s works on is not in the copy." % ("cut" if operation == "cut" else "intersect"),
                    gap_hints.AFTER_GAP)
    problem = facts.section_problem(data)
    if problem is not None:
        return Skip.of(problem)
    path = data.get("path")
    skip = sweeps.path_problem(path)
    if skip is not None:
        return _as_pipe(skip)
    start = facts.start_of(path)
    if is_problem(start):
        return Skip.of(start)
    profile, area = facts.section_profile(data, start)
    built = dict(data, solid=True, profiles=[profile], areas=[area], rail=None, guide_surfaces=[],
                 orientation="perpendicular", taper_deg=0.0, twist_deg=0.0)
    # A closed path that starts on a sharp corner (`facts.SEAM_CORNER`) is left out with the sharp corners here.
    found = sweeps.plan_path(item, built, [profile], path)
    if isinstance(found, Skip):
        return _as_pipe(found)
    route = _route(found, path)
    if route is None:
        return Skip(_FREE_CURVE, causes.SWEEP_PATH)
    issue = reach_problem(profile_points(profile), found.start, route.normal, route.tightest)
    if issue is not None:
        return _as_pipe(Skip.of(issue))
    made = _write(ctx, item, data, profile, route)
    if not isinstance(made, Skip):
        sweeps.mark_path(ctx, item, path, "pipe")
    return made


def _line_normal(found, path):
    """A normal of a plane that holds a straight path: its sketch's normal when that is square to the line."""
    direction = vec.unit(found.direction)
    given = (path.get("frame") or {}).get("z")
    if isinstance(given, list) and len(given) == 3 and vec.length(given) > 0 \
            and abs(vec.dot(vec.unit(given), direction)) <= _SQUARE:
        return vec.unit(given)
    other = [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 1.0, 0.0]
    return vec.unit(vec.cross(direction, other))


def _route(found, path):
    """The `_Route` of a checked path, or None when a spline of it cannot be drawn exactly."""
    if found.kind == "circle":
        found = dataclasses.replace(found, curves=[dict(c, radius=found.radius) for c in half_circles(found)],
                                    closed=True)
    if found.kind in ("arc", "circle"):
        normal, tightest = vec.unit(found.axis["dir"]), float(found.radius)
    elif found.kind == "line":
        normal, tightest = _line_normal(found, path), math.inf
    else:
        normal, tightest = vec.unit(found.recipe["on"]["normal"]), found.tightest
    frame = sweeps.path_frame(found, normal)
    flat = [sweeps.flat_curve(c, frame) for c in found.curves]
    entities = entities_of([flat]) if all(c is not None for c in flat) else None
    if entities is None:
        return None
    if found.kind == "flat":
        # The planner's tightest bend is read from its fitted curve; the spline Orca builds is the exact one.
        tightest = min(tightest, sweep_splines.tightest(flat))
    return _Route(found, normal, frame, entities, tightest)


def _circle(radius):
    return [{"kind": "circle", "center": [0.0, 0.0], "radius": float(radius)}]


def _write(ctx, item, data, profile, route):
    """The sketches, sweeps and, for a hollow pipe on a part with material, the tool body and Boolean of a pipe."""
    operation = data["operation"]
    mode = _SOLID_MODES[operation]
    name = label(item)
    frame = profile["frame"]
    outer, inner = facts.radii(data)
    shapes = [sweeps.carried(frame, [_circle(r)], route.found, route.normal) for r in (outer, inner) if r is not None]
    if mode != ADD:
        tube = Solid([(ADD, shapes[0])] + [(CUT, s) for s in shapes[1:]])
        if not ctx.solid.meets(tube):
            return Skip(*steps.misses_reason(ctx, "cut" if mode == CUT else "intersect"))
    size = ctx.quantity(item, "section_size", data["section_size"]).scaled(0.5)
    radii = [size]
    if inner is not None:
        radii.append(size.plus(ctx.quantity(item, "section_thickness", data["section_thickness"]).scaled(-1.0)))
    tool = ctx.push(Body(None, "%s tool" % name)) if inner is not None and ctx.has_body else None
    out, sketches = [], []
    try:
        for n, (radius, shape) in enumerate(zip(radii, shapes)):
            tag = name if n == 0 else "%s hole" % name
            sketch = feature(FeatureType.SKETCH, "%s section" % tag, shape=SketchShape.CIRCLE, radius=radius.n,
                             plane=ctx.place.plane(frame["origin"], frame["x"], frame["y"], frame["z"]))
            at = ctx.add(sketch)
            ctx.bind(sketch, "radius", radius, "%s radius" % sketch.name)
            sketches.append(sketch)
            out.append(sketch)
            if n == 0:
                plane = route.frame
                out.append(feature(FeatureType.SKETCH, "%s path" % name, entities=route.entities,
                                   plane=ctx.place.plane(plane["origin"], plane["x"], plane["y"], plane["z"])))
                path_at = ctx.add(out[-1])
            made = feature(FeatureType.SWEEP, tag, sketch_ref=at, sweep_path_ref=path_at)
            if n:
                made.mode, acts = BooleanMode.CUT, CUT
            elif not ctx.has_body:
                made.mode, acts = BooleanMode.NEW, ADD
            else:
                made.mode, acts = OPERATIONS.get(operation, BooleanMode.ADD), mode
            ctx.add(made)
            ctx.has_body = True
            ctx.solid.add(acts, shape)
            out.append(made)
    finally:
        if tool is not None:
            ctx.pop()
    if tool is not None:
        out.append(boolean(ctx, tool, OPERATIONS.get(operation, BooleanMode.ADD), "%s into the part" % name))
    _limit(ctx, name, sketches, route)
    return out


def _limit(ctx, name, sketches, route):
    """Tell how far the variables of the section's radii may go: the hole must stay inside the outer circle, and the
    pipe clear of the centre of the tightest bend and of the other parts of the path, or Orca's sweep runs into
    itself. A radius that reaches zero is a limit of every sized shape (`limits.POSITIVE`)."""
    fields = [(sketch, "radius", "%s radius" % sketch.name) for sketch in sketches]
    if not any("radius" in sketch.expr for sketch in sketches):
        return
    points = [p for c in route.found.curves for p in path_curves.polyline(c)]

    def ok(numbers):
        outer = numbers[0]
        if len(numbers) > 1 and numbers[1] >= outer:
            return limits.Stop(limits.SHAPE_ZERO)
        if bend_problem(outer, route.tightest) is not None:
            return limits.Stop(limits.SWEEP_BEND)
        return limits.stop(overlap_problem(points, outer, route.found.closed) is None, limits.SWEEP_OVERLAP)

    limits.guard(ctx, fields, ok, "%s: the Orca copy cannot tell how far this may change before the pipe runs into "
                 "itself" % name)


HANDLERS = {"PipeFeature": pipe}
