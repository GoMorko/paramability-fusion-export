"""The length of a cut through all, and whether a tapered one stays open until it passes the part."""
from .. import range_check, sketch_motion, through_taper, vec
from ..result import Refusal
from .taper import MAX_TAPER_DEG


# A tapered cut through all whose walls lean in ends this far (mm) past the part.
THROUGH_TAPER_MARGIN_MM = 1.0


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


def _resolve_through(ctx, plan, data, origin, z, combine, box_max=None, profiles=(), item=None, outlines=()):
    """Give a one sided through all its distance, or a Refusal. `box_max` holds the part at every size the probe
    tried, so the cut still clears it when sizes grow.

    A tapered side keeps the same outline at each height whatever its length, so any length past the part cuts what
    Fusion's through all cuts. One whose walls can lean in, at the taper or at any size its taper follows, ends just
    past the part, and only while its outlines stay open there. When the taper or the outlines (`outlines`, the
    `sketch_motion.Outline` of each) follow sizes, it is checked over their ranges, which are cut where it would close
    (`through_taper.keep_open`)."""
    for entry in plan:
        if entry["extent"] == "through" and combine not in ("cut", "intersect"):
            return Refusal("Extruding through all is only copied for cuts.")
        if entry["extent"] == "through-one":
            if combine not in ("cut", "intersect"):
                return Refusal("Extruding through all is only copied for cuts.")
            box = _box_union(data.get("target_box_before"), box_max)
            if not box:
                return Refusal("The part this cuts through could not be measured.")
            entry["extent"] = "oneSide"
            direction = vec.scale(z, entry["sign"])
            lean = _lean_in(ctx, entry)
            if lean > 0:
                entry["distance"] = _farthest(box, origin, direction) + THROUGH_TAPER_MARGIN_MM
                moves = any(drawn is not None and sketch_motion.outline_movers(ctx.table, drawn) for drawn in outlines)
                if (moves or not through_taper.stays_open(profiles, entry["distance"], lean)) and not \
                        through_taper.keep_open(ctx, item, entry, profiles, outlines, MAX_TAPER_DEG):
                    return Refusal("This tapered cut through all closes before it passes the part, which is not "
                                   "copied.")
            else:
                entry["distance"] = _reach_through(box, origin, direction)
    return None


def _lean_in(ctx, entry):
    """The steepest recipe taper (degrees, walls leaning in) the side reaches: its own, or the largest its formula
    gives over the size ranges, at most MAX_TAPER_DEG (also when that cannot be worked out)."""
    lean = entry["taper"] or 0.0
    q = entry.get("taper_q")
    if q is not None and q.sized:
        span = range_check.sweep(ctx.table, q.text, q.reads)
        lean = MAX_TAPER_DEG if span.failed or span.high is None else max(lean, span.high)
    return min(lean, MAX_TAPER_DEG)
