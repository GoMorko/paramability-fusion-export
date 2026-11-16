"""Pattern directions that spread copies to both sides of the original.

A recipe pattern starts at the original and runs one way, so a symmetric direction is written as two parts that both
start at the original: a forward part and a backward part. Copies are counted in steps from the original, negative
behind it. The copies stay where Fusion measured them, and the places follow this rule for `count` copies:

  odd count   the original is the middle copy: `count // 2` steps each way.
  even count  the original is one of the two middle copies: `count // 2` steps one way and one less the other. The
              side with the extra step is the same for every even count. Fusion's rectangular patterns put it ahead
              of the original (`FUSION_EXTRA_SIDE` in `design_model/steps/repeat.py`, seen at counts 4, 6 and 8, by spacing and by extent).

A count that follows sizes writes the two part counts as formulas of it (`part_counts`). The side of the extra step
is read from the measured copies when the count is even. When it is odd, the copies the probe read at the tries with
an even count tell it (`extra_side`); without such a try the side Fusion was seen to use is taken (rectangular
patterns only), and when the copies at a try break the rule the sizes that can make the count even are marked.
"""
from ...capture_model import tool_items
from ...design_model.steps.repeat import read_in_component, reach
from ...design_model.values import Quantity, wrapped
from ...params.expressions.errors import ExpressionError
from ...params.expressions.evaluation import evaluate
from ..ranges import range_check


def part_counts(count_q, back, forward, side=0):
    """`(back_q, forward_q)`: the copies of the backward and forward part, the original included, as Quantities.

    Numbers when the count follows no size. Else formulas of the count: the longer part has `floor(n / 2) + 1` and the
    shorter `floor((n - 1) / 2) + 1`, which are equal for an odd count. `side` (+1 forward, -1 backward, from
    `extra_side`) says which part is the longer one; 0 gives both parts the longer formula."""
    if not count_q.sized:
        return Quantity(back + 1.0), Quantity(forward + 1.0)
    text = wrapped(count_q.text)
    longer = Quantity(max(back, forward) + 1.0, "floor(%s / 2) + 1" % text, count_q.reads)
    if not side:
        return longer, longer
    shorter = Quantity(min(back, forward) + 1.0, "floor((%s - 1) / 2) + 1" % text, count_q.reads)
    return (longer, shorter) if side < 0 else (shorter, longer)


def value_at(quantity, env):
    """The number of a Quantity at the sizes in `env`, or None when its formula cannot be worked out."""
    if not quantity.sized:
        return quantity.n
    try:
        return float(evaluate(quantity.text, env))
    except (ExpressionError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _setting(table, values):
    """The size values of a probe state by recipe name, or None when a derived size cannot be worked out."""
    found = {}
    for name, value in (values or {}).items():
        size = table.size_name(name)
        if size and "value" in table.sizes.get(size, {}):
            found[size] = value
    try:
        return range_check.size_env(table, found)
    except ExpressionError:
        return None


def _tried_side(ctx, item, count_q, places_at):
    """`(side, broken)` from the probe's reads of the pattern. `side` is +1 or -1 when the tries with an even count agree
    on the side of the extra step, else 0. `broken` is True when a built try put the copies against the rule (or off
    the grid the sizes of that try give), or the even tries disagree. `places_at(env, read, count)` gives the signed
    steps of the copies read at a try, or None."""
    key = str(item.get("index"))
    sides = set()
    for state in getattr(ctx.motion, "states", None) or ():
        read = (state.get("patterns") or {}).get(key)
        if read is None or state.get("built") is False:
            continue
        read = read_in_component(read, tool_items.component_frame(ctx))
        env = _setting(ctx.table, state.get("values"))
        count = None if env is None else value_at(count_q, env)
        if count is None or abs(count - round(count)) > 1e-9 or count < 2:
            continue
        count = int(round(count))
        found = places_at(env, read, count)
        reach_ = None if found is None else reach(found, count)
        if reach_ is None:
            return 0, True
        if count % 2 == 0:
            sides.add(1 if reach_[1] > reach_[0] else -1)
    if len(sides) > 1:
        return 0, True
    return (sides.pop() if sides else 0), False


def extra_side(ctx, item, count_q, count, reach_, places_at, default=0):
    """The side with the extra step for an even count: +1 forward, -1 backward. `reach_` is `(back, forward)` of the
    measured copies. A measured even count shows the side itself. For an odd one a count that stays odd needs no side
    (0). A count that can be even takes the side the tries read (`places_at` reads the copies of one try). With no
    try that had an even count it takes `default` (the side Fusion was seen to use), and 0 when there is none. The
    sizes are marked, giving 0, when a try put the copies against the rule or no side is known."""
    back, forward = reach_
    if back != forward:
        return 1 if forward > back else -1
    if not count_q.sized or ctx.table is None:
        return 0
    span = range_check.sweep(ctx.table, count_q.text, count_q.reads)
    if not (span.failed or (span.low is not None and span.high - span.low >= 1)):
        return 0
    side, broken = _tried_side(ctx, item, count_q, places_at)
    side = 0 if broken else (side or default)
    if not side:
        ctx.doubt(count_q.reads, "%s spreads copies to both sides of the first one, and where Fusion puts them for an "
                  "even count was not confirmed" % item.get("name", "a pattern"))
    return side
