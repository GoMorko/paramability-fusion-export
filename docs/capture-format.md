# Capture format

The capture is the plain dict the reader (`lib/fusion_reader/`) returns for one design, and the only input of the
pure translator (`lib/translator/`). Fixtures in `tests/fixtures/captures/` use this format, so every translator test
runs without Fusion. They are written by hand or saved from real designs: the export writes the capture into
`report.json` (section 6). The reader writes capture number 3 and the translator reads only that number: a capture is
made and read in one export run, so no older number is kept. The translator refuses any other number, or a capture
that lacks `capture`, `target` or `items`, with a `CaptureError`.

## 1. Rules for every value

- Lengths in mm (Fusion cm times 10), angles in degrees (Fusion radians times 180 / pi), through
  `lib/package/units.py`. Unitless values stay.
- 3D values are in the coordinates of the target's component (the native body's own frame; for a body in the root
  component these are the design's model coordinates), before any up axis turn. `target.placement` (section 2)
  maps them to the root. Points and vectors are `[x, y, z]` lists.
- 2D sketch values are in the sketch's own frame: `[x, y]` in mm.
- A frame is `{ "origin": [..], "x": [..], "y": [..], "z": [..] }` (unit axes, model frame), read with
  `Matrix3D.getAsCoordinateSystem()`.
- A plane is `{ "point": [..], "normal": [..] }`. An axis is `{ "point": [..], "dir": [..] }` (dir unit).
- A box is `{ "min": [..], "max": [..] }` from `BRepBody.boundingBox` (`minPoint`, `maxPoint`).
- Bodies are named by `BRepBody.entityToken` plus `BRepBody.name`. Two refs name one body when both tokens match; the
  names are compared only when a token is missing. A body with the target's name and another token is not matched:
  the translator refuses ("The body could not be followed through the timeline") rather than guess.
- An entity the reader cannot express becomes `{ "kind": "other", "type": "<objectType>" }`; the translator
  refuses it with a note. The reader never throws for an unknown shape.

## 2. Envelope

```json
{
  "capture": 3,
  "fusion": "2.0.21508",
  "design": "Cable clip",
  "up_axis": "z",
  "design_units": "mm",
  "parameters": { "user": [ PARAMETER, ... ], "model": [ PARAMETER, ... ] },
  "targets": [ TARGET ],
  "target": TARGET,
  "items": [ ITEM, ... ],
  "sketch_links": [ SKETCH LINK, ... ],
  "sketch_graphs": [ SKETCH GRAPH, ... ],
  "marker": { "position": 48, "count": 120 },
  "reach": REACH
}
```

`sketch_graphs` (section 2, "Sketch graphs") is optional, is kept in `report.json` with the rest of the capture and
nothing reads it yet: it holds the points, curves,
dimensions and constraints of every sketch the target's steps use, so a later version can work out sketch values
without trying sizes. `marker` says where the timeline marker was: `position` items sat before it, `count` is the length of the timeline.
`items` holds only the items before the marker; the design is read as it is there. The translator does not read
`marker` (captures without it read as before). `reach` is optional and is not written by `read_capture`: the pipeline
adds it when the first translation left steps out of the copy (see "Reach" below).

TARGET:

```json
{
  "token": "...", "name": "Body1",
  "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume_mm3": 8000.0,
  "component": { "token": "...", "name": "Tray", "root": false },
  "placement": PLACEMENT
}
```

`target` is the first of `targets` (the same object). `targets` holds the one picked body; a file with several bodies
has one capture per body. The token, name, box
and volume are those of the **native** body (component coordinates), not of the occurrence proxy that the person
picked. `component` is the component that owns the body. `placement` is `null` for a body of the root component;
otherwise:

```json
"placement": {
  "path": "Box:1+Tray:2",
  "frame": { "origin": [100, 50, 0], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1] },
  "source": "transform2",
  "checked_points": 3,
  "uses": 2,
  "linked": false
}
```

- `frame` maps component coordinates to root coordinates (mm, before any up axis turn). `path` is
  `Occurrence.fullPathName`.
- `source` names the candidate that passed (`lib/fusion_reader/placement.py`): `transform2` (the picked occurrence's
  own transform), `path_transform2` (the native occurrence transforms from the top down, multiplied), or the same with
  `transform` for the retired member when `transform2` cannot be read.
- A candidate passes when its frame is a pure rotation plus move (unit, perpendicular, right handed axes within 1e-9;
  no scale or mirror) and up to 3 native vertices (face points when the body has fewer than 3 vertices), mapped by
  it, land on the same vertices of the proxy within 1e-3 mm. `checked_points` is how many were compared.
- `uses` is the number of occurrences of the component in the design; `linked` is true when an occurrence on the path
  comes from a linked design (`Occurrence.isReferencedComponent`).
- When no candidate passes, or the body was not picked through an occurrence, the record is
  `{ "path", "error": "<reason>", "uses", "linked" }` without `frame` and `source`; the export then lands a fixed shape.

`design_units` is the design's default length unit (`fusionUnitsManager.defaultLengthUnits`, `mm` when unreadable); a
bare number in a length formula is read in it. `parameters.user` is `list_user_parameters(design)` and
`parameters.model` is `list_model_parameters(component)` (`lib/fusion_reader/parameters.py`: name, expression, value
in Fusion's internal cm and radians, unit, kind, favourite, dependency lists, and for model parameters `role` and
`created_by` as `{ kind, token, name, sketch, component }`, where `sketch` is the name of the sketch that holds a sketch
dimension (`SketchDimension.parentSketch`) and empty otherwise, and `component` is the token of the component the maker
lives in: the sketch's component for a dimension, else the component the parameter is listed from) for the target's
component, then for each component on its occurrence path up to the root, merged by name (the nearest component wins).
Both are empty lists when unreadable. Each user parameter also has `dependents` (see "Geometry links" below). The
export builds its size table from them
(`lib/params/size_table.py`); the translator reads only `data.params` of the items and, through the size table,
the `created_by` kinds. How a Fusion expression becomes an app formula (operators, `if`, units, functions) is in
`docs/expressions.md`.

`target` is the picked body at the end of the timeline (`volume` cm3 times 1000). `items` lists every timeline
item in order. Group objects are skipped; the children of a group are listed as ordinary items, and the reader raises
when a group lists a child the walk did not reach.

What the translator trusts: `target.token` and `target.name` (to follow the body), `target.placement`, the item fields
in section 5, and the item level `target_box_before` boxes (through all cuts, mirrors). It never reads `target.box` or
`target.volume_mm3`; they are kept for a later geometry check against the rebuilt recipe. In fixtures both are
computed from the capture by `scripts/fixture_geometry.py` (needs numpy; box within one 0.2 mm voxel, volume within
about 0.5 percent). `volume_mm3` is null when the part has steps that script does not model (rounds, chamfers, shells,
tapers, modeled threads, face outlines). A fixture with no geometry in its items (the `core_*` cases and
unreadable ones) keeps a nominal box.

ITEM:

```json
{
  "index": 3,
  "name": "Extrude2",
  "type": "ExtrudeFeature",
  "suppressed": false,
  "health": "ok",
  "message": "",
  "component": "<component token>",
  "in_target_component": true,
  "bodies_after": [{ "token": "...", "name": "Body1" }],
  "target_changed": true,
  "target_before": { "box": { "min": [0, 0, 0], "max": [40, 20, 10] }, "volume_mm3": 8000.0 },
  "target_after": { "box": { "min": [0, 0, 0], "max": [40, 20, 22] }, "volume_mm3": 8900.0 },
  "data": { }
}
```

- `type`: the part of `entity.objectType` after the last `::` (`adsk::fusion::ExtrudeFeature` gives
  `ExtrudeFeature`). Items without an entity: `"type": "none"`.
- `health`: from `TimelineObject.healthState` (`ok`, `warning`, `error`); `message` from
  `errorOrWarningMessage`.
- `component`: the token of the component the item lives in (read on the native entity; empty when unreadable): the
  `parentComponent` of a feature or sketch, the `component` of construction geometry, and for an `Occurrence` the
  component it sits in (the `component` of its `assemblyContext`, else its `sourceComponent`; its own `component` is
  the one it shows). `in_target_component`: that component is the target's component, compared as Fusion objects and
  not by token text. When the component cannot be read it is true for a feature (so the translator still refuses a
  feature of the target it cannot read) and false for the items that are not modeling steps (sketches, construction
  geometry, occurrences, joints and the like: the roles `sketch` and `assembly` in the step kind table,
  `lib/translator/step_kinds.py`). Feature readers run only for items in the target's component, plus the second pass
  below for the steps of a Combine's tool bodies from other components; the other items keep `"data": {}` with their
  `bodies_after`, health and message.
- `helper_of`, `helper_unread`, `body_states`: only on items that made a body a Combine of the target takes as a tool,
  or a body such a tool is copied from (see CombineFeature in section 5). `helper_of` (items of another component):
  the body's token; the item's `data` was read in a second pass in that component's frame. `body_states` (any such
  item, in the target's component or another): per body token the state of that body around the item,
  `{ "box_before": BOX, "volume_before": 8000.0, "volume_after": 7000.0 }` (mm3). `box_before` and `volume_before` are
  null when the body does not exist before the item (the item made it) or cannot be read, `volume_after` when it
  does not exist after it or cannot be read. The feature readers measure the exported body around an item; these are
  the numbers of the tool body, and a tool step without an entry reads null, never the exported body's numbers. One
  item can serve several bodies (a pattern makes many copies), so the map has one
  entry per token. `helper_unread` says why such an item was not read (a limit, or a body or place that could not be
  read).
- `entity_context`: `"proxy"` only when `TimelineObject.entity` came as an occurrence proxy and was turned native
  (`nativeObject`) before reading; absent otherwise.
- `bodies_before` (not for suppressed items): the bodies of the target's component at the marker before the item.
- `target_changed`: whether the native target's box (1e-4 mm) or volume changed from the marker before the item to the
  marker after it. `true` also when the target appears or disappears; `null` when it exists on neither side or a
  measure could not be read. The translator uses `false` to skip a step it has no handler for (see "Parameters behind values" in section 5).
- `target_before`, `target_after`: the native target's box and volume (`{ "box": BOX, "volume_mm3": number }`, in the
  coordinates of section 1) at the marker before the item and at the marker after it, the same two reads that give
  `target_changed`. A side is `null` when the target did not exist there or could not be read. They are written for
  every item, also one with no reader (`"data": {}`: a sweep, a loft), so a step the copy leaves out still says where
  it changed the part and by how much. A left out step (see `docs/recipe-gaps.md`) gets them as `bodyBefore` and
  `bodyAfter`, moved into the recipe's coordinates. The item level `target_box_before` of section 5 stays the
  box the handlers use.
- `bodies_after`: `feature.bodies` read with the marker just after the item. `null` (with an item level
  `"read_error": "bodies: ..."`) when the bodies cannot be read; it is not the same as `[]`, which says the item
  makes no body. The driver must not treat `null` as helper geometry. Items that are not modeling steps get `[]`
  without a read. The translator skips them whatever their bodies say (captures of add-in 0.3.1 have `null` there);
  an occurrence, joint or the like that changes the target is refused.
- `data`: per type, below. Types without a reader (sketches, construction geometry, unknown features) carry
  `"data": {}`. When a reader fails, `data` is `{ "read_error": "<message>" }`.
- A member that cannot be read never becomes a plausible value: it reads as `null` or as an `other` entry
  (`"extent_type": "other"`, `"hole_type": "other"`, `{ "kind": "other" }`), and the translator refuses it.

### Geometry links (`sketch_links`, `dependents`, `sketch_inputs`)

A sketch of the target can follow another component without any parameter of its own: a circle projected from a
pipe in another component, an arc constrained to such a projection, a sketch drawn on a face of another component.
`lib/fusion_reader/read_links.py` reads, with the marker back at its start position, every sketch whose
`sketch_token` a record of an item in the target's component names (records marked `foreign` are skipped):

```json
{ "sketch": "PipeHole", "token": "...", "unknown": 0,
  "links": [{ "token": "...", "name": "Pipe", "references": 2, "constrained": 1, "plane": false,
              "bodies": [{ "token": "...", "name": "Pipe body" }], "sketches": [] }] }
```

- `links`: one entry per component other than the target's that the sketch is tied to. `references` counts the
  reference entities of the sketch (`Sketch.sketchCurves` and `sketchPoints` with `SketchEntity.isReference`) whose
  `referencedEntity` belongs to it: the component of the occurrence it is seen through (`assemblyContext.component`),
  else its own (`component_of`, through `nativeObject` when there is one). `constrained` counts the geometric
  constraints (`Sketch.geometricConstraints`) that tie such a reference to an entity that is not a reference
  (members `point`, `entity`, `entityOne`, `entityTwo`, `curveOne`, `curveTwo`, `lineOne`, `lineTwo`, `line`,
  `curve`). `plane` is true when the sketch lies on a face or plane of that component (`Sketch.referencePlane`).
- `bodies` and `sketches`: what the references point at, by the token and name of the native object: the `body` of
  a referenced edge, face or vertex, the `parentSketch` of a referenced sketch curve or point.
- `unknown` counts reference entities whose `referencedEntity` is null (a reference that is not parametric).
- A sketch that cannot be found by its token (`Design.findEntityByToken`) or read is `{ sketch, token, error }`.
- At most 200 sketches, 5000 entities and 5000 constraints per sketch are read.

Each item that is not a sketch, of any component, has `sketch_inputs` when it takes outlines, a path or points from
sketches: `[{ token, name }]` of each `parentSketch` of its `profile` and `profiles` (a profile, a sketch text or an
ObjectCollection of them; a planar face adds nothing), of the `PathEntity.entity` items of its `path` and
`guideRail`, of the `LoftSection.entity` of its `loftSections`, and of the sketch points of a hole
(`holePositionDefinition.sketchPoints`). It is read with the marker before the item and reads no geometry. The key
is left out when nothing is found.

Each user parameter has `dependents`: one record per model parameter that reads it, directly or through other
parameters that read it (`dependentParameters`, walked transitively, at most 2000 visits; user parameters on the way
are walked but not listed):

```json
{ "name": "d26", "kind": "sketchDimension", "component": "<token>", "sketch": "Top_thick", "sketch_token": "..." }
{ "name": "d30", "kind": "feature", "component": "<token>", "feature": "Extrude8" }
```

`kind` is the maker kind of `created_by` (section 2), read from `ModelParameter.createdBy` (made native when it comes
through an occurrence). `component` is the token of the maker's component: `parentSketch.parentComponent` for a
sketch dimension or text, `component_of` of the feature or construction geometry; `ModelParameter.component` only
when the maker gives none (in a real design Fusion answered the root component there for every parameter). A maker
that cannot be read gives `{ name, kind: "other", component: "" }`. The model parameters of other components are not
listed in `parameters.model`; these records are all the capture keeps of them.

For a sketch dimension, `ModelParameter.createdBy` can answer the owning Sketch and not the dimension. A record whose
maker is a Sketch is then `kind: "sketchDimension"` when one of the sketch's `sketchDimensions` has this parameter
(`sketchText` when a `sketchTexts` height parameter does), with the sketch's name, token and component; a parameter the
sketch does not own that way keeps `kind: "other"` and the sketch name in `feature`.

Where a user parameter acts (`lib/params/geometry_links.py`, `acts`): the component of each dependent; for a sketch
dimension, every item whose `sketch_inputs` names that sketch (by token, else by name in the same component) and that
item's component; for a feature value, the item of that name in that component. A user parameter may reach the
target through a link (`reach`), in this order:

1. `via: "sketch"`: the link's `sketches` names a sketch one of its dimensions sits on;
2. `via: "body"`: when the link's `bodies` name a body that items before the target's sketch made or changed
   (`bodies_after`), one of those items is one it drives; when such items exist and it drives none of them, it has
   no link through that component;
3. `via: "component"`: otherwise, when the link's component is one it acts on.

Tokens are compared, names only when a token is missing. The export works with the sketches the picked body's own
steps use (`body_scope.body_links`), and the translator, given a size table without links, takes them from the whole
capture. A link is `{ "param", "sketch", "component", "via" }` (the component's name). Such a parameter is ticked to
start with like one the body reads, the size probe tries it like a size behind a sketch dimension, and the translator
counts it as a size the sketch reads (`sizes.sketch_sizes`, section 5). The link only makes it worth trying; the
probe decides.

A step can also use a plane, axis, direction or point of another component directly (measured references, "Measured
references", section 4). A user parameter that acts on the component that owns such a reference gets a link `{ "param", "sketch": "", "component", "via": "reference", "step", "ref" }` once per
component (`reference_links`; `step` is the step's name, `ref` the key of the first reference). It is offered, ticked
to start with and probed like a sketch link; the offer text says which step uses which component.

When a sketch of the body is tied to another component (a link, or only `unknown` references), or a step of the body
uses a reference of another component, the user parameters that act on a component other than the target's
(`outside`: the ones acting on a tied or referenced component first, then the rest, each in parameter order) are
candidates for discovery tries ("Probe states", section 5). A try also counts as moving the part when a measured
reference moved.

### Sketch graphs (`sketch_graphs`)

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

### Reach (`reach`)

Which step made the faces a later step picks. It exists because a later round, chamfer, shell or offset of faces picks
its edges and faces with measured points (`near`), and the capture does not say which step made a face (only `made_by`
on face outlines, section 4). When a step is left out of the copy, a pick on its faces would land on some other edge of
the copy. `lib/fusion_reader/read_gap_reach.py` reads the answer, and only when the first translation left a step out
(`lib/export_plan/reach_pass.py`; the capture is then translated again with it):

```json
"reach": { "read": true, "gaps": [12], "makers": { "17": [12], "19": [12, 17] } }
```

or `{ "read": false, "error": "<reason>" }` when the read failed.

- `gaps` are the steps the read was asked about: the steps the first translation left out for their own reason (verdict
  `leftOut` with `cause: "own"`, also inside the `tool_steps` of a Combine). A step left out only because it may pick
  faces of another gap (`cause: "picks"`) is not one of them; the read tests it as a picking step.
- `makers` has one entry per later step that was tested: the key is the item `index`, the list holds the `index` of
  each candidate step that made, or may have made, a face the step picks. Candidates are the steps of `gaps`, the
  steps that made the tool bodies of a Combine among them (reported under the Combine's index), and every later step
  that picks geometry, without items that make no body (sketches, construction geometry). Only steps after the first
  step of `gaps` are tested, and a step of `gaps` is not tested.
- Which items pick geometry is decided by `translator.gaps.pick_records(item)`: the edge records of rounds and
  bevels, and face records with a token, a point or loops (shell and offset faces, the face inputs of a round). These
  are the picks the copy writes as measured points. A face given only by a `face_point` (an emboss face, a face an
  extrude starts from or reaches to) and a face used as an outline are not picks: the copy writes them as numbers or
  shifts and marks the sizes it cannot follow. Lists of bodies and of the faces a step made (`faces_after`,
  `tangent_faces`, `end_points` and the like) are not picks either.
- `Feature.faces` lists the faces a step made, but only all of them with the marker right after the step: the API
  says a later change to the body can take faces out of the list. So the reader first reads each candidate's list
  with the marker right after it. Then it moves the marker to just before each tested step and compares each picked
  face (for an edge: each face it joins, found by `BRepEdge.faces`) with the candidate's list at that point. A face is
  found by its entity token, or by `Component.findBRepUsingPoint` at the recorded point. A candidate counts as reached
  by every pick when its list is empty (a Move, a Combine, a draft may list none), shorter than right after the step,
  or cannot be read; so does every candidate when a pick cannot be found. More than 100 tested steps or 200 candidates
  give `read: false`. The marker goes back to where it was at the end, with the same check as `read_capture`
  (`MarkerError` when it does not read there).
- The translator (`gaps.picked_gaps`): a later step that picks faces of a left out step is left out too, with the gap
  in its `dependsOn`. A left out step that the read did not cover (not in `gaps` and not a tested step, for example
  one that only the final translation leaves out) counts as "may pick". Without `reach`, without `gaps`, or with
  `read: false`, every later step that picks geometry is left out ("It may pick faces of Extrude5, which is missing
  from the copy."). A step that picks nothing is copied either way.
- `validate_capture` refuses a `reach` that is not `{ read: bool }`, a `read: true` without a `makers` dict of index
  lists, and a `gaps` that is not a list of indexes.

## 3. Walk and marker

`lib/fusion_reader/capture.py`, `read_capture(design, body) -> dict`:

1. Read the start marker `end = timeline.markerPosition` (`timeline.count` when the marker is at the end). The walk
   treats it as the end of the timeline: items at `end` and after are left out, never refused.
2. For `k` from 0 to `end`: set `timeline.markerPosition = k`. Read the target's box and volume once. Read
   `bodies_after` and `target_changed` of item `k - 1` and, for items of the target's component, the inputs of item `k`
   (profiles, edges, faces, tool bodies, the target box before it). One recompute per item.
3. The second pass (`lib/fusion_reader/helper_pass.py`), only when a Combine that changes the target lists a tool
   body: roll to the item that holds a body of another component to read its place, then to the items that made the
   tool body, and those that made the bodies it is copied from (see CombineFeature in section 5). It runs in rounds,
   since the items it reads name more bodies. Two marker moves per such item at most, none for other items.
4. `finally`: put the marker back at `end` (`moveToEnd` when `end == count`, else `markerPosition = end`), then
   check it reads `end`; else `MarkerError`. After that, each `timeline.timelineGroups` entry that starts before
   `end` must be covered by the walk up to `end`; else `read_capture` raises `CaptureReadError` and the export lands
   as a fixed shape.
5. The STEP file is written before the capture, with the marker at `end`. The sketch tries keep it there, or at a
   rolled position just after the last item they need (`lib/export_plan/marker_roll.py`, "Sketch values that follow sizes" in section 5): the
   parameter store puts the marker back after every recompute and counts only the items before it for health
   (`lib/fusion_reader/rows.py`), and the temporary copy of a component body deletes only what it added
   (`lib/design_edit/temp_copy.py`). `report.json` records `marker` (`position`, `count`).

Reading inputs at the position before the item covers the getters that the reference says need
`timelineObject.rollTo(True)` (fillet `edges`, chamfer `edges`, extrude and revolve `profile`, `participantBodies`).

## 4. Sketch profiles (inside extrude and revolve data)

```json
"profiles": [
  {
    "sketch": "Sketch1",
    "frame": { "origin": [0, 0, 5], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1] },
    "space": "sketch",
    "loops": [
      { "outer": true, "curves": [ CURVE, ... ] },
      { "outer": false, "curves": [ CURVE, ... ] }
    ]
  },
  { "face": true, "type": "BRepFace", "surface": "Plane", "frame": { ... }, "space": "sketch", "loops": [ ... ],
    "token": "...", "face_point": [x, y, z], "body": { "token": "...", "name": "Body1" },
    "made_by": { "index": 3, "name": "Extrude3", "which": "end" } },
  { "text": true, "sketch": "Sketch2", "sketch_token": "...", "frame": { ... }, "space": "sketch", "loops": [ ... ] },
  { "text": true, "sketch": "Sketch2", "sketch_token": "...", "problem": "open" }
]
```

Optional keys that let the size probe find the sketch again (section 5, "Probe states"): `sketch_token`
(`Sketch.entityToken`) and `reference` (`{ "kind": "constructionPlane" | "face" | "plane" | "other", "token" }` from
`Sketch.referencePlane`; `token` is empty for a plane without one). Each curve also gets `entity`, the token of its
sketch curve (`ProfileCurve.sketchEntity.entityToken`). A key is left out when Fusion does not give it.

From `Profile.parentSketch.transform`, `Profile.profileLoops`, `ProfileLoop.isOuter`, `ProfileLoop.profileCurves`,
`ProfileCurve.geometry` and `ProfileCurve.geometryType`.

A flat face of a body used as the outline (`ExtrudeFeature.profile` is a `BRepFace`) is read by
`lib/fusion_reader/read_face.py` into a record shaped like a sketch profile, plus `"face": true`:

- `surface`: the type of `BRepFace.geometry` (`Plane`, `Cylinder`, `Cone`, `other`), null when it cannot be read. A
  face that is not a `Plane` has only `face`, `type` and `surface`.
- `frame`: the plane (`Plane.origin`, `Plane.uDirection` as `x`), with `z` the outward normal
  (`BRepFace.evaluator.getNormalAtPoint` at `pointOnFace`), in the target component's coordinates.
- `loops`: one entry per `BRepFace.loops` item (`BRepLoop.isOuter`, `BRepLoop.edges`), each edge's
  `BRepEdge.geometry` read as a CURVE in the face's 2D frame (`Line3D`, `Arc3D`, `Circle3D`, `Ellipse3D`). Any other
  curve (a NURBS edge) is sampled like a free sketch curve through `BRepEdge.evaluator`, so the samples stop at the
  edge's ends. `space` is `sketch`.
- `token` (`entityToken`), `face_point` (`pointOnFace`), `body` (`{ token, name }` of `BRepFace.body`).
- `made_by` (optional): the latest extrude before the step, of the face's component (`Component.features.
  extrudeFeatures`, `Feature.timelineObject.index`), whose `startFaces`, `endFaces` or `sideFaces` hold the face (the
  same entity, or the same `entityToken`), read with the marker before the step. `index` is that extrude's timeline
  index, `which` is `start`, `end` or `side`. At most 200 earlier extrudes are looked at.
- A face whose surface, plane or edges cannot be read has `"problem": "unread"` and no `frame` or `loops`.

The area of the face (`BRepFace.area`, mm2) is the record's entry in `areas` and the extrude's `profile_area`, and
`end_offset` and `side_leans` are measured along the face's `z`. A capture made before add-in 0.8.1 has
`{ "face": true, "type": "BRepFace" }` only; the translator refuses it and asks for a new export.

The translator (`lib/translator/face_outline.py`) copies an extrude of one such face, alone. When `made_by` names the
`start` or `end` face of an extrude step written earlier in the same walk, that step has no taper, `face_point` lies
on its start or end face and the face's edges lie on that step's outline and back (within 1e-3 mm), the step's written
outline is drawn again on a plane at that face: the plane's origin is the step's origin plus its length (times the
place of the face along it) along its direction, so it follows the sizes of that step. The face is compared only at
the measured sizes, so when any step was written or left out after that extrude, every size the steps written so far
read is marked loose: a later step may reach the face at other sizes. Any other flat face is written
from `loops` and `frame` as numbers, and every size the steps written so far read (every ticked size when the face
lies on a body this walk does not build) is marked loose with the reason. A tool body with such a step is written as a
tool step (`toolBody`), never step by step onto the part, since the part alone does not hold the tool's earlier
faces.

A `SketchText` is read from `SketchText.asCurves()` (transient curves; the text and the design are not changed): the
curves are chained into closed loops, and each loop is an outer outline or a hole by how many loops contain it (even
count: outer, odd: hole of the nearest loop around it). Each outer outline with its holes is one profile record like
the one above, plus `"text": true` and no curve `entity`: a text of "OI" with a hole in the "O" is two records. The
space of the points (sketch or model) is decided like for other profiles, except that the curves have no sketch entity:
the points are compared with `SketchText.boundingBox` (sketch space) and the record is a marker when both readings
fit or neither does. Every text record, outline or marker, carries `text_params` (the name of the text's height
parameter, `SketchText.heightParameter`) or `text_params_unknown: true` when Fusion does not give the name; the sizes
behind them are kept from following the copied letters. A text that cannot be turned into profiles is one record with
`text`, `sketch`, `sketch_token` and a `problem`: `unread` (no curves), `open` (the curves do not close), `overlap`
(two loops cross, as in a script font whose strokes overlap, so holes cannot be told from strokes), `space`,
`too_many` (over 4000 curves or 400 outlines) or `foreign` (a text of another component). The translator refuses a marker with its own reason
(`loops.TEXT_PROBLEMS`), and every size that moves the sketch of a text stays loose or is left out, since the size
probe does not follow it.

`space` says how the curve space was decided: `sketch` or `model` (the reader mapped model space curves into sketch
2D) or `ambiguous`. A curve off the plane z = 0 proves model space. Points all at z = 0 that do not lie on one line
prove sketch space when the sketch plane is not the plane z = 0 (model points on such a plane cannot all have
z = 0). In the plane z = 0 with a sketch frame other than the identity, the reader compares the curve with
`ProfileCurve.sketchEntity`; if that cannot decide it writes `ambiguous` and the translator refuses the profile. A
loop whose chained curves enclose no area is refused.

A profile of another component's sketch (Fusion hands it over through that component's occurrence) is read from its
`nativeObject`, so `loops` are in that sketch's own 2D frame, and it keeps `"foreign": true`. It adds:

- `native_frame`: the sketch frame in its own component's coordinates;
- `frame`: the same frame brought into the target's coordinates through the assembly (that component's `placement`,
  then the inverse of the target's), only when both places can be read;
- `component`: `{ token, name }` of the sketch's component;
- `placement`: like the target's placement (section 2), read for the occurrence the profile came through. Its point
  check compares `SketchPoint.worldGeometry` of up to three native sketch points with the same points made for the
  occurrence (`SketchPoint.createForAssemblyContext`). Without a match it holds `error` and no `frame`;
- `sketch_params`: one `{ name, expression, reads }` per sketch dimension (`Sketch.sketchDimensions`,
  `SketchDimension.parameter`), where `reads` lists every parameter it reads, directly or through others
  (`dependencyParameters`).

The translator copies such a profile like its own when `frame`, `native_frame` and `placement.frame` are present
(`lib/translator/borrowed.py`). The size probe reads the sketch at every state (section 5, "Probe states"), so the
outline follows the sizes through the motion file under the usual keys (`<item>/p<profile>/...`). Where the motion
holds no value for the profile, the outline is written as numbers and every size that `sketch_params` read becomes a
fixed number; the first translation of an export (no sizes fixed for sketches) skips that. The step gets a note that
names the sketch and its component. Without the frames and the place the step is refused as before.

Nothing ties such a step to the walls of the part, so it must keep meeting the part as measured
(`lib/translator/meets_part.py`): along the normal of each of its faces, the nearest flat parallel faces of the part
within 2 mm keep their side of the face at every size setting of the range (every mix of the ends for up to 6
sizes, a bounded sample past that), and a face that lies on a wall stays on it. Where a gap would close or open, the sizes it reads stay free over
their ranges and are listed in `loose`, with the values past which the step may stop meeting the part ("past 2.05",
"below 0.98"). Those values come from `lib/translator/kept_ranges.py`, which finds, without changing any range, the
values up to which the gaps keep their side (each size alone first, then all together); when that value would be the
size's own value or the person typed the range, no value is given and the size cannot follow (`Context.doubt`, listed
in `loose` without one).

CURVE, in sketch 2D mm, in the order Fusion lists them (not chained, not oriented):

| Fusion geometry | Dict |
|---|---|
| `Line3D` (`startPoint`, `endPoint`) | `{ "kind": "line", "start": [x, y], "end": [x, y] }` |
| `Arc3D` (`center`, `radius`, `startPoint`, `endPoint`) | `{ "kind": "arc", "start", "end", "mid", "center", "radius" }`; `mid` from the evaluator at the middle parameter |
| `Circle3D` (`center`, `radius`) | `{ "kind": "circle", "center", "radius" }` |
| `Ellipse3D` (`center`, `majorAxis`, `majorRadius`, `minorRadius`) | `{ "kind": "ellipse", "center", "major_dir": [x, y], "major_radius", "minor_radius" }` |
| `EllipticalArc3D`, `NurbsCurve3D`, other | `{ "kind": "other", "type": "NurbsCurve3D", "start", "end", "mid", "samples": [[x, y], ...], "tangent_start", "tangent_end" }` |

A free curve is read as a dense polyline: 16 equal parameter spans, each split at its middle parameter until the middle
point lies within 0.0005 mm of the chord, at most 800 points (`truncated: true` when the cap stopped the splitting or
when the chords do not add up to the curve's own length, and the translator then refuses the curve). `start`, `end` and `mid` are samples. `tangent_start` and `tangent_end` are unit
directions of the curve at its ends (`CurveEvaluator3D.getTangent`), left out when they cannot be read; the recipe's
spline segment has no tangent field, so they are for checks only. A curve that cannot be evaluated has `samples: []`.
The translator fits the app's spline through points chosen from the samples (`lib/translator/spline_fit.py`, tolerance
0.005 mm between the points, also where the curve runs between two samples, at most 64 points inside one segment, split into several segments past that, at most 1000 points in a loop).

## 5. Feature data

**ExtrudeFeature** (`operation`, `profile`, `extentType`, `hasTwoExtents`, `extentOne`, `extentTwo`,
`symmetricExtent`, `startExtent`, `taperAngleOne`, `taperAngleTwo`, `isThinExtrude`, `participantBodies`,
`endFaces`):

```json
{
  "operation": "join",
  "profiles": [ ... ],
  "start": { "kind": "profilePlane" },
  "extent_type": "one",
  "side_one": EXTENT,
  "side_two": null,
  "symmetric": null,
  "thin": false,
  "participants": [{ "token": "...", "name": "Body1" }],
  "target_box_before": { "min": [..], "max": [..] },
  "end_offset": 10.0
}
```

- `operation`: `join`, `cut`, `intersect`, `newBody`, `newComponent` (from `FeatureOperations`). A new body from
  several profiles is copied only when `bodies_after` lists one body (the profiles touch).
- `profiles`: section 4. A flat face of a body as the outline is a face record (section 4); the extrude's own
  length, taper and operation are read and followed as for a sketch outline.
- `start`: `{ "kind": "profilePlane" }`, `{ "kind": "offset", "offset": mm }` (`OffsetStartDefinition.offset`),
  `{ "kind": "fromEntity", "plane": PLANE or null, "entity_type": "...", "face_point": [..] }`
  (`FromEntityStartDefinition`, TARGET below).
- `extent_type`: `one`, `two`, `symmetric`.
- EXTENT: `{ "kind": "distance", "distance": mm, "taper_deg": d }` (`DistanceExtentDefinition.distance`, the value
  as Fusion stores it, sign kept), `{ "kind": "throughAll", "positive": bool, "taper_deg": d }`
  (`ThroughAllExtentDefinition.isPositiveDirection`), `{ "kind": "all" }`, `{ "kind": "toEntity", "plane": PLANE or
  null, "offset": mm, "entity_type": "...", "face_point": [..] }` (TARGET below), `{ "kind": "other", "type": "..." }`.
- TARGET (the face or plane of a from or to entity): `plane` from the entity's `geometry` (its origin need not lie on
  the face), `entity_type` the entity's type name (`BRepFace`, `ConstructionPlane`, or null), and for a face
  `face_point` (`BRepFace.pointOnFace`) and `body` (`{ token, name }`, the body it lies on). These keys are optional;
  without `face_point` the translator cannot tell whether the face moves with sizes, and without `body` a step of a tool
  body cannot tell a face of the tool from a face of the part at the same place. For a `ConstructionPlane` or `ConstructionAxis` the record also has `token`
  (`entityToken`), which names the model parameters behind it (`created_by.token`).
- `symmetric`: `{ "distance": mm, "full_length": bool, "taper_deg": d }`
  (`SymmetricExtentDefinition.distance`, `isFullLength`, `taperAngle`).
- `target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet.
- `end_offset`: signed distance along the first profile's sketch `z` from its sketch plane to
  `endFaces[0].pointOnFace`, or null. The measured check of the direction and, for one side, symmetric (half
  length) and two sided extrudes, of the length: the translator refuses when `abs(end_offset - start shift)` is not
  the planned length within 1e-3 mm. A one sided cut that ends past the whole `target_box_before` makes no end face
  of its own, so a nearer measured end is not checked there. A two sided extrude has faces on both sides of its
  sketch, so the measured face turns its direction only when it lies out of reach of the stored one.
- `side_leans` (optional): per face of `ExtrudeFeature.sideFaces` (at most 256), the outward normal at
  `pointOnFace` along the first profile's sketch `z`, which is the sine of how far that wall leans. The taper check:
  a wall that narrows away from the sketch leans its outward normal along the travel; a cut lists the part's walls,
  which face the other way. Every measured wall must match a side of the plan (within 1e-4), and each tapered side
  must have a wall that shows it, else the translator refuses.
- `thin_wall` (only when `thin` is true): `{ "location", "thickness", "location_two", "thickness_two",
  "profile_type" }` from `thinExtrudeWallLocationOne` and `thinExtrudeWallLocationTwo` (`ThinExtrudeWallLocation`:
  `side1`, `side2`, `center`, else `other`; null when unreadable), `thinExtrudeWallThicknessOne` and
  `thinExtrudeWallThicknessTwo` (mm, null when unreadable) and the type name of `ExtrudeFeature.profile` (an open
  line shows here and as `{ "kind": "other", "type": ... }` in `profiles`). The thickness of side one also names its
  parameter as `params["thin.thickness"]`. The translator copies one closed outline without holes, one way or
  symmetric, without a taper. Side one and side two are not taken for inside and outside (the API does not say):
  `end_area`, the area of the wall's end face, is compared with the expected area of each side of the outline,
  worked out from its lengths and corners, and decides the side. The area is used rather than the volume change
  because a wall that joins or cuts an existing part overlaps it, while the end face stays the wall's cross section.
- `profile_area`, `end_area` (optional, mm2): the area of the first profile and of `endFaces[0]`. Without
  `side_leans`, a tapered extrude of one outline is checked by them (the end face must be smaller for a positive
  recipe taper); a tapered extrude of several outlines is refused. Fusion's positive taper widens the walls (the
  recipe's positive `taperDeg` narrows them), so the translator writes Fusion's angle with the other sign.
- `areas`, `volume_before`, `volume_after` (only when the outlines hold sketch text or a free curve): `areas` as for an
  emboss (one entry per profile record; the area the reader worked out for text, `Profile.areaProperties` for a
  spline), and the volume in mm3 the part had before and after the item: the target's, or for a new body 0 and the
  summed volume of `ExtrudeFeature.bodies`. The translator expects a new body to have exactly the outline area times
  the length; a join or cut may lose volume to material it overlaps, so it only refuses a change larger than that or in
  the wrong direction. A taper, through all, thin and intersect are not checked. A capture without these keys (made
  before they were read) is not checked.
- Profiles of one extrude that share a sketch curve are merged into one outline with holes before they are copied
  (`lib/translator/outlines.py`), since Fusion extrudes and tapers their whole region at once. Outlines that stay
  apart are written so that each step touches what is already built (the part, or an outline written before it).
- `bodies_before` (optional, on any item): root bodies at the marker before the item. With it the driver finds a
  body the item made or split off (refused); without it the driver compares `bodies_after` with the bodies the item's
  data names (`participants`, `tools`, `target`).

**RevolveFeature** (`operation`, `profile`, `axis`, `isProjectAxis`, `extentDefinition`, `startFaces`):

```json
{
  "operation": "newBody",
  "profiles": [ ... ],
  "axis": { "point": [..], "dir": [..] },
  "project_axis": false,
  "extent": { "kind": "angle", "angle_deg": 360, "symmetric": false },
  "participants": [ ... ],
  "start_face_normal": null
}
```

- `axis` from a `SketchLine` (`worldGeometry`), a `ConstructionAxis` (`geometry`, an `InfiniteLine3D`), a linear
  `BRepEdge` (`geometry`, a `Line3D`) or a cylindrical `BRepFace` (`geometry`, a `Cylinder`); else `{ "kind":
  "other", "type" }` with the entity type, plus `geometry` (the curve or surface type) for an edge or face, or `error`
  when reading the revolve axis raised. The translator's refusal says which of these the axis is. An axis from a sketch line also has `entity` (the line's token), `sketch_token` and `sketch` (the
  sketch's token and name); one from a construction axis has `token`. Circular pattern axes are read the same way.
- `extent`: `{ "kind": "angle", "angle_deg", "symmetric" }` (`AngleExtentDefinition.angle`, `isSymmetric`),
  `{ "kind": "twoSidesAngle", "angle_one_deg", "angle_two_deg" }`, `{ "kind": "other", "type" }`.
- `start_face_normal`: outward normal of `startFaces[0]` at its `pointOnFace` (surface evaluator), or null for a
  full turn. The measured check of the turning sense.

**HoleFeature** (`holeType`, `holeTapType`, `holeDiameter`, `tipAngle`, `counterboreDiameter`, `counterboreDepth`,
`countersinkDiameter`, `countersinkAngle`, `position`, `direction`, `extentDefinition`, `holePositionDefinition`,
`sideFaces`, `endFaces`, `thread`):

```json
{
  "hole_type": "simple",
  "tap_type": "simple",
  "thread_modeled": null,
  "diameter": 5.0,
  "tip_angle_deg": 118,
  "counterbore": null,
  "countersink": null,
  "direction": [0, 0, -1],
  "positions": [[10, 10, 10]],
  "extent": { "kind": "distance", "depth": 8.0 },
  "side_cylinders": [{ "origin": [..], "axis": [..], "radius": 2.5 }],
  "end_points": [[10, 10, 2.0]],
  "end_face_types": ["cone"],
  "participants": [ ... ]
}
```

- `hole_type`: `simple`, `counterbore`, `countersink`. `tap_type`: `simple`, `clearance`, `tapped`,
  `taperTapped`. `thread_modeled`: `thread.isModeled` for a tapped hole, else null.
- `counterbore`: `{ "diameter", "depth" }`; `countersink`: `{ "diameter", "angle_deg" }`.
- `positions`: one point per `SketchPointsHolePositionDefinition.sketchPoints` item (`worldGeometry`), else
  `[position]`. Points of another component's sketch are brought into the target's coordinates; such a hole gets
  `position_refs` (one measured reference per point, slot `positions.<n>`) and no `sketch_token`, `sketch` or
  `point_tokens`, so the size probe leaves the sketch alone. When a point cannot be brought in, the hole is marked
  `foreign`. A hole placed on a face, plane or edge of another component (the `planarEntity`, `edge`, `face` and similar
  members of the position definition) is marked `foreign` and carries `position_refs` too.
- `sketch_token`, `sketch` (optional): token and name of the sketch of the first sketch point.
  `point_tokens` (optional): `entityToken` of each sketch point, same order as `positions`; absent when a token is
  missing or the points sit on more than one sketch.
- `extent`: `{ "kind": "distance", "depth" }`, `{ "kind": "throughAll" }` (also for the `All` kind), `{ "kind":
  "toEntity" }`, `{ "kind": "other" }`.
- `side_cylinders`: every `sideFaces` item whose geometry is a `Cylinder` (`origin`, `axis`, `radius`).
  `end_points`: `pointOnFace` of each `endFaces` item. `end_face_types`: the geometry type of each of those faces
  (`"plane"` or `"cone"`; `null` when the type is another one or cannot be read), one per `end_points` entry; a flat or
  tipped bottom is decided from it, not from `tip_angle_deg`. Measured checks of direction, count and diameter.

**FilletFeature** (`edgeSets`, `isRollingBallCorner`):

```json
{
  "rolling_ball": true,
  "sets": [
    {
      "kind": "constant",
      "radius": 2.0,
      "continuity": "tangent",
      "input_kinds": ["edge"],
      "tangent_chain": true,
      "edges": [EDGE, ...],
      "faces": [{ "token": "...", "point": [..] }]
    }
  ]
}
```

- `kind`: `constant` (`ConstantRadiusFilletEdgeSet`: `radius`, `edges`, `isTangentChain`, `continuity`),
  `variable`, `chordLength`, `asymmetric`, `other`.
- The reader expands the input: a face gives its `BRepFace.edges`; a tangent chain gives
  `BRepEdge.tangentiallyConnectedEdges`. A feature as input is listed in `input_kinds` as `feature` and not
  expanded.
- How the set picked its edges: `tangent_chain` is `isTangentChain`; with it on, each EDGE that was an input of the
  set (not one the chain added) has `"seed": true`. `faces` lists the face inputs, as the shell's `faces` records
  (`point` is `BRepFace.pointOnFace`); it is absent when the set has no face input or a face cannot be read. Captures
  of add-in 0.5.0 and older have none of these keys.
- EDGE: `{ "token", "closed": bool, "points": [[..]] }`. `points` holds the middle point for an open edge and the
  points at 0.25 and 0.75 of the parameter range for a closed edge (`startVertex` equal to `endVertex`), from
  `BRepEdge.evaluator`.

**ChamferFeature** (`edgeSets`, `cornerType`):

```json
{ "corner_type": "chamfer", "sets": [{ "kind": "equal", "distance": 1.0, "edges": [EDGE, ...] }] }
```

`kind`: `equal` (`EqualDistanceChamferEdgeSet.distance`), `twoDistances` (`distanceOne`, `distanceTwo`,
`isFlipped`, as `distance`, `distance_two`, `flipped`), `distanceAngle` (`distance`, `angle`, `isFlipped`, as
`distance`, `angle_deg`, `flipped`), `other`. Edges expanded as for fillets.

The API does not say which face of an edge takes the first distance (`isFlipped` only swaps them, and is reported
as unreliable). For `twoDistances` and `distanceAngle` sets each EDGE also gets, per point in `points`:

- `sides` (before the item): `[[a], [b]]`, the outward normals of the edge's two faces (`BRepEdge.faces`,
  `SurfaceEvaluator.getNormalAtPoint`) at the point;
- `cut_normals` (after the item): the normal of the chamfer face nearest to the point (`ChamferFeature.faces`;
  `getParameterAtPoint`, `getPointAtParameter`, `isParameterOnFace`, `getNormalAtParameter`), a face whose nearest
  point lies on it first.

The chamfer face normal is `d1 * a + d2 * b` (normalized) when `d1` lies on face `a` and `d2` on face `b`, for any
angle between the faces, so the ratio of its two weights names the face of the first distance (for a distance and
an angle, the second distance is taken as `distance * tan(angle)`). An edge without these keys, or whose weights fit
neither way, refuses an uneven chamfer.

**ShellFeature** (`inputEntities`, `insideThickness`, `outsideThickness`, `isTangentChain`, `shellType`):

```json
{ "faces": [{ "token": "...", "point": [..] }], "bodies_input": false, "inside": 2.0, "outside": 0.0, "shell_type": "sharp" }
```

`faces[].point` is `BRepFace.pointOnFace`; tangent chains expanded with `tangentiallyConnectedFaces`;
`bodies_input` true when the input is a body (a closed hollow). `shell_type`: `sharp` or `rounded`.

**RectangularPatternFeature** (`patternEntityType`, `inputEntities`, `directionOne`, `directionTwo`,
`quantityOne`, `quantityTwo`, `distanceOne`, `distanceTwo`, `patternDistanceType`, `isSymmetricInDirectionOne`,
`isSymmetricInDirectionTwo`, `patternElements`, `suppressedElementsIds`):

```json
{
  "entity_type": "features",
  "sources": [4, 5],
  "direction_one": [1, 0, 0], "quantity_one": 3, "distance_one": 20.0,
  "direction_two": null, "quantity_two": 1, "distance_two": 0.0,
  "distance_type": "spacing",
  "symmetric_one": false, "symmetric_two": false,
  "elements": [{ "id": 1, "suppressed": false, "frame": FRAME }, ...],
  "suppressed_ids": []
}
```

- `entity_type`: `features`, `faces`, `bodies`, `occurrences`. `sources`: `timelineObject.index` of each input
  feature. A Combine of the target among the sources is repeated by the steps it wrote (its `toolBody` step, or its
  tool's steps written one by one) when every item that built its tools is a source too (`repeat._combined_tools`;
  the same holds for a circular pattern and a mirror of features). Only some of those items, the items of a tool
  without its Combine, or an intersect Combine refuse the pattern.
- For `entity_type: bodies` (rectangular and circular patterns, and the mirror below) the item also has
  `source_bodies` and `result_bodies`: each a list of body records with `points` (see "Body records" below).
  `source_bodies` come from `inputEntities` with the marker before the item, `result_bodies` from `bodies` with the
  marker after it (null when they cannot be read). `PatternElement` has no `bodies` member, so the translator matches a
  copy to its source and element by the points.
- `distance_type`: `spacing` or `extent` (enum `PatternDistanceType`), `other` when unreadable. The translator then
  takes the kind whose grid holds every kept element.
- `elements`: every `PatternElement` (`id`, `isSuppressed`, `transform` as a frame). The original is the element with
  the identity frame; in a symmetric direction it is not the first one.
- `symmetric_one`, `symmetric_two`: the copies spread to both sides of the original along that direction (false when
  the flag cannot be read). In a symmetric direction an `extent` distance is the reach to each side, so the step is
  `2 * distance / (count - 1)`; a `spacing` distance is the step as usual.
- `direction_one_sketch`, `direction_two_sketch` (optional): `{ "sketch_token", "sketch" }` when that direction is a
  sketch line, so the sketch is known to feed a pattern.
- `direction_one_place`, `direction_two_place` (optional): a direction taken from an axis, edge or face of another
  component. The entity is seen in the root's coordinates, so its direction is turned into the target's
  (`direction_one` holds the result) and the place is `{ "assembly": true, "dir": [..], "ref": REF }` (slot
  `direction_one` or `direction_two`, see "Measured references"). When the direction cannot be brought in, `direction_*`
  is null and the place is `{ "foreign": true, "ref": REF }`, so the pattern is refused. The sketch of a foreign sketch
  line is not named in `direction_*_sketch`.

**CircularPatternFeature** (`inputEntities`, `axis`, `quantity`, `totalAngle`, `isSymmetric`, `patternElements`,
`suppressedElementsIds`):

```json
{ "entity_type": "features", "sources": [4], "axis": AXIS, "quantity": 6, "total_angle_deg": 360, "symmetric": false, "elements": [...], "suppressed_ids": [] }
```

`symmetric` (circular): the copies turn to both sides of the original. It matters for a part turn only; on a full
circle the copies are the ordinary full circle.

**MirrorFeature** (`inputEntities`, `mirrorPlane`, `isCombine`):

```json
{ "entity_type": "features", "sources": [4], "plane": PLANE, "combine": false, "target_box_before": { "min": [..], "max": [..] } }
```

The mirror `plane` and the circular pattern `axis` also say what they are, so the translator can tell whether sizes move
them (`lib/fusion_reader/read_reference.py`). All keys below are optional and are added next to the plane or axis keys
(`point`, `normal` or `dir`, `token`); a record of another component gets none.

- `origin`: true for an origin plane or axis of the component. Nothing else is read then; it never moves.
- `entity_type`: the type name of the picked entity (`BRepFace`, `BRepEdge`, `ConstructionPlane`, `ConstructionAxis`).
- `face_point` and `surface` (`Plane`, `Cylinder`, ...) of a face; `edge_points` of an edge; `body` (`{ token, name }`),
  the body either lies on, left out when Fusion does not give it.
- Construction geometry also has `token`, `made_by` (the timeline index of the feature that made it), `definition` (the
  type name of how it is defined) and `built_on`, a list of the same descriptions for the entities that definition
  names (own component only, up to three levels deep).

A reader that cannot read one of these leaves it out, and the plane or axis then stays where it was measured.

`target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet (as
for extrudes).

`plane` from a `ConstructionPlane` (`geometry`, a `Plane`: `origin`, `normal`) or a planar `BRepFace`
(`geometry`). A construction plane adds `token`.

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

Optional `volume_before` and `volume_after` (mm3) hold the volume of the target with the marker before and after the
Combine (`read_geometry.target_volume`; null when it cannot be read). When both are present the translator refuses a Combine that changes the part by more than its tool steps can
fill (`combine_volume.py`). Each tool also has `volume` (mm3, null when unreadable), read with the marker before the
Combine.

An intersect of two or more tools has `intersect_volumes` and `intersect_model`. Fusion's help does not say whether the
result keeps the part and every tool or the part and any tool. `combine_before` copies the part and the tools with
`TemporaryBRepManager` (temporary bodies, nothing is added to the design) and measures two volumes in mm3:
`{ "every": part AND each tool in turn, "any": part AND the union of the tools }` (null when no manager was available
or a tool is of another component, whose coordinates differ). Each candidate is measured on its own and is null when
it cannot be measured; a temporary intersect that reports failure counts as empty, 0. `combine_after` compares them with
`volume_after`: `intersect_model` is `every`, `any` or `unknown` (no match, a volume missing, or `intersect_volumes`
null). Volumes match within 1e-3 mm3 or 1e-6 of the larger. When the two candidates are equal the model is `every`, and
the translator marks the sizes the tools read, since the capture cannot show which rule Fusion used; the same goes for
a candidate that is null. A Combine inside a tool works out the model again in the translator (`tool_walk`), from
the volume of that tool in `body_states`, since `volume_after` here is the exported body's.

The translator walks each tool body on its own (`tool_walk.build`): the items that made it run through the normal item
loop in a child context whose target is the tool, so every handler sees the tool as its body. A step that cannot be
copied stops that walk, and the Combine is refused with the reason naming the tool, the step and what stops it.

- A tool whose steps only add material (`combine.adds_only`: `ExtrudeFeature` and `RevolveFeature` items whose recipe
  steps are `new` for the first and `add` for the rest) is written step by step at the Combine's place with the
  Combine's operation, as long as no tool step reaches to a face when the tool has more than one step or lives in
  another component. An intersect does this only for one tool of one step. The recipe stays at the version it had before tool steps existed.
- Any other tool is written as one `toolBody` step per tool, whose `features` are the tool's steps and whose `combine`
  is the Combine's operation. Its steps are those of rounds, chamfers, cuts, holes, shells, a Combine of the tool
  itself, `move` steps, and a pasted or patterned body (the steps of the source written again).
- Tool bodies nest 3 levels deep (`tool_walk.MAX_DEPTH`); deeper refuses.
- An intersect with several tools has the model `every` (one `toolBody` per tool, each `intersect`) or `any` (one
  `intersect` step that holds the tools as inner steps, the first `new` and the rest `add`); `unknown` refuses.
- A pattern or mirror of bodies that the Combine takes whole is written as a `pattern` or `mirror` step over the tool
  steps (`body_copies.groups`, `write`); a subset of the copies, or a layout `repeat.py` refuses, is one tool per copy
  with a `move`. An intersect never uses the pattern form. A size the count reads is marked, since it is not known
  whether Fusion adds new copies to the Combine (hand test B6); spacing and angle follow without a mark.
- A later pattern or mirror of features may hold the Combine and the items that built its tools as sources; it then
  repeats the steps the Combine wrote (see RectangularPatternFeature above, hand test F2).
- A Combine whose result differs from the tools' own volumes by more than they can give (`combine_volume.exceeds_tools`
  for tool steps, `exceeds` for steps written one by one) is refused.
- A tool the Combine keeps (`keep_tools`) stays usable: a later Combine walks it again up to its own index. A tool
  the Combine does not keep is used up, and a second Combine that lists it is refused. A Combine that keeps the
  exported body as a tool and changes another body is skipped.
- A tool is refused when a step its walk cannot see may have changed it (`tool_walk.unseen_change`): a step of another
  component that lists it, or a step that lists its name under another token after the tool first appears.
- A Combine inside a tool of another component that takes a tool of yet another component is refused: the place of
  that tool is read against the exported body, not against the component that holds the Combine.

A tool body of another component is `foreign` and names where to find it:

```json
{ "token": "<native token>", "name": "Body2", "foreign": true,
  "component": { "token": "...", "name": "Rod" }, "path": "Rod:1", "place": TOOL PLACE }
```

`token` is the native body's (the one `bodies_after` of the steps that made it give), `component` the component that
owns it, `path` the `fullPathName` of the occurrence the tool is seen through (empty for a tool in the root). Without
`component` the Combine stays refused ("in another component").

TOOL PLACE (`placement.tool_place`, read with the marker just before the Combine, since the places of the two
components at that moment shape the result):

```json
{ "path": "Rod:1", "frame": FRAME, "source": "transform2", "checked_points": 3, "target_frame": null,
  "xy": { "ref": REF }, "xz": { "ref": REF }, "yz": { "ref": REF } }
```

- `frame` maps the tool component's coordinates to the root's. It is checked like the target's placement, with the
  points 10 mm along the normals of the component's three origin planes (native against shown through the occurrence),
  since a body proxy is not needed for that. A tool in the root has `source: "root"` and the identity frame.
- `target_frame` is the same for the exported body's component at that moment, `null` for a body of the root;
  `target_error` replaces it when it could not be read. `{ "path", "error" }` replaces the whole record when the tool
  component's place could not be read (the tool body or the occurrence was not found, the frame did not land the
  planes, a plane could not be shown).
- `xy`, `xz`, `yz` hold a measured reference (section "Measured references") of the origin plane, slot
  `tool<n>.<plane>` (`n` is the tool's place in `tools`), with `point` and `normal` in the exported body's
  coordinates. The size probe reads them again at other sizes; they only move with the component's occurrence.

The steps that made a foreign tool are read in a second pass (`lib/fusion_reader/helper_pass.py`) after the main walk,
with the same feature readers and a `ReadContext` whose target is the tool body, so the tool component's own sketches,
planes and faces are not `foreign` and every value is in that component's coordinates. Only the items that
`translator/tool_items.py` picks are rolled to: the modeling steps before the Combine whose `bodies_after` list the tool
and that sit in the tool's component. Tools of the target's own component are planned the same way: their items are
already read, and only `body_states` is added. The plan follows the bodies behind a tool: the source of a Paste
(`sources`), the source bodies of a pattern or mirror of bodies (`source_bodies`) and the tools of a Combine that
changed the tool. A body held by several items is followed up to the latest of them, so steps added to a kept tool
between two Combines are read. Limits: `MAX_ITEMS` 120 steps for the whole capture, `MAX_TOOLS` 32 bodies counted by distinct
sources (the copies of a Paste or a body pattern count as their source, so a pattern of many copies is one), and
source depth 3 (`tool_items.MAX_DEPTH`). Each item of another component gets `helper_of` (the body's token) and
`bodies_before` of its component; their `in_target_component` stays false. An item past a limit keeps its data (empty
for another component) and gets `helper_unread` with the limit as the reason; a body of another component past the
tool limit has `place: { "error": reason }`. An item whose body or place could not be read keeps `data: {}` and gets
`helper_unread` too. A Paste source or pattern source of another component carries `foreign`, `component`, `path` and
`place` like a tool does (the place is read with the marker just before the item that holds it, slot `tool<n>.<plane>`
with `n` its place in that item's list). The model parameters of the tool component and the components above it are
added to `parameters.model` (names already listed win).

The translator walks the steps of a `helper_of` item when a Combine takes its tool (`tool_walk.build`), like those of
another body of the target's component. The Combine moves them by the tool's frame and the inverse of the exported body's own
(`combine.tool_move`), plus a move that follows sizes: the offsets of the three origin planes along their normals
(`ref_motion.moves`, formulas of the sizes, or sizes marked loose where the probe could not follow, as for any
reference). A frame that is scaled or mirrored refuses the Combine, naming the component. Slabs of the moved steps are
copied with that move, so picks on them follow sizes; other placers (`moved_placer.py`) answer `material_at` for the
moved points and cannot place a pick on their faces.

**CopyPasteBody** (`sourceBody` with the marker before the item, `bodies` after it):

```json
{ "sources": [ BODY WITH POINTS ], "result_bodies": [ BODY WITH POINTS ] }
```

`sourceBody` is an `ObjectCollection`: `sources` has one record per body in it, and a single body is accepted too. It
is empty or shorter when a source is gone or cannot be read. A source of another component is `foreign` and has the
identity keys of a foreign tool. `result_bodies` is null when `bodies` cannot be read.

The handler (`translator/paste.py`) walks the source up to the paste (`tool_walk.build`) and writes its steps again,
with ids of their own, in the list of the pasted body. It needs as many sources as results, a result among
`result_bodies`, and a pasted body that has no steps yet. Several sources are paired with the results by their points:
one at the same place first, else one rigid move apart; a result with no single source refuses. The first vertices of source and result must be the same points (a paste in place) or one
rigid move apart (`move.fit`); then a `move` step in plain numbers follows, and the sizes that could change that place
are marked.

**MoveFeature** (`inputEntities`, `definition`, with the marker before the item and again after it):

```json
{ "input_kind": "bodies", "bodies": [BODY], "move_type": "translateXYZ",
  "points_before": [[[x, y, z], ...]], "points_after": [[[x, y, z], ...]],
  "translate": [dx, dy, dz], "is_design_space": true, "params": { "translate.0": PARAM } }
```

- `input_kind`: `bodies`, `faces` or `other` (mixed or unreadable inputs). `bodies` is empty unless the kind is bodies.
- `move_type`: from the class of `definition`: `translateXYZ`, `rotate`, `free`, `pointToPoint`, `pointToPosition`,
  `alongEntity` (translate along entity), else `other`.
- `points_before`, `points_after`: per body in `bodies`, its first vertex points in the body's own coordinates and
  vertex order; `points_after` is found again by token with the marker after the item and is empty for a body that
  cannot be found. The translator fits the rigid move from them.
- `translateXYZ`: `translate` is the three distances in mm (`xDistance`, `yDistance`, `zDistance`; null for one that
  cannot be read), `is_design_space` from `isDesignSpace` (null when unreadable). Params paths: `translate.0`,
  `translate.1`, `translate.2`.
- `rotate`: `angle_deg` (null when unreadable), `axis` (an axis record with what it is, as for a circular pattern; the
  axis comes from `axisEntity`, `{ "kind": "other" }` when unreadable). Params path: `angle_deg`.
- `free`: `transform` as a frame from `transform` of the definition (null when it cannot be read).
- `alongEntity`: the points, and in `params` the parameter of `distance` (path `distance`).
- `pointToPosition`: the points, and in `params` the parameters of `xDistance`, `yDistance`, `zDistance` (paths
  `translate.0`, `translate.1`, `translate.2`).
- `pointToPoint` carries only the points.

The handler (`translator/move.py`) writes a `move` step in the walk of the body it moves, and refuses a Move of faces
and one that does not map the measured points rigidly (a mirror or a scale). `translateXYZ`, `rotate` and `free` must
agree with the measured points, and `translateXYZ` and `rotate` write their distances and angle through the sizes. The
other types are written as the numbers of the fit. What they follow can move with any size, so every ticked size is
marked, and the parameters in their `params` are pinned. After the step the walk's
placers are carried by the move, so later picks follow sizes.

Body records (`lib/fusion_reader/read_bodies.py`): `{ "token", "name" }`, `foreign` and the identity keys of a foreign
tool for a body of another component, and `points`: up to 8 vertices in mm of the native body, in the body's vertex
order (empty when one cannot be read, since a gap would shift the order).

**ThreadFeature**: `{ "modeled": bool }` (`isModeled`).

**OffsetFacesFeature** (press pull; `inputFaces` (a list or a collection), else `faces`, read before the item;
`distance`; `faces` after it. When no face is readable before the item, `faces` holds the flat faces of
`feature.faces` read after it, moved back by `distance`):

```json
{
  "distance": 2.0,
  "faces": [
    { "token": "...", "frame": FRAME, "space": "sketch", "loops": [LOOP, ...], "sides": "square", "meets_offset": false }
  ],
  "faces_after": [{ "point": [x, y, z], "normal": [x, y, z] }]
}
```

- `distance`: mm, positive along the outward face normal.
- `faces[]`: a flat face as a profile record (section 4): `frame` is the face plane with `z` the outward normal
  (`SurfaceEvaluator.getNormalAtPoint`) and `x` the plane's `uDirection`; `loops` from `BRepFace.loops`
  (`isOuter`, `edges`, each `edge.geometry` mapped into the frame). A face that is not a plane is
  `{ "kind": "other", "type": "Cylinder" }`.
- `sides`: `square` when every face next to it (`edge.faces`) is a plane across it or a cylinder along its normal,
  else `other`. `meets_offset`: a face next to it is moved by the same step.
- `faces_after`: a point and the outward normal of each flat face of `feature.faces` with the marker after the item.
  The translator copies a face only when one of them lies on the face plane moved by `distance`; each face becomes an
  extrude of its outline (join outwards, cut inwards).

**EmbossFeature** (`profiles`, `inputFaces`, `faces`, `isTangentChain`, `depth`, `horizontalDistance`,
`verticalDistance`, `rotationAngle`; `adsk.fusion.EmbossFeature` is marked preview in the API reference):

```json
{
  "profiles": [ ... ],
  "areas": [304.0],
  "faces": [{ "entity_type": "BRepFace", "surface": "Plane", "plane": PLANE, "outward": [0, 0, 1],
              "face_point": [30, 20, 4] }],
  "tangent_chain": true,
  "tangent_faces": [{ "surface": "Cylinder", "plane": null }],
  "made_surfaces": ["Plane", "Plane"],
  "depth": 1.0,
  "offset_x": 0.0, "offset_y": 0.0, "rotation_deg": 0.0,
  "participants": [{ "token": "...", "name": "Body1" }],
  "target_box_before": { "min": [..], "max": [..] },
  "volume_before": 9600.0,
  "volume_after": 9904.0,
  "end_offset": 1.0,
  "end_area": 304.0
}
```

- `profiles`: sketch profile records (section 4), including the outline records of a `SketchText`. `areas` holds
  `Profile.areaProperties` of each, in mm2; for a text record it is the area of its outlines (outer less holes),
  computed by the reader, null for a text marker.
- `faces`: the `inputFaces` the outline lands on. `surface` is `Plane`, `Cylinder`, `Cone` or `other` (from
  `BRepFace.geometry`); `plane` (origin and normal of the geometry), `outward` (`getNormalAtPoint` at `pointOnFace`) and
  `face_point` are null when they cannot be read. `participants` are the bodies of these faces.
- `depth`: mm, as Fusion stores it. There is no emboss or deboss flag: the sign decides (assumed: positive raises the
  outline, negative sinks it; hand test E1 and E2). `offset_x`, `offset_y` (`horizontalDistance`,
  `verticalDistance`, mm) and `rotation_deg` (`rotationAngle`) move and turn the outline on the face in a frame the
  reference does not document; the translator copies the step only when all three are zero. Each setting is null when
  it cannot be read. A size behind any of the three is pinned (a loose size with the reason), since it would move the
  outline in Fusion at other values.
- `tangent_chain` is `isTangentChain`. `tangent_faces` lists the faces that touch the input faces tangentially
  (`BRepFace.tangentiallyConnectedFaces`) as `{ surface, plane }`; null when they cannot be listed. `made_surfaces` is
  the surface kind of every face in `feature.faces` (read after the item), null when unreadable.
- `volume_before` and `volume_after`: the target's volume in mm3 with the marker before and after the item.
- `end_offset` and `end_area`: signed distance along the first outline's sketch `z`, from its sketch plane, and the
  area (mm2) of the farthest flat face of `feature.faces` that is parallel to the input face (the top of a raised
  outline or the floor of a sunk one); null when none is found.

The translator (`lib/translator/emboss.py`) copies a flat face emboss as an extrude that starts on the face
(`start.kind` is `fromEntity`): `join` for a positive depth, `cut` for a negative one, going out of the face or into
it. The measured `end_offset` decides the direction when it is known. It refuses a curved face, faces that are not on
one plane, a moved or turned outline, text, a sketch plane tilted to the face, Tangent Chain on (or unreadable) with a
tangent neighbour that is curved or not on the input plane (when the neighbours could not be listed: any curved made
face), and a measured volume change that is not
`sum(areas) * abs(depth)` within 1 percent in the direction the sign of `depth` says.

### Inputs from another component (`foreign`)

A record whose entity does not belong to the target's component carries `"foreign": true`; the key is absent
otherwise. Fusion can hand a feature's inputs over as occurrence proxies even when they are the target component's
own; such an entity is read through its `nativeObject` (component coordinates) and is not foreign
(`native_input()` in `lib/fusion_reader/read_geometry.py`). Any other entity is foreign when it has an
`assemblyContext` (it is seen through an occurrence) or its component is not the target's component, compared as
Fusion objects (`foreign()` in `lib/fusion_reader/read_geometry.py`; the
component is read from `parentComponent`, `component`, `body.parentComponent` or `parentSketch.parentComponent`,
whichever answers). An entity whose component cannot be read is not marked.

| Where | Record |
|---|---|
| Extrude and revolve `profiles[]` | the profile entry (its profile or sketch is foreign) |
| Extrude `start` and `side_one` / `side_two` of kind `fromEntity` / `toEntity` | the extent entry (the picked face or plane) |
| `participants[]` of extrude, revolve and hole | the body ref |
| Combine `target` and `tools[]` | the body ref |
| Fillet and chamfer `sets[].edges[]` | the edge record (`edge.body`) |
| Shell `faces[]` | the face record (`face.body`); a foreign body input sets `"foreign": true` on the data itself |
| Revolve and circular pattern `axis`, mirror `plane` | the axis or plane (see below) |
| Offset faces `faces[]` | the face record |

A revolve or circular pattern `axis`, or a mirror `plane`, of another component that is seen through an occurrence
or belongs to the root is read in the root's coordinates. The reader brings it into the target's coordinates
(inverse of the target's placement) and writes `"assembly": true` instead of `"foreign"` (`from_assembly()` in
`lib/fusion_reader/placement.py`); when the target's place cannot be read it stays foreign. An axis from a sketch line
of another component loses `entity`, `sketch_token` and `sketch` (the probe follows only the target's own sketch
lines); the sketch is named in its `ref`.

### Measured references (`ref`)

An entity of another component that a step uses (the face or plane an extrude starts from or reaches to, a mirror
plane, a pattern or revolve axis, the point or face a hole sits on) is recorded as a plain `ref` dict, built by
`ref_record()` in `lib/fusion_reader/placement.py`. The record keeps what is needed to find the entity again and to
tell which sizes may move it:

```json
{ "slot": "plane", "type": "ConstructionPlane", "token": "<native token>",
  "component": { "token": "...", "name": "Cover" }, "path": "Cover:1",
  "body": { "token": "...", "name": "Body1" }, "sketch": { "token": "...", "name": "Sketch2" }, "origin": true,
  "point": [0, 0, 21.6], "normal": [0, 0, 1], "face_point": [3, 4, 21.6] }
```

- `slot`: where the step uses it: `start`, `side_one`, `side_two` (extrude), `plane` (mirror), `axis` (revolve and
  circular pattern), `direction_one`, `direction_two` (rectangular pattern), `positions.<n>` (hole), `tool<n>.<xy|xz|yz>` (an origin plane
  of the component a Combine's tool body lives in). The key of a
  reference is `<item index>.<slot>` (`params.geometry_links.ref_key`, `item_refs`). The holes' `position_refs` take
  `<n>` from their place in the list.
- `type`: the Fusion type of the native entity (`BRepFace`, `ConstructionPlane`, `ConstructionAxis`, `SketchLine`,
  `SketchPoint`, `BRepEdge`). `token`: the `entityToken` of the native entity, which `Design.findEntityByToken` finds
  again. `component`: the component that owns it (the component of the occurrence it is seen through, else its own).
  `path`: the `fullPathName` of the occurrence it is seen through, empty for the root.
- `body` (faces, edges) and `sketch` (sketch entities): the native body or sketch it belongs to.
- `origin`: true for an origin plane or axis of the owning component. It moves only with its occurrence.
- `point`, `normal` or `dir`, and for a face `face_point`: the entity's geometry in the target's coordinates. They are
  left out when the entity is not in root coordinates or the target's place cannot be read.

Mirror planes and pattern or revolve axes keep their geometry in the record (`assembly: true`); `ref` repeats it with
the identity. An extrude `start` or `side_one` / `side_two` of kind `fromEntity` / `toEntity` on a face or plane of
another component is read as `foreign` and carries `ref` with the geometry in the target's coordinates; its own `plane`
and `face_point` stay as Fusion gave them (the translator replaces them from `ref` when the face is flat).

The translator (`lib/translator/ref_motion.py`) reads these records as follows.

- `bring_in` makes a flat face or plane of another component that an extrude starts from or reaches to usable: the
  record loses `foreign`, gets `assembly: true`, and its `plane` and `face_point` are taken from `ref` (the target's
  coordinates). The same for a hole whose `position_refs` are all flat faces or planes. A record without a flat `ref`
  (a curved face, an edge, a place that could not be brought in) stays `foreign` and the step is refused, with a reason
  that says which.
- For a record with `assembly: true` (and the `position_refs` of a hole, a `direction_*_place` of a pattern) the
  size marks come from the motion file (`probe.motion.refs` and the `<item>/r/<slot>/...` keys,
  `sketch_values.coverage.ref_answer`), for each ticked size whose user parameter acts on `ref.component`
  (`dependents` of the parameter, the rule in `lib/params/geometry_links.py`):
  - measured and the size does not move it: nothing is marked;
  - measured and moved by an `Affine`: the step writes the move as a formula (mirror plane origin, pattern `axisPoint`,
    revolve axis point, extrude start shift or reach, hole centre) and the size stays free;
  - a `Stuck` key (the reference turns, or the move is no exact formula): the sizes behind it are marked loose and the
    place stays where the capture has it;
  - not measured (`probe.motion.refs` holds a reason, or the size was left without rows), not looked at (no entry),
    or no motion file: every such size is marked loose with the step and the component named.
  The first translation of an export (`OPTIMISTIC`) marks nothing. An `origin` reference is handled like any other: it
  moves with the occurrence of its component. A capture that
  lists no `dependents`, or a record without a component, gives the step a note instead.
- A plane or face moves along its captured `normal`; an axis moves across its direction. A pattern direction stays the
  number read; only a turn marks sizes.

### Parameters behind values (`data.params`)

A value that Fusion keeps as a model parameter is listed in the item's `data.params`: capture field path to
`{ "name": "d12", "expression": "FilterBox_height_mm", "value": 32.0 }`. `value` is in mm, degrees or as is (counts),
like the field it belongs to. Written by `lib/fusion_reader/param_refs.py`; a member that is not a model parameter (a
plain number, a retired member) adds nothing, and `params` is absent when nothing is listed. The translator
(`lib/translator/values.py`) turns a listed value into a formula over the sizes when its expression reads one.

| Type | Field paths |
|---|---|
| ExtrudeFeature | `side_one.distance`, `side_two.distance`, `side_one.taper_deg`, `side_two.taper_deg`, `side_one.offset` (to entity), `side_two.offset`, `symmetric.distance`, `symmetric.taper_deg`, `start.offset` |
| RevolveFeature | `extent.angle_deg` |
| HoleFeature | `diameter`, `tip_angle_deg`, `extent.depth`, `counterbore.diameter`, `counterbore.depth`, `countersink.diameter`, `countersink.angle_deg` |
| FilletFeature | `sets.<n>.radius` |
| ChamferFeature | `sets.<n>.distance`, `sets.<n>.distance_two`, `sets.<n>.angle_deg` |
| ShellFeature | `inside` |
| RectangularPatternFeature | `quantity_one`, `quantity_two`, `distance_one`, `distance_two` |
| CircularPatternFeature | `quantity`, `total_angle_deg` |
| EmbossFeature | `depth` (read like an extrude length; a negative depth is written negated), `offset_x`, `offset_y`, `rotation_deg` (not followed: the copy needs them to be zero, and a size behind them is pinned) |

Sketch dimensions, construction planes, axes and joints are not listed per item. They are model parameters whose
`created_by.kind` is `sketchDimension`, `constructionPlane`, `constructionAxis` or `joint`. The full list of kinds is
`feature`, `sketchDimension`, `sketchText` (the height of a sketch text), `constructionPlane`, `constructionAxis`,
`joint` and `other`.

How the translator uses them (`translate(capture, size_table=table, motion=motion)`):

- A value is written as `{ "expr": formula }` (never `{ "size": ... }`) when its expression translates, reads at least
  one free size and equals the measured number within 1e-6 once scaled to the unit of the field (a plain number in a
  length is read in the parameter's unit or the design's, whichever gives Fusion's number). Lengths written as absolute
  values (extrude and hole depths, spacing) must also stay above zero over the size range; counts at least 1.
  A negative parameter is written negated.
- Symmetric half length is written as `2 * (formula)`. An extent spacing is `(distance) / ((count) - 1)`. Hole
  tip outlines and counterbore or countersink sizes follow sizes point by point.
- Pattern counts that follow sizes must give whole numbers at every size value: the formula is rounded as a whole
  (`round`, `floor`, `ceil`), or it adds, subtracts and multiplies whole numbers and count sizes. Otherwise the sizes
  are fixed. An extent spacing divides by `max((count) - 1, 1)`, so a count of 1 never divides by zero.
- Values that stay numbers while a size reaches them: construction geometry that a step uses itself, the "up
  to" offset, a tip angle, a countersink angle, a full circular turn, a revolve that is not a plain
  part turn, and a pattern whose copies are left out by number or are rounds copied one by one. The sizes behind
  them are fixed.
- Picks and reaches that follow sizes (`lib/translator/follow.py`). Every extrude step is kept with its placement,
  profile and length. A pick point (fillet and chamfer edge points, shell face points) or a TARGET `face_point` that
  lies on an end face of an earlier extrude (inside its profile), or on its side at a profile corner (any outline
  point for a face), moves with that extrude's length:
  - a shell that opens one such moving end face writes `{ "featureFace": <id>, "which": "start" | "end" }`;
  - a round or chamfer whose edges are exactly the side edges, or exactly the edges of a moving end face, of one
    extrude writes `{ "featureEdges": <id>, "which": "sides" | "start" | "end" }`;
  - otherwise, a round or chamfer step that holds whole sets of one size picks the way Fusion did (recipe version
    14): sets picked only by faces write `{ "faceEdges": <face selector of the face points> }`, every edge around
    those faces, and tangent chain sets picked only by edges write one point per `seed` edge with
    `"chain": "tangent"`. Both keep picking every edge when a size adds edges (more bumps along a rim) or splits
    one, which one point per edge cannot. A step with part of a set, mixed inputs or sizes per edge keeps a point
    per edge;
  - other points write the coordinate along the extrude as a formula (`0.5 * height` for a side point half way up);
  - a "to entity" reach to a moving end face writes its length as a formula; a construction plane stays where it is;
  - a start offset that follows sizes, or a "from entity" start on a moving end face, moves the sketch placement
    along its normal (`sketch.on.origin` as formulas), and the picks on that extrude follow it too. Such a moving
    start with a side that reaches "to" a face is fixed.
  - a copy made by a pattern or mirror of an extrude is placed like the extrude and moved by the copy's motion: a
    linear spacing that follows sizes moves the point with it, a turn or a mirror moves it by numbers. A pick on a
    copy fixes the sizes behind that pattern's count (and a circular angle), since the list of points cannot grow.
    A copy has no `featureEdges` or `featureFace`: the app traces only extrudes, so copies are picked by points.
  - a point on the inner wall of a shell (`lib/translator/shells.py`) is moved back out by the thickness and placed
    on the extrude whose outer wall it came from; its coordinates follow that extrude and the thickness.
  - an edge where the flat walls of two steps cross (`lib/translator/crossings.py`), for example a cut's floor
    running into a rib, stays on both walls as they move; along the edge it follows the shorter wall.
  - a point on the far outline of a tapered extrude follows its length; a taper that follows a size is fixed.
  A point or face that no extrude explains may sit on geometry that moves, so every size read by the steps written
  before it is marked, with the step's name in the reason. Rounds and chamfers that a pattern or mirror copies take
  their source's written points (formulas included) through each copy's motion; their count is fixed, and a circular
  angle too. A copied uneven chamfer turns its `sizeOn` with the copy, and a tangent chain pick stays one. Without
  sizes the picks stay plain points. A rectangular pattern whose count follows sizes, with no copy left out, writes
  instead one round or chamfer step per copy for every count the size ranges allow (at most 64 copies), each with
  `when: "<count formula> >= n + 1"` for the copy n steps along a part, so the rounds and chamfers follow the count as
  Fusion repeats them (`repeat._counted_finishes`); the count is not fixed for them. The app recipe cannot repeat a
  round or chamfer itself, nor pick the edges of every copy of a step.
- A round whose edges are exactly the four side edges of an earlier extrude with a plain rectangle outline, with a
  radius equal to half the rectangle's short side at every size setting, is drawn into that extrude: its outline
  becomes a `slot` (length the long side, width the short side, turned 90 degrees when the long side runs along the
  sketch y) and the round writes no step, with a note (`finish._slot_outline`). Not when a later pattern or mirror
  repeats the extrude without the round. Where the other side would get shorter than the short one, Fusion cannot make
  the round either, and the app refuses the slot.
- A formula longer than the app's cap (`MAX_FORMULA_LENGTH` in `lib/params/expressions.py`, 300 characters) fixes
  the sizes it reads (they become plain numbers), also when a step builds it from several values.
- Sketch values follow sizes through the probe's motion file (next section). Without one, every size that a model
  parameter created by a sketch dimension (also one whose creator reads as `other` but whose `role` names a
  dimension), construction plane or axis, or joint reads cannot be followed (reason "it changes a sketch, which could
  not be tried at other values"). A size that a joint reads can never be followed ("it moves a joint"). The
  dimensions of another component's
  sketch are not model parameters of the target's path; the sizes in their `sketch_params` are fixed when the step
  that borrows the sketch is copied, and its outline stays numbers.
- An uneven chamfer writes `sizeOn` (one direction per step: the sum of `first - other` face normals over its edge
  points, which must favour the first face by at least 0.1 at every point; edges that one direction cannot serve
  start another step) with `otherSize` or `cutAngleDeg`. Both distances follow sizes; an angle must stay under 90
  degrees over the size range, else its sizes are fixed.
- A value that cannot follow its sizes is written as its number and its sizes are recorded (`Context.doubt`; the notes
  here say a size is "fixed" or "marked" for such a value). The translator walks twice. The first walk makes each
  recorded size a plain number in a new size table (`with_fixed`) and walks again until nothing new is recorded, to
  learn which sizes and reasons there are. The second walk keeps those sizes free: every value that can follow them
  still does, and the values that cannot keep their numbers, so the shape at the current values is the same. In that
  walk a stuck sketch value follows its `rest` (the sizes that still move it), as it does once its own sizes are
  fixed. `TranslateResult.loose` lists the sizes as `{ name, reason }` ("... may give unexpected results: ..."). A
  size that no formula reads after that is not a size: it is left out and listed in `TranslateResult.dropped` with its
  reason. The ranges are always the table's. A rule that can fail inside a range
  (a count that a pick needs, a taper, a step that must keep meeting the part) marks the sizes it reads, with the
  value past which it fails where `kept_ranges` gives one. Only `TranslateResult.fixed` holds sizes that became
  numbers: a formula too long to copy (`Context.doubt` with `fixed`). Without a motion (`motion=None`) every size behind
  a sketch dimension, construction plane or axis, or a joint, is marked with a reason, and the ones no formula reads
  are dropped with that reason.
- End of walk audit (`lib/translator/audit.py`). After the last walk every free size that a copied step reads must be
  in a known state: read by a written formula, fixed, loose, or dropped, each with a reason. A step reads a size
  through its `data.params` (what each expression reads), the dimensions of the sketches its data names, and the
  construction geometry it uses. A value of a step's `data.params` that its handler never dealt with
  (`values.quantity`, `values.pin` or `values.handled` record the path) and that reads a free size, or a sketch size that a measured motion says moves something and no formula reads, and that no handler named, gets the
  reason "<step> reads it, and the copy does not follow it": loose when another formula reads it, else dropped. A sketch
  size that a measured motion says moves nothing is dropped as "changes nothing in the copied steps" (for a size tied
  to the sketch only through another component, as "nothing in this part moved with it"). This makes a value a
  handler forgets to record safe by default.
- `TranslateResult.dropped` is `[{ name, reason, used }]`, one per ticked size the recipe does not hold: `used` is
  true when a step reads it and the copy could not follow it (the reason says why), false when no copied step reads it
  ("not used by any copied step") or a measured sketch does not move with it.
- Only steps whose result reaches the exported body count. The steps of another body are walked on their own when a
  Combine takes that body (`tool_walk.build`): the sizes they cannot follow join the walk only when the Combine writes
  them, and only then do its items count for the audit.
- A step with no handler stops the copy, with two exceptions that the capture proves harmless: a step that lists no
  body and whose `target_changed` is false (a Remove of another body) is skipped, and so is a Split Face of the exported
  body with `target_changed` false, with the note that picks on its faces may not follow. In the walk of a tool,
  `target_changed` is false when `body_states` shows the tool's volume unchanged. A step of another body that
  has no handler is helper geometry and is skipped. A `target_changed` of true or null keeps the stop.
- A copied step that Fusion reports with a `warning` health gets a note with Fusion's message.
- The copy limits (`MAX_PATTERN_COPIES`, `MAX_FEATURES`, `MAX_NEAR_POINTS`) are checked at the current values; a pattern
  count that can pass its limit inside the size ranges (`range_check.sweep`) marks the sizes it reads.
- The recipe is version 12, or the lowest version that holds its steps and selectors (13 with an `offsetFaces` step, 14
  with a `chain` or `faceEdges` pick). With a size table it carries `sizesAsWritten: true` and `sizes`: the sizes that a written
  formula reads, plus the sizes those formulas read. A ticked size that nothing reads is left out (see `dropped`).
  Without a table the recipe has no `sizes`, and no marker.

### Sketch values that follow sizes (`lib/translator/sketch_motion.py`)

The export measures the sketches at other size values (probe states, next section) and fits each value the translator
writes as a sum over Fusion parameters, or marks it stuck (`lib/probe/`). That is the motion file, `sketch_values.motion`:
keys `<item>/p<profile>/l<loop>/<field path>` (loop 0 is the outer one, then the holes; `center.0`, `width`,
`segments.2.through.1`), `<item>/p<profile>/plane` (the sketch plane along its normal, from the component origin),
`<item>/positions/<n>/<0|1|2>` (hole points) and `<item>/axis/point/<0|1|2>` (a revolve axis from a sketch line).
`lib/sketch_values/keys.py` writes all keys; the probe and the translator both use it.

Measured references of other components (below) have their own keys, `<item>/r/<slot>/...`, and their own list `refs`.

The probe tries (`lib/probe/plan.py`, at most 64 rows), in this order:

1. Near rows (`plan.probe_rows`): each ticked size that moves a covered sketch value or reaches a sketch dimension, a
   construction plane or, through another component, a sketch ("Geometry links" in section 2), at 25 percent of its
   value below and above (`NEAR_SHARE`), inside its range; a count moves by whole numbers, a value of zero by that
   share of the way to the range ends. Then up to 8 ticked sizes that nothing ties to a sketch (`MAX_EXTRA_SIZES`, in
   table order) while rows are left: the person ticked them, so a sketch may follow them in a way the capture cannot
   show. Such a size left without rows is not listed as untried.
2. With two or more sizes tried, one near row puts every tried size at its lower near value and one at its higher.
3. The nearer rows below, for near rows that did not build.
4. Far rows (`plan.far_rows`): the range ends that differ from the value and from the near values, so the measured span
   grows; then, with two or more sizes tried, every size at its minimum and one at its maximum. Nearer rows follow
   for the far rows that did not build.

A size that only feeds step values (a free size that moves no covered sketch value and reaches no sketch dimension or
reference) has no row: its formula is exact, and it is never reported as untried (only a moved size left without a
near row by the cap is). Each row has a `label`, the line of the progress window: "HolderWidth at 32 mm" (the value in
the parameter's own unit), "several sizes together", "checking if X changes this part" for a discovery row, or the
label with "The last value did not rebuild, so this one is nearer." for a nearer row.

While the rows run, the timeline marker waits just after the last item the part needs (`lib/export_plan/marker_roll.py`),
so Fusion rebuilds fewer items per recompute. The items needed: any that may change the target, the sketches the steps
use (matched by name and component), the last item of every other component a sketch link or measured reference
depends on, the steps of tool bodies of other components, and joints, rigid groups and items of unknown types. sketch record without a name gives no roll; a reference without a component, or a link with an unsourced reference,
keeps every other component. The marker is moved only after the first read (E0), and only stays when a read
at the rolled marker gives the same sketches, points, lines, references and body box as E0. `report.json` keeps
`probe.timeline`: `{ rolled, items, of, reason? }`, the items each try rebuilt out of the items before the person's
marker, and why it did not move. A read while the marker sits before the rolled position counts as not read: the probe
is not used. The marker and the later items are put back and rebuilt once when the tries end, also on cancel and error.

A row that Fusion cannot build is tried again nearer to the value now (`plan.nearer_rows`, `NEARER_STEPS`): half way
to that range end, then a quarter, then a tenth, one step per batch and per side, until a row on that side builds.
Sizes that no row built go first. A size that moved a sketch or a measured place with only one row that built, and
nothing left to try, gets one more row half way to that value, so the fit has two readings. These rows are at most
24 per export (`MAX_NEARER_ROWS`, each is a Fusion recompute) and stay inside the 64 row cap; the discovery rows get
what is left. The range ends come first for every size, also for one that reaches the part only through another
component: a far end that builds gives the widest span measured, and only a failed end costs the nearer rows. When
a value moves along a curve with one size on its own, or follows a `Terms` formula with an angle function (below),
once per export (`plan.check_rows`, inside the row cap, in this order): each such size half way to the lowest and to
the highest value it was measured at; each such size with each other size of those values, both low and both high
(products show there); then every other size at the lowest and at the highest value it was measured at, the curved
ones at their value now, so the formula over those sizes is checked by a state that changes several of them. A state that did not build keeps the
first step that failed (`failed`). A ticked size the probe set to other values that no formula reads at the end is dropped with
"it was tried at other values, and it changes nothing in this part" (`used` false, `tried` true), with "between A and
B; beyond that it could not be tried" when the rows that built cover less than its range. A size that reaches a sketch
or a measured place (`translator.sizes.probed_sizes`) and whose rows all failed to build was not measured: it is
doubted up front with "the design does not rebuild in Fusion at A (step) or B (step), the nearest values tried, so it
could not be measured" (loose when a formula reads it, else dropped with `used` true), never called unchanging. A
free size measured over less than its range is loose with "it was followed between A and B; beyond that it could not
be tried" (added to its other reason when there is one and it fits the note). Every state also
reads the body's box (and volume when the state has it): a size whose state alone changed the box but moved no
followed sketch or reference is kept in `Motion.body_moved` (`SizeProbe.finish`). The translator treats it as doubtful
with "it changes this part in a way the copy does not follow": loose when a formula reads it, else dropped with
`used` true. It is never reported as changing nothing.

Discovery tries come last, in the rows the cap leaves: up to 12 unticked plain parameters (`MAX_DISCOVERY`) from the
discovery candidates of "Geometry links" (section 2), one row each with only that parameter at one end of its range
(the upper end, the lower one when the upper is its value). They are not states of the motion. Before them the
design is read once more with the parameters back (`SizeProbe.set_discovery_base`), and each discovery read is
compared with that read, not with the first one: a sketch Fusion left on another solution after the rows reads the
same in both and is not a move. What reads differently from the first read at that point is kept in
`probe.after_rows` (`{ changed, unread }`). The comparison covers the followed sketches as read (frame and curves
within 1e-4 mm), hole points, axis lines, the followed references and the body's box and volume
(`SizeProbe.differences`): `changed` and `unread` in a discovery entry name what read differently and what one of
the two reads lacked; `moved` is true when something changed, false when the rest compared the same, null when
nothing could be compared. A row that did not build (`failed` names the step) or gave no read has `moved: null`,
`tried: false` and a `reason`, so it is never a move. They never become sizes in this
export. `probe.discovery` in `report.json` lists `{ param, value, built, moved, changed, unread }` (see below); a candidate the cap or the row room left without a row is listed as `{ param, moved: null, tried: false,
reason }`, and the result window counts those in a "Not tried" group (ticking one makes the export try it).
`also_changes` lists the parameters that moved the part; the result window says "These parameters also change this
part: ... Tick them and export again to get them as sizes." For a parts file the group is "Also change these parts" and
each parameter names the parts it changed (read from each part's `probe.discovery`).
The sketch curves of each profile have `<item>/p<profile>/c<loop>.<curve>/<field>` in the capture's loop and curve
order: a line's `offset` (its distance from the sketch origin along the left normal of its captured direction) and
`turn` (degrees it turned), an arc's `center.0`, `center.1` and `radius`; `curves` lists the profiles
(`<item>/p<profile>`) whose curves were measured. For a sketch the probe measured, a key that is not listed did not
move. `spans` gives, per size the probe set to other values, the lowest and highest value of the states that built
(the value now included) and `failed`, `[value, step]` for each value tried alone that did not build
(`probe.build.spans`). A sketch the probe could not measure (a step uses it in a way the probe cannot follow, its first read did not
match the capture, or there was no read at the current sizes) is listed in `unmeasured` (sketch name to reason), and
nothing is known about it. For one sketch and one size the motion file therefore gives one of three answers: measured
and still, measured and moved (the keys), or not measured (`translator.sizes.sketch_answer`). A motion file without
`unmeasured` (written by hand) says nothing about such sketches. The translator uses it like this:

- `motion=None`: the rule above, sketch sizes fixed up front. `motion=OPTIMISTIC` (the export's first translation):
  sketch values are written as numbers and nothing is fixed for them, so the export can see which sizes to try.
- Each written value with a key becomes a formula over the sizes (`{ "expr": "0.5 * FilterBox_width_mm" }`); a model
  parameter in a sum is written through its own expression. Its number stays the captured one; a formula that misses
  it by more than 1e-3 mm fixes its sizes ("could not be read at other values"). A width, height or radius that would
  reach zero over the size ranges fixes its sizes ("would shrink to nothing").
- A value of an unmeasured sketch is stuck with cause `untried` for every size the sketch reads (`sizes.sketch_sizes`:
  the sizes behind that sketch's dimensions, and the sizes that may reach it through the geometry of another
  component, "Geometry links" in section 2). The size is loose, with "it changes <sketch> and could not be tried at
  other values". A size the sketch does not read is not touched: a size that moves the sketch only through its
  construction plane is not named here.
- A size that may reach a sketch only through another component follows the measured motion like any other: when the
  probe saw the sketch move with it and the fit holds, the outline is written as formulas of it (two arcs of radius
  `pipe_d_mm / 2` give points such as `0.5 * pipe_d_mm`; a circle writes its `radius`). When the fit fails or the
  outline changes shape, its sizes are loose or dropped with the probe's cause, which names the sketch. When the
  sketch was measured and did not move, the size is dropped ("it changes <component>, but nothing in this part moved
  with it", `used` false). Without a motion (`motion=None`), it is dropped with "it changes <component>, which
  <sketch> is drawn around, and could not be tried at other values".
- A stuck value that a step writes fixes every size the probe lists for it, with the probe's cause: `curve` (a point
  moves along a curve), `shape` (the outline changes), `turns` (the sketch plane turns), `unread`, `untried`. When
  only some states failed (a size whose state changed the outline), the probe lists only those sizes and fits the
  value over the other states as `rest`, which the translator writes once the listed sizes are fixed. A value that
  does not fit as a whole blames only the sizes whose own readings (every other size at its value now) do not lie on
  a straight line, when the value fits over the states that keep those sizes at their value now: it is stuck with
  cause `curve` for them, and its `rest` follows the others (`probe.series`). Otherwise every size that moved it is
  listed. The fit takes up to four columns; columns that change in a state where the value moved are tried before
  the others, so a design with many sizes does not push the right column past the 12 candidates.
- Before that, a value no straight formula fits is tried as a sum of terms over the free sizes that moved it
  (`probe.terms`): each size, the product of two length sizes, and for an angle size `sin`, `cos`, `tan` and `cot` of
  the angle and of half the angle, alone and times a length size. The straight terms come first, then up to 3 others
  chosen one at a time (each the one that leaves the smallest miss), then every term the value can do without is
  dropped. The sum is used only when every measured state follows from the others within 1e-4 mm (solved without
  that state, it still gives it), and when no other term in place of a chosen one also gives every state but another
  value half way to an end or with every size at an end. The motion file keeps it as `{ const, sum: [{ k, of }] }`
  (`Terms`): `of` lists the factors `[function, name, scale]`, `function` empty for a size, scale 1 or 0.5 for the
  half angle. The translator writes it as a formula with `sin`, `cos` and `tan` in degrees (`cot` as `cos / sin`),
  checked over the size ranges like any formula (a value that would reach zero, or a divisor that would cross zero,
  marks its sizes; a formula past the length cap fixes them). A `Terms` value holds the sizes that a stuck value of the
  motion names at their value now, so all values of one outline follow the same sizes. A sketch can
  have more than one solution, and Fusion may land on another one after the rows run before (a row that did not build
  often leaves it there). A different outline blames a size only in that size's own row (the row that changes it
  alone), when the row started on the captured outline and the outline came back once the parameters were put back
  (`probe.build`): the read before the row (`start` of the state) or, without one, the row before it (E0 for the
  first) tells how it started, and the next row's `start` or read (or the read once all rows are done) tells whether
  it came back. A row of several sizes never blames one for a different outline. Every other state with a different
  outline blames no size (`apart` lists them, by number in `states`), and so do the states where a sketch reads as
  the same different outline in rows that change different sizes or one size to two values. A sketch known to have
  stayed on its other outline after the parameters were put back (a `start` read shows it, or the same different
  read in rows of unrelated sizes) is named in `flipped`, and `health.flipped` gives the result window one line about
  it.
- Fusion may give a projected or intersection curve a new token when it recomputes a sketch, although it is the same
  curve. A curve of the first read whose token is gone pairs with a new curve of the same kind that sits in its place
  along a loop, between curves that kept their tokens, when every loop agrees (`probe.match.renamed`); the sketch then
  reads as its captured outline. The restore check and the discovery compare reads the same way.
- A state whose read shows one of its sizes at another value than its row set (the read of another row) is left out
  of the fit (`probe.build._Run.mislabelled`). The reads of the rows are kept by row key, so every row has its own key.
- An outline merged from touching profiles takes each point from the part profile that has it (rect corners from
  centre, width and height); a rect drawn through merged corners gets its centre, width and height from them. A
  corner whose part value cannot follow (it is held by a line between the profiles that the merge leaves out) is taken
  from the two sketch curves of the outline that cross there, when the probe measured them. Pieces
  of one sketch line in a merged loop are joined back into the line, and a loop of arcs of one circle becomes the
  circle, with the centre and radius of that sketch circle.
- A corner the probe could not fit (it moves along a curve) is rebuilt from the two sketch curves that cross there:
  two lines give an affine point, a line and a circle or two circles a point with `sqrt`. An arc's middle point
  becomes a fixed direction from its centre. The rebuilt outline must keep its crossings and the order of its corners
  at every mix of the size ends (up to 6 sizes; a bounded sample past that) and the probe's states; otherwise its sizes are fixed ("along a curve"). A
  line that turns cannot carry its crossings.
- A sketch plane that moves writes the placement origin along its normal (`sketch.on.origin`); a "to entity" reach is
  the face's move less the plane's move. Outlines of one step whose planes move differently fix those sizes.
- A reversed placement negates the y formulas of its loops.
- Hole points write `origin` as formulas (the drill tip revolve too); a revolve axis from a sketch line writes
  `axis.point` in the sketch plane. A symmetric revolve turns its moving origin about the axis.
- Picks on an extrude whose outline moves follow it: a side corner moves with that corner, a point on an outline line
  between its two ends, a point on an arc with the arc's middle (or with the whole arc when it only shifts), on a
  circle with its centre and radius, and a point inside an end face with the outline's centre. A point on an arc that
  changes shape fixes those sizes. An edge inside one flat side wall, away from its corners, where no second flat wall
  crosses it (a round meets the wall), follows that wall: the outline curve under it and the length. The same holds
  for pattern and mirror copies, shell inner walls, crossing edges
  and faces an `offsetFaces` step moved (the point moves back by the distance, then follows what made the face).
- A pick on a tapered wall follows the taper and the length: the wall leans in by `tan(taper)` times the height along
  the extrude, also when the taper is a size.
- Symmetric patterns (`lib/translator/symmetric.py`, `repeat.py`). A symmetric direction is written as a forward and a
  backward pattern that both start at the original; the grids that result (one per choice of a part in each direction)
  skip the places another grid already makes when their counts are numbers. The copies follow this rule, and the
  measured copies must match it or the pattern is refused: for `n` copies, an odd `n` has `n // 2` steps each way and
  an even `n` has `n // 2` on one side and one less on the other, the longer side being the one measured. The two part
  counts are `floor(n / 2) + 1` and `floor((n - 1) / 2) + 1`, so a count formula keeps the pattern centred. A count
  measured odd that can be even inside its range marks its sizes (the even places were not seen). A pick on a copy
  off the middle of a symmetric direction fixes the sizes behind the count, since Fusion moves its copies when the
  count changes. A pattern whose original is not among the copies (it sits between two) is refused. The circular
  case turns the copies back and forth from the original by `k * total / (count - 1)`. Copies left out by number need
  a fixed count in the app, so the count is written as a number and its size is dropped with the reason.
- A pick on a copy of a rectangular pattern needs that copy at every size: copy n needs a count of n or more over
  the size range (count formulas such as `ceil(width_count) * 2` are evaluated at the range ends, `lib/translator/
  copy_counts.py`). When the count can drop below that, the sizes it reads are marked ("a smaller value would leave
  that copy out"); the range stays. Copies of a circular pattern keep their count and angle.
- A taper that follows sizes should stay under 45 degrees either way: the sizes it reads are marked past the value
  where it reaches 45.
- A through cut clears the part at the largest sizes tried (`box_max` of the motion file). A cut through all to one
  side without a measured end face cuts toward the side where its outline meets the part built so far (sampled on a
  grid over the outline); Fusion's stored direction is kept when both sides, or neither, hold material, and turned with
  a note otherwise.
- A construction plane or axis that a step uses itself (start from, reach to, turn about, mirror across, with `token`)
  fixes the sizes of the model parameters it made (`created_by.token`); without a token, of every construction plane
  or axis.

### Measured references in the motion file (`lib/probe/ref_fit.py`)

The probe reads every measured reference (`ref`, section 4) that has a place in the target's coordinates and fits how
far it moves from the captured place. A size that acts on the reference's component is probed like a size behind a
sketch (`reference` links, section 2). The values are moves, zero at the sizes the capture was read at:

| Reference | Keys | Meaning |
|---|---|---|
| plane (`point` and `normal`: a mirror plane, a plane or face an extrude reaches or starts from, a hole's face) | `<item>/r/<slot>/offset` | distance the plane moved along its captured normal |
| axis (`point` and `dir`) | `<item>/r/<slot>/point/<0|1|2>` | how far the axis moved across its direction, per coordinate (a slide along the axis is not a move) |
| point (a sketch point or vertex) | `<item>/r/<slot>/point/<0|1|2>` | how far the point moved, per coordinate |
| direction (`dir` alone: a pattern direction) | `<item>/r/<slot>/dir` | stuck only, when the direction turns |

Each value is an `Affine` of the sizes (exact within 1e-4 mm, same fit and checks as sketch values), or a `Stuck`: with
cause `turns` when the normal or direction changes or flips (the sizes of those states), `unread` when a state did not
give the reference, `curve` or `untried` when the move is no exact formula of the sizes. Like the sketch values, a
`Stuck` may carry `rest`. A measured reference that stays has no key.

`refs` lists every reference the probe looked at, by key `<item>.<slot>`: `""` when it was measured, else why not
(it has no place in the target's coordinates or no token, the first read did not match the capture within 1e-4 mm, the
reader could not read it, or there was no first read). Such a reference is not read at the other states. A key that is
not in `refs` was not looked at (a motion file written without references, or the export's first translation):
nothing is known. For one
reference and one size acting on its component, `sketch_values.coverage.ref_answer` gives the same three answers as for
sketches: `STILL`, `MOVED` (with the keys) or `NOT_MEASURED` (with the reason, or `NOT_TRIED` for a size left without
rows, `NOT_LOOKED` for a key not in `refs`).

### Probe states (`lib/fusion_reader/probe_state.py`)

The size probe sets other size values, recomputes and reads a state with `read_state(design, request, ctx)`.
`request` is `{ "sketches": [token], "points": [token], "lines": [token], "params": [name], "target": true }`, plus
`borrowed`, `native` and `refs` below. Every
entity is found with `Design.findEntityByToken` (the match without `assemblyContext`; for a proxy only, its
`nativeObject`), so values are in component coordinates like the capture. The result, mm and degrees except `params`:

```json
{
  "sketches": { "<sketch token>": { "frame": FRAME, "profiles": [PROFILE, ...] } },
  "points": { "<sketch point token>": [x, y, z] },
  "lines": { "<sketch line token>": { "point": [x, y, z], "dir": [x, y, z] } },
  "params": { "d12": 2.0 },
  "box": { "min": [..], "max": [..] },
  "refs": { "57.plane": { "point": [x, y, z], "normal": [x, y, z] } }
}
```

- `sketches`: `frame` from `Sketch.transform`; `profiles` are every `Sketch.profiles` item read like a capture
  profile (section 4, each curve with `entity`). A sketch with more than 200 profiles, or a profile whose space is
  `ambiguous`, is left out.
- `points`: `SketchPoint.worldGeometry`; `lines`: `SketchLine.worldGeometry` start point and unit direction.
- `params`: `value` of each named parameter in Fusion's own units (cm, radians), as in `parameters.*.value`. A name
  is looked up in the user parameters, then in the target component's model parameters.
- `box`: the target body's box, as `target.box`.
- A sketch of another component that a step borrows is requested with the optional `borrowed`: `{ "<sketch token>":
  { "path": "<fullPathName the capture recorded>" } }`. It is found by token, read native, and its place is found
  again at every state: the occurrence of its component with that path (the only one when there is no path), then the
  placement check of section 4 (native sketch points against the same points through the occurrence). Its `frame` is
  brought into the target's coordinates (that place, then the inverse of the target's, read once per capture), so
  it compares with the capture profile's brought-in `frame`; it adds `native_frame` and `placement` (`{ path, source }`).
  When it cannot be read or placed, it has no key under `sketches` and `unread` (only then present) gives
  `{ token: reason }`.
- `native` lists the sketches of tool bodies from other components (the steps of `helper_of` items). They are read like
  the target's own sketches, in their own component's frame (not brought into the part's), since the translator writes
  those steps in that frame before it moves them.
- Measured references are requested with `refs`: `{ "<key>": { "token", "type", "path", "shape" } }` (`shape` is
  `plane`, `axis`, `direction` or `point`, from the record: `lib/probe/plan.py` `refs`). Each is found by the token of
  its native entity (`lib/fusion_reader/probe_refs.py`), shown through the occurrence with the recorded `path` as that
  occurrence sits now (`createForAssemblyContext`), read the way the capture read it (`plane_of`, `axis_of`,
  `direction_of`, `worldGeometry`), and brought into the target's coordinates with the inverse of the target's own
  place read again at this state (the body is shown through its occurrence again, so a size that moves the target's
  component is taken out). `refs` maps a key to `{ point, normal }`, `{ point, dir }`, `{ dir }` or `{ point }`; a
  reference that cannot be read has no key there and `unread` gives `{ key: reason }`. The reads change nothing in the
  design.
- Nothing raises. A part that cannot be read has no key, which the fit treats as unread.

## 6. Report and capture file

The export writes `report.json` into the package: `{ "writer", "outcome": "recipe" | "stepOnly", "items": [ITEM
VERDICT, ...], "capture": CAPTURE }` (verdicts: see the translator, `lib/translator/result.py`; a Combine written as tool
steps has `tool_steps`, the verdicts of the items that built its tools). The app never reads it. A report saved from a real
design gives a fixture: its `capture` is copied as is.

`also_changes` (only when not empty) names the unticked parameters that a discovery try showed changing the part.
`links` (only when the export found geometry links) lists each link of the picked body with what became of its
parameter: `{ param, sketch, component, outcome, reason }`, `outcome` one of `size`, `loose`, `fixed`, `dropped` or
`formula` (a parameter worked out by a formula, which cannot be ticked; the reason names what it follows) or
`not ticked` (`recipe_export.link_outcomes`; `reason` when the size has one).

`gaps` (only when the recipe leaves steps out of the copy) holds the gap records exactly as they go into the gaps file
of the package (`docs/recipe-gaps.md`), and `reach` (the capture's, as read, or `{ read: false, error }`) is beside it.
An item verdict of a left out step is `leftOut`, with `gap` (the gap id), `note` (the reason) and `cause`: `picks` for a
step left out only because it picks, or may pick, faces of a gap, `own` otherwise. `outcome` stays `recipe`, and the
package notes say how many steps were left out and which ("2 steps were left out: Extrude5, Fillet3."). A parts file
has `gaps` and `reach` in the record of each part.

`sizes` holds `free` (recipe size names), `fixed` and `loose` (`{ name, reason }` by recipe size name, as in the
manifest), and `dropped` (`{ name, reason, used }` by Fusion name, plus `tried: true` for a size the probe set to
other values that changed nothing: the ticked parameters that are not sizes, from
`TranslateResult.dropped`; `used` is true when a step reads the parameter and the copy could not follow it). `loose` comes
from the translator and from the probe. `checks` in the manifest is
always empty. The report has a
`probe` when a sketch could be followed (the rows only recompute and the parameters are restored; its `timeline`
says how many timeline items each try rebuilt, section 5), `marker` and
`health`. `health.restore_unverified` is true when a followed sketch could not be compared with its first read after
the parameters were put back; `health.unchecked` then names each such sketch and why ("reads another outline",
"could not be read", "lies on a turned plane"), and the result window says so (`probe.restore_unchecked` too).
`health.flipped` names the sketches that stayed on their other outline after a restore during the rows (`Motion.flipped`);
the result window says that the tries made then were not used to judge any size. After a row that did not build, or
whose read showed a followed sketch on another outline, the design is read again once the parameters are back and
before the next row (`ProbeRun`); that read is the next state's `start` in `probe.states`. A probe row that Fusion cannot build is listed in `probe.dropped`; no size is fixed for it.

A file with several bodies (package kind `parts`) has one `report.json` with a `parts` list, one record per body:
`{ name, outcome, items, notes, capture, probe, sizes, derived }`, plus `refusal` or `error` for a body saved as a fixed
shape (and `gaps`, `reach` for a body with left out steps). The `sizes` record at the top is shared by all bodies;
`derived` is per body.

### Derived values (`derived`)

Shadow mode of reading sketches directly (`lib/probe/derived.py`, `derived_keys.py`, `derived_sizes.py`). When the
capture has `sketch_graphs`, the export solves each graph with `sketch_solve`, works out the values the probe keys
(section 5, "Sketch values that follow sizes") from the solution, and compares them with what the probe read. The
result is written as `derived` in `report.json` and used for nothing else: the recipe, the size lists, the notes and
the result window are the same with or without it, and the add-in log gets one line. It runs after the tries and
calls Fusion no more. A capture without graphs has no `derived`.

```json
{ "version": 1,
  "summary": { "sketches": 4, "derived": 3, "partly": 1, "not_derived": 0, "values": 21, "agree": 20, "disagree": 1,
               "skipped": 0, "errors": 0 },
  "sketches": [ { "sketch": "Sketch1", "token": "...", "outcome": "derived", "solver_outcome": "derived",
                  "values": { "derived": 15, "not_derived": 0 }, "reasons": { "piece": 2 },
                  "formulas": { "affine": 8, "const": 7 }, "solver_open": { "blocked": 3 },
                  "leaves": { "d1": { "kind": "dimension", "value": 40, "expression": "width", "formula": "width" } },
                  "constants": ["c3", "p7"], "assumptions": [ { "text": "...", "flips": [] } ],
                  "keys": { "4/p0/l0/center.0": { "formula": "0.5 * width", "kind": "affine" },
                            "4/p0/l0/points.1.0": { "numbers": true, "why": "..." },
                            "4/p0/c0.0/offset": { "open": "piece", "reason": "..." } },
                  "compare": { "states": 5, "values": 15, "compared": 15, "agree": 14, "disagree": 1,
                               "never_compared": 0, "max_diff": 2.0,
                               "listed": [ { "key": "4/p0/l1/center.0", "state": 4, "derived": 37, "read": 35,
                                             "sizes": { "margin": 3 } } ],
                               "measured_fit": { "same": 14, "differs": 1 } },
                  "solver": { } } ] }
```

- Per sketch: `error` (text, the solving stopped on an exception; the others go on) or `skipped` (more than
  `MAX_ENTITIES` = 400 points and curves, or past `MAX_SKETCHES` = 60 sketches) instead of the fields below.
  `outcome` is `derived` when every key of the sketch's profiles, hole points and axis lines has numbers, `partly` when
  some have, `not_derived` when none do; a sketch no step reads has no keys and takes `solver_outcome`, the solver's
  verdict on points and radii (`outcome.Solution.outcome`). `solver` is `Solution.json()`; `leaves` repeats its leaves
  with each dimension's formula over the recipe size names.
- `keys`: every key the probe reads for the sketch (at most 300 listed). The sketch plane (`<prefix>/plane`) is not
  counted. A key has `formula` (text over recipe size names, as the translator writes it) and `kind` (`const`, `affine`
  or `curved`: sines, cosines, products), or `numbers: true` (it has numbers at every size setting but no formula, for
  example a line's turn or a width along a slanted line), or `open` with a `code`. A formula may carry `inputs` (it
  reads the measured coordinate of a projected entity, named `@p3.x`, `@p3.y`, `@c5.r`) and `unread_dimensions`
  (it reads a dimension whose expression could not be written; its comparison runs at the first state only).
- Codes in `reasons` (keys without values, by code): the solver's (`blocked`, `refused`, `free`, `no_rule`,
  `conflict`, `unread`; `solver_open` counts the same for points and radii) and the key mapping's: `not_in_sketch` (the
  profile curve or hole point is not an entity of the graph), `piece` (a profile curve is only a part of a sketch
  curve, so its ends are crossings with other curves), `kind` (an ellipse or other curve the solver does not work
  out), `loop` (the curve is drawn but another curve of its loop is open: a loop is drawn from the solution as a
  whole), `no_frame` (a hole point or axis needs the sketch frame of the first read), `no_match` (the outline drawn from
  the solution is not the captured one).
- How a key is found. A profile curve is found in the graph by its sketch entity token (`entity` equals the graph
  curve's `token`). Its ends, centre and radius are the solver's formulas for that curve; an arc's middle point is
  worked out from them. The profile is drawn again from those numbers and run through `match.state_values`, so the key
  means exactly what a read in Fusion gives it. The formula of a key is fitted as a constant plus a sum of coefficients
  times the solver's point coordinates and radii of its own loop (or its own curve, for `c<loop>.<curve>` keys), over the
  size settings below, then each dimension leaf is replaced by its expression over the sizes
  (`translate` of the dimension parameter's expression). A hole point or axis start is the solver's point put
  through the frame of its sketch at the first read.
- Size settings (`derived_sizes.override_sets`): the sizes the sketch's dimensions read, at most 12, each at 25 percent
  below and above its value (as the first tries), then all low and all high. Two dimensions that read one size move
  together. The solver checks its redundant rules and choices at these settings, and the formulas are fitted over them.
  Settings where a value has no number (a square root of a negative value) leave the key without a formula.
- Constants (`derived.constants_of`): a projected entity from another component that no parameter reaches through
  `geometry_links.reach`, and an implicit line through the sketch origin (an origin axis). Other projected entities
  (from the body's own edges or sketches) are measured inputs: the solver leaves them where they are, the fit moves
  each one up and down by a quarter of its value (at most 40 inputs, `derived.MAX_INPUTS`), and a derived value that
  reads one is flagged `inputs`. Their values at other states are not read, so such a value is compared with the
  input at its first value and its disagreements are flagged `reads_inputs`.
- `compare`: for each state the probe read (state 0 is the first read; `sizes` in a listed disagreement are the
  sizes that state changed), the derived value of each key (the formula over the state's size values, else the numbers
  drawn from the solution) against the number read there, within 1e-4 mm. `agree` counts keys that match at every state
  they were compared at, `disagree` the others (the first disagreement of each is listed, at most 12), `never_compared`
  the keys no state gave a read for. `formula_off` lists keys where the formula and the numbers drawn from the solution
  differ at a state. `target_not_read` counts keys of a profile whose first read did not match the capture.
  `measured_fit` counts each key against the measured motion (`probe.motion`): `same` (the same free sizes, both linear
  or both not), `differs` (listed in `measured_fit_listed`), `derived_only` (the measured fit is stuck or did not look
  at the sketch, the derived side has a formula) and `numbers_only` (no formula to compare). Moving a hole or axis
  sketch's plane is not followed: those keys are compared in the frame of the first read.

## 7. API names and what is not verified

Read in the API reference on 2026-11-10: `SketchEntity` (`isReference`, `referencedEntity`, `isLinked`,
`geometricConstraints`, `parentSketch`), `Sketch` (`sketchCurves`, `sketchPoints`, `geometricConstraints`,
`referencePlane`, `parentComponent`), `SweepFeature` (`profile`, `path`, `guideRail`), `PathEntity.entity` (a sketch
curve or an edge), `LoftSection.entity`, `ExtrudeFeature.profile` (a profile, a planar face or an ObjectCollection;
null for a feature that is not parametric), `BRepFace` (no member names the feature that made it, so links are
matched through `body` and `bodies_after`), `CoincidentConstraint` (`point`, `entity`), `ConcentricConstraint`
(`entityOne`, `entityTwo`), `EqualConstraint` and `TangentConstraint` (`curveOne`, `curveTwo`), `ModelParameter`
(`component`, `dependentParameters`, `createdBy`).

Read in the API reference on 2026-11-10 for the tool body readers: `CombineFeature`, `MoveFeature`,
`MoveFeatureDefinition` and its translate, rotate and free move classes, `CopyPasteBody`, `PatternElement`,
`CircularPatternFeature`, `TemporaryBRepManager`, `BooleanTypes`.

Read in the API reference on 2026-11-08: `HoleFeature` (all members above, plus `isDefaultDirection`;
the page says "the extent type of a hole is currently limited to a distance extent" but also lists
`setAllExtent` and `setOneSideToExtent`), `SketchPointsHolePositionDefinition.sketchPoints`,
`SymmetricExtentDefinition` (`distance`, `isFullLength`, `taperAngle`), `DistanceExtentDefinition.distance`,
`ThroughAllExtentDefinition.isPositiveDirection`, `OffsetStartDefinition` (`offset`, `profilePlane`),
`ExtrudeFeature` (members above), `RevolveFeature` (members above), `AngleExtentDefinition` (`angle`,
`isSymmetric`), `PatternElement` (`id`, `isSuppressed`, `transform`, `faces`), `RectangularPatternFeature`
(members above), `ProfileCurve` (`geometry`, `geometryType`, `sketchEntity`), `Arc3D`, `Ellipse3D`, `Matrix3D`
(`getAsCoordinateSystem`, `asArray`, `translation`), `Timeline` (`markerPosition` get and set, `moveToEnd`,
`item`, `count`, `timelineGroups`), `BRepEdge` (`evaluator`, `faces`, `startVertex`, `endVertex`,
`tangentiallyConnectedEdges`, `pointOnEdge`), `BRepFace` (`pointOnFace`, `evaluator`, `geometry`, `edges`,
`tangentiallyConnectedFaces`), `BRepBody` (`volume`, `boundingBox`, `name`, `entityToken`),
`ConstantRadiusFilletEdgeSet` (`edges`, `radius`, `isTangentChain`, `continuity`), `TwoDistancesChamferEdgeSet`
(`distanceOne`, `distanceTwo`, `edges`, `isFlipped`), `ShellFeature` (members above; default `SharpOffsetShellType`).
Read on 2026-11-07: `TimelineObject`, `FilletFeature`, `ChamferFeature`, `CircularPatternFeature`,
`MirrorFeature`, `CombineFeature`, `Sketch`, `Profile`, `ProfileLoop`, `FeatureOperations`.

Read in the API stubs of the installed Fusion (`API/Python/defs/adsk/fusion.py` and `core.py`) on 2026-11-11 for
face outlines: `BRepFace` (`loops`, `geometry`, `evaluator`, `pointOnFace`, `entityToken`, `body`, `area`),
`BRepLoop` (`isOuter`, `edges`), `BRepEdge` (`geometry`, `evaluator`), `Plane` (`origin`, `uDirection`), `Line3D`,
`Arc3D`, `Circle3D`, `Ellipse3D`, `NurbsCurve3D` (`controlPointCount`, `degree`), `Component.features`,
`Features.extrudeFeatures`, `Feature.timelineObject`, `TimelineObject.index`, `ExtrudeFeature` (`startFaces`,
`endFaces`, `sideFaces`; the stub says the start faces of a symmetric extrude are on the positive normal side).

Used by the reach read and not yet confirmed on a real design (see its row below): `Feature.faces` (the faces a
feature created, for each feature type that can be a candidate), `BRepEdge.faces`, `Design.findEntityByToken`,
`Component.findBRepUsingPoint`, `Timeline.markerPosition`, `TimelineObject.entity`. The stub of `Feature.faces` says it
may not return every face the feature made once later steps changed the body; the read takes that into account
(section 2, `reach`).

Not verified (each has a measured check or a test in section 7 of `docs/hand-tests.md`):

| Item | Check |
|---|---|
| Enum value names: `HoleTypes`, `HoleTapTypes`, `FeatureExtentTypes`, `PatternEntityTypes`, the spacing value of `PatternDistanceType` (add-in 0.3.1 looked for `PatternDistanceTypes` and wrote `other`), the rounded value of `ShellTypes`, `Curve3DTypes`, fillet continuity, `ChamferCornerTypes` | the reader maps by name text with a fallback to `other`; the "Capture reader calls to watch" lists in `docs/hand-tests.md` logs unknown names |
| `ProfileCurve.geometry` in sketch space or model space; `ProfileCurve.sketchEntity` and `SketchCurve.geometry` in sketch space | reader decides per profile and writes `space` (`ambiguous` is refused); the Tilted sketch test (offset, tilted, bottom face sketch) |
| `getAsCoordinateSystem()` returns `(origin, xAxis, yAxis, zAxis)` in Python | the Tilted sketch test |
| `CurveEvaluator3D.getParameterExtents`, `getPointAtParameter`, `getTangent`; `SurfaceEvaluator.getNormalAtPoint` | the "Capture reader calls to watch" lists in `docs/hand-tests.md` |
| A flipped one sided extrude stores a negative distance | `end_offset`; the Extrude directions test |
| Taper sign (Fusion positive grows or shrinks) | one constant `FUSION_TAPER_SIGN` in `extrude.py`; the Extrude directions test |
| `ToEntityExtentDefinition`, `TwoSidesDistanceExtentDefinition`, `TwoSidesAngleExtentDefinition`, `FromEntityStartDefinition` field names | reader falls back to `other`; the Extrude directions test |
| Revolve turning sense | `start_face_normal`; the Turned knob test |
| Hole `direction` points into the material; blind depth is measured to the shoulder, not the tip; how a flat drill point shows (`tipAngle` 180 or another member) | `end_points`; the Holes test |
| `patternElements` includes suppressed elements | translator fills missing lattice places from the quantities; the Bin test |
| `entityToken` of a body stays the same across marker positions | a token that changes makes the translator refuse the capture; the Combine test |
| `Timeline.item` walks inside groups; `TimelineGroup.startIndex`, `endIndex` | reader raises `CaptureReadError` when a group child is not in the walk; the "Capture reader calls to watch" lists in `docs/hand-tests.md` |
| Moving the marker marks the document changed or adds undo entries | the Marker and document test |
| New timeline items (the temporary copy) go in at a rolled back marker, and `computeAll` leaves the marker in place | the copy is checked for a body, the marker is put back after each recompute and at the end; the Marker rolled back tests |
| `isRollingBallCorner` still on `FilletFeature` (some fillet members are retired) | reader reads it in a try, default true; the Bin test |
| The members in the `params` table return a `ModelParameter` (name, expression, value): `DistanceExtentDefinition.distance`, `taperAngleOne` and `taperAngleTwo`, `OffsetStartDefinition.offset`, the `HoleFeature` size members, `ConstantRadiusFilletEdgeSet.radius`, chamfer set distances, `insideThickness`, pattern `quantityOne`, `distanceOne` and the circular ones | a member that is not one adds nothing and the value stays a number; the sizes hand test logs which members gave a parameter |
| `Sketch.entityToken`, `Sketch.referencePlane`, `ProfileCurve.sketchEntity.entityToken`, `entityToken` of sketch points, lines, construction planes and axes; the sketch curve tokens staying the same after a recompute | the probe compares its first state with the capture and fixes the sizes of a sketch that does not match; the Sketches that follow sizes tests in `docs/hand-tests.md` |
| `Design.findEntityByToken` for a sketch of a component inside an occurrence (native object, proxies, or both) | `read_state` takes the match without `assemblyContext`, else the `nativeObject` of the first |
| `ModelParameter.createdBy` kinds and `name` for a sketch dimension | the kind comes from the type name; the sketch rule needs only the kind |
| `ToEntityExtentDefinition.entity` and `FromEntityStartDefinition.entity` give the picked face (`BRepFace`, read for `pointOnFace`) or construction plane | an unreadable face point fixes the sizes written before the extrude; the "Pick points that follow sizes" hand test |
| `BRepBody.nativeObject`, `BRepBody.assemblyContext` of a picked body inside a component; `Feature.assemblyContext`, `Feature.nativeObject` of timeline entities | the target is the native body and a proxy entity is turned native; `entity_context` logs when it was a proxy; the "Bodies inside components" hand tests |
| `Occurrence.transform2` of a nested proxy is relative to the root or to the parent | `placement.source` says which candidate passed the point check (`transform2` or `path_transform2`) |
| Vertex and face point geometry of a proxy body is in root coordinates, of the native body in component coordinates | the point check; a mismatch gives `placement.error` and a fixed shape |
| `Occurrence.isReferencedComponent`, `Component.allOccurrencesByComponent` | `linked` and `uses`; a wrong value only changes a note or refusal |
| `Sketch.transform`, `SketchPoint.worldGeometry` of a native component sketch are in component coordinates | the "Nested and turned" hand test compares one hole position |
| `Occurrence.sourceComponent` and `Occurrence.assemblyContext` of a timeline occurrence; `ConstructionPlane.component` | the item `component`; the "Bodies inside components" hand tests |
| Feature inputs (profiles, edges, planes, faces) of a component feature come as proxies through the occurrence; `nativeObject` gives the component's own entity | records of the target's own inputs carry no `foreign`; the "Bodies inside components" hand tests |
| `OffsetFacesFeature.inputFaces` (or `faces` before the item), `distance`, `faces` after it; `BRepFace.loops`, `BRepLoop.isOuter`, `BRepLoop.edges`, `Plane.uDirection`; positive distance moves the face outwards | `faces_after` must show the face moved by `distance`; the Offset faces hand test |
| `EmbossFeature.profiles` (`Profile` and `SketchText` items; the area of a text is computed from its outlines), `inputFaces`, `faces` after the item, `isTangentChain`, `depth`, `horizontalDistance`, `verticalDistance`, `rotationAngle`; `BRepFace.area`, `BRepFace.body`; a positive `depth` raises and a negative one sinks; the feature exists only in Fusion builds from September 2025 and is marked preview in the API reference | `volume_after` must differ from `volume_before` by `sum(areas) * abs(depth)` with the sign of `depth`, else the translator refuses; the Emboss hand tests (section 10 of `docs/hand-tests.md`) |
| `SketchText.asCurves()` returns the text outline as closed `Curve3D` loops (lines, arcs, free curves) without changing the design; the points are in sketch or model space; `SketchText.boundingBox` is in sketch space | `space` is decided by the bounding box and `ambiguous` or a failed read gives a text marker; an emboss checks the text area against the measured volume; the Text hand tests (section 11 of `docs/hand-tests.md`) |
| Free curves (`NurbsCurve3D`, `EllipticalArc3D`) evaluate through `CurveEvaluator3D.getPointAtParameter` over `getParameterExtents`, and `getTangent` gives the direction at an end | a curve that cannot be evaluated has no samples and is refused; a missing tangent is left out; the Spline hand tests (section 11 of `docs/hand-tests.md`) |
| `Sketch.parentComponent`, `ConstructionPlane.component`, `BRepFace.body`, `BRepEdge.body` | `foreign` reads them in a try; an unreadable one leaves the record unmarked |
| `SketchEntity.referencedEntity` of an entity projected from another component comes as a proxy whose `assemblyContext.component` is that component (confirmed by a real export: the pipe component was found); the `body` of such an edge and its `nativeObject` token equal the token `bodies_after` gives; `lineOne`, `lineTwo`, `line` and `curve` name the entities of the other line constraints; `ModelParameter.createdBy` of a parameter that `dependentParameters` gives names the same maker as when the parameter is listed from its component (`ModelParameter.component` answered the root for every one); `profile`, `path`, `guideRail`, `loftSections` and `holePositionDefinition` can be read with the marker before a step of another component | a wrong read only leaves a link out; the discovery tries still find a parameter that moves the part; the K10 hand test in `docs/hand-tests.md` |
| `Component.xYConstructionPlane` / `xZConstructionPlane` / `yZConstructionPlane` and `ConstructionPlane.createForAssemblyContext(occurrence)` (in the API reference) show a component's origin planes in the root's coordinates; the three tips 10 mm along the normals fix the occurrence frame | `tool_place` lands the frame on them within 1e-3 mm or records an error; the G tests in `docs/hand-tests.md` |
| The `entityToken` of a tool body's native body equals the token in `bodies_after` of the steps that made it, and `Design.findEntityByToken` finds it with the marker just before the Combine | an unmatched token leaves the steps unread and the Combine refused naming the step; G1 |
| `BRepBody.copyToComponent(proxy)` keeps the assembly place | the copy guard in `step_export.py` compares the bounding boxes (1e-3 mm) and refuses before writing |
| `MoveFeature.inputEntities` (only bodies or only faces) read with the marker before the item; the same bodies found by token after it, with their vertices in the same order | `points_before` and `points_after` are fitted by the translator; a mismatch is refused; the Move hand tests B3 to B5 |
| `MoveFeature.definition` has a class per type, and the type name contains `TranslateXYZ`, `Rotate`, `FreeMove`, `PointToPoint`, `PointToPosition` or `TranslateAlongEntity` | an unknown name reads `other` and the Move is refused; B3 to B5 |
| `xDistance`, `yDistance`, `zDistance` (model parameters in cm) and `isDesignSpace` of a translate move; `angle` (model parameter in radians) and `axisEntity` of a rotate move | a member that cannot be read is null, and the Move is refused; the sign and the space (component or design) come from the fit against the points; B4, B5 |
| `MoveFeatureFreeMoveDefinition.transform` answers for a free move | null when it cannot be read; the fit against the points decides alone; B3 |
| `CopyPasteBody.sourceBody`, an `ObjectCollection` in the API stubs, can be read with the marker before the item (and is empty or shorter when a source was consumed), `CopyPasteBody.bodies` after it, also when the source lives in another component | empty `sources` or null `result_bodies` refuse the Paste; B2, B8 |
| `inputEntities` of a rectangular, circular or mirror pattern of bodies with the marker before the item, `bodies` after it holding every copy (not the sources) | null `result_bodies` refuses the pattern; copies are matched to the elements by the points; B6 |
| `BRepBody.vertices` and `BRepVertex.geometry` of the native body: the first 8 in a stable order across a paste, a move and a pattern copy | fewer than 3 usable points refuses the fit; B2, B3, B6 |
| `BRepBody.volume` of a tool body with the marker before the Combine, and of any body the second pass finds by token (`Design.findEntityByToken`) | null in `tools[].volume` and `body_states`; the volume checks on a tool are left out; B1, B9 |
| `TemporaryBRepManager.get()`, `copy(body)`, `booleanOperation(targetBody, toolBody, booleanType)` (changes the target body in place and answers true or false), `BooleanTypes.IntersectionBooleanType` and `UnionBooleanType`, and the `volume` of a temporary body; none of it changes the design | any exception or a false answer gives null `intersect_volumes` and `intersect_model: unknown`, which refuses the Combine; B7 |
| Face outlines, to confirm by hand: `ExtrudeFeature.profile` gives the `BRepFace` with the marker before the step; `BRepFace.loops`, `BRepLoop.isOuter`, `BRepLoop.edges` and `BRepEdge.geometry` give the edges in the component's coordinates; `BRepEdge.evaluator` covers only the edge; `Plane.uDirection` lies in the face; `BRepFace.evaluator.getNormalAtPoint` points out of the body; `BRepFace.area`; `Component.features.extrudeFeatures` lists the earlier extrudes and `Feature.timelineObject.index` their places; `startFaces`, `endFaces` and `sideFaces` of an earlier extrude, read with the marker before the step, hold the face the step uses (the same entity or `entityToken`); a positive distance goes along the outward normal | a face that cannot be read refuses the step; a face no extrude lists is copied as measured with its sizes marked; `end_offset` and `side_leans` check the direction and taper; hand test F1 in `docs/hand-tests.md` |
| Reach, to confirm by hand: `Feature.faces` of the entity of a timeline item, read with the marker right after the step, lists every face that step created, and read with the marker just before a later step it still gives the same faces (the same entity or `entityToken`) as the ones a later pick finds through `BRepEdge.faces`, `findEntityByToken` or `findBRepUsingPoint`, for each feature type that can be a candidate (extrude, revolve, sweep, loft, round, chamfer, shell, pattern, combine, move); whether the list of a Move, a Combine join and a draft is empty; whether a face a later step trimmed or split drops out of the list; `Component.findBRepUsingPoint` with `BRepFaceEntityType` finds a face from a recorded point | a list that is empty, shorter than right after the step or unreadable counts as reached by every pick, a pick that cannot be found counts as reached, and the translator then leaves the later step out (safe side); hand tests L2, L3, L5 and L14 in "Check first in this version" of `docs/hand-tests.md` |
| An intersect with several tools keeps the part and every tool, or the part and any tool | measured per export from the volumes and written as `intersect_model`; B7 |
