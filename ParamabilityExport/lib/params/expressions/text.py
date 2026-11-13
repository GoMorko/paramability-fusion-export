"""Number and expression text: the number format, the plain-number check and the text written into a parameter."""
import re

from ...package.units import unit_kind

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


def format_expression(value, unit):
    """Expression text to write into a parameter, for example "40 mm"."""
    number = format_number(value)
    unit = (unit or "").strip()
    if unit_kind(unit) == "count":
        return number
    return f"{number} {unit}"
