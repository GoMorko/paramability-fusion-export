"""Adding up the equal terms of a formula's outer sum."""
from .errors import ExpressionError
from .formula import parse_formula
from .writing import _PREC, _prec, render


def _plain_value(node):
    """The number of a node made of numbers and arithmetic only, else None."""
    kind = node[0]
    if kind == "num":
        return float(node[1])
    if kind == "neg":
        inner = _plain_value(node[1])
        return None if inner is None else -inner
    if kind == "bin" and node[1] in ("+", "-", "*", "/"):
        a, b = _plain_value(node[2]), _plain_value(node[3])
        if a is None or b is None or (node[1] == "/" and b == 0):
            return None
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0.0}[node[1]]
    return None


def _summands(node, factor, out):
    """Adds `factor` times `node` to `out` (term text to coefficient, "" for the number), splitting sums, differences,
    negations, multiples of a number and divisions by one; any other node is one term, keyed by its text."""
    kind = node[0]
    plain = _plain_value(node)
    if plain is not None:
        out[""] = out.get("", 0.0) + factor * plain
    elif kind == "neg":
        _summands(node[1], -factor, out)
    elif kind == "bin" and node[1] in ("+", "-"):
        _summands(node[2], factor, out)
        _summands(node[3], factor if node[1] == "+" else -factor, out)
    elif kind == "bin" and node[1] == "*" and _plain_value(node[2]) is not None:
        _summands(node[3], factor * _plain_value(node[2]), out)
    elif kind == "bin" and node[1] == "*" and _plain_value(node[3]) is not None:
        _summands(node[2], factor * _plain_value(node[3]), out)
    elif kind == "bin" and node[1] == "/" and _plain_value(node[3]):
        _summands(node[2], factor / _plain_value(node[3]), out)
    elif kind == "bin" and node[1] in ("*", "/") and node[2][0] == "neg":
        _summands(("bin", node[1], node[2][1], node[3]), -factor, out)
    else:
        text = render(node)
        out[text] = out.get(text, 0.0) + factor


# Denominators a collected coefficient is written over (`x / 3`), so a third stays exact instead of 0.333333333.
_DENOMINATORS = range(2, 65)


def _exact_text(value):
    """A number with up to 12 decimals, so adding up written numbers keeps their digits."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = ("%.12f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _times(coef, text):
    """`coef` (positive) times the term `text`, written over a small denominator where the coefficient is one."""
    level = _prec(parse_formula(text))
    if abs(coef - 1.0) <= 1e-12:
        return text if level > _PREC["+"] else "(" + text + ")"
    body = text if level > _PREC["*"] else "(" + text + ")"
    if abs(coef - round(coef)) <= 1e-12 * max(1.0, coef):
        return "%d * %s" % (round(coef), body)
    for q in _DENOMINATORS:
        p = coef * q
        if abs(p - round(p)) <= 1e-12 * max(1.0, p):
            return "%s / %d" % (body if round(p) == 1 else "%d * %s" % (round(p), body), q)
    return "%s * %s" % (_exact_text(coef), body)


def collected_sum(formula):
    """The formula with equal terms of its outer sum added up (`a + 2 * b - (b + 1) + 3` is `a + b + 2`), or the formula
    itself when it does not read as a formula. A coefficient that is a fraction with a small denominator is written
    as one (`a / 3`); any other keeps 12 decimals."""
    try:
        parts = {}
        _summands(parse_formula(formula), 1.0, parts)
    except ExpressionError:
        return formula
    const = parts.pop("", 0.0)
    out = ""
    for text, coef in parts.items():
        if abs(coef) <= 1e-12:
            continue
        body = _times(abs(coef), text)
        if not out:
            out = ("-" if coef < 0 else "") + body
        else:
            out += (" - " if coef < 0 else " + ") + body
    if abs(const) > 1e-12 or not out:
        out += (" - " if const < 0 else " + ") + _exact_text(abs(const)) if out else _exact_text(const)
    return out
