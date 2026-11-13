"""The steps a repeat writes: the pattern or mirror steps, and the round and chamfer copies that go with them.

`build` joins the repeat steps and the finish copies into one result, refusing a repeat that makes too many bodies.
Copies of rounds and chamfers are placed point by point, so a repeat whose copies cannot follow a changed count or
angle fixes the sizes behind them (`keep_pattern_fixed`).
"""
from ..geometry import vec
from ..geometry.vec import POINT_TOL
from ..package.numbers import round9
from . import follow, values
from .picks import MAX_NEAR_POINTS
from .placer_makers import CopiesMaker
from .result import Refusal, StepResult
from .step_kinds import recipe_kind
from .values import number

MAX_COPIED_BODIES = 256


def round_vec(values):
    return [round9(v) for v in values]


def _written_points(ctx, item, source):
    """The source's pick points as written (formulas where they follow sizes). A pick that names a step is placed
    again here; when that fails, its sizes are fixed and the measured points are used."""
    if source.get("written") is not None:
        return source["written"]
    followed = follow.follow_points(ctx, item, source["near"]) if ctx.written_reads else None
    return followed if followed is not None else source["near"]


def finish_copies(ctx, item, finishes, motions):
    """Round and bevel steps for the copies. `motions` are the follow.Motion of each copy. Each source has its
    measured points in `near` and its written points in `written`.

    A moved point that lands on one of the source's own points is dropped, with its size: that edge is already
    finished, and the point would pick a neighbouring edge of the new surface. The copies are packed whole into
    steps of at most MAX_NEAR_POINTS points; copies whose `sizeOn` turns differently get their own steps.
    """
    steps = []
    for source in finishes:
        near = source["near"]
        if not near:
            continue
        written = _written_points(ctx, item, source)
        sizes = source.get("edgeSizes")
        if sizes is not None:
            sizes = list(sizes) + [source["size"]] * (len(near) - len(sizes))
        groups = []
        for motion in motions:
            kept = [(motion.numbers(p), n) for n, p in enumerate(near)]
            kept = [(follow.cleaned_all(motion.quantities(written[n])), n) for q, n in kept
                    if not any(vec.close(q, p, POINT_TOL) for p in near)]
            if not kept:
                continue
            size_on = round_vec(motion.turn_vector(source["sizeOn"])) if "sizeOn" in source else None
            if groups and groups[-1][0] == size_on and len(groups[-1][1]) + len(kept) <= MAX_NEAR_POINTS:
                groups[-1][1].extend(kept)
            else:
                groups.append((size_on, list(kept)))
        for size_on, group in groups:
            step = {"kind": source["kind"], "edges": {"near": [q for q, _ in group]}, "size": source["size"]}
            if (source.get("edges") or {}).get("chain"):
                step["edges"]["chain"] = source["edges"]["chain"]
            for key in ("otherSize", "cutAngleDeg"):
                if key in source:
                    step[key] = source[key]
            if size_on is not None:
                step["sizeOn"] = size_on
            if sizes is not None:
                step["edgeSizes"] = [sizes[n] for _, n in group]
            steps.append(step)
    return steps


def _kept_copy_count(step):
    """Copies a pattern step makes beyond the original, as the app counts them."""
    grid = 0
    if "linear" in step:
        grid = max(0, number(step["linear"]["count"]) * number(step.get("linear2", {}).get("count", 1)) - 1)
    turned = max(0, number(step["polar"]["count"]) - 1) if "polar" in step else 0
    return max(0, grid + turned - len(set(step.get("skip", ()))))


def copied_bodies(steps):
    """Tool bodies the pattern and mirror steps add, counted as the app counts them.

    A step named in `of` counts once; a repeat among them counts all the bodies it makes, original included.
    """
    bodies = {}
    total = 0
    for step in steps:
        if not recipe_kind(step.get("kind")).repeats:
            continue
        sources = sum(bodies.get(i, 1) for i in set(step["of"]))
        added = sources if step["kind"] == "mirror" else _kept_copy_count(step) * sources
        total += added
        bodies[step.get("id")] = added + sources
    return total


def build(ctx, item, solids, finishes, repeat_steps, what):
    """The repeat steps (when there are solid sources) followed by the finish copies. `repeat_steps` are
    `(step, motions)`: a step and the Motions of the copies it makes. The finish copies use every Motion."""
    out = StepResult()
    if solids:
        for repeat_step, owned in repeat_steps:
            repeat_step["of"] = solids
            out.add(repeat_step, [CopiesMaker(owned)])
        if copied_bodies(list(ctx.steps) + out.steps) > MAX_COPIED_BODIES:
            return Refusal("This %s makes more than %d copies in all." % (what, MAX_COPIED_BODIES))
    motions = [motion for _, owned in repeat_steps for motion in owned]
    out.extend(StepResult.of(finish_copies(ctx, item, finishes, motions)).entries)
    if not out.entries:
        return Refusal("This %s makes no copies." % what)
    return out


def keep_pattern_fixed(ctx, item, skip, finishes, counts, turns=()):
    """Copies that are left out by number, or rounds that are copied one by one, cannot follow a changed count;
    turned copies cannot follow a changed angle either. The sizes behind them become fixed numbers."""
    name = item.get("name", "a pattern")
    if skip:
        for path in counts:
            values.pin(ctx, item, path, "%s leaves copies out, so its count must stay" % name)
    if finishes:
        for path in counts + tuple(turns):
            values.pin(ctx, item, path, "the rounded or chamfered copies in %s are placed one by one" % name)
