"""Fillet and chamfer steps as Orca rounds and chamfers of a whole group of edges; shell and draft are left out.

Orca can round or chamfer only every edge of a face group of the part (all, top, bottom or side edges, see
`finish_body`); it names single edges by its own numbering, which the copy cannot know. So a step is copied only when
its picked edges are exactly one group of the part as the copy builds it, with one size (the size may follow
variables). A step whose sets have different sizes is made as one feature for each size, when each is such a group
(a top and a bottom one). The sets are read by `design_model.steps.finish`. Orca stops the whole rebuild on a round
it cannot make, so a step is also left out when the copy cannot tell the part's edges (`finish_body.body_of`), or
when the size leaves too little of a face (`finish_body.room`).
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
from ..design_model.steps import finish as sets_of
from ..design_model.values import Quantity
from ..orca_recipe.enums import FeatureType
from ..orca_recipe.feature import CadFeature
from . import causes, corner_hosts, finish_body, limits, outline_rounds
from .skip import Skip

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


def _quantity(ctx, item):
    """The `quantity(path, number, dim)` the set readers call: a size that may follow the design's sizes."""
    def quantity(path, number, dim):
        return ctx.quantity(item, path, float(number), dim)
    return quantity


def _set_check(one, kind):
    """A Skip for a set whose edges cannot be copied, else None."""
    if one.follows_step:
        return Skip("A %s that follows another step's edges is not copied to Orca." % kind.noun)
    if not one.edges or one.unlocated:
        return Skip("The edges of this %s could not be located." % kind.noun)
    if one.foreign:
        return Skip("This %s is on edges of another component, which is not copied." % kind.noun,
                    gap_hints.OTHER_COMPONENT)
    return None


def _different_sizes(kind):
    return Skip("This %s has edges of different sizes that are not each a whole group of edges, and Orca makes a %s "
                "of one size on one group, so it is left out." % (kind.noun, kind.noun),
                gap_hints.ROUND_KIND if kind is ROUND else gap_hints.REFUSED)


def _by_size(ctx, item, sets, sizes):
    """The edges of `sets` in parts of one size: [(`Quantity`, edge records)], in order of first appearance. Sets whose
    numbers are equal are one part, made with the first set's size; the sizes of the others, when they follow other
    variables, get the reason."""
    parts = [sets_of.Part(Quantity(size.n), None, {}, one.edges, [one]) for one, size in zip(sets, sizes)]
    found = []
    for part in sets_of.merge(parts):
        value = sizes[part.sets[0].index]
        for one in part.sets[1:]:
            other = sizes[one.index]
            if other.text != value.text:
                ctx.doubt(other.reads, "%s: Orca makes every edge with the size of its first edges" % _label(item))
        found.append((value, part.edges))
    return found


def fillet(ctx, item):
    """The Orca round of a fillet step, or a Skip."""
    data = _data(item)
    sets = sets_of.round_sets(data)
    if not sets:
        return Skip("This round has no edges to copy.")
    quantity = _quantity(ctx, item)
    for one in sets:
        if one.kind != sets_of.CONSTANT:
            return Skip(_ROUND_KINDS.get(one.kind, "This kind of round is not copied to Orca."),
                        gap_hints.ROUND_KIND if one.kind in _ROUND_KINDS else gap_hints.REFUSED)
        if one.continuity == "curvature":
            return Skip("Rounds with curvature continuity are not copied to Orca.")
        problem = _set_check(one, ROUND)
        if problem:
            return problem
        if one.radius is None:
            return Skip("This round has no readable radius.")
    sizes = [one.size(quantity) for one in sets]
    drawn = outline_rounds.made(ctx, item, [outline_rounds.Pick(one.edges, size) for one, size in zip(sets, sizes)],
                                False)
    if drawn is not None:
        return drawn
    notes = []
    if data.get("rolling_ball") is False:
        notes.append("%s: Fusion used setback corners; Orca uses rolling ball corners, so corners where three "
                     "rounded edges meet can look different." % _label(item))
    return _finish_parts(ctx, item, ROUND, _by_size(ctx, item, sets, sizes), notes)


def _even_chamfer(ctx, item, one):
    """The `Quantity` of the distance of an even chamfer set, or a Skip. Two equal distances, or a distance and 45
    degrees, are even while they stay so: the second value's sizes get the reason."""
    if one.distance is None:
        return Skip("This chamfer has no readable size.")
    if one.problem == sets_of.UNKNOWN_KIND:
        return Skip("This kind of chamfer is not copied to Orca.")
    if not one.even:
        return Skip("This chamfer has two different sizes, and Orca makes only even chamfers, so it is left out.")
    if one.held:
        held = one.held.size(_quantity(ctx, item))
        ctx.doubt(held.reads, "%s: the chamfer stays even in Orca" % _label(item))
    return one.size(_quantity(ctx, item))


def chamfer(ctx, item):
    """The Orca chamfer of a chamfer step, or a Skip."""
    data = _data(item)
    sets = sets_of.chamfer_sets(data)
    if not sets:
        return Skip("This chamfer has no edges to copy.")
    sizes = []
    for one in sets:
        found = _even_chamfer(ctx, item, one)
        if isinstance(found, Skip):
            return found
        problem = _set_check(one, CHAMFER)
        if problem:
            return problem
        sizes.append(found)
    drawn = outline_rounds.made(ctx, item, [outline_rounds.Pick(one.edges, size, one.kind == sets_of.DISTANCE_ANGLE)
                                            for one, size in zip(sets, sizes)], True)
    if drawn is not None:
        return drawn
    notes = []
    if data.get("corner_type", "chamfer") != "chamfer":
        notes.append("%s: Fusion used another corner type; Orca uses its own." % _label(item))
    return _finish_parts(ctx, item, CHAMFER, _by_size(ctx, item, sets, sizes), notes)


def _finish_parts(ctx, item, kind, parts, notes):
    """The Orca features of a step whose edges are in parts of one size (`_by_size`): one round or chamfer for each
    part, made one after the other, or a Skip. A step with several parts is copied only when each part is a group of
    edges Orca makes (`_finish`); a part that is not leaves the whole step out. A part that is no group of edges, or
    that cannot follow a part of the same step because Orca's groups change after it, gets the reason of the
    different sizes."""
    if len(parts) == 1:
        value, records = parts[0]
        return _finish(ctx, item, kind, records, value, notes)
    features = []
    for value, records in parts:
        made = _finish(ctx, item, kind, records, value, notes if not features else [])
        if isinstance(made, Skip):
            own = made.cause in (causes.HAND_PICKED, causes.EDGES_NOT_ON_COPY) or (
                features and made.cause == causes.EDGES_CHANGED)
            return _different_sizes(kind) if own else made
        features += made
    ctx.notes.append("%s: the edges have different sizes, so the copy makes one %s for each size, one after the "
                     "other." % (_label(item), kind.noun))
    return features


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


def note_left_out(ctx, step):
    """Measure a round or chamfer that is left out (`step`, a `design_model.design.ResolvedStep`), so that a later
    round of side edges can tell whether it came near (`outline_rounds.note_left_out`)."""
    handler = HANDLERS.get(step.type)
    if handler in (fillet, chamfer):
        outline_rounds.note_left_out(ctx, step.item, step.facts, handler is chamfer)


HANDLERS = {"FilletFeature": fillet, "ChamferFeature": chamfer, "ShellFeature": shell, "DraftFeature": draft}
