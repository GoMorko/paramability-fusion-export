"""The first tries: near rows, near pair rows, far rows and far pair rows."""
from ...geometry.tolerances import SAME_SIZE
from ...package.manifest import MAX_NAME_CHARS
from .history import fails_by, farthest_built
from .rows import MAX_PROBE_ROWS, probe_row, tried_sizes

# How far from its value a size is first tried, as a share of the value, below and above.
NEAR_SHARE = 0.25


def near_values(size):
    """`(low, high)`: the value `NEAR_SHARE` of itself below and above, inside the range. A value of zero moves by that
    share of the way to the range ends. A count is a whole number and at least one step from the value. A side that
    cannot move off the value is None."""
    value, lo, hi = size["value"], size["min"], size["max"]
    step = NEAR_SHARE * abs(value)
    sides = [value - step, value + step] if step > SAME_SIZE else [value + NEAR_SHARE * (lo - value),
                                                                 value + NEAR_SHARE * (hi - value)]
    out = []
    for number, sign in zip(sides, (-1, 1)):
        if size.get("kind") == "count":
            number = float(round(number))
            if abs(number - value) <= SAME_SIZE:
                number = value + sign
        number = min(max(number, lo), hi)
        out.append(number if abs(number - value) > SAME_SIZE else None)
    return tuple(out)


def _far_ends(size, near):
    """The ends of the size's range that differ from its value and from the near values."""
    return [end for end in (size["min"], size["max"])
            if abs(end - size["value"]) > SAME_SIZE and all(n is None or abs(end - n) > SAME_SIZE for n in near)]


def probe_rows(sizes, moved, limit=MAX_PROBE_ROWS, extra=()):
    """The first states to try, as `(rows, untried)`: the near rows (step 1 of the module docstring).

    sizes: the kept sizes. moved: the params that move covered sketch values. A row has no STEP (`"step": False`);
    `state` holds the manifest values, `varied` the params that differ, `label` the progress line. `untried` lists
    the moved params left without near rows by the row limit. `extra` are params tried on a guess (`extra_sizes`):
    their rows follow the moved ones, and one left without rows is not listed in `untried`.
    """
    rows, untried = [], []
    tried = tried_sizes(sizes, moved, extra)
    near = {s["param"]: near_values(s) for s in tried}
    for size in tried:
        wanted = [(label, v) for label, v in zip(("near min", "near max"), near[size["param"]]) if v is not None]
        if len(rows) + len(wanted) > limit:
            if size["param"] in moved:
                untried.append(size["param"])
            continue
        for label, value in wanted:
            rows.append(probe_row(sizes, "%s (%s)" % (size["size"][:MAX_NAME_CHARS - 11], label), {size["param"]: value},
                             "%s (%s)" % (size["param"], label)))
    return rows, untried


def pair_rows(sizes, moved, states, room, extra=()):
    """The near pair rows (step 2 of the module docstring), at most `room`: all tried sizes at their lower near value,
    then at the higher. `states` are the probe states so far, marked as for `nearer_rows`: a size whose own row did
    not build at its near value on that side, or nearer, stays at its value. A row needs two sizes that differ."""
    tried = tried_sizes(sizes, moved, extra)
    if len(tried) < 2:
        return []
    rows = []
    for label, side in (("all lower", 0), ("all higher", 1)):
        overrides = {}
        for size in tried:
            value = near_values(size)[side]
            if value is not None and not fails_by(states, size, value):
                overrides[size["param"]] = value
        if len(overrides) >= 2 and len(rows) < room:
            rows.append(probe_row(sizes, label, overrides, "all near %d" % side))
    return rows


def far_rows(sizes, moved, room, extra=(), states=()):
    """The far rows (step 3 of the module docstring), at most `room` of them: every tried size at the range ends that
    differ from its value and from its near values, so the measured span grows. An end is left out when `states` (the
    probe states so far, marked as for `nearer_rows`) hold a row of that size alone that did not build at a value on
    that side. Sizes and arguments as in `probe_rows`; the export asks for these after the near rows and their nearer
    tries."""
    rows = []
    tried = tried_sizes(sizes, moved, extra)
    for size in tried:
        wanted = [end for end in _far_ends(size, near_values(size)) if not fails_by(states, size, end)]
        if len(rows) + len(wanted) > room:
            continue
        for end in wanted:
            label = "min" if end == size["min"] else "max"
            rows.append(probe_row(sizes, "%s (%s)" % (size["size"][:MAX_NAME_CHARS - 6], label), {size["param"]: end},
                             "%s (%s)" % (size["param"], label)))
    return rows


def far_pair_rows(sizes, moved, states, room, extra=()):
    """The far pair rows (step 4 of the module docstring), at most `room`: all sizes at their minimum, then at their
    maximum, when two or more sizes are tried. A tried size goes to the farthest value on that side that built on its
    own and kept every outline (`states` marked as for `nearer_rows`), or stays at its value when none did; a size
    without rows goes to its range end. A row needs two sizes that differ from their value, and one tried size past
    its near value (else the near pair row has measured it already)."""
    tried = {s["param"] for s in tried_sizes(sizes, moved, extra)}
    if len(tried) < 2:
        return []
    rows = []
    for label, key, side in (("all min", "min", 0), ("all max", "max", 1)):
        overrides, past = {}, False
        for size in sizes:
            value = farthest_built(states, size, size[key]) if size["param"] in tried else size[key]
            if value is not None and abs(value - size["value"]) > SAME_SIZE:
                overrides[size["param"]] = value
                near = near_values(size)[side]
                past = past or (size["param"] in tried and (near is None or abs(value - size["value"])
                                                            > abs(near - size["value"]) + SAME_SIZE))
        if len(overrides) >= 2 and past and len(rows) < room:
            rows.append(probe_row(sizes, label, overrides))
    return rows
