"""Round and chamfer steps whose sets of edges are copied one after the other (FilletFeature, ChamferFeature).

A Fusion fillet or chamfer can hold several sets of edges, each picked its own way (edge by edge, through faces, along
tangent chains) and each with its own size. One recipe step picks its edges in one way only. Fusion builds the sets
together; where they lie apart (`design_model.steps.finish.apart`: no shared edge or corner, and no corners near
each other) it gives the same part when it builds them one after the other. The handler then copies the sets as
several steps, one per group of sets that one step can pick the way Fusion did (`groups`), in the order of the sets,
and a set that cannot be copied is left out on its own: a gap after the written steps (`result.LeftOut`). The caller
checks that the sets lie apart; `copy_apart` does the rest.
"""
from ...capture_model import gap_hints
from ...design_model.steps import finish as sets_of
from ..result import LeftOut, Refusal, StepResult

SPLIT_NOTE = ("The sets of edges of this step are copied one after the other, since Fusion picked them in different "
              "ways or with different sizes.")


def groups(sets, joins):
    """`sets` in groups, in the order of their first sets: a set joins the first group whose first set `joins` it."""
    found = []
    for one in sets:
        for group in found:
            if joins(group[0], one):
                group.append(one)
                break
        else:
            found.append([one])
    return found


def _numbers(indexes):
    words = [str(n + 1) for n in indexes]
    return words[0] if len(words) == 1 else "%s and %s" % (", ".join(words[:-1]), words[-1])


def _left_out(item, left, count):
    """The `LeftOut` of the sets of `left` (`[(set, Refusal)]` in the order of the sets) of `item`, a step of `count`
    sets: the reason and the cause are those of the first set left out."""
    indexes = [one.index for one, _ in left]
    first = left[0][1]
    reason = "%s %s of %d of this step %s left out, the other sets are copied. %s" % (
        "Set" if len(indexes) == 1 else "Sets", _numbers(indexes), count, "is" if len(indexes) == 1 else "are",
        first.reason)
    kept = [n for n in range(count) if n not in indexes]
    return LeftOut(sets_of.only_sets(item, indexes, renumber=True), sets_of.only_sets(item, kept), reason,
                   gap_hints.refusal_cause(first))


def copy_apart(ctx, item, sets, refusal_of, grouped, copy_group, notes=None):
    """The `StepResult` of the step `item` copied group of sets by group of sets, or None when the step is to be
    copied as one: no set can be copied, or the sets make one group that can be copied. The sets must lie apart.

    `refusal_of(set)` gives the `Refusal` of a set that cannot be copied, else None. `grouped(sets)` puts the sets that
    can be copied in groups (`groups`). `copy_group(sets)` gives the `Entry` records of one group, or a `Refusal`: then
    what it recorded on `ctx` is dropped, and each set of the group is copied on its own; a set that still gives a
    `Refusal` is left out. Sets left out make the result's `left_out`.
    `notes(sets)`, when given, records the notes of the whole step once, for the sets written."""
    left, kept = [], []
    for one in sets:
        refusal = refusal_of(one)
        if refusal is None:
            kept.append(one)
        else:
            left.append((one, refusal))
    found = grouped(kept) if kept else []
    if not found:
        return None
    if not left and len(found) == 1:
        # One group: the step is copied as one, unless the group cannot be; then its sets are tried one by one.
        with ctx.recording():
            whole = copy_group(found[0])
        if not isinstance(whole, Refusal) or len(found[0]) == 1:
            return None
    entries, written = [], []
    queue = list(found)
    while queue:
        group = queue.pop(0)
        with ctx.recording() as recorded:
            made = copy_group(group)
        if isinstance(made, Refusal):
            if len(group) > 1:
                # Each set on its own, so only the sets that cannot be copied are left out.
                queue[:0] = [[one] for one in group]
            else:
                left.append((group[0], made))
            continue
        ctx.replay(recorded)
        entries += made
        written.append(group)
    if not entries:
        return None
    if notes is not None:
        notes([one for group in written for one in group])
    if len(written) > 1:
        ctx.note(SPLIT_NOTE)
    out = StepResult(entries)
    if left:
        out.left_out = _left_out(item, sorted(left, key=lambda pair: pair[0].index), len(sets))
    return out
