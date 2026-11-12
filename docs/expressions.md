# Fusion expressions to app formulas

`lib/params/expressions.py` turns the expression of a Fusion parameter into a formula in the app grammar
(`@packages/expressions` in the app). The app formula is a plain number over size names: lengths in mm, angles in
degrees. So every unit is converted away. The unit powers (length, angle) are tracked only to convert numbers, never
to refuse: Fusion already refuses an expression whose units do not fit, so whatever it accepts is translated.

Sources: the Fusion help pages "Parameters reference" (operators, constants, logic, functions) and "Unit types"
(unit words), and the API page "Understanding Units in Fusion" (bare numbers, internal cm and radians). The Fusion
`sign` behaviour at 0 comes from the Autodesk community forum, not from the help.

## Operators and syntax

| Fusion | App formula | Note |
|---|---|---|
| `a + b`, `a - b`, `a * b`, `a / b` | same | `x * 1` and `x / 1` (from a unit word) drop the `1` |
| `a ^ b` | `pow(a, b)` | binds tighter than unary minus: `-a ^ 2` is `-pow(a, 2)` |
| `a % b` | `mod(a, b)` | the app's `mod` takes the sign of `b`; what Fusion gives for a negative `a` is not confirmed, so a formula whose `a` can be negative over the size ranges is not copied (the sizes it reads are loose with a reason) |
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

A value without a unit next to a length (in a sum, a comparison, `min`, `max`, `%` or the two results of `if`) is
read in the design's default length unit, next to an angle in degrees. This holds for a number and for a unitless
parameter. A value without a unit in an angle position (`sin(30)`) is read in degrees. A unitless parameter times
`1 mm` is the same number in mm (`count * 1 mm` is `count`). Other unit words (`kg`, `s`) cannot be read.

### The unit of the parameter

The formula of a parameter is scaled to the parameter's own unit when the two differ. A plain number formula in a
length parameter (`layers * 0.4` in a mm parameter) is read in the parameter's unit, else in the design's unit. A
length formula in a parameter without a unit is read as mm, else in Fusion's internal cm, else in the design's unit.
The value check picks the first reading that gives Fusion's number. Feature values of model parameters are scaled the
same way, to the unit of the field they set.

A parameter unit built from lengths and angles (`mm^2`) gives a plain number in mm squared: formulas can read it,
but it cannot be ticked as a size. A parameter in another unit (a mass, a time) is left out, and so is any formula
that reads it.

### Helper parameters

A user parameter that only other formulas read is handled like any other. Ticked, it is a size. Unticked and plain,
its number is written into each formula that reads it. Unticked and a formula, it becomes a derived size when it
follows a ticked size, else its number. Past 64 named sizes, a derived formula is written in full where it is read.
A formula that cannot be translated and follows no size is read as its number, so it breaks nothing.

### Which parameters a body reads

`lib/params/dependencies.py` builds one graph of what each parameter reads, user and model parameters alike:

- the names in its expression, read with the parser above. When the parser refuses the text (a unit it cannot
  read, a chained comparison), the words of the text that name a known parameter stand in, so the chain is not cut;
- Fusion's own list (`dependency_parameters`), which Fusion fills through every formula on the way;
- the reverse of a user parameter's `dependent_parameters` and `dependents`. A model parameter of the body that reads
  a model parameter of another component (one the capture does not hold) still reaches the user parameters behind
  it this way.

A walk over the graph keeps a set of the names it has seen, so a cycle ends. The size table walks it to find the
free sizes behind a value (`depends`); the dialog walks it from the body's model parameters and from the parameters
that reach the body through another component (`Graph.usage`):

- every plain user parameter the body reads, at any depth, is ticked to start with (with favourites, the favourites
  it reads, plus the plain parameters behind a favourite formula);
- a parameter the body reads only through formulas of other user parameters says so in its row: "This part uses it
  through the formula `FilterBox_width_mm`." The formula named is the outermost one, the one the body reads itself;
- a formula stays a derived size over the base sizes (`expr`), and the size probe tries only the base sizes.

A formula that cannot be translated still passes on what it reads: its base sizes are ticked, and a value that reads
the formula cannot follow them, so the driver fixes them with the reason. In the manifest `parameters` list such a
formula keeps Fusion's text next to its number.

## Functions

Function names are matched without case.

| Fusion | Takes | App formula | Gives |
|---|---|---|---|
| `sin`, `cos`, `tan` | angle | same; the app takes degrees | no unit |
| `asin`, `acos`, `atan` | no unit | same; the app gives degrees | angle |
| `sinh`, `cosh`, `tanh` | angle | written with `exp` over the angle in radians | no unit |
| `asinh`, `acosh`, `atanh` | no unit | written with `ln` and `sqrt`, then `* 180 / pi()` | angle |
| `exp`, `ln`, `log` | no unit | same (`log` is base 10 in both) | no unit |
| `sqrt` | any | `sqrt` | half the unit |
| `pow(a; b)` | any | `pow(a, b)` | `a`'s unit to the power `b` |
| `abs`, `floor`, `ceil`, `round` | any | same | the same unit |
| `min`, `max` | values of one unit | same | that unit |
| `sign(x)` | any | `x > 0` | 1 above zero, else 0 |
| `random()` | | refused | |

## Value check

`evaluate` works out a written formula with the app's own function rules (trig in degrees and exact at quarter
turns, `round` half up, floored `mod`, only the taken branch of a choice). The size table compares the result with
the value Fusion reports and refuses a formula that misses it; the sizes it reads are then fixed with that reason.
This pins the unverified readings above: the design unit for bare numbers, degrees for unitless angles, the reading
of a formula in its parameter's unit, and the rounding of negative halves (`round(-1.5)` is -2 in Fusion and -1 in
the app).

## Not translated

- `random()`: the app formula has no random numbers.
- `Gravity`, `SpeedOfLight` and unit words other than lengths and angles.
- Text parameters and the `{name}` text form.
- `sin(PI/4 rad)` as written in the Fusion help reads as `PI / (4 rad)` here and is refused; `sin((PI/4) rad)` works.
