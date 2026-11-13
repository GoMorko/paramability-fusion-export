"""Output node tree to app formula text, with the brackets the app grammar needs."""
from .text import format_number

# Output nodes: ("num", v), ("name", s), ("neg", a), ("not", a), ("bin", op, a, b) for + - * /,
# ("cmp", op, a, b), ("logic", op, a, b), ("cond", test, a, b), ("call", f, args)

# Binding strength, as in the app grammar: choice, ||, &&, comparison, + -, * /, unary, atom.
_PREC = {"||": 1, "&&": 2, "<": 3, "<=": 3, ">": 3, ">=": 3, "==": 3, "!=": 3, "+": 4, "-": 4, "*": 5, "/": 5}
_UNARY = 6
_ATOM = 7


def _prec(node):
    kind = node[0]
    if kind == "cond":
        return 0
    if kind in ("bin", "cmp", "logic"):
        return _PREC[node[1]]
    if kind in ("neg", "not"):
        return _UNARY
    return _ATOM


def render(node):
    kind = node[0]
    if kind == "num":
        return format_number(node[1])
    if kind == "name":
        return node[1]
    if kind in ("neg", "not"):
        inner = render(node[1])
        return ("-" if kind == "neg" else "!") + (inner if _prec(node[1]) == _ATOM else "(" + inner + ")")
    if kind == "call":
        return node[1] + "(" + ", ".join(render(a) for a in node[2]) + ")"
    if kind == "cond":
        test = render(node[1])
        if _prec(node[1]) == 0:
            test = "(" + test + ")"
        return f"{test} ? {render(node[2])} : {render(node[3])}"
    op, left, right = node[1], node[2], node[3]
    p = _PREC[op]
    ltext = render(left)
    rtext = render(right)
    # A comparison does not chain, so a comparison on either side needs brackets.
    if _prec(left) < p or (kind == "cmp" and _prec(left) == p):
        ltext = "(" + ltext + ")"
    if _prec(right) <= p:
        rtext = "(" + rtext + ")"
    return f"{ltext} {op} {rtext}"
