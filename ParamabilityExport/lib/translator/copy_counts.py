"""Pattern copies that a later step picks must exist at every size.

Fusion keeps the edges a round or chamfer picked when a pattern count changes: new copies get no round, and a copy
that goes away takes its round with it. So a pick on copy n of a pattern needs at least n + 1 copies over the whole
size range.
"""
from . import range_check


def stays_at_least(table, q, least):
    """True when the count `q` (a Quantity) stays at `least` or more at every corner of the size ranges
    (`range_check.corners`). A count that follows no size always holds."""
    return not q.sized or range_check.sweep(table, q.text, q.reads).at_least(least - 1e-9)
