"""Number and expression text: the number format, the plain-number check and the text written into a parameter."""
import re

from ...package.units import unit_kind
from .errors import ExpressionError
from .reading import parse

# Longest formula text the app accepts in a recipe.
MAX_FORMULA_LENGTH = 300


def format_number(value):
    """Number text with at most 9 decimals and no exponent."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = ("%.9f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


_PLAIN_NUMBER = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*([A-Za-z]+)?\s*$")


def is_plain_number(expression):
    """True for "20", "20 mm" or "1.5e2 deg"; false for formulas such as "d1 * 2" or "20 mm + 1 mm"."""
    return bool(_PLAIN_NUMBER.match(expression or ""))


def _names_nothing(node):
    """True when the parse tree reads no parameter and calls no `random`."""
    if node[0] == "name" or (node[0] == "call" and node[1] == "random"):
        return False
    return all(_names_nothing(part) for part in node[1:] if isinstance(part, tuple)) and all(
        _names_nothing(arg) for part in node[1:] if isinstance(part, list) for arg in part)


def is_constant_expression(expression):
    """True for a formula of plain numbers that Fusion can work out alone (`3 * 0.4 mm`, `3/8 in`, `PI * 10 mm`): it
    reads no other parameter and does not call `random`. False for text the parser refuses."""
    try:
        return _names_nothing(parse(expression or ""))
    except ExpressionError:
        return False


def format_expression(value, unit):
    """Expression text to write into a parameter, for example "40 mm"."""
    number = format_number(value)
    unit = (unit or "").strip()
    if unit_kind(unit) == "count":
        return number
    return f"{number} {unit}"
