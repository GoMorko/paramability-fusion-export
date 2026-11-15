"""Fusion expression text to a formula in the app grammar (`@packages/expressions`).

Fusion writes `;` between function arguments, `^` for powers, `%` for the remainder, `<>` for not equal, the words
`and`, `or`, `not`, and `if(test; a; b)`. The app formula writes `,`, `pow`, `mod`, `!=`, `&& || !` and
`test ? a : b`. A formula is a number over size names with lengths in mm and angles in degrees, so every unit is
converted away: `2 mm` becomes `2`, `1 in` becomes `25.4` and `w / mm` becomes `w`. Units are tracked as a pair of
powers (length, angle) only to convert numbers: Fusion already refuses expressions whose units do not fit, so a mix
of units is written as it stands. docs/expressions.md has the full table.

Unverified in Fusion: a number without a unit added to a length is read in the design's default length unit, a value
without a unit in an angle position is read in degrees, and `-a ^ b` binds as `-(a ^ b)`. The value check compares
the written formula with the number Fusion reports, so a wrong guess is caught instead of writing a wrong formula.

The modules, from the bottom up: `errors`, `units` (unit words and powers), `reading` (Fusion text to a parse tree),
`text` (number and expression text), `writing` (output tree to formula text), `formula` (formula text to an output
tree), `functions` and `evaluation` (the value of a formula), `simplify` (equal terms of a sum) and `translation`
(parse tree to a typed output tree).
"""
from .errors import ExpressionError
from .evaluation import evaluate
from .reading import parse, referenced_names
from .simplify import collected_sum
from .text import format_expression, is_constant_expression, is_plain_number
from .translation import Typed, translate_tree
from .units import ANGLE, LENGTH, SCALAR
from .writing import render

__all__ = [
    "ANGLE", "LENGTH", "SCALAR", "ExpressionError", "Typed", "collected_sum", "evaluate", "format_expression",
    "is_constant_expression", "is_plain_number", "parse", "referenced_names", "render", "translate_tree"]
