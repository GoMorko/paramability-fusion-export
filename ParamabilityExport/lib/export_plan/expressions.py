"""Parameter expressions: plain number check and building an expression from a number and a unit."""
import re

from ..package.units import unit_kind

_PLAIN = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*([A-Za-z]+)?\s*$")


def is_plain_number(expression):
    """True for "20", "20 mm" or "1.5e2 deg"; false for formulas such as "d1 * 2" or "20 mm + 1 mm"."""
    return bool(_PLAIN.match(expression or ""))


def format_number(value):
    return "%.10g" % value


def format_expression(value, unit):
    """Expression text to write into a parameter, for example "40 mm"."""
    number = format_number(value)
    unit = (unit or "").strip()
    if unit_kind(unit) == "count" and not unit:
        return number
    return f"{number} {unit}"
