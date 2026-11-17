# sketch_solve

Works out each point of a sketch as a formula of the sketch's own dimensions, from one `capture.sketch_graphs`
record (`docs/capture-format.md`, "Sketch graphs"). Pure Python, no Fusion, no numeric solving. Imports `package` and
`sketch_values` only. `probe.derived` calls it in shadow mode, after the tries, and records the result in
`report.json` (`docs/capture-format.md`, "Derived values").

## Interface

```python
from lib.sketch_solve.solve import solve_sketch, input_name, default_settings

solution = solve_sketch(record, settings=None, constants=(), tol=1e-6, extended=False, distance_parallel=True)
```

- `record`: one sketch graph record as the reader writes it.
- `settings`: other size settings to check redundant rules and choices at, a list of `{leaf: number}`. A leaf left
  out keeps its value now. Without them the solver moves each dimension leaf on its own (`default_settings`) and
  keeps measured inputs where they are. A caller that knows how the sizes tie the dimensions together (two
  dimensions that read one user parameter) should pass settings made from user parameter values.
- `constants`: refs `("point", id)` or `("curve", id)` of projected entities that do not move with any size; they
  become numbers instead of measured inputs. `constants.constants_of(record, linked)` lists them: the projections of
  another component when no parameter reaches the sketch through that component (`linked` false), and the
  projections of the origin point, the origin axes and the origin planes of the sketch's own component (`origin` on
  the reference, `own_origin`) when the caller says that no size moves the sketch plane (`fixed_plane`); an origin
  axis the reader did not mark is found by its place.
- `extended`: the reading the Orca copy uses (`orca_translate.sketches`); the recipe export and `probe.derived` keep
  the default, so their output does not change with it (`tests/test_sketch_solve_extended.py`). It reads a driving
  distance dimension between two lines as keeping them parallel, tests angle dimensions and the parallel lines of a
  distance dimension within what the rounding of the drawing allows for the lines' lengths
  (`checks.turn_slack`, at most `checks.MAX_SLACK` radians), fills `directions`, and gives a line its direction
  from the gap between its ends when that gap is known on both axes although the ends are not (the diagonals of a
  rectangle, so a centre point on both diagonals places it).
- `distance_parallel`: with `extended`, False leaves out the rule that a distance dimension keeps its two lines
  parallel. The Orca copy solves a sketch both ways to find the formulas that rest on that rule (hand test OR18).

`solution` (`outcome.Solution`):

- `outcome`: `derived`, `partly` or `not_derived`; `reason` says why a whole sketch is not derived.
- `points[id]`: `(x, y)`, each an `outcome.Value`: `expr` (an `sketch_values.expr.Expr`) or `code` and `reason`.
  `Value.affine()` gives an `Affine` for a linear formula.
- `radii[id]`: a `Value` per arc and circle.
- `leaves[name]`: every name a formula may read. `kind` `dimension`: the dimension's model parameter (`d16`), with
  the dimension id, `expression` and `reads`. `kind` `input`: a measured coordinate of a projected entity, named
  `input_name(ref, field)`: `@p3.x`, `@p3.y`, `@c5.r`, with the entity ref, field and token.
- `directions[id]`: with `extended`, a `Value` per line with a direction: its angle in degrees from its first point
  to its second, when the rules give it as an angle (horizontal, vertical, angle dimensions, perpendicular and
  parallel lines).
- `parallel_by_distance`: with `extended` and `distance_parallel`, the pairs of line ids that only a distance
  dimension keeps parallel.
- `assumptions`: each choice between two solutions, with a `guard` expression that stays above zero while the
  choice holds and `flips`, the numbers of the settings where it does not.
- `dimensions[id]`, `constraints[id]`: `Usage` with `status` (`used`, `driven`, `refused`, `not_covered`,
  `not_used`, `unread`, `suppressed`), a reason and, for dimensions, the value measured on the drawing.
- `json()`: the record for `report.json`.

Open value codes (`outcome`): `blocked` (an item the solver does not read names the entity), `refused` (a dimension
on it does not match the drawing), `free` (Fusion says it is not fully constrained), `no_rule`, `conflict`, `unread`.

## How the record is read

These details are not fixed by the format doc; the reader and the solver agree on them here.

- A ref `[kind, id]` with any curve kind (`line`, `arc`, `circle`, `curve`, ...) names `curves[id]`. A `surface`,
  `other` or null ref makes the item unusable: its other entities stay open.
- A record with `unread` or `unknown` is not used and keeps its entities open. A sketch whose `unread` names a
  collection is not derived; `isFullyConstrained` alone does not matter.
- `linear` with one line in `on` measures between the line's two ends. A `horizontal` or `vertical` linear
  dimension to a line measures to the line's start point, and only when the line runs vertical or horizontal on
  the drawing.
- `angular`: the value is one of the angles the two lines make (compared modulo 180 degrees); the solved lines pick
  the turn.
- `offset` constraint: read from `parents`, `children`, `distance`, `topology_matched` and `dimension`. Used only
  when `topology_matched` is true and every child is a line parallel to a parent at the distance or an arc
  concentric with a parent, its radius larger or smaller by the distance. Its `offset_curves` dimension gives the
  distance's leaf.
- A point without its own `reference` that belongs to a projected curve takes the curve's reference.
- The origin point and `fixed` entities are constants. A reference with source `none` is a constant; `own` and
  `other` are measured inputs unless the caller lists them in `constants`.
- `implicit` entities are ordinary geometry; their own `fixed` and `reference` decide.
- `free: null` counts as not free. Pattern constraints with `suppressed: true` are ignored.

## Rules

Line directions: horizontal, vertical, parallel and collinear classes, perpendicular and angle dimensions, a line
through two known points. Linear relations between point coordinates, line offsets, radii and line lengths: linear
dimensions, offset dimensions, coincident, horizontal and vertical points, collinear, equal, concentric, midpoint,
symmetry about a line, offset of matching lines and arcs, tangency of a line and an arc (the arc end is the foot of
the centre), diameter, radius and concentric circle dimensions. Distances: a point on an arc or circle, an aligned
dimension between two points, two tangent arcs (the touching point lies between the centres).

Not read (their entities stay open): smooth, polygon and pattern constraints, surface constraints and dimensions,
tangent distance and linear diameter dimensions, ellipses, splines and conics, a midpoint on an arc, a tangent
between two lines.
