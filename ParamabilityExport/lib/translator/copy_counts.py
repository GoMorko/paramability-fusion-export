"""Pattern copies that a later step picks must exist at every size.

Fusion keeps the edges a round or chamfer picked when a pattern count changes: new copies get no round, and a copy
that goes away takes its round with it. So a pick on copy n of a pattern needs at least n + 1 copies over the whole
size range. When the count formula drops below that at the smallest sizes, the smallest values of the sizes it reads
are raised instead of fixing them; a size whose minimum the person typed is not raised.
"""
import math

from . import range_check


def _sizes(table, reads):
    """(Fusion name, recipe name, size) of the read sizes that have a range."""
    out = []
    for name in reads:
        size_name = table.size_name(name)
        size = table.sizes.get(size_name) if size_name else None
        if size is not None and "min" in size:
            out.append((name, size_name, size))
    return out


def _holds(table, q, least, mins):
    """True when the count `q` stays at `least` or more at every corner of the size ranges; `mins` (recipe name to
    number) replaces the minimum of some sizes."""
    bounds = {n: (m, table.sizes[n]["max"]) for n, m in (mins or {}).items()}
    return range_check.sweep(table, q.text, q.reads, bounds).at_least(least - 1e-9)


def _tidy(size, value, extra):
    """A raised minimum as the form shows it: a whole number for a count, else two decimals, `extra` steps up; never
    past the value."""
    step = 1.0 if size.get("kind") == "count" else 0.01
    out = (math.ceil(value / step - 1e-9) + extra) * step
    return min(round(out, 6), size["value"])


def raised_minimums(table, q, least):
    """`{Fusion name: new minimum}` that keeps the count `q` (a sized Quantity) at `least` or more over the size range.

    Empty when it holds already; None when raising the minimums cannot make it hold (the count falls at the largest
    sizes, or every size it reads has a typed minimum)."""
    if not q.sized or _holds(table, q, least, None):
        return {}
    free = [(name, size_name, size) for name, size_name, size in _sizes(table, q.reads)
            if not table.typed_ends(name)[0] and size["value"] > size["min"]]
    if not free:
        return None

    def mins_at(t):
        return {size_name: size["min"] + t * (size["value"] - size["min"]) for _, size_name, size in free}

    if not _holds(table, q, least, mins_at(1.0)):
        return None
    high = range_check.smallest_share(lambda t: _holds(table, q, least, mins_at(t)))
    exact = mins_at(high)
    chosen = exact
    for extra in (0, 1):
        tidy = {size_name: _tidy(size, exact[size_name], extra) for _, size_name, size in free}
        if _holds(table, q, least, tidy):
            chosen = tidy
            break
    return {name: chosen[size_name] for name, size_name, size in free if chosen[size_name] > size["min"] + 1e-12}
