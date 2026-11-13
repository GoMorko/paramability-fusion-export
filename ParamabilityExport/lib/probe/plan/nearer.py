"""Rows that try a size nearer to its value after a row that did not build, or between values that built and failed."""
from ...package.manifest import MAX_NAME_CHARS
from .history import changed_alone, tried_alone
from .rows import SAME_VALUE, probe_row, value_toward

# A row that does not build is tried again nearer to the value now: this share of the way to the range end, in turn.
# Each try is one more Fusion recompute; a nearer value that builds is enough for the fit, which then holds between
# the values measured.
NEARER_STEPS = (0.5, 0.25, 0.1)
# Rows the export adds for those tries in all, inside `MAX_PROBE_ROWS`: discovery rows get what is left.
MAX_NEARER_ROWS = 24
# A side with a value that built and a farther one that did not is halved between them until the two are within this
# share of the way from the value now to the range end, so at most `BISECT_STEPS` more tries per side.
BISECT_GAP = 0.1
BISECT_STEPS = 4


def _next_nearer(size, end, tried):
    """The next value toward `end` to try after rows on that side that did not build, or None when the steps are used
    up. `tried` are the values tried alone on that side."""
    span = end - size["value"]
    nearest = min(abs((v - size["value"]) / span) for v in tried)
    for share in NEARER_STEPS:
        if share >= nearest - SAME_VALUE:
            continue
        value = value_toward(size, end, share)
        if abs(value - size["value"]) > SAME_VALUE and all(abs(value - v) > SAME_VALUE for v in tried):
            return value
    return None


def _between(size, end, tried):
    """The value half way between the farthest value tried alone toward `end` that built and the nearest one past it
    that did not, or None when no value failed past the last that built, or the two are already close
    (`BISECT_GAP`)."""
    now, span = size["value"], end - size["value"]
    if abs(span) <= SAME_VALUE:
        return None
    side = [((v - now) / span, ok) for v, ok in tried if (v - now) / span > SAME_VALUE]
    built = max((share for share, ok in side if ok), default=None)
    failed = [share for share, ok in side if not ok and built is not None and share > built + SAME_VALUE]
    if not failed or min(failed) - built <= BISECT_GAP + SAME_VALUE:
        return None
    value = value_toward(size, end, (built + min(failed)) / 2)
    shares = [share for share, _ in side]
    if abs(value - now) <= SAME_VALUE or any(abs((value - now) / span - share) <= SAME_VALUE for share in shares):
        return None
    return value


def _nearer_for(size, states, moved):
    """`[(label, value)]`: the rows that try `size` nearer to its value after rows that did not build. On a side
    where a row changed an outline, only the values nearer than it count: the range stops before it."""
    now = size["value"]
    tried = tried_alone(states, size["param"], now)
    changed = changed_alone(states, size["param"], now)
    out = []
    for label, end in (("min", size["min"]), ("max", size["max"])):
        side = [(v, ok) for v, ok in tried if (v - now) * (end - now) > 0]
        stops = [abs(v - now) for v in changed if (v - now) * (end - now) > 0]
        inside = [(v, ok) for v, ok in side if not stops or abs(v - now) < min(stops) - SAME_VALUE]
        if side and not any(ok for _, ok in inside):
            value = _next_nearer(size, end, [v for v, _ in side])
        elif stops:
            value = _between(size, end, inside + [(now + (min(stops) if end > now else -min(stops)), False)])
        else:
            value = _between(size, end, tried)
        if value is not None:
            out.append((label, value))
    built = [v for v, ok in tried if ok]
    if not out and size["param"] in moved and len(built) == 1:
        value = value_toward(size, built[0], 0.5)
        if abs(value - size["value"]) > SAME_VALUE and all(abs(value - v) > SAME_VALUE for v, _ in tried):
            out.append(("check", value))
    return out


def nearer_rows(sizes, states, moved=(), limit=MAX_NEARER_ROWS):
    """The next rows that try sizes nearer to their value now, after rows that did not build.

    `states` are the probe states so far (`values`, `built` and `changed`, a row that changed a followed outline
    counting as one that did not build). For each size and each side of its value whose rows all failed to build:
    one row `NEARER_STEPS` of the way toward that range end, the first step nearer than the nearest value tried
    there. On a side where a value built and a farther one did not: one row half way between them (`_between`); with
    a row that changed an outline on that side, only the values nearer than it count. A size in `moved` (it moved a
    sketch or a measured place) with only one row that built and nothing left to try gets one more row half way to
    that value, so the fit has two readings to tell a straight line from a curve. Sizes that no row built come
    first. At most `limit` rows; the export calls this again after each batch, so each call gives one step per
    side."""
    plans = [(size, _nearer_for(size, states, set(moved))) for size in sizes]
    unbuilt = {size["param"] for size in sizes
               if not any(ok for _, ok in tried_alone(states, size["param"], size["value"]))}
    plans.sort(key=lambda entry: entry[0]["param"] not in unbuilt)
    rows = []
    for size, wanted in plans:
        for label, value in wanted:
            if len(rows) >= limit:
                return rows
            name = "%s (%s, nearer)" % (size["size"][:MAX_NAME_CHARS - 16], label)
            rows.append(probe_row(sizes, name, {size["param"]: value}, "%s (%s %r)" % (size["param"], label, value),
                             retry=label != "check"))
    return rows
