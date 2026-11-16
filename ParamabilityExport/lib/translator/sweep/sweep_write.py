"""What a sweep is written as: the extrude or revolve it equals, or a `sweep` step with its twist, taper and placer."""
import copy

from ...design_model import design
from ...design_model.values import Quantity
from ...geometry import vec
from .. import extrude, placement
from ..faces.placer_makers import EndCapsMaker
from ..result import Refusal, StepResult
from ..revolve import step as revolve
from ..sketch import loops, sketch_motion
from . import sweep_frames, sweep_reach
from .sweep_marks import keep_outline_in_bends


def written_form(found, twisted, tapered, fixed):
    """What the sweep is written as: an `extrude`, a `revolve` or a `sweep` step."""
    if twisted or tapered or (fixed and found.kind != "line"):
        return "sweep"
    return {"line": "extrude", "arc": "revolve", "circle": "revolve"}.get(found.kind, "sweep")


def _common(data, profile):
    return {
        "operation": data["operation"],
        "profiles": [profile],
        "participants": data.get("participants") or [],
        "target_box_before": data.get("target_box_before"),
    }


def as_extrude(item, data, profile, found, ctx, followed=None):
    """The sweep along a straight path as the extrude it equals. A path that follows sizes gives its own length."""
    forward = vec.dot(found.direction, vec.unit(profile["frame"]["z"])) > 0
    built = dict(_common(data, profile), start={"kind": "profilePlane"}, extent_type="one", thin=False,
                 side_one={"kind": "distance", "distance": found.length, "taper_deg": 0.0,
                           "direction": 1 if forward else -1, "quantity": followed.length if followed else None},
                 side_two=None, symmetric=None)
    return extrude.handle(ctx, design.as_read(dict(item, data=built)))


def as_revolve(item, data, combine, profile, found, ctx, followed=None):
    """The sweep along an arc or a full circle as the revolve it equals. The start face of the turn faces against
    the travel (along it for a cut), which fixes which way the axis turns. A path that follows sizes gives the axis
    point and the angle as values."""
    toward = 1.0 if combine == "cut" else -1.0
    axis = {"point": found.axis["point"], "dir": found.axis["dir"], "fixed": True,
            "raw": followed.centre if followed else None}
    built = dict(_common(data, profile), project_axis=True, axis=axis,
                 extent={"kind": "angle", "angle_deg": found.angle_deg, "symmetric": False,
                         "quantity": followed.turn if followed else None},
                 start_face_normal=vec.scale(found.direction, toward))
    return revolve.handle(ctx, design.as_read(dict(item, data=built)))


def _doubt_angle(ctx, item, what, quantity, outline_reads):
    """Until the way Fusion measures a twist or taper is confirmed: mark the sizes behind the angle and the outline,
    and ask for a look at the shape."""
    name = item.get("name", "a sweep")
    reads = tuple(dict.fromkeys(tuple(quantity.reads) + tuple(outline_reads)))
    if reads:
        ctx.doubt(reads, "Fusion may measure the %s of %s another way than the copy reads it" % (what, name))
    ctx.note("The %s of %s is copied as Paramability reads it; check the shape." % (what, name))


def as_sweep(item, combine, profile, found, ctx, angles=(), fixed=False, growth=0.0, followed=None):
    """A `sweep` step: the outline on its own placement and the path, with the twist, taper and direction setting.
    `angles` are `(what, recipe key, Quantity, confirmed)`. A path that follows sizes is written as it gives it. An
    outline the path planner moved to the path's start (`found.moved`) is written there."""
    outcome = loops.profile_loops(profile)
    if isinstance(outcome, Refusal):
        return outcome
    outer, inners = outcome
    drawn = sketch_motion.outline(ctx, item, profile, outer, inners, [(sketch_motion.profile_number(profile), profile)])
    frame = profile["frame"]
    on = placement.from_frame(dict(frame, origin=vec.add(frame["origin"], found.moved)) if found.moved else frame)
    if drawn is not None:
        # A move along the first line of the path is a move along the outline's normal.
        along = vec.dot(found.moved, vec.unit(frame["z"])) if found.moved else 0.0
        on["origin"] = drawn.origin(ctx, Quantity(along))
        outer, inners = drawn.written(ctx)
        if followed is None:
            keep_outline_in_bends(ctx, item, profile, found, outer, growth)
    sketch = {"on": on, "outer": outer}
    if inners:
        sketch["inner"] = inners
    path = followed.written if followed is not None else copy.deepcopy(found.recipe)
    step = {"kind": "sweep", "sketch": sketch, "path": path, "combine": combine}
    for what, key, quantity, confirmed in angles:
        step[key] = quantity.json()
        if not confirmed:
            _doubt_angle(ctx, item, what, quantity, sweep_reach.written_reads(outer, *inners))
    if fixed:
        step["orientation"] = "fixed"
    maker = _faces_maker(profile, found, bool(angles), fixed)
    out = StepResult()
    out.add(step, [maker] if maker else [])
    return out


def _faces_maker(profile, found, shaped, fixed):
    """The placer maker for the faces of a written sweep, or None when it has none the recipe can name: a closed path
    has no end faces and a hollow outline leaves none. A twist or taper (`shaped`) turns or shrinks the end face and the
    walls, so only the start face is placed then."""
    if found.closed or any(not loop.get("outer") for loop in profile.get("loops") or []):
        return None
    faces = {"start": (profile["frame"], profile)}
    end = None if shaped else sweep_frames.end_frame(profile["frame"], found, fixed)
    if end is not None:
        faces["end"] = (end, profile)
    walk = None if shaped or fixed else sweep_frames.SideWalk.of(profile["frame"], found)
    return EndCapsMaker(faces, walk)
