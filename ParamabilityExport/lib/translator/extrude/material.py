"""The side of the part that a cut through all goes to, found from where the outlines meet material."""
from ..faces import follow
from ...design_model.steps.extrude import walls_confirm
from ...geometry import vec
from ...geometry.footprint import Footprint, polyline
from .checks import facts_of
from .common import SAMPLE_INSET


# Points per side of the bounding box of an outline, and steps along the extrude, that the material test samples.
_SAMPLE_GRID = 7
_SAMPLE_STEPS = 48


def _outline_samples(profile):
    """Points inside the outline of `profile` (its holes left out), in its sketch plane: a grid over its box."""
    footprint = Footprint(profile)
    points = [p for curve in footprint.curves for p in polyline(curve)]
    if not points:
        return []
    lo = [min(p[0] for p in points), min(p[1] for p in points)]
    hi = [max(p[0] for p in points), max(p[1] for p in points)]
    out = []
    for i in range(_SAMPLE_GRID):
        for j in range(_SAMPLE_GRID):
            uv = [lo[0] + (hi[0] - lo[0]) * (i + 0.5) / _SAMPLE_GRID, lo[1] + (hi[1] - lo[1]) * (j + 0.5) / _SAMPLE_GRID]
            if footprint.covers(uv):
                out.append(uv)
    return out


def _meets_material(ctx, profiles, shift, sign, reach):
    """True when the outlines, carried from the start plane `sign` along their normal up to `reach`, pass through the
    part built so far."""
    for profile in profiles:
        frame = profile["frame"]
        z = vec.unit(frame["z"])
        for uv in _outline_samples(profile):
            flat = vec.add(frame["origin"], vec.add(vec.scale(frame["x"], uv[0]), vec.scale(frame["y"], uv[1])))
            for height in _sample_heights(reach):
                if follow.inside(ctx, vec.add(flat, vec.scale(z, shift + sign * height))):
                    return True
    return False


def _sample_heights(reach):
    """Heights along the extrude that the material test samples: _SAMPLE_STEPS even steps up to `reach`, and
    heights doubling from SAMPLE_INSET below the first step, so a thin wall right at the start plane is found."""
    step = reach / _SAMPLE_STEPS
    near, height = [], SAMPLE_INSET
    while height < step:
        near.append(height)
        height *= 2.0
    return near + [step * k for k in range(1, _SAMPLE_STEPS + 1)]


def cut_toward_material(ctx, plan, data, profiles, shift, combine):
    """A cut through all to one side with no measured end face cuts on the side where its outlines meet the part:
    Fusion's stored direction is used only when both sides, or neither, hold material there, or when the measured
    walls of a tapered cut lean the way that direction gives and not the other (they show where Fusion cut). Only an
    extrude of one side turns: turning one side of two would send both the same way."""
    box = data.get("target_box_before")
    if combine != "cut" or any(e.read.measured is not None for e in plan) or not box or len(plan) != 1:
        return
    reach = vec.length(vec.sub(box["max"], box["min"])) + 1.0
    for entry in plan:
        if entry.extent != "through-one":
            continue
        if walls_confirm(facts_of([entry])[0], data.get("side_leans"), "cut"):
            continue
        ahead = _meets_material(ctx, profiles, shift, entry.sign, reach)
        behind = _meets_material(ctx, profiles, shift, -entry.sign, reach)
        if behind and not ahead:
            entry.sign = -entry.sign
            ctx.note("Fusion stored the cut direction toward a side without material; the side the cut goes through "
                     "was used.")

