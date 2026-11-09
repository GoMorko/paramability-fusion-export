# Fusion expressions to app formulas

`lib/params/expressions.py` turns the expression of a Fusion parameter into a formula in the app grammar
(`@packages/expressions` in the app). The app formula is a plain number over size names: lengths in mm, angles in
degrees. So every unit is converted away, and the unit powers (length, angle) are tracked only to refuse sums and
comparisons of unlike things.

Sources: the Fusion help pages "Parameters reference" (operators, constants, logic, functions) and "Unit types"
(unit words), and the API page "Understanding Units in Fusion" (bare numbers, internal cm and radians). The Fusion
`sign` behaviour at 0 comes from the Autodesk community forum, not from the help.

## Operators and syntax

| Fusion | App formula | Note |
|---|---|---|
| `a + b`, `a - b`, `a * b`, `a / b` | same | `x * 1` and `x / 1` (from a unit word) drop the `1` |
| `a ^ b` | `pow(a, b)` | binds tighter than unary minus: `-a ^ 2` is `-pow(a, 2)` |
| `a % b` | `mod(a, b)` | the app's `mod` takes the sign of `b`; Fusion's floating point modulo may differ for negative values |
| `f(a; b)` | `f(a, b)` | a comma is read as a separator too |
| `<`, `<=`, `>`, `>=`, `==` | same | gives 1 or 0; `a < b < c` is refused, as in the app |
| `<>` (and `!=`) | `!=` | |
| `a and b`, `a or b`, `not a`, `not(a)` | `a && b`, `a \|\| b`, `!a` | also `AND`, `OR`, `NOT` |
| `if(test; a; b)` | `test ? a : b` | nested `if` becomes a chain `t1 ? a : t2 ? b : c` |
| `PI`, `π` | `pi()` | |
| `E` | `exp(1)` | |

## Units

A unit word after any operand multiplies it: `2 mm`, `500mm`, `(a + b) mm`, `w mm`. It binds to that operand only,
so `w / 42 mm` is `w / (42 mm)`. A unit word on its own is 1 of that unit: `w / mm` is `w`, `w / in` is `w / 25.4`.
After a value, the unit is matched without case (`2 MM`); on its own it must match exactly, so a parameter named `M`
is not taken for metres.

| Kind | Words | In the formula |
|---|---|---|
| Length | `mm`, `millimeter`, `cm`, `centimeter`, `m`, `meter`, `hm`, `um`, `micron`, `µ`, `in`, `inch`, `"`, `ft`, `foot`, `yd`, `yard`, `mi`, `mile`, `mil`, `nauticalMile` | mm |
| Angle | `deg`, `degree`, `degrees`, `°`, `˚`, `rad`, `radian`, `radians`, `grad` | degrees (`rad` writes `* 180 / pi()`) |

A bare number next to a length (in a sum, a comparison, `min`, `max`, `%` or the two results of `if`) is read in the
design's default length unit. A value without a unit in an angle position (`sin(30)`) is read in degrees. Any
other unit (`kg`, `s`) is refused. A length plus an angle is refused.

## Functions

Function names are matched without case.

| Fusion | Takes | App formula | Gives |
|---|---|---|---|
| `sin`, `cos`, `tan` | angle | same; the app takes degrees | no unit |
| `asin`, `acos`, `atan` | no unit | same; the app gives degrees | angle |
| `sinh`, `cosh`, `tanh` | angle | written with `exp` over the angle in radians | no unit |
| `asinh`, `acosh`, `atanh` | no unit | written with `ln` and `sqrt`, then `* 180 / pi()` | angle |
| `exp`, `ln`, `log` | no unit | same (`log` is base 10 in both) | no unit |
| `sqrt` | any unit that can be halved | `sqrt` | half the unit |
| `pow(a; b)` | any, `b` without a unit | `pow(a, b)` | `a`'s unit to the power `b` (a whole number when `a` has a unit) |
| `abs`, `floor`, `ceil`, `round` | any | same | the same unit |
| `min`, `max` | values of one unit | same | that unit |
| `sign(x)` | any | `x > 0` | 1 above zero, else 0 |
| `random()` | | refused | |

## Value check

`evaluate` works out a written formula with the app's own function rules (trig in degrees and exact at quarter
turns, `round` half up, floored `mod`, only the taken branch of a choice). The size table compares the result with
the value Fusion reports and refuses a formula that misses it. This pins the unverified readings above: the design
unit for bare numbers, degrees for unitless angles, and the rounding of negative halves (`round(-1.5)` is -2 in
Fusion and -1 in the app).

## Not translated

- `random()`: the app formula has no random numbers.
- `Gravity`, `SpeedOfLight` and units other than lengths and angles.
- Text parameters and the `{name}` text form.
- `sin(PI/4 rad)` as written in the Fusion help reads as `PI / (4 rad)` here and is refused; `sin((PI/4) rad)` works.
