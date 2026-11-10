### Sketch graphs (`sketch_graphs`)

Draft subsection for `docs/capture-format.md`, to sit after "Geometry links". Add `"sketch_graphs": [ SKETCH GRAPH, ... ]`
to the envelope in section 2.

For every sketch that a step of the target's component uses (the target's own sketches and sketches borrowed from
another component), `lib/fusion_reader/read_constraints.py` records the sketch as plain data: its points and curves,
what each dimension measures and what each geometric constraint ties together. It is read once, with the marker back
at its start position. Nothing is solved or evaluated: values are what Fusion gives directly. Lengths are in mm,
angles in degrees, points in the sketch's own 2D frame (`SketchPoint.geometry`, the same frame as the profile
curves). A borrowed sketch is read through its native object, so its numbers are in its own component's frame.

```json
{ "sketch": "Sketch5", "token": "...", "borrowed": true,
  "component": { "token": "...", "name": "Lid" },
  "fully_constrained": true, "origin": 3, "cut": "",
  "points": [ { "id": 0, "xy": [12.5, 0.0], "origin": false, "fixed": false, "free": false, "linked": false,
                "reference": null, "token": "..." } ],
  "curves": [ { "id": 0, "kind": "line", "points": [3, 0], "center_line": false, "construction": false,
                "fixed": false, "free": false, "linked": false, "reference": null, "token": "..." },
              { "id": 1, "kind": "arc", "center": 4, "points": [2, 3], "radius": 5.0, "construction": false, "...": "..." },
              { "id": 2, "kind": "circle", "center": 5, "radius": 3.0, "construction": true, "...": "..." } ],
  "dimensions": [ { "id": 0, "type": "linear", "orientation": "horizontal",
                    "on": [["point", 3], ["point", 0]], "param": "d16", "expression": "WallThickness",
                    "reads": ["WallThickness"], "value": 3.0, "driving": true, "text": [10.0, -4.0],
                    "token": "..." } ],
  "constraints": [ { "id": 0, "type": "horizontal", "on": [["line", 0]], "token": "..." },
                   { "id": 1, "type": "coincident", "on": [["point", 3], ["line", 0]], "token": "..." },
                   { "id": 2, "type": "other", "name": "adsk::fusion::FutureConstraint", "unknown": true,
                     "on": [["curve", 7]], "token": "..." } ] }
```

- `borrowed` is present (true) only for a sketch that every record naming it marks `foreign`. `component` is the
  sketch's component. A sketch that cannot be found or read is `{ sketch, token, error }`; at most 200 sketches are
  read, the rest are `{ sketch, token, cut: "sketches" }`.
- Ids are local to the record: `points[i].id == i`, `curves[i].id == i`. Entities are matched by object identity
  (`read_geometry.same_entity`), never by token text, because Fusion can give one entity several tokens. A token is
  kept for finding the entity again later.
- `fully_constrained` is `Sketch.isFullyConstrained`. `origin` is the id of the sketch's origin point. If the
  sketch's own point list does not hold it, it is added with `implicit: true`.
- Per entity: `fixed` is `isFixed`; `free` is `not isFullyConstrained`; `linked` is `isLinked`; `construction` is
  `SketchCurve.isConstruction`. `reference` is `null` for own geometry, else
  `{ "source": "own" | "other" | "none", "component", "token" }` from `referencedEntity`: `own` is a source in the
  target's component, `other` one in another component, `none` a reference with no source (not parametric).
- Curve kinds: `line` (`points`: start, end; `center_line`), `arc` (`center`, `points`: start, end, counter clockwise;
  `radius`), `circle` (`center`, `radius`), and for curves the reader does not tabulate `ellipse`, `elliptical_arc`,
  `conic`, `spline` or `other` (with `name`, the class name); these carry no geometry beyond the common fields.
- `on` is a list of entity refs, in the member order of the API. A ref is `["point", id]`, `["line", id]`,
  `["arc", id]`, `["circle", id]` or `["curve", id]` (ids of `points` or `curves`), `["surface", "BRepFace" |
  "ConstructionPlane"]` for a face or plane, `["other", "<class>"]` for anything else, or `null` when the member is
  null or cannot be read. An entity a dimension or constraint names that the sketch's lists do not hold (for example
  an axis line) is added to `points` or `curves` with `implicit: true`.
- `dimensions[].type`, with the API class and members read into `on`:

  | `type` | Class | `on` |
  | --- | --- | --- |
  | `linear` | `SketchLinearDimension` | `entityOne`, `entityTwo`; `orientation`: `aligned`, `horizontal`, `vertical` or `other` |
  | `offset` | `SketchOffsetDimension` | `line`, `entityTwo` |
  | `angular` | `SketchAngularDimension` | `lineOne`, `lineTwo` (value in degrees; which of the four angles it is has to be decided from the solved lines) |
  | `diameter`, `radial` | `SketchDiameterDimension`, `SketchRadialDimension` | `entity` |
  | `concentric_circles` | `SketchConcentricCircleDimension` | `circleOne`, `circleTwo` |
  | `linear_diameter` | `SketchLinearDiameterDimension` | `line`, `entityTwo` |
  | `tangent_distance` | `SketchTangentDistanceDimension` | `entityOne`, `circleOrArc` |
  | `offset_curves` | `SketchOffsetCurvesDimension` | none; `offset_constraint` is the id of its offset constraint |
  | `ellipse_major_radius`, `ellipse_minor_radius` | `SketchEllipse...RadiusDimension` | `ellipse` |
  | `point_surface` | `SketchDistanceBetweenPointAndSurfaceDimension` | `point`, `surface` |
  | `line_surface` | `SketchDistanceBetweenLineAndPlanarSurfaceDimension` | `line`, `planarSurface` |
  | `other` | any other class | every entity named by a member of the common names; `name` is `objectType`, `unknown: true`, `value: null` |

  Every dimension also has `param` (the model parameter name, or null), `expression`, `reads` (the parameters the
  expression reads, directly or through others), `value` (mm, or degrees for `angular`; null when unreadable),
  `driving` (`isDriving`: a driven dimension is a measurement, not an input), `text` (`textPosition`, x and y in mm)
  and `token`.
- `constraints[].type`: `coincident` (`point`, `entity`), `horizontal`, `vertical` (`line`), `horizontal_points`,
  `vertical_points` (`pointOne`, `pointTwo`), `parallel`, `collinear` (`lineOne`, `lineTwo`), `perpendicular` (`line`,
  `curve`; the retired `lineOne`, `lineTwo` are tried when the new ones fail), `equal`, `tangent`, `smooth`
  (`curveOne`, `curveTwo`), `concentric` (`entityOne`, `entityTwo`), `midpoint` (`point`, `midPointCurve`), `symmetry`
  (`entityOne`, `entityTwo`, `symmetryLine`), `coincident_surface` (`point`, `surface`), `line_on_surface` (`line`,
  `planarSurface`). Constraints whose members are lists list every entity flat in `on`: `offset` (`parents`,
  `children`, `distance` in mm, `topology_matched`, `dimension` = id of its dimension), `polygon` (centre first, then
  the points), `rectangular_pattern` and `circular_pattern` (entities, created entities, direction entities or centre;
  `suppressed`). Any other class, including `LineParallelToPlanarSurfaceConstraint` and
  `PerpendicularToSurfaceConstraint`, is `{ "type": "other", "name": "<objectType>", "unknown": true, "on": [...] }`
  with every entity a member of the common names holds.
- A member that raises, or does not exist, never stops the read. It is listed in the record's `unread` (for a
  sketch: the collections or `isFullyConstrained`), the value reads `null` and an entity place in `on` reads `null`.
  A consumer must not use a dimension or constraint that has `unread`, `unknown` or a `null` in `on`; it keeps its
  entities open instead of ignoring it. A collection item that cannot be fetched keeps its id as an unknown record
  with `unread: ["item"]`.
- Limits: a sketch with more than 2000 points and curves, more than 2000 dimensions or more than 2000 constraints is
  `cut: "entities"`, `"dimensions"` or `"constraints"`, with empty lists; it must not be used.
- The read costs no recompute and evaluates no geometry beyond `SketchPoint.geometry`.
