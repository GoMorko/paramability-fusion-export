"""Size ranges shortened so that some values keep their sign.

A rule is `(value, sign)`: a sized Quantity that must stay above `tol` (sign 1), below `-tol` (sign -1) or within
`tol` of zero (sign 0) at every size setting of the range (`range_check.corners`: every mix of the ends of the sizes
it reads). `shortened` brings the ends of the sizes it reads toward their values until the rules hold: each size at
its own ends first, then all of them by the same share of what is left for the settings that change several sizes at
once. A size whose range the person typed keeps it.
"""
import math

from . import range_check


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


def shortened(table, rules, tol):
    """`{Fusion name: (min, max)}` that keeps every rule: empty when they hold already, None when shortening the
    ranges cannot make them hold (they fail at the current values, a range would shrink to its value, or every size
    read has a typed range)."""
    reads = list(dict.fromkeys(r for value, _ in rules for r in value.reads))
    sized = [(name, table.size_name(name)) for name in reads]
    sized = [(name, s) for name, s in sized if s in table.sizes and "min" in table.sizes[s]]
    bounds = {s: (table.sizes[s]["min"], table.sizes[s]["max"]) for _, s in sized}
    if _holds(table, rules, bounds, tol):
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
    if not _holds(table, rules, toward(bounds, names, 0.0, 0.0), tol):
        return None
    # Each size alone first, so a size whose own ends hold keeps them; then all together for the joint settings.
    limits = dict(bounds)
    for s in names:
        t_high = range_check.largest_share(lambda t: _holds(table, rules, toward(limits, [s], 1.0, t), tol, (s, 1)))
        t_low = range_check.largest_share(lambda t: _holds(table, rules, toward(limits, [s], t, 1.0), tol, (s, 0)))
        limits = toward(limits, [s], t_low, t_high)
    t_high = range_check.largest_share(lambda t: _holds(table, rules, toward(limits, names, 1.0, t), tol))
    t_low = range_check.largest_share(lambda t: _holds(table, rules, toward(limits, names, t, t_high), tol))
    exact = toward(limits, names, t_low, t_high)
    tidy = dict(exact)
    for _, s in free:
        size, (lo, hi) = table.sizes[s], exact[s]
        tidy[s] = (min(_tidy(size, lo, True), size["value"]), max(_tidy(size, hi, False), size["value"]))
    chosen = tidy if _holds(table, rules, tidy, tol) else exact
    if any(chosen[s][1] - chosen[s][0] <= 1e-9 for _, s in free):
        return None
    return {name: chosen[s] for name, s in free if chosen[s] != bounds[s]}
