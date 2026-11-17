"""The length of a cut through all, whether a tapered one stays open until it passes the part, and when a join or new
body through all is written as the recipe's extrude to the far side of the part.

The recipe's add or new extrude `through` with no distance runs from its sketch plane along its normal to the far side
of the part built so far: the plane through the part's farthest point along that normal. Fusion's join "All" with the
target body as its only participant ends at the far side of that body. The two are taken to agree only when the
capture shows it (`_join_far_side`): the measured end cap lies on the far side of the body's box before the step, and
the face Fusion measured there is larger than the caps of the outlines, so the body had material on that plane and
the box is not loose there."""
from ...capture_model import gap_hints
from ...design_model.steps import extrude as dm
from ...geometry import vec
from ...geometry.combine_volume import profile_area
from .. import values
from ..ranges import range_check
from ..result import Refusal
from ..sketch import sketch_motion
from . import through_taper
from .taper import MAX_TAPER_DEG


# A tapered cut through all whose walls lean in ends this far (mm) past the part.
THROUGH_TAPER_MARGIN_MM = 1.0
_ADDS = "A join or new body through all is only copied one way, with no taper and no thin wall."
_JOIN_UNSURE = ("This step extrudes through all, and the copy could not check that it ends where the part ends, so "
                "it is left out.")
_JOIN_BODIES = ("This step extrudes through all, and Fusion ends it at the far side of other bodies too, so it is "
                "left out.")


def _farthest(box, origin, direction):
    """How far the box reaches from `origin` along `direction` (0 when it lies behind)."""
    lo, hi = box["min"], box["max"]
    farthest = 0.0
    for i in range(8):
        corner = [hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]]
        farthest = max(farthest, vec.dot(vec.sub(corner, origin), direction))
    return farthest


def _reach_through(box, origin, direction):
    """A distance that clears the whole box when cutting from `origin` along `direction`."""
    return _farthest(box, origin, direction) + vec.length(vec.sub(box["max"], box["min"])) + 1.0


def _box_union(box, other):
    if not box or not other:
        return box
    return {"min": [min(a, b) for a, b in zip(box["min"], other["min"])],
            "max": [max(a, b) for a, b in zip(box["max"], other["max"])]}


def resolve_through(ctx, plan, data, origin, z, combine, box_max=None, profiles=(), item=None, outlines=()):
    """Give a one sided cut or intersect through all its distance, write a one sided join or new body through all
    to the far side of the part (`_join_far_side`), or give a Refusal. `box_max` holds the part at every size the
    probe tried, so the cut still clears it when sizes grow.

    A tapered side keeps the same outline at each height whatever its length, so any length past the part cuts what
    Fusion's through all cuts. One whose walls can lean in, at the taper or at any size its taper follows, ends just
    past the part, and only while its outlines stay open there. When the taper or the outlines (`outlines`, the
    `sketch_motion.Outline` of each) follow sizes, it is checked over their ranges, which are cut where it would close
    (`through_taper.keep_open`)."""
    for entry in plan:
        if entry.extent == "through" and combine not in ("cut", "intersect"):
            return Refusal(_ADDS, cause=gap_hints.THROUGH_ADDS)
        if entry.extent == "through-one":
            if combine not in ("cut", "intersect"):
                refusal = _join_far_side(ctx, item, plan, entry, data, origin, z, outlines)
                if refusal:
                    return refusal
                continue
            box = _box_union(data.get("target_box_before"), box_max)
            if not box:
                return Refusal("The part this cuts through could not be measured.")
            entry.extent = "oneSide"
            direction = vec.scale(z, entry.sign)
            lean = _lean_in(ctx, entry)
            if lean > 0:
                entry.distance = _farthest(box, origin, direction) + THROUGH_TAPER_MARGIN_MM
                moves = any(drawn is not None and sketch_motion.outline_movers(ctx.table, drawn) for drawn in outlines)
                if (moves or not through_taper.stays_open(profiles, entry.distance, lean)) and not \
                        through_taper.keep_open(ctx, item, entry, profiles, outlines, MAX_TAPER_DEG):
                    return Refusal("This tapered cut through all closes before it passes the part, which is not "
                                   "copied.")
            else:
                entry.distance = _reach_through(box, origin, direction)
    return None


def _lean_in(ctx, entry):
    """The steepest recipe taper (degrees, walls leaning in) the side reaches: its own, or the largest its formula
    gives over the size ranges, at most MAX_TAPER_DEG (also when that cannot be worked out)."""
    lean = entry.taper or 0.0
    q = entry.taper_q
    if q is not None and q.sized:
        span = range_check.sweep(ctx.table, q.text, q.reads)
        lean = MAX_TAPER_DEG if span.failed or span.high is None else max(lean, span.high)
    return min(lean, MAX_TAPER_DEG)


def _cap_areas(data):
    """The sum of the outline areas of the extrude in `data` (mm2), or None when one cannot be worked out."""
    profiles = data.get("profiles") or []
    listed = data.get("areas") if isinstance(data.get("areas"), list) else []
    total = 0.0
    for n, profile in enumerate(profiles):
        area = profile_area(profile) if isinstance(profile, dict) else None
        if area is None and n < len(listed) and isinstance(listed[n], (int, float)):
            area = float(listed[n])
        if area is None and n == 0 and isinstance(data.get("profile_area"), (int, float)):
            area = float(data["profile_area"])
        if area is None or area <= 0:
            return None
        total += area
    return total if profiles else None


def _join_far_side(ctx, item, plan, entry, data, origin, z, outlines):
    """Write a one sided join or new body through all as the recipe's extrude to the far side of the part (extent
    `through`, no distance), or give a Refusal.

    Fusion ends it at the far side of its participant bodies, so the target body must be the only one. The measured
    end must be an end cap on the far side of the target's box before the step, along the direction the plan settled
    on. A box can be looser than the body, so that alone does not show where the body ends; the face Fusion measured
    at the end must also be larger than the caps of all outlines together: a join merges its cap with a face of the
    body on the same plane, so the body had material on that plane. The recipe's taper and thin wall do not go with
    this extent. Sizes that move the part before the step or the outlines may move its far side; the copy cannot
    check that Fusion and the recipe still end at the same place there, so they are marked."""
    participants = data.get("participants") or []
    if not participants:
        return Refusal(_JOIN_UNSURE, cause=gap_hints.THROUGH_ADDS)
    if len(participants) != 1 or not ctx.is_target(participants[0]):
        return Refusal(_JOIN_BODIES, cause=gap_hints.THROUGH_BODIES)
    if len(plan) != 1 or entry.taper or data.get("thin"):
        return Refusal(_ADDS, cause=gap_hints.THROUGH_ADDS)
    box, measured = data.get("target_box_before"), entry.read.measured if entry.read is not None else None
    if not box or measured is None or dm.end_is_cap(data, z) is not True:
        return Refusal(_JOIN_UNSURE, cause=gap_hints.THROUGH_ADDS)
    far = _farthest(box, origin, vec.scale(z, entry.sign))
    if far <= dm.LENGTH_TOL or abs(measured * entry.sign - far) > dm.LENGTH_TOL:
        return Refusal(_JOIN_UNSURE, cause=gap_hints.THROUGH_ADDS)
    caps, end = _cap_areas(data), data.get("end_area")
    if (caps is None or not isinstance(end, (int, float))
            or end <= caps * (1 + dm.CAP_RELATIVE_TOL) + dm.CAP_ABSOLUTE_TOL):
        return Refusal(_JOIN_UNSURE, cause=gap_hints.THROUGH_ADDS)
    values.pin(ctx, item, entry.read.taper_path, "a taper of zero cannot follow it")
    movers = set(ctx.written_reads or ())
    for drawn in outlines:
        if drawn is not None and ctx.table is not None:
            movers |= set(sketch_motion.outline_movers(ctx.table, drawn))
    if movers:
        ctx.doubt(sorted(movers), "%s reaches the far side of the part, and the copy cannot check that it still ends "
                                  "where Fusion ends it when the part changes" % item.get("name", "a step"))
    entry.extent, entry.distance = "through", None
    return None
