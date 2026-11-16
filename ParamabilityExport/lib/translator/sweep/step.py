"""Sweep feature handler (SweepFeature): one sketch outline carried along a path of sketch curves or body edges.

The path decides what is written (`design_model.paths.planner.plan` orders it and checks the limits of the recipe's
sweep step, with the recipe's caps from `path_limits`):
- a straight path is an extrude of the outline (`extrude.handle`);
- one arc or a full circle is a revolve of the outline about the arc's axis (`revolve.step.handle`);
- a chain of lines, arcs and free curves in one plane, or of lines and tangent arcs in 3D, is a `sweep` step; a closed
  chain in one plane is a `sweep` step along a closed flat path (a full circle stays a revolve unless it twists),
  with an outline on a sharp corner moved along the path to the middle of the line it is square to (`closed`);
  in one plane, sharp corners between lines are mitred as Fusion builds them, unless the outline twists, tapers or
  keeps its direction;
- a twist, a taper, or an outline kept in one direction (parallel) along a path that turns, also makes a `sweep` step
  (a line becomes a path of two points, an arc a flat path), with `twistDeg`, `taperDeg` and `orientation`.

The outline follows sizes as an extrude outline does. A straight, arc or flat chain path of sketch lines and arcs
follows them too when the probe measured it (`path_motion`), and the app's rules for the path are tested over the size
ranges, which are cut where they stop holding. Any other path (a free curve, corner points, body edges, a tapered
sweep) is written as measured, so the sizes behind its sketch are marked. A new body must have the volume the outline
area and the path give (along a closed path that is Pappus' volume), and the end face Fusion made must lie where the
path ends (`design_model.steps.sweep`). Twist together with taper or parallel, tapers along
free curves, guide rails and guide surfaces, a path that is not square to the outline, closed paths that bend in 3D or that taper or keep
the outline's direction, a twist along a closed path that is not whole turns, and sweeps along part of a path are
refused.

A sweep of several outlines along one path is one sweep per outline (`_each_outline`): for a join, a cut or a new body
they make the same shape together, since the outlines move along the path as one. Each outline is checked on its own,
except the volume of a new body, which Fusion measures for all of them together. An intersect of several outlines is
refused, and so is a taper: without the volume check the copy cannot tell whether Fusion tapers each outline or the
set as a whole.

A sweep step gets the placer of `end_caps` (the start face, the end face where the path leaves it known, the side walls
along a path of lines and arcs), so a later round or chamfer on a whole end face names the step.

This module is the handler only. The outline's points, the volume and end face checks are read in
`design_model.steps.sweep` (shared with the Orca output). The outline, settings, taper, size marks, path rules and
what is written live in `sweep_outline`, `sweep_settings`, `sweep_taper`, `sweep_marks`, `sweep_rules` and
`sweep_write`; refusal texts in `sweep_limits`.

Fusion does not document how it measures the sweep taper (an offset of the outline or a scale) or which way a twist
turns, and no export has confirmed either (`TAPER_MEANING_CONFIRMED`, `TWIST_SIGN_CONFIRMED`). Every written twist or
taper marks the sizes behind it and the outline, and adds a note asking the person to check the shape.
"""
import math

from ...capture_model import gap_hints
from ...geometry import vec
from ..extrude import COMBINE
from ...design_model.paths import planner
from ...design_model.problems import is_problem
from ...design_model.steps.sweep import end_check, outline_shapes, profile_points, volume_problem
from ..paths import path_limits
from ..result import Refusal, StepResult
from ..sketch import borrowed
from . import sweep_taper
from .sweep_taper import taper_lean
from .sweep_limits import (
    MIXED_PATH, NOT_MATCHING, PATH_TOO_LONG, PATH_UNREADABLE, SCALED_OUTLINE, SEVERAL_OUTLINES, SEVERAL_TAPERED,
    TAPER_CLOSES, TWIST_CLOSED, UNREADABLE, WHOLE_TURN_TOL, ZERO_TOL,
)
from .sweep_marks import keep_path_on_plane, mark_path
from .sweep_outline import outline_of
from .sweep_rules import follow_path
from .sweep_settings import angle_value, pin_settings, settings_refusal, taper_growth, taper_path_refusal
from .sweep_write import as_extrude, as_revolve, as_sweep, written_form

TAPER_MEANING_CONFIRMED = False   # true once an export shows how Fusion measures the sweep taper
TWIST_SIGN_CONFIRMED = False      # true once an export shows which way Fusion's twist turns
# Signs between Fusion's angles and the recipe's: Fusion's extrude taper widens the walls where the recipe narrows
# them, and the sweep is taken the same way. A twist turns the same way in both. Fusion does not document this.
TAPER_SIGN = -1
TWIST_SIGN = 1


def _carried(profile, moved):
    """The outline moved by `moved` (where the path planner started the path), or the outline itself."""
    if not moved:
        return profile
    return dict(profile, frame=dict(profile["frame"], origin=vec.add(profile["frame"]["origin"], moved)))


def _each_outline(item, ctx, data, profiles):
    """One sweep per outline, the first with the sweep's own operation and the rest joined to it for a new body."""
    if COMBINE[data["operation"]] == "intersect":
        return Refusal(SEVERAL_OUTLINES)
    if isinstance(data.get("taper_deg"), (int, float)) and abs(data["taper_deg"]) > ZERO_TOL:
        return Refusal(SEVERAL_TAPERED)
    out = StepResult()
    for n, profile in enumerate(profiles):
        operation = "join" if n and COMBINE[data["operation"]] == "new" else data["operation"]
        one = dict(profile, profile_index=n) if isinstance(profile, dict) else profile
        found = handle(dict(item, data=dict(data, profiles=[one], areas=None, operation=operation)), ctx)
        if isinstance(found, Refusal):
            return found
        out.extend(found.entries)
        out.join(found)
    return out


def handle(item, ctx):
    data = item.get("data") or {}
    operation = data.get("operation")
    if operation == "newComponent":
        return Refusal("Sweeps that make a new component are not copied.", cause=gap_hints.NEW_COMPONENT)
    if operation not in COMBINE:
        return Refusal("This sweep combines with the part in a way that is not copied yet.")
    if data.get("solid") is not True:
        if data.get("solid") is False:
            return Refusal("Surface sweeps are not copied.", cause=gap_hints.SURFACE)
        return Refusal(UNREADABLE)
    profiles = data.get("profiles")
    if isinstance(profiles, list) and len(profiles) > 1:
        return _each_outline(item, ctx, data, profiles)
    combine = COMBINE[operation]
    profile = outline_of(data)
    if isinstance(profile, Refusal):
        return profile
    refusal = settings_refusal(data)
    if refusal is not None:
        return refusal
    path = data.get("path")
    if not isinstance(path, dict):
        return Refusal(PATH_UNREADABLE)
    if path.get("kind") == "mixed":
        return Refusal(MIXED_PATH)
    if path.get("truncated"):
        return Refusal(PATH_TOO_LONG)
    twist, taper = data["twist_deg"], data["taper_deg"]
    twisted, tapered, fixed = abs(twist) > ZERO_TOL, abs(taper) > ZERO_TOL, data["orientation"] == "parallel"
    options = path_limits.options(as_step=twisted or tapered or fixed, twisted=twisted, tapered=tapered,
                                  growth=taper_growth(profile, taper), fixed=fixed)
    found = planner.plan(path, profile["frame"], profile_points(profile), options)
    if is_problem(found):
        return path_limits.refusal(found)
    if found.closed and twisted and abs(twist / 360.0 - round(twist / 360.0)) > WHOLE_TURN_TOL:
        return Refusal(TWIST_CLOSED)
    taper_sign = TAPER_SIGN
    if tapered:
        refusal = taper_path_refusal(found)
        if refusal is not None:
            return refusal
        shapes = outline_shapes(profile)
        slope = math.tan(math.radians(TAPER_SIGN * taper))
        lean = taper_lean(item, shapes, data, combine, found, slope)
        if lean == sweep_taper.SCALED:
            return Refusal(SCALED_OUTLINE)
        if lean == sweep_taper.NO_FIT:
            return Refusal(NOT_MATCHING)
        if lean == sweep_taper.FLIPPED:
            taper_sign = -TAPER_SIGN
        elif lean is None and shapes is not None and sweep_taper.closes(shapes, found.length, slope):
            return Refusal(TAPER_CLOSES)
    placed = _carried(profile, found.moved)
    problem = volume_problem(item, data, combine, placed, found)
    if problem is not None:
        return path_limits.refusal(problem)
    problem, end_note = end_check(data, combine, placed, found, profile_points(placed), fixed, tapered)
    if problem is not None:
        return path_limits.refusal(problem)
    pin_settings(ctx, item, data, found.closed)
    if end_note:
        ctx.note(end_note % item.get("name", "this sweep"))
    form = written_form(found, twisted, tapered, fixed)
    # A path started away from the outline is written as measured.
    followed = None if found.moved else follow_path(ctx, item, profile, path, found, form, options)
    if followed is None:
        mark_path(ctx, item, path)
        keep_path_on_plane(ctx, item, profile)
    if found.kind != "line":
        borrowed.mark_unchecked(ctx, item, profile)
    angles = [(what, key, quantity, confirmed)
              for what, key, quantity, confirmed in (
                  ("twist", "twistDeg", angle_value(ctx, item, "twist_deg", twist, TWIST_SIGN, not found.closed),
                   TWIST_SIGN_CONFIRMED),
                  ("taper", "taperDeg", angle_value(ctx, item, "taper_deg", taper, taper_sign),
                   TAPER_MEANING_CONFIRMED))
              if quantity is not None]
    if form == "extrude":
        outcome = as_extrude(item, data, profile, found, ctx, followed)
    elif form == "revolve":
        outcome = as_revolve(item, data, combine, profile, found, ctx, followed)
    else:
        outcome = as_sweep(item, combine, profile, found, ctx, angles, fixed, options.growth, followed)
    if path.get("kind") == "edges" and isinstance(outcome, StepResult):
        for entry in outcome.entries:
            entry.repeatable = False
    return outcome
