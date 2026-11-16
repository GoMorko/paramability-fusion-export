"""Fillet and chamfer steps as Orca rounds and chamfers of a whole group of edges; shell and draft are left out.

Orca can round or chamfer only every edge of a face group of the part (all, top, bottom or side edges, see
`finish_body`); it names single edges by its own numbering, which the copy cannot know. So a step is copied only when
its picked edges are exactly one group of the part as the copy builds it, with one size (the size may follow
variables). Orca stops the whole rebuild on a round it cannot make, so a step is also left out when the copy cannot
tell the part's edges (`finish_body.body_of`), or when the size leaves too little of a face (`finish_body.room`).
After a round or chamfer the edges change: a later one is copied only on the other end of the same part (top after
bottom, or bottom after top), with the two sizes counted together.
A step whose edges are all side edges of copied straight extrudes (the corners of their outlines) is drawn into those
outlines instead (`outline_rounds`), each set with its own size.

Shell: Orca opens a shell only at a face it picks by its own numbering, and its shell without an open face keeps the
inner block instead of a hollow part. Draft: Orca picks the face by its own numbering and always tilts it about the
bottom of the part. Both are left out with the reason.
"""
import math

from ..capture_model import gap_hints
from ..orca_recipe.enums import FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, corner_hosts, finish_body, limits, outline_rounds
from .skip import Skip

SIZE_TOL = 1e-9
EVEN_ANGLE_DEG = 45.0
_ROUND_KINDS = {
    "variable": "Rounds with a changing radius are not copied to Orca.",
    "chordLength": "Rounds set by chord length are not copied to Orca.",
    "asymmetric": "Rounds with two different radii are not copied to Orca.",
}


class _Kind:
    """The words and feature type of a round or a chamfer."""

    def __init__(self, noun, verb, feature_type):
        self.noun, self.verb, self.type = noun, verb, feature_type


ROUND = _Kind("round", "round", FeatureType.FILLET)
CHAMFER = _Kind("chamfer", "chamfer", FeatureType.CHAMFER)


def _data(item):
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _label(item):
    return item.get("name") or "the step"


def _set_check(entry, kind):
    """A Skip for a set whose edges cannot be copied, else None."""
    if "feature" in (entry.get("input_kinds") or []):
        return Skip("A %s that follows another step's edges is not copied to Orca." % kind.noun)
    edges = entry.get("edges") or []
    if not edges or any(not e.get("points") for e in edges):
        return Skip("The edges of this %s could not be located." % kind.noun)
    if any(e.get("foreign") for e in edges):
        return Skip("This %s is on edges of another component, which is not copied." % kind.noun,
                    gap_hints.OTHER_COMPONENT)
    return None


def _one_size(ctx, item, kind, sizes):
    """The `Quantity` of the size every set shares (`sizes`: (param path, number) per set), or a Skip. Sets with their own
    parameter keep the first set's: their sizes get the reason."""
    first_path, first = sizes[0]
    if any(abs(number - first) > SIZE_TOL for _, number in sizes[1:]):
        return Skip("This %s has edges of different sizes, and Orca makes a %s of one size, so it is left out."
                    % (kind.noun, kind.noun), gap_hints.ROUND_KIND if kind is ROUND else gap_hints.REFUSED)
    value = ctx.quantity(item, first_path, first)
    for path, number in sizes[1:]:
        other = ctx.quantity(item, path, number)
        if other.text != value.text:
            ctx.doubt(other.reads, "%s: Orca makes every edge with the size of its first edges" % _label(item))
    return value


def fillet(ctx, item):
    """The Orca round of a fillet step, or a Skip."""
    data = _data(item)
    sets = data.get("sets") or []
    if not sets:
        return Skip("This round has no edges to copy.")
    sizes = []
    for n, entry in enumerate(sets):
        kind = entry.get("kind")
        if kind != "constant":
            return Skip(_ROUND_KINDS.get(kind, "This kind of round is not copied to Orca."),
                        gap_hints.ROUND_KIND if kind in _ROUND_KINDS else gap_hints.REFUSED)
        if entry.get("continuity") == "curvature":
            return Skip("Rounds with curvature continuity are not copied to Orca.")
        problem = _set_check(entry, ROUND)
        if problem:
            return problem
        radius = entry.get("radius")
        if not isinstance(radius, (int, float)) or not radius > 0:
            return Skip("This round has no readable radius.")
        sizes.append(("sets.%d.radius" % n, float(radius)))
    drawn = outline_rounds.made(ctx, item, [outline_rounds.Pick(entry["edges"], ctx.quantity(item, path, number))
                                            for entry, (path, number) in zip(sets, sizes)], False)
    if drawn is not None:
        return drawn
    value = _one_size(ctx, item, ROUND, sizes)
    if isinstance(value, Skip):
        return value
    notes = []
    if data.get("rolling_ball") is False:
        notes.append("%s: Fusion used setback corners; Orca uses rolling ball corners, so corners where three "
                     "rounded edges meet can look different." % _label(item))
    return _finish(ctx, item, ROUND, [e for entry in sets for e in entry["edges"]], value, notes)


def _even_chamfer(ctx, item, n, entry):
    """(param path, distance) of an even chamfer set, or a Skip. Two equal distances, or a distance and 45 degrees,
    are even while they stay so: the second value's sizes get the reason."""
    kind = entry.get("kind")
    distance = entry.get("distance")
    if not isinstance(distance, (int, float)) or not distance > 0:
        return Skip("This chamfer has no readable size.")
    uneven = Skip("This chamfer has two different sizes, and Orca makes only even chamfers, so it is left out.")
    if kind == "twoDistances":
        other = entry.get("distance_two")
        if not isinstance(other, (int, float)) or abs(other - distance) > SIZE_TOL:
            return uneven
        second = "sets.%d.distance_two" % n
    elif kind == "distanceAngle":
        angle = entry.get("angle_deg")
        if not isinstance(angle, (int, float)) or abs(angle - EVEN_ANGLE_DEG) > 1e-6:
            return uneven
        second = "sets.%d.angle_deg" % n
    elif kind == "equal":
        second = None
    else:
        return Skip("This kind of chamfer is not copied to Orca.")
    if second is not None:
        dim = "angle" if second.endswith("angle_deg") else "length"
        held = ctx.quantity(item, second, float(entry.get("angle_deg") if dim == "angle" else entry["distance_two"]),
                            dim)
        ctx.doubt(held.reads, "%s: the chamfer stays even in Orca" % _label(item))
    return "sets.%d.distance" % n, float(distance)


def chamfer(ctx, item):
    """The Orca chamfer of a chamfer step, or a Skip."""
    data = _data(item)
    sets = data.get("sets") or []
    if not sets:
        return Skip("This chamfer has no edges to copy.")
    sizes = []
    for n, entry in enumerate(sets):
        found = _even_chamfer(ctx, item, n, entry)
        if isinstance(found, Skip):
            return found
        problem = _set_check(entry, CHAMFER)
        if problem:
            return problem
        sizes.append(found)
    drawn = outline_rounds.made(ctx, item, [outline_rounds.Pick(entry["edges"], ctx.quantity(item, path, number),
                                                                entry.get("kind") == "distanceAngle")
                                            for entry, (path, number) in zip(sets, sizes)], True)
    if drawn is not None:
        return drawn
    value = _one_size(ctx, item, CHAMFER, sizes)
    if isinstance(value, Skip):
        return value
    notes = []
    if data.get("corner_type", "chamfer") != "chamfer":
        notes.append("%s: Fusion used another corner type; Orca uses its own." % _label(item))
    return _finish(ctx, item, CHAMFER, [e for entry in sets for e in entry["edges"]], value, notes)


def _finish(ctx, item, kind, records, value, notes):
    """The Orca feature that makes `kind` of `value` on the face group the Fusion `records` name, or a Skip."""
    if not ctx.has_body:
        return Skip("The part this %s is on is not in the copy." % kind.noun, gap_hints.AFTER_GAP)
    earlier = finish_body.earlier(ctx.scope, ctx.features)
    if any(done["group"] is None for done in earlier):
        return Skip("The part has a thread before this %s, and Orca would also %s the edges of the thread, so it is "
                    "left out." % (kind.noun, kind.verb), causes.EDGES_CHANGED)
    if any(done["pieces"] != len(ctx.solid.pieces) for done in earlier):
        return Skip("The part changed after an earlier round or chamfer, and the Orca copy cannot tell its edges "
                    "any more, so this %s is left out." % kind.noun, causes.EDGES_CHANGED)
    body = finish_body.body_of(ctx.solid)
    if isinstance(body, str):
        return Skip("Orca can %s only whole groups of edges, and the Orca copy cannot tell the edges of this part "
                    "(%s), so this %s is left out." % (kind.verb, body, kind.noun), causes.EDGES_UNKNOWN)
    chosen = finish_body.picked(body, records)
    if chosen is None:
        gap = bool(ctx.left_out)
        return Skip("The edges of this %s are not on the part as the Orca copy builds it%s, so it is left out."
                    % (kind.noun, " (a step before it is left out)" if gap else ""),
                    gap_hints.AFTER_GAP if gap else causes.EDGES_NOT_ON_COPY)
    found = finish_body.matching_group(body, ctx.place.direction, chosen)
    if found is None:
        return Skip("This %s is on hand-picked edges. Orca can %s only all edges of the part, or all its top, "
                    "bottom or side edges, so it is left out." % (kind.noun, kind.verb), causes.HAND_PICKED)
    group, taken = found
    if earlier and (group not in (finish_body.TOP, finish_body.BOTTOM)
                    or any(done["group"] not in (finish_body.TOP, finish_body.BOTTOM) or done["group"] == group
                           for done in earlier)):
        return Skip("After an earlier round or chamfer Orca's groups of edges change, and only a top one after a "
                    "bottom one (or the other way) is copied, so this %s is left out." % kind.noun,
                    causes.EDGES_CHANGED)
    ends = {body.edges[n].faces[0] for n in taken if body.edges[n].kind == "end"}
    for done in earlier:
        ends |= done["ends"]
    total = value.n + sum(done["size"] for done in earlier)
    why = finish_body.room(body, total, len(ends))
    if why:
        return Skip("This %s is too big for Orca to make safely on this part (%s), and a %s Orca cannot make stops "
                    "the whole rebuild, so it is left out." % (kind.noun, why, kind.noun), causes.NO_ROOM)
    outlines = corner_hosts.rebuilt(ctx, ctx.solid)
    if outlines is None:
        return Skip("The part has rounded corners whose sizes follow parameters, and the Orca copy cannot tell how "
                    "far they may change before this %s no longer fits, so it is left out." % kind.noun,
                    causes.NO_ROOM)
    name = _label(item)
    feature = CadFeature(type=kind.type, name=name, face_group=group, thread_major_nominal=True,
                         pattern_inclusive=True)
    ctx.bind(feature, "dressup_size", value, "%s size" % name)
    sized = _part_sized(ctx)
    ctx.add(feature)
    finish_body.finished(ctx.scope, feature, group, value.n,
                         {body.edges[n].faces[0] for n in taken if body.edges[n].kind == "end"})
    features = ctx.features
    finish_body.unsure(ctx.scope, body, taken, total, lambda: any(f is feature for f in features))
    unsure = _limits(ctx, body, [feature] + [done["feature"] for done in earlier], len(ends), outlines)
    if unsure:
        return Skip("The Orca copy cannot tell how far %s may change with this %s, so it is left out."
                    % (", ".join(unsure), kind.noun), causes.NO_ROOM)
    if sized:
        largest = _largest(body, total, len(ends))
        notes.append("%s: Orca stops the whole rebuild on a %s that does not fit the part. It fits while each side "
                     "and the height of the part stay above %d%% of what they are now." % (
                         name, kind.noun, int(math.ceil(100.0 * total / largest))))
    ctx.notes.extend(notes)
    if group != finish_body.ALL:
        ctx.notes.append("%s: copied as Orca's %s of all %s edges of the part; while the part keeps its shape "
                         "these are the edges picked in Fusion." % (name, kind.noun, finish_body.GROUP_WORDS[group]))
    return [feature]


def _limits(ctx, body, rounds, ends, outlines):
    """Tell the person how far the variables of the rounds on this part (`rounds`, their sizes added together) may
    go before Orca can no longer make them. The outlines whose corners corner tools cut (`outlines`, as
    `corner_hosts.rebuilt` gives them) change with their sizes: each of those sizes is walked too, with the part
    worked out again at each value. Returns the Orca variables whose limits cannot be told."""
    fields = [(f, "dressup_size") for f in rounds]
    reads, at = outlines
    if not reads:
        limits.tell(ctx, fields, lambda sizes: finish_body.room(body, sum(sizes), ends) is None, floor=True)
        return []

    def ok(sizes, env):
        shape = at(env)
        found = finish_body.body_of(shape) if shape is not None else "no shape"
        return not isinstance(found, str) and finish_body.room(found, sum(sizes), ends) is None
    return limits.tell_sizes(ctx, fields, reads, ok)[1]


def _largest(body, size, ends):
    """The largest size (mm) of the rounds that `finish_body.room` allows on this part as it is now."""
    good, bad = size, size * 2.0
    while finish_body.room(body, bad, ends) is None:
        good, bad = bad, bad * 2.0
    for _ in range(40):
        mid = (good + bad) / 2.0
        if finish_body.room(body, mid, ends) is None:
            good = mid
        else:
            bad = mid
    return good


def _part_sized(ctx):
    """True when a variable sets a size of the part the round sits on: a bound value of an earlier feature that
    shapes it."""
    return any(f.expr for f in ctx.features if f.type not in (FeatureType.FILLET, FeatureType.CHAMFER))


def shell(ctx, item):
    """Shells are left out: see the module note."""
    if _data(item).get("bodies_input"):
        return Skip("Orca's shell without an open face keeps the inside block instead of a hollow part, so this "
                    "closed hollow shell is left out.", causes.FACE_BY_NUMBER)
    return Skip("Orca opens a shell only at a face it picks by its own numbering, which the copy cannot know, so "
                "this shell is left out.", causes.FACE_BY_NUMBER)


def draft(ctx, item):
    """Drafts are left out: see the module note."""
    return Skip("Orca tilts only a face it picks by its own numbering, which the copy cannot know, and always about "
                "the bottom of the part, so this draft is left out.", causes.FACE_BY_NUMBER)


def note_left_out(ctx, item):
    """Measure a round or chamfer that is left out, so that a later round of side edges can tell whether it came near
    (`outline_rounds.note_left_out`)."""
    handler = HANDLERS.get(item.get("type"))
    if handler in (fillet, chamfer):
        outline_rounds.note_left_out(ctx, item, handler is chamfer)


HANDLERS = {"FilletFeature": fillet, "ChamferFeature": chamfer, "ShellFeature": shell, "DraftFeature": draft}
