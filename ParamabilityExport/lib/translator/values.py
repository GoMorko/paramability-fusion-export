"""Feature values that follow Fusion parameters.

A reader gives each value that Fusion keeps as a model parameter in the item's `data.params` (capture field path to
`{ name, expression, value }`). `quantity` turns such a value into a `Quantity` (`design_model/values.py`): the
measured number plus, when the parameter's expression reads a size of the size table, the formula to write instead.
`num` is the same for a field written as a number or `{ "expr": ... }`.

When a value cannot follow its sizes (the formula does not translate, its unit or sign breaks inside the size range,
or the step writes it as a plain number), it is written as its number and the sizes it reads are recorded as a doubt
(`Context.doubt`). The driver then keeps them free with a warning (`translate`); a value that depends on a size never
stays a number while that size stays free without one. A formula the
parser cannot read still marks the sizes on Fusion's own list of what its parameter depends on. An angle the step
needs above zero that reaches zero inside the size ranges has the ranges cut instead, since the default range of a
small angle starts at 0 degrees.
"""
from ..design_model import design
from ..design_model.values import Quantity, negated_text
from ..params.expressions.errors import ExpressionError
from ..params.expressions.formula import parse_formula
from ..params.expressions.text import MAX_FORMULA_LENGTH
from .ranges import kept_ranges, range_check

TOLERANCE = 1e-6
# How far above zero (degrees) an angle the step needs positive stays when the size ranges are cut for it: half the
# form's step, so the cut end lands on 0.01.
ABOVE_ZERO = 0.005


def _param(item, path):
    found = design.params_of(item).get(path)
    return found if isinstance(found, dict) and found.get("expression") else None


def _unread(ctx, ref, tr):
    """Fusion names of the sizes behind a parameter whose expression the parser could not read: Fusion's own list of
    the parameters it depends on. Empty when the parser read the expression."""
    if tr.ok or tr.reads:
        return ()
    return tuple(sorted(ctx.table.depends(ref.get("name") or "")))


def _reads_of(ctx, ref):
    """Fusion names of the sizes a parameter reads."""
    if ctx.table is None:
        return ()
    tr = ctx.table.translate(ref["expression"])
    return tuple(tr.reads) or _unread(ctx, ref, tr)


def handled(ctx, item, path, same_as=None):
    """The value at `path` needs nothing here (the step kind or its settings do not use it), so the audit does not
    expect it to follow the sizes it reads. With `same_as`, only when that other path of the item was dealt with:
    a handler that rewrites its item names the same value differently."""
    ctx.ask(item, path, same_as)


def pin(ctx, item, path, why):
    """The value at `path` stays a number here: the sizes its parameter reads stay free and are marked with `why`."""
    ctx.ask(item, path)
    ref = _param(item, path)
    if ref is not None:
        ctx.doubt(_reads_of(ctx, ref), why)


def _stays_in_range(table, formula, reads, sign, low):
    """True when sign * formula stays at or above `low` over the size range, mixed corners included."""
    span = range_check.sweep(table, formula, reads)
    return span.at_least(low) if sign > 0 else span.at_most(-low)


_ROUNDING = ("round", "floor", "ceil")
_WHOLE_FROM_WHOLE_PARTS = ("min", "max", "abs", "mod")
# How many derived sizes deep `_gives_whole_numbers` follows before it gives up.
_WHOLE_DEPTH = 8


def _gives_whole_numbers(table, formula, depth=0):
    """True when a formula gives a whole number at every size value. It is built from whole parts: whole number
    literals, count sizes, derived sizes that are whole, `+ - *`, `round`, `floor` and `ceil` of anything, `min`,
    `max` and `abs` of whole parts, `mod` of whole parts, `pow` of a whole part to a whole literal of 0 or more, and a
    choice `test ? a : b` whose two results are whole (the test can be anything)."""
    if depth > _WHOLE_DEPTH:
        return False
    try:
        tree = parse_formula(formula)
    except ExpressionError:
        return False
    return _whole(table, tree, depth)


def _whole(table, node, depth):
    kind = node[0]
    if kind == "num":
        return node[1] == int(node[1])
    if kind == "name":
        size = table.sizes.get(node[1])
        if size is None:
            return False
        if "expr" in size:
            return _gives_whole_numbers(table, size["expr"], depth + 1)
        return size.get("kind") == "count"
    if kind == "neg":
        return _whole(table, node[1], depth)
    if kind == "bin":
        return node[1] in "+-*" and _whole(table, node[2], depth) and _whole(table, node[3], depth)
    if kind == "cond":
        return _whole(table, node[2], depth) and _whole(table, node[3], depth)
    if kind == "call":
        name, args = node[1], node[2]
        if name in _ROUNDING:
            return True
        if name == "pow":
            exponent = args[1] if len(args) == 2 else None
            return (exponent is not None and exponent[0] == "num" and exponent[1] >= 0
                    and _whole(table, args[0], depth) and _whole(table, exponent, depth))
        if name in _WHOLE_FROM_WHOLE_PARTS:
            return bool(args) and all(_whole(table, arg, depth) for arg in args)
    return False


def stays_below(ctx, item, q, limit, why):
    """`q` when it stays under `limit` over the size range; else its number, with its sizes fixed for `why`."""
    if not q.sized or _stays_in_range(ctx.table, q.text, q.reads, -1, -limit + 1e-9):
        return q
    ctx.doubt(q.reads, why)
    return Quantity(q.n)


def stays_positive(table, q):
    """True when a sized Quantity stays above zero over the size range."""
    return _stays_in_range(table, q.text, q.reads, 1, 1e-9)


def quantity(ctx, item, path, literal, dim="length", sign=1, absolute=False, whole=False):
    """The value at `path` as a Quantity.

    `literal` is the number the step writes (what Fusion measured, mm or degrees). `dim` is length, angle or scalar.
    `sign` is 1 or -1 when the step writes the absolute value of a negative parameter. `absolute` asks the value to
    stay above zero over the size range; `whole` asks it to stay at least 1 (counts).
    """
    plain = Quantity(literal)
    ctx.ask(item, path)
    ref = _param(item, path)
    if ref is None or ctx.table is None:
        return plain
    tr = ctx.table.translate(ref["expression"], expected=ref["value"], dim=dim, unit=ctx.table.unit_of(ref.get("name")))
    if not tr.reads:
        behind = _unread(ctx, ref, tr)
        if behind:
            ctx.doubt(behind, "a value of %s cannot be copied: %s"
                      % (item.get("name", "a step"), tr.reason.rstrip(".")))
        return plain
    if not tr.ok:
        ctx.doubt(tr.reads, "a value of %s cannot be copied: %s"
                  % (item.get("name", "a step"), tr.reason.rstrip(".")))
        return plain
    if abs(sign * tr.value - literal) > TOLERANCE + 1e-9 * abs(literal):
        ctx.doubt(tr.reads, "its formula in %s does not match what Fusion measured" % item.get("name", "a step"))
        return plain
    if len(tr.formula) > MAX_FORMULA_LENGTH:
        ctx.doubt(tr.reads, "its formula in %s is too long to copy" % item.get("name", "a step"))
        return plain
    if whole and not _gives_whole_numbers(ctx.table, tr.formula):
        ctx.doubt(tr.reads, "%s needs a whole number of copies, and its formula can give a part number"
                  % item.get("name", "a step"))
        return plain
    text = tr.formula if sign > 0 else negated_text(tr.formula)
    q = Quantity(literal, text, tr.reads)
    if (absolute or whole) and not _stays_in_range(ctx.table, tr.formula, tr.reads, sign, 1.0 if whole else 1e-9):
        if dim == "angle" and not whole:
            return _angle_above_zero(ctx, item, q)
        ctx.doubt(tr.reads, "%s would leave its working range (a length reaching zero or a count under 1)"
                  % item.get("name", "a step"))
        return plain
    return q


def _angle_above_zero(ctx, item, q):
    """`q`, an angle the step needs above zero that reaches zero inside the size ranges (the default range of a small
    angle starts at 0 degrees): the ranges of the sizes it reads are cut where it stays above ABOVE_ZERO, or its number
    when no cut does that, with its sizes marked."""
    found = kept_ranges.holding_ranges(ctx.table, [(q, 1)], ABOVE_ZERO)
    why = "%s needs an angle above zero" % item.get("name", "a step")
    if found is None:
        ctx.doubt(q.reads, why)
        return Quantity(q.n)
    if found:
        ctx.cut(found, why)
    return q


def num(ctx, item, path, literal, **kwargs):
    """`quantity(...).json()`: a number, or { "expr": formula } when the value follows sizes."""
    return quantity(ctx, item, path, literal, **kwargs).json()
