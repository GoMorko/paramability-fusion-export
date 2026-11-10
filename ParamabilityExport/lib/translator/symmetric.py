"""Pattern directions that spread copies to both sides of the original.

A recipe pattern starts at the original and runs one way, so a symmetric direction is written as two parts that both
start at the original: a forward part and a backward part. Copies are counted in steps from the original, negative
behind it. The copies stay where Fusion measured them, and the places follow this rule for `count` copies:

  odd count   the original is the middle copy: `count // 2` steps each way.
  even count  the original is one of the two middle copies: `count // 2` steps one way and one less the other. Which
              way has the extra step is read from the measured copies and holds for every even count.

A count that follows sizes writes the two part counts as formulas of it (`part_counts`). When the measured count is odd
the even rule was not seen, so sizes that can make the count even are marked (`check_even_unseen`).
"""
from . import range_check
from .values import Quantity, wrapped


def reach(places, count):
    """`(back, forward)`: the steps the measured copies run behind and ahead of the original, or None when they do not
    follow the rule for `count` copies. `places` are the signed steps of every copy, the original (0) included."""
    if not places:
        return None
    back, forward = -min(places), max(places)
    if back < 0 or forward < 0 or back + forward + 1 != count:
        return None
    half = count // 2
    allowed = {(half, half)} if count % 2 else {(half, half - 1), (half - 1, half)}
    return (back, forward) if (back, forward) in allowed else None


def part_counts(count_q, back, forward):
    """`(back_q, forward_q)`: the copies of the backward and forward part, the original included, as Quantities.

    Numbers when the count follows no size. Else formulas of the count: the longer part has `floor(n / 2) + 1` and the
    shorter `floor((n - 1) / 2) + 1`, which are equal for an odd count."""
    if not count_q.sized:
        return Quantity(back + 1.0), Quantity(forward + 1.0)
    text = wrapped(count_q.text)
    longer = Quantity(max(back, forward) + 1.0, "floor(%s / 2) + 1" % text, count_q.reads)
    if back == forward:
        return longer, longer
    shorter = Quantity(min(back, forward) + 1.0, "floor((%s - 1) / 2) + 1" % text, count_q.reads)
    return (longer, shorter) if back > forward else (shorter, longer)


def check_even_unseen(ctx, item, count_q, count):
    """Marks the sizes of a count that was measured odd and can be even inside the size ranges: Fusion's places for
    an even count were not seen."""
    if count % 2 == 0 or not count_q.sized or ctx.table is None:
        return
    span = range_check.sweep(ctx.table, count_q.text, count_q.reads)
    if span.failed or (span.low is not None and span.high - span.low >= 1):
        ctx.doubt(count_q.reads, "%s spreads copies to both sides of the first one, and where Fusion puts them for an "
                  "even count was not checked" % item.get("name", "a pattern"))
