"""The first tries: near rows, near pair rows, far rows and far pair rows."""
from ...design_model.dimension_sizes import near_values
from ...geometry.tolerances import SAME_SIZE
from ...package.manifest import MAX_NAME_CHARS
from ..state import as_states
from .history import fails_by, farthest_built, tried_alone
from .rows import MAX_PROBE_ROWS, probe_row, tried_sizes


def _far_ends(size, near):
    """The ends of the size's range that differ from its value and from the near values."""
    return [end for end in (size["min"], size["max"])
            if abs(end - size["value"]) > SAME_SIZE and all(n is None or abs(end - n) > SAME_SIZE for n in near)]


def probe_rows(sizes, moved, limit=MAX_PROBE_ROWS, extra=()):
    """The first states to try, as `(rows, untried)`: the near rows (step 1 of the module docstring).

    sizes: the kept sizes. moved: the params that move covered sketch values. A row has no STEP (`"step": False`);
    `state` holds the manifest values, `varied` the params that differ, `label` the progress line. `untried` lists
    the moved params left without near rows by the row limit. `extra` are params tried on a guess
    (`probe_flow.sizes.extra_sizes`): their rows follow the moved ones, and one left without rows is not listed in
    `untried`.
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
    states = as_states(states)
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


def far_order(sizes, moved, extra=(), late=(), risky=()):
    """The Fusion names of the tried sizes in the order their far rows run, one size after the other: as `probe_rows`
    tries them, the favourites of the design first. In each of the two groups, the favourites and the rest, the sizes
    in `risky` come after the others and the sizes in `late` come last, each in the same order. `late` are the sizes
    whose tries so far showed trouble outside the part (`ProbeRun`); `risky` are the sizes that drive a step of another
    component (`geometry_links.outside_drivers`). A far try of such a size is the likeliest to leave the design broken
    and stop the tries, so the other sizes get their far tries first. The favourites stay first, so a time limit or
    the row limit cuts the tries of the other sizes first."""
    tried = tried_sizes(sizes, moved, extra)
    late, risky = set(late), set(risky)

    def place(at):
        name = tried[at]["param"]
        return (not tried[at].get("favorite"), 2 if name in late else 1 if name in risky else 0, at)

    return [tried[at]["param"] for at in sorted(range(len(tried)), key=place)]


def far_rows(sizes, moved, room, extra=(), states=(), only=None):
    """The far rows (step 3 of the module docstring), at most `room` of them: every tried size at the range ends that
    differ from its value and from its near values, so the measured span grows. An end is left out when `states` (the
    probe states so far, marked as for `nearer_rows`) hold a row of that size alone that did not build at a value on
    that side. `only`, when given, are the Fusion names of the sizes to plan (in the order of `far_order`); every row
    still sets all sizes. Sizes and arguments as in `probe_rows`; the export asks for these after the near rows and
    their nearer tries."""
    rows = []
    tried = tried_sizes(sizes, moved, extra)
    if only is not None:
        chosen = set(only)
        tried = [s for s in tried if s["param"] in chosen]
    states = as_states(states)
    for size in tried:
        wanted = [end for end in _far_ends(size, near_values(size)) if not fails_by(states, size, end)]
        if len(rows) + len(wanted) > room:
            continue
        for end in wanted:
            label = "min" if end == size["min"] else "max"
            rows.append(probe_row(sizes, "%s (%s)" % (size["size"][:MAX_NAME_CHARS - 6], label), {size["param"]: end},
                             "%s (%s)" % (size["param"], label)))
    return rows


def far_left(sizes, states):
    """`{param: [side, ...]}`: the sides ("low", "high") of each size with a try of its own that built where no try of
    that size alone reached the range end and none on that side failed or changed an outline (`states` marked as for
    `nearer_rows`). On such a side the far row never ran, so nothing is known past the farthest value that built
    there. A side with a try that failed is not listed: the range stops before that try anyway (`nearer_left` tells
    whether the search there had ended)."""
    states = as_states(states)
    out = {}
    for size in sizes:
        now = size["value"]
        tried = tried_alone(states, size["param"], now)
        if not any(ok for _, ok in tried):
            continue
        sides = []
        for side, end in (("low", size["min"]), ("high", size["max"])):
            reach = abs(end - now)
            if reach <= SAME_SIZE:
                continue
            there = [(v, ok) for v, ok in tried if (v - now) * (end - now) > 0]
            if all(ok and abs(v - now) < reach - SAME_SIZE for v, ok in there):
                sides.append(side)
        if sides:
            out[size["param"]] = sides
    return out


def far_pair_rows(sizes, moved, states, room, extra=()):
    """The far pair rows (step 4 of the module docstring), at most `room`: all sizes at their minimum, then at their
    maximum, when two or more sizes are tried. A tried size goes to the farthest value on that side that built on its
    own and kept every outline (`states` marked as for `nearer_rows`), or stays at its value when none did; a size
    without rows goes to its range end. A row needs two sizes that differ from their value, and one tried size past
    its near value (else the near pair row has measured it already)."""
    tried = {s["param"] for s in tried_sizes(sizes, moved, extra)}
    if len(tried) < 2:
        return []
    states = as_states(states)
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
