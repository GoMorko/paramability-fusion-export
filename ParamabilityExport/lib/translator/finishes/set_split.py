"""Round and chamfer steps whose sets of edges are copied one after the other (FilletFeature, ChamferFeature).

A Fusion fillet or chamfer can hold several sets of edges, each picked its own way (edge by edge, through faces, along
tangent chains) and each with its own size. One recipe step picks its edges in one way only. Fusion builds the sets
together; where they lie apart (`apart`) it gives the same part when it builds them one after the other. The handler
then copies the sets as several steps, one per group of sets that one step can pick the way Fusion did (`groups`), in
the order of the sets, and a set that cannot be copied is left out on its own: a gap after the written steps
(`result.LeftOut`). The caller checks that the sets lie apart; `copy_apart` does the rest.

Two sets lie apart when their edges stay further apart (`design_model.steps.finish.box_gap`) than the margin times
the most the two sets reach over the size ranges (`reach_terms`, swept with `range_check.sweep`). Sizes that move the
edges are not tried edge by edge, so the sizes read before a step that is copied as several steps are marked, as for
a pick the copy cannot follow (`mark_apart`).
"""
from ...capture_model import gap_hints
from ...design_model import reach
from ...design_model.steps import finish as sets_of
from ...design_model.values import Quantity
from .. import values
from ..ranges import range_check
from ..result import LeftOut, Refusal, StepResult

SPLIT_NOTE = ("The sets of edges of this step are copied one after the other, since Fusion picked them in different "
              "ways or with different sizes.")


def _largest_reach(ctx, item, sets):
    """The most (mm) that `sets` reach together along their faces at any size setting, or None when it is not known:
    also when a value cannot follow its sizes, or a value that the reach holds only while it stays follows sizes.
    Nothing it works out counts for the walk."""
    total = Quantity(0.0)
    with ctx.recording() as recorded:
        for one in sets:
            found = sets_of.reach_terms(one)
            if found is None:
                return None
            for field, number, dim in found.held:
                if values.quantity(ctx, item, one.path(field), number, dim=dim).sized:
                    return None
            for field, number, factor, dim in found.terms:
                total = total.plus(values.quantity(ctx, item, one.path(field), number, dim=dim, absolute=True)
                                   .scaled(factor))
    if recorded.doubts:
        return None
    if not total.sized or ctx.table is None:
        return total.n
    span = range_check.sweep(ctx.table, total.text, total.reads)
    if span.failed or span.high is None:
        return None
    return max(span.high, total.n)


def apart(ctx, item, a, b):
    """True when the edges of the sets `a` and `b` of `item` stay further apart than `sets_of.CORNER_MARGIN` times the
    most the two reach together, so Fusion gives the same part when it applies them one after the other."""
    gap = sets_of.box_gap(a, b)
    if gap is None:
        return False
    most = _largest_reach(ctx, item, [a, b])
    return most is not None and gap > sets_of.CORNER_MARGIN * most + sets_of.CORNER_TOL


def all_apart(ctx, item, sets):
    """True when every two of `sets` lie `apart`."""
    return all(apart(ctx, item, a, b) for n, a in enumerate(sets) for b in sets[n + 1:])


def mark_apart(ctx, item):
    """The step `item` is copied as several steps: mark the sizes that may move the edges of its sets near each other
    (`reach.any_face_sizes`: every size read before the step). The first translation of an export marks nothing."""
    if ctx.table is None or getattr(ctx.motion, "optimistic", False):
        return
    names = reach.any_face_sizes(ctx.table, ctx.capture.get("items") or [], item)
    if names:
        ctx.doubt(names, "%s is copied as several steps, one after the other, which gives the same part only while "
                  "its sets of edges stay apart" % item.get("name", "a step"))


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
        if not isinstance(whole, Refusal) or len(found[0]) == 1 or not all_apart(ctx, item, found[0]):
            return None
    entries, written = [], []
    queue = list(found)
    while queue:
        group = queue.pop(0)
        with ctx.recording() as recorded:
            made = copy_group(group)
        if isinstance(made, Refusal):
            if len(group) > 1 and all_apart(ctx, item, group):
                # Each set on its own, so only the sets that cannot be copied are left out.
                queue[:0] = [[one] for one in group]
            else:
                left += [(one, made) for one in group]
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
        mark_apart(ctx, item)
    out = StepResult(entries)
    if left:
        out.left_out = _left_out(item, sorted(left, key=lambda pair: pair[0].index), len(sets))
    return out
