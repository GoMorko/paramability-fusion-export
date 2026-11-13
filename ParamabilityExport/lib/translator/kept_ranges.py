"""The values of the sizes inside which some rules keep their sign.

A rule is `(value, sign)`: a sized Quantity that must stay above `tol` (sign 1), below `-tol` (sign -1) or within
`tol` of zero (sign 0) at every size setting of the range (`range_check.corners`: every mix of the ends of the sizes
it reads). `holding_ranges` looks for the values the ends of the sizes it reads can go to while the rules still hold:
each size at its own ends first, then both ends of all of them by the same share of what is left for the settings that
change several sizes at once, so no one size gives up all of its room, and an end the rules do not need cut gets its
whole range back (a test costly to run moves the far ends first, `holding_ranges_where` without `balanced`). It does
not change the ranges itself: the caller marks the sizes past the values found (`past_reasons`), so the person knows
past which value a size may give unexpected results, or cuts the ranges to them (`Context.cut`). A size whose range
the person typed gets no value: the rules cannot be kept for it.

`built_ranges` does change ranges: where Fusion itself did not rebuild the design at a value the size probe tried, the
range stops at the farthest value that built on that side, since the form should not offer a value the design cannot
take. Only a failure in a step the part is built from counts. Where a sketch the copy follows makes a different outline
(`Motion.spans` `kept`, `probe.build.outline_windows`), the range stops at the farthest value tried that kept it.
"""
import math

from . import range_check
from .notes import Past, number_text as _number
from ..params.size_table import Cut
from ..sketch_values import coverage

_SAME = 1e-9


def past_reasons(table, found, why):
    """`{Fusion name: notes.Past}` for each size in `found` (`holding_ranges`): `why` with the values past which the
    rules may fail ("past 2.05", "below 1", "outside 1 to 2.05")."""
    out = {}
    for name, (lo, hi) in found.items():
        size = table.sizes.get(table.size_name(name)) or {}
        below, past = lo > size.get("min", lo), hi < size.get("max", hi)
        where = ("outside %s to %s" % (_number(lo), _number(hi)) if below and past
                 else "below %s" % _number(lo) if below else "past %s" % _number(hi))
        out[name] = Past(where, why)
    return out


def _part_step(capture):
    """A test for the step names (`Motion.spans` `failed`) of timeline items the part is built from: items of the
    target's component and the steps that made a tool body of a Combine. A name that also belongs to an item outside
    those, or to no item, is not the part's. A failure with no step name (the design did not recompute at all), or
    without a capture, counts for the part."""
    if capture is None:
        return lambda step: True
    mine, other = set(), set()
    for item in capture.get("items") or ():
        owned = item.get("in_target_component") or item.get("helper_of") or item.get("body_states")
        (mine if owned else other).add(item.get("name"))
    return lambda step: not step or (step in mine and step not in other)


def failure_cut(table, entry, span, mine):
    """`(low, high, found)`: the range of a free size cut on each side where Fusion did not rebuild with only that
    size changed (`span` as `Motion.spans`), past the farthest value that built; `mine(step)` says whether a failed
    step counts (`_part_step`). An end the person typed is kept; `found` holds `(value, step)` of the nearest failure
    behind each cut end."""
    size = table.sizes[entry.size_name]
    failed = [(value, step) for value, step in span.get("failed") or () if mine(step)]
    typed_low, typed_high = table.typed_ends(entry.name)
    low, high, found = size["min"], size["max"], {}
    below = [f for f in failed if f[0] < span["low"] - _SAME]
    past = [f for f in failed if f[0] > span["high"] + _SAME]
    if not typed_low and below:
        low, found["low"] = max(low, span["low"]), max(below, key=lambda f: f[0])
    if not typed_high and past:
        high, found["high"] = min(high, span["high"]), min(past, key=lambda f: f[0])
    return low, high, found


def outline_cut(table, entry, span):
    """`(low, high, changed)`: the range cut to the values a sketch the copy follows kept its outline at (`span`
    `kept`, an end None where nothing changed), with `(value, sketch)` of the nearest different outline behind each
    cut end. An end the person typed is kept."""
    size = table.sizes[entry.size_name]
    kept, changed = span.get("kept") or (None, None), span.get("changed") or ()
    typed = table.typed_ends(entry.name)
    low, high, found = size["min"], size["max"], {}
    now = size["value"]
    for side, at, sign in (("low", 0, -1), ("high", 1, 1)):
        if kept[at] is None or typed[at]:
            continue
        past = [(v, s) for v, s in changed if (v - kept[at]) * sign > _SAME]
        if not past:
            continue
        found[side] = min(past, key=lambda c: abs(c[0] - now))
        if side == "low":
            low = max(low, kept[at])
        else:
            high = min(high, kept[at])
    return low, high, found


def built_ranges(table, motion, capture=None):
    """`{Fusion name: Cut}` of the free sizes whose range goes past a value at which Fusion did not rebuild the design
    (`Motion.spans`: a value tried with only that size changed), or at which a followed sketch makes a different
    outline (`outline_cut`). On that side the range stops at the farthest value that built and kept the outline. An end
    the person typed is kept, and a range that would shrink to the value now is left as it is (the size could not be
    measured). A failure in a step the part is not built from (`capture` items of other components) cuts nothing: the
    part itself may rebuild there."""
    out = {}
    mine = _part_step(capture)
    for e in table.entries:
        span = coverage.span(motion, e.name)
        size = table.sizes.get(e.size_name) if e.size_name else None
        if not span or not size or "min" not in size:
            continue
        low, high, found = failure_cut(table, e, span, mine)
        kept_low, kept_high, changed = outline_cut(table, e, span)
        cut = Cut(low, high, found).meet(Cut(kept_low, kept_high, changed=changed))
        if (cut[0], cut[1]) != (size["min"], size["max"]) and cut[1] - cut[0] > _SAME:
            out[e.name] = cut
    return out


def _keeps(sign, span, tol):
    if sign == 0:
        return span.at_least(-tol) and span.at_most(tol)
    return span.above(tol) if sign > 0 else span.below(-tol)


def _holds(table, rules, bounds, tol, only=None):
    """True when the rules keep their sign at the settings of `bounds` (every corner of the ranges); `only` (size, 0 for
    its min or 1 for its max) limits them to that one end."""
    for value, sign in rules:
        if only is None:
            span = range_check.sweep(table, value.text, value.reads, bounds)
        elif any(table.size_name(r) == only[0] for r in value.reads):
            span = range_check.sweep(table, value.text, (), extra=[{only[0]: bounds[only[0]][only[1]]}])
        else:
            continue
        if not _keeps(sign, span, tol):
            return False
    return True


def _tidy(size, value, up):
    """`value` on the step the form shows (whole numbers for a count, else hundredths), rounded toward the size."""
    step = 1.0 if size.get("kind") == "count" else 0.01
    return round((math.ceil(value / step - 1e-9) if up else math.floor(value / step + 1e-9)) * step, 6)


def holding_ranges(table, rules, tol):
    """`{Fusion name: (min, max)}` inside which every rule holds: empty when they hold over the whole ranges, None when
    no shorter ranges make them hold (they fail at the current values, a range would shrink to its value, or every size
    read has a typed range)."""
    reads = list(dict.fromkeys(r for value, _ in rules for r in value.reads))
    return holding_ranges_where(table, reads, lambda bounds, only=None: _holds(table, rules, bounds, tol, only))


def holding_ranges_where(table, reads, holds, steps=range_check.STEPS, balanced=True):
    """`holding_ranges` for a rule that is a test, not a sized value: `holds(bounds, only=None)` says whether it holds
    at the settings of `bounds` ({recipe size name: (low, high)}, `range_check.corners` for the settings), or at the
    one end `only` ((size, 0 for its min or 1 for its max), the other sizes at their value now). `reads` are the
    Fusion names of the sizes the rule depends on. `steps` is how many halvings find each end of a range.

    Without `balanced` (for a test that is costly to run), the joint cut moves the far ends first and the near ends
    after, which tests fewer settings, and gives back only a whole range that holds."""
    sized = [(name, table.size_name(name)) for name in reads]
    sized = [(name, s) for name, s in sized if s in table.sizes and "min" in table.sizes[s]]
    bounds = {s: (table.sizes[s]["min"], table.sizes[s]["max"]) for _, s in sized}
    if holds(bounds):
        return {}
    free = [(name, s) for name, s in sized if not table.typed_range(name)]
    if not free:
        return None

    def toward(limits, names, t_low, t_high):
        out = dict(limits)
        for s in names:
            value, (lo, hi) = table.sizes[s]["value"], limits[s]
            out[s] = (lo if t_low >= 1.0 else value - t_low * (value - lo),
                      hi if t_high >= 1.0 else value + t_high * (hi - value))
        return out

    names = [s for _, s in free]
    if not holds(toward(bounds, names, 0.0, 0.0)):
        return None
    # Each size alone first, so a size whose own ends hold keeps them; then all together for the joint settings.
    limits = dict(bounds)
    for s in names:
        t_high = range_check.largest_share(lambda t: holds(toward(limits, [s], 1.0, t), (s, 1)), steps)
        t_low = range_check.largest_share(lambda t: holds(toward(limits, [s], t, 1.0), (s, 0)), steps)
        limits = toward(limits, [s], t_low, t_high)
    if balanced:
        # Both ends by one share, so no size gives up all of its room for the others.
        both = range_check.largest_share(lambda t: holds(toward(limits, names, t, t)), steps)
        exact = toward(limits, names, both, both)
        ends = [(s, (end,)) for s in names for end in (0, 1)]
    else:
        t_high = range_check.largest_share(lambda t: holds(toward(limits, names, 1.0, t)), steps)
        t_low = range_check.largest_share(lambda t: holds(toward(limits, names, t, t_high)), steps)
        exact = toward(limits, names, t_low, t_high)
        ends = [(s, (0, 1)) for s in names]
    # The share also shortens ends the rules hold at (a size that only helps one way, or cancels out): give them back.
    for s, back in ends:
        trial = dict(exact, **{s: tuple(bounds[s][k] if k in back else exact[s][k] for k in (0, 1))})
        if trial[s] != exact[s] and holds(trial):
            exact = trial
    tidy = dict(exact)
    for _, s in free:
        size, (lo, hi) = table.sizes[s], exact[s]
        tidy[s] = (min(_tidy(size, lo, True), size["value"]), max(_tidy(size, hi, False), size["value"]))
    chosen = tidy if holds(tidy) else exact
    if any(chosen[s][1] - chosen[s][0] <= 1e-9 for _, s in free):
        return None
    return {name: chosen[s] for name, s in free if chosen[s] != bounds[s]}
