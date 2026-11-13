"""Rows after the first tries: check rows for a fit along a curve and discovery rows for unticked parameters."""
from ...package.manifest import MAX_NAME_CHARS
from .rows import _SAME, _row, _toward

# Unticked parameters that act on another component, tried once each to find links the reader cannot see.
MAX_DISCOVERY = 12


def _span_ends(spans, size):
    """`(low, high)` the size was measured at (`spans`), or its range ends when it has no span."""
    span = spans.get(size["param"]) or {}
    return span.get("low", size["min"]), span.get("high", size["max"])


def check_rows(sizes, curved, spans, room, partners=()):
    """The rows that let a value that moves along a curve be fitted with products and functions of angles
    (`probe.terms`), and checked by states the fit did not need, in this order while `room` lasts:

    - each size in `curved` half way to the lowest and to the highest value it was measured at (`spans`, as
      `Motion.spans`): the fit can tell a cosine from a cotangent there;
    - each curved size with each size in `partners` (the other sizes of the same values) both at the high ends, then
      both at the low ends: a product of the two shows there;
    - every size other than the curved ones at its lowest, then at its highest measured value, the curved ones at
      their value now: the formula over those sizes alone is checked by a state that changes several of them.
    """
    by_name = {s["param"]: s for s in sizes}
    wanted = []
    for name in (n for n in curved if n in by_name):
        size = by_name[name]
        for end in _span_ends(spans, size):
            middle = _toward(size, end, 0.5)
            if abs(middle - size["value"]) > _SAME and abs(middle - end) > _SAME:
                wanted.append(("%s (half way)" % size["size"][:MAX_NAME_CHARS - 11], {name: middle},
                               "%s (half way to %r)" % (name, end)))
    for name in (n for n in curved if n in by_name):
        for other in (n for n in partners if n in by_name and n not in curved):
            ends = list(zip(_span_ends(spans, by_name[name]), _span_ends(spans, by_name[other])))
            for label, (mine, theirs) in zip(("low", "high"), ends):
                overrides = {n: v for n, v in ((name, mine), (other, theirs))
                             if abs(v - by_name[n]["value"]) > _SAME}
                if len(overrides) == 2:
                    wanted.append(("%s and %s (%s)" % (name, other, label), overrides, None))
    for label, at in (("all low but curved", 0), ("all high but curved", 1)):
        overrides = {s["param"]: _span_ends(spans, s)[at] for s in sizes
                     if s["param"] not in curved and abs(_span_ends(spans, s)[at] - s["value"]) > _SAME}
        if len(overrides) >= 2:
            wanted.append((label, overrides, None))
    # Each row has its own key: the reads of the rows are kept by key, so two rows under one key would share a read.
    return [_row(sizes, name, overrides, key) for name, overrides, key in wanted[:max(0, room)]]


def discovery_rows(candidates, room, limit=MAX_DISCOVERY):
    """One row per candidate, in order, at most `limit` and `room`: the parameter alone set to its `end`.

    A candidate is a size dict as in `probe_rows` plus `end` (a manifest number). These rows only tell whether a
    sketch moves with the parameter; they are not states of the motion fit."""
    rows = []
    for candidate in candidates[:max(0, min(limit, room))]:
        row = _row([candidate], "%s (try)" % candidate["size"][:MAX_NAME_CHARS - 6],
                   {candidate["param"]: candidate["end"]}, "try %s" % candidate["param"])
        row["label"] = "checking if %s changes this part" % candidate["param"]
        rows.append(row)
    return rows


def discovery_left(candidates, room, limit=MAX_DISCOVERY):
    """The candidates `discovery_rows` leaves without a row, in order."""
    return list(candidates[max(0, min(limit, room)):])
