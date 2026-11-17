"""Pipe feature handler (PipeFeature): a circle, or a ring for a hollow pipe, carried along a path.

A pipe is a sweep whose outline Fusion draws itself: the section, square to the path where it starts and centred on
it (`design_model.steps.pipe`). The handler builds the data of a sweep with that outline and hands it to the sweep
handler (`step.handle`), so the path is planned, checked and written as for a sweep: a straight path is an extrude
of the circle, one arc or a full circle a revolve, a chain of lines, arcs and free curves a `sweep` step. The volume
of a new body and the end faces Fusion made are checked against the outline and the path there too. A refusal of the
sweep handler keeps its reason, with the pipe named as a pipe.

Sizes:
- The section follows sizes through the radii of the outline. The probe measures no sketch for the section, so its
  radii are given to the outline as motion values over the pipe's own parameters (half the section size; less the
  wall for the hole), with its centres and plane as they are, while the sweep handler writes it
  (`_section_values`). The outline's rules then hold them over the size ranges, as for a drawn circle: above zero,
  the hole inside the circle, clear of the tightest bend of the path and of a revolve axis. Without a motion file the
  radii stay numbers and the sizes behind them are marked.
- The path follows sizes where a sweep path does. The copy keeps the section where it was measured, so a size that
  moves the start of the path is marked (`_keep_start`). A size that turns the path where it starts is held by the
  sweep's rule that the path starts square to its outline.

Sharp corners are mitred as for a sweep, which is how Fusion builds a pipe (live check PI2). Left out: a square or
triangle section, a pipe over part of its path, a closed path that starts on a sharp corner (how Fusion closes the
pipe there is not known), and what the sweep handler leaves out.
"""
import contextlib
import re

from ...capture_model import gap_hints
from ...design_model import design
from ...design_model.paths import planner
from ...design_model.paths.curves import near
from ...design_model.problem import is_problem
from ...design_model.steps import pipe as facts
from ...design_model.steps.sweep import profile_points
from ...geometry import vec
from ...sketch_values import keys
from ...sketch_values.motion import Affine, Stuck
from .. import values
from ..ranges import kept_ranges
from ..extrude import COMBINE
from ..paths import path_limits
from ..result import Refusal
from ..sketch import sketch_motion
from . import step as sweep

OLD_EXPORT = "This pipe was captured without its details. Export again with this version of the add-in to copy it."
NEW_COMPONENT = "Pipes that make a new component are not copied."
OTHER_OPERATION = "This pipe combines with the part in a way that is not copied yet."
_SWEEP_WORDS = re.compile(r"\b([Ss])weep(s?)\b")


def _as_pipe(refusal):
    """A refusal of the sweep handler with the step named as a pipe."""
    refusal.reason = _SWEEP_WORDS.sub(lambda m: ("P" if m.group(1) == "S" else "p") + "ipe" + m.group(2),
                                      refusal.reason)
    return refusal


def _term(ref, factor, number):
    """`factor` times the parameter `ref` (`{ name, expression, value }`) as a motion value, or `factor` times
    `number` when the value has no parameter."""
    if ref is None:
        return Affine(factor * number)
    return Affine(0.0, {ref["name"]: factor})


class _WithSection:
    """A motion file that also gives the section's radii (`get`); everything else is the motion file's own."""

    def __init__(self, motion, given):
        self._motion, self._given = motion, given

    def get(self, key):
        return self._given[key] if key in self._given else self._motion.get(key)

    def __getattr__(self, name):
        return getattr(self._motion, name)


def _radii(ctx, item, data):
    """The motion values of the outer radius and, for a hollow pipe, the hole's radius: half the section size, less
    the wall for the hole."""
    params = design.params_of(item)
    outer = _term(params.get("section_size"), 0.5, data["section_size"])
    if not data["hollow"]:
        return [outer]
    return [outer, outer.plus(_term(params.get("section_thickness"), -1.0, data["section_thickness"]))]


@contextlib.contextmanager
def _open_section(ctx, item, data):
    """While the sweep handler writes the outline, the size table with the ranges cut where a radius of the section
    would reach zero (a wall that closes the hole, a size that shrinks the pipe to nothing). The cut is recorded, so
    the written ranges are the same; the outline's own rules and the path's then hold inside them. Without such a
    cut (the radii hold over the whole ranges, or no shorter ranges keep them) the table stays, and the outline marks
    the sizes as for a drawn circle. The context's table is put back afterwards."""
    if not sketch_motion.active(ctx):
        yield
        return
    rules = []
    for raw, number in zip(_radii(ctx, item, data), facts.radii(data)):
        q = sketch_motion.rendered(ctx.table, raw, number)
        if not isinstance(q, Stuck) and q.sized:
            rules.append((q, 1))
    found = kept_ranges.holding_ranges(ctx.table, rules, values.ABOVE_ZERO) if rules else None
    if not found:
        yield
        return
    name = item.get("name", "a pipe")
    ctx.cut(found, ("the hole of %s would close" if data["hollow"] else "%s would shrink to nothing") % name)
    base = ctx.table
    ctx.table = base.with_narrowed(found)
    try:
        yield
    finally:
        ctx.table = base


@contextlib.contextmanager
def _section_values(ctx, item, data, frame):
    """While the sweep handler writes the outline, every value of it as a motion value: the radii over the pipe's
    parameters, so they follow sizes as the radius of a drawn circle does, and the centres and the plane (`frame`) as
    they are. The probe measures no outline of a pipe, so none of these keys is asked of the motion file. Yields True
    when they are given (a motion file is in use), else False. The context's motion file is put back afterwards."""
    if not sketch_motion.active(ctx):
        yield False
        return
    radii = _radii(ctx, item, data)
    prefix = keys.profile(item.get("index"), 0)
    given = {keys.plane(prefix): Affine(vec.dot(frame["origin"], frame["z"]))}
    for loop, radius in enumerate(radii):
        given[keys.loop_field(prefix, loop, "radius")] = radius
        given.update({keys.loop_field(prefix, loop, "center.%d" % c): Affine(0.0) for c in range(2)})
    base = ctx.motion
    ctx.motion = _WithSection(base, given)
    try:
        yield True
    finally:
        ctx.motion = base


def _start_values(path, start, index):
    """`(key, captured number)` of the probe's values that place the start of the path: the path sketch's plane and
    the coordinates of each curve end at `start` (for a full circle, its centre and radius)."""
    frame = path["frame"]
    found = [(keys.path_plane(index), vec.dot(frame["origin"], frame["z"]))]
    for number, curve in enumerate(path.get("curves") or []):
        flat = curve.get("flat")
        if not isinstance(flat, dict):
            continue
        prefix = keys.path_curve(index, number)
        if curve.get("kind") == "circle":
            found += [(prefix + "center.%d" % c, float(flat["center"][c])) for c in range(2)]
            found.append((prefix + "radius", float(flat["radius"])))
            continue
        for end in ("start", "end"):
            if end in curve and end in flat and near(curve[end], start):
                found += [(prefix + "%s.%d" % (end, c), float(flat[end][c])) for c in range(2)]
    return found


def _keep_start(ctx, item, path, start):
    """Mark the sizes that move the start of a sketch path: in Fusion the section moves with it, in the copy it stays
    where it was measured."""
    if not sketch_motion.active(ctx) or path.get("kind") != "sketch" or not isinstance(path.get("frame"), dict):
        return
    sketch = path.get("sketch") or ""
    names = []
    for key, number in _start_values(path, start, item.get("index")):
        names += [n for n in sketch_motion.movers(ctx.table, sketch_motion.raw(ctx, key, number, sketch))
                  if n not in names]
    if names:
        ctx.doubt(names, "%s starts its section where its path starts, which the copy cannot move with it"
                  % item.get("name", "a pipe"))


def _first_look(ctx, item, data, outcome):
    """In the first look (`OPTIMISTIC`) the outline is written as numbers. The radii are written as formulas of the
    section's values there, so the sizes behind them count as sizes a copied step reads, as an extrude's distance
    does: the size probe then does not try them as sizes that may move a sketch, which would mark them as changing
    the part in a way the copy does not follow."""
    outer = values.quantity(ctx, item, "section_size", data["section_size"]).scaled(0.5)
    inner = None
    if data["hollow"]:
        wall = values.quantity(ctx, item, "section_thickness", data["section_thickness"])
        inner = outer.plus(wall.scaled(-1.0))
    for entry in outcome.entries:
        sketch = entry.step.get("sketch")
        if not isinstance(sketch, dict) or (sketch.get("outer") or {}).get("kind") != "circle":
            continue
        sketch["outer"]["radius"] = outer.json()
        if inner is not None and sketch.get("inner"):
            sketch["inner"][0]["radius"] = inner.json()


def _keep_section(ctx, item, followed):
    """The section's values: followed through the outline, or written as numbers with their sizes marked. A first
    look without a motion file (`OPTIMISTIC`) fixes nothing."""
    for path in ("section_size", "section_thickness"):
        if followed or getattr(ctx.motion, "optimistic", False):
            values.handled(ctx, item, path)
        else:
            values.pin(ctx, item, path, "it sets the section of %s, which the copy keeps as it is now"
                       % item.get("name", "a pipe"))


def handle(ctx, step):
    item, data = step.brought, step.brought_data
    if "section" not in data:
        return Refusal(OLD_EXPORT, cause=gap_hints.OLD_EXPORT)
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal(NEW_COMPONENT, cause=gap_hints.NEW_COMPONENT)
    if operation not in COMBINE:
        return Refusal(OTHER_OPERATION)
    problem = facts.section_problem(data)
    if problem is not None:
        return path_limits.refusal(problem)
    path = data.get("path")
    start = facts.start_of(path)
    if is_problem(start):
        return path_limits.refusal(start)
    profile, area = facts.section_profile(data, start)
    found = planner.plan(path, profile["frame"], profile_points(profile), path_limits.options())
    if not is_problem(found) and found.moved:
        # The planner moves an outline off a sharp corner of a closed path; Fusion starts the pipe on it.
        return path_limits.refusal(facts.SEAM_CORNER)
    built = dict(data, solid=True, profiles=[profile], areas=[area], rail=None, guide_surfaces=[],
                 orientation="perpendicular", taper_deg=0.0, twist_deg=0.0)
    with _open_section(ctx, item, data), _section_values(ctx, item, data, profile["frame"]) as followed:
        outcome = sweep.handle(ctx, design.as_read(dict(item, data=built)))
    if isinstance(outcome, Refusal):
        return _as_pipe(outcome)
    if getattr(ctx.motion, "optimistic", False):
        _first_look(ctx, item, data, outcome)
    _keep_start(ctx, item, path, found.start)
    _keep_section(ctx, item, followed)
    return outcome
