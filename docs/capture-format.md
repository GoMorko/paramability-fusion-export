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
  "addin": "0.13.0",
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

`addin` is the version of the add-in that read the capture (from its `.manifest`). It is optional: captures read
before it was kept do not have it, and the replay of a saved report or package takes it from the report's `writer`
text. The translator reads it only to tell an export of an add-in before 0.10.6 (see "Old exports" in the part on
other components).

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
in Fusion's internal cm and radians, unit, kind (`derived` only when the expression reads another parameter, calls
`random` or cannot be read; a formula of plain numbers such as `3 * 0.4 mm` has the kind of its unit), favourite,
dependency lists, and for model parameters `role` and
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
  `lib/capture_model/step_kinds.py`). Feature readers run only for items in the target's component, plus the second pass
  below for the steps of a Combine's tool bodies from other components; the other items keep `"data": {}` with their
  `bodies_after`, health and message.
- `helper_of`, `helper_unread`, `body_states`: only on items that made a body a Combine of the target (or of a body
  the target was split from, before that split) takes as a tool, or a body such a tool is copied from (see
  CombineFeature in section 5). `body_states` is also on the steps that built
  a body the target was split from, up to that split (SplitBodyFeature in section 5): the translator reads those
  steps with these measures, as steps of the target, so a draft or a Split Face before the split is checked. `helper_of` (items of another component):
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
  every item, also one with no reader (`"data": {}`: a coil), so a step the copy leaves out still says where
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
(`holePositionDefinition.sketchPoints`, or `sketchPoint` for one point). It is read with the marker before the item and reads no geometry. The key
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
3. `via: "component"`: otherwise, when the link's component is one it acts on;
4. `via: "assembly"`: otherwise, when it acts on an item that may place an occurrence (`design_model.step_links.places_occurrence`: a
   dependent of kind `joint`, an assembly item of the timeline, or a Move whose `input_kind` is not `bodies` or
   `faces`). The capture does not say which occurrence the item places, so every link to another component counts.

Tokens are compared, names only when a token is missing. The export works with the sketches the picked body's own
steps use (`body_scope.body_links`), and the translator, given a size table without links, takes them from the whole
capture. A link is `{ "param", "sketch", "component", "via" }` (the component's name). Such a parameter is ticked to
start with like one the body reads, the size probe tries it like a size behind a sketch dimension, and the translator
counts it as a size the sketch reads (`design_model.reach.sketch_sizes`, section 5). The link only makes it worth trying; the
probe decides.

A step can also use a plane, axis, direction or point of another component directly (measured references, "Measured
references", section 4). A user parameter that acts on the component that owns such a reference gets a link `{ "param", "sketch": "", "component", "via": "reference", "step", "ref" }` once per
component (`reference_links`; `step` is the step's name, `ref` the key of the first reference). A user parameter that
may place an occurrence (`places_occurrence`) gets the same link with `via: "assembly"` for every component whose
reference moves with its occurrence: not a reference of the target's own component, and not one marked `own`. It is
offered, ticked to start with and probed like a sketch link; the offer text says which step uses which component,
and for `assembly` that the parameter may move that component in the assembly.

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
  target's component, `other` one in another component, `none` a reference with no source (not parametric). A
  projection of the origin point (`Component.originConstructionPoint`), an origin axis or an origin plane of the
  component named in `component` also has `"origin": true` (`placement.is_component_origin`). A projected origin of
  the sketch's own component sits still in the sketch when the export can show that no ticked size moves or turns
  the sketch plane (`design_model.reach.plane_fixed`, `sketch_solve.constants.own_origin`); otherwise it stays a
  measured input like other projected geometry.
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
or stopped because the part holds more gaps than it may (`lib/export_plan/reach_pass.py`; the capture is then
translated again with it, and the gap cap applies to that translation):

```json
"reach": { "read": true, "gaps": [12], "makers": { "17": [12], "19": [12, 17] }, "moves": 3 }
```

or `{ "read": false, "error": "<reason>" }` when the read failed.

- `gaps` are the steps the read was asked about: the steps the first translation left out for their own reason (verdict
  `leftOut` with `cause: "own"`, also inside the `tool_steps` of a Combine). A step left out only because it may pick
  faces of another gap (`cause: "picks"`) is not one of them; the read tests it as a picking step.
- `makers` has one entry per later step that was tested: the key is the item `index`, the list holds the `index` of
  each candidate step that made, or may have made, a face the step picks. Candidates are the steps of `gaps`, the
  steps that built the bodies a step among them takes (the tools of a Combine, the source of a Paste, the source
  bodies of a pattern, and the bodies behind those, by the same rules as the reading pass, `tool_items.built_by`;
  reported under the index of that step of `gaps`), and every later step that picks geometry, without items that make
  no body (sketches, construction geometry). Only steps after the first
  step of `gaps` are tested, and a step of `gaps` is not tested.
- Which items pick geometry is decided by `capture_model.gap_picks.pick_records(item)`: the edge records of rounds and
  bevels, and face records with a token, a point or loops (shell and offset faces, the face inputs of a round). These
  are the picks the copy writes as measured points. A face given only by a `face_point` (an emboss face, a face an
  extrude starts from or reaches to) and a face used as an outline are not picks: the copy writes them as numbers or
  shifts and marks the sizes it cannot follow. Lists of bodies and of the faces a step made (`faces_after`,
  `tangent_faces`, `end_points` and the like) are not picks either.
- `Feature.faces` lists the faces a step made, but only all of them with the marker right after the step: the API
  says a later change to the body can take faces out of the list. So the reader reads each candidate's list with the
  marker right after it, and moves the marker to just before each tested step to compare each picked
  face (for an edge: each face it joins, found by `BRepEdge.faces`) with the candidate's list at that point. A face is
  found by its entity token, or by `Component.findBRepUsingPoint` at the recorded point. A candidate counts as reached
  by every pick when its list is empty (a Move, a Combine, a draft may list none), shorter than right after the step,
  or cannot be read; so does every candidate when a pick cannot be found. More than 100 tested steps or 200 candidates
  give `read: false`, and so does any other failure of the read. The marker goes back to where it was at the end, with the same check as `read_capture`
  (`MarkerError` when it does not read there).
- `moves` is how many times the read moved the marker, not counting the move back. The marker goes forward once over
  the positions it needs: right after each candidate that a later tested step may compare, and right before each
  tested step; a position that is both is visited once. A face's token is read once per position, not once per pair
  of faces. `report.json` keeps it in `reach`.
- The translator (`gap_picks.picked_gaps`): a later step that picks faces of a left out step is left out too, with the gap
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
   (profiles, edges, faces, tool bodies, the target box before it). One recompute per item. Between two quiet steps
   of another named component the target is not measured (a quiet step is of a type the step kind table lists without
   `reaches_bodies` and does not belong to the root component; a Combine, a Move or a Split Body is measured on both
   sides, so a change it makes is seen even when a later step undoes it): a run of quiet steps is measured once before
   and once after,
   and when the target reads the same on both sides every step of the run gets `target_changed` false with those
   numbers. When it does not (or a measure failed), the walk goes back over the run and measures each step, so the
   capture is the same as with a measure at every position.
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
`Sketch.referencePlane`; `token` is empty for a plane without one). A construction plane of the body's component
also says what it is: `origin`, or `made_by`, `definition` and `built_on` as in a mirror plane record
(`read_reference.describe_plane`). Each curve also gets `entity`, the token of its
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

The translator (`lib/translator/sketch/face_outline.py`) copies an extrude or emboss of one such face. When the size probe
read the face before its step at every try (`Motion.faces` names its `token` under `<item>/face`, "Probe states"), its
loops and plane are written as formulas of the sizes from the keys `<item>/face/l<loop>/<field path>` and
`<item>/face/plane`; a size whose move no formula fits (stuck, or an edge along a curve) is marked by the value it
moves, a size that may change the face but was not tried is marked with the reason below, and a size that does not
move the face is not marked. The plane is one distance along the face normal, so a curved formula of it (a wall set
back along a half angle) is written as fitted. Otherwise the rules below apply. Sketch outlines may
come with it when they lie on the face plane; the face is then written as measured (with the probe's reads, only the
sizes that moved the face or were not tried are marked). When `made_by` names the
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
when the plane test below does not decide, the points are compared with `SketchText.boundingBox` (sketch space) and
the record is a marker when both readings fit or neither does. In Fusion 2706 `asCurves` gives sketch space points
(lines and degree 2 NURBS curves for a TrueType font such as Arial), so text on a face of the part reads as `sketch`
by the plane test. The area of an outline is the area of its chained curves, each curve run in the direction of the
chain. Every text record, outline or marker, carries `text_params` (the name of the text's height
parameter, `SketchText.heightParameter`) or `text_params_unknown: true` when Fusion does not give the name; the sizes
behind them are kept from following the copied letters. A text that cannot be turned into profiles is one record with
`text`, `sketch`, `sketch_token` and a `problem`: `unread` (no curves), `open` (the curves do not close), `overlap`
(two loops cross, as in a script font whose strokes overlap, so holes cannot be told from strokes), `space`,
`too_many` (over 4000 curves or 400 outlines) or `foreign` (a text of another component). The translator refuses a marker with its own reason
(`loops.TEXT_PROBLEMS`), and every size that moves the sketch of a text stays loose or is left out, since the size
probe does not follow it.

`space` says how the curve space was decided: `sketch` or `model` (the reader mapped model space curves into sketch
2D) or `ambiguous`. A curve off the plane z = 0 proves model space. Points all at z = 0 with a sketch frame other
than the identity are read as model points (`Sketch.modelToSketchSpace`): when one of them then lies off the sketch
plane, they cannot be model points and the space is `sketch`. When both readings put the points (at least three, not
on one line) at the same place in the sketch, the choice does not change the outline and the space is `sketch`. Else
the reader compares the curve with `ProfileCurve.sketchEntity` (the box for text); if that cannot decide it writes
`ambiguous` and the translator refuses the profile. A
loop whose chained curves enclose no area is refused.

A profile of another component's sketch is read from its native object, so `loops` are in that sketch's own 2D frame,
and it keeps `"foreign": true`. Fusion hands such a profile over in two ways: through that component's occurrence
(`nativeObject` gives the native profile), or native, without an occurrence. The second way is the usual one for an
extrude, revolve, loft or sweep made with the operation New Component: the step and its body belong to the new
component, while its sketch stays in the component that was active (often the root). It adds:

- `native_frame`: the sketch frame in its own component's coordinates;
- `frame`: the same frame brought into the target's coordinates through the assembly (that component's `placement`,
  then the inverse of the target's), only when both places can be read;
- `component`: `{ token, name }` of the sketch's component;
- `placement`: like the target's placement (section 2), read for the occurrence the profile came through. Its point
  check compares `SketchPoint.worldGeometry` of up to three native sketch points with the same points made for the
  occurrence (`SketchPoint.createForAssemblyContext`). Without a match it holds `error` and no `frame`. A profile
  handed over native has no occurrence: a sketch of the root gets the root's own frame
  (`{ "path": "", "frame": identity, "source": "root", "checked_points": 0 }`), and a sketch of another component
  is placed through the one occurrence of that component (`Component.allOccurrencesByComponent`, then the same point
  check). A component with several occurrences gives `error` (`native_sketch_placement` in
  `lib/fusion_reader/placement.py`);
- `sketch_params`: one `{ name, expression, reads }` per sketch dimension (`Sketch.sketchDimensions`,
  `SketchDimension.parameter`), where `reads` lists every parameter it reads, directly or through others
  (`dependencyParameters`).

The translator copies such a profile like its own when `frame`, `native_frame` and `placement.frame` are present
(`lib/design_model/borrowed.py`: the profile loses `foreign` and the place keys and gets `borrowed`, the name of its
component; it keeps `sketch` and `sketch_token`, so it must never be matched to a sketch of the part by name). The size probe reads the sketch at every state (section 5, "Probe states"), so the
outline follows the sizes through the motion file under the usual keys (`<item>/p<profile>/...`). Where the motion
holds no value for the profile, the outline is written as numbers and every size that may move the sketch becomes a
fixed number (`borrowed.movers`: the sizes that `sketch_params` read, those that act on the sketch's component or on
an item that may place an occurrence, those that may move its plane, and those that may move geometry projected into
it, from its sketch graph found by token); the first translation of an export (no sizes fixed for sketches) skips
that. The step gets a note that
names the sketch and its component. Without the frames and the place the step is refused as before.

Nothing ties such a step to the walls of the part, so it must keep meeting the part as measured
(`lib/translator/faces/meets_part.py`): along the normal of each of its faces, the nearest flat parallel faces of the part
within 2 mm keep their side of the face at every size setting of the range (every mix of the ends for up to 6
sizes, a bounded sample past that), and a face that lies on a wall stays on it. Where a gap would close or open, the sizes it reads stay free over
their ranges and are listed in `loose`, with the values past which the step may stop meeting the part ("past 2.05",
"below 0.98"). Those values come from `lib/translator/ranges/kept_ranges.py`, which finds, without changing any range, the
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
The translator fits the app's spline through points chosen from the samples (`lib/geometry/spline_fit.py`, tolerance
0.005 mm between the points, also where the curve runs between two samples, at most 64 points inside one segment, split into several segments past that, at most 1000 points in a loop).

A `NurbsCurve3D` also carries its exact definition from `NurbsCurve3D.getData` (`read_sketch._nurbs`), when Fusion
gives it and the curve has at most 1000 poles: `"nurbs": { "degree", "knots": [..], "poles": [[x, y], ...],
"rational", "weights", "periodic" }`, the poles in sketch 2D mm like the other points, `knots` the full knot vector
(poles plus degree plus one) and `weights` null unless `rational`. The recipe translator does not read it; the Orca
copy (`lib/orca_translate/splines.py`) draws the curve from it exactly, piece by piece, after checking the pieces
against `samples`.

## 5. Feature data

**ExtrudeFeature** (`operation`, `profile`, `extentType`, `hasTwoExtents`, `extentOne`, `extentTwo`,
`symmetricExtent`, `startExtent`, `taperAngleOne`, `taperAngleTwo`, `isThinExtrude`, `participantBodies`,
`endFaces`, and `faces` for a thin extrude of an open line):

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
  several profiles is copied only when `bodies_after` lists one body (the profiles touch). A feature made with the
  operation New Component belongs to the new component, and Fusion reads its operation back as
  `NewBodyFeatureOperation` (Fusion 2706): the capture of a body of that component reads `newBody`, and its profile
  is a profile of another component's sketch handed over native (section 4).
- `profiles`: section 4. A flat face of a body as the outline is a face record (section 4); the extrude's own
  length, taper and operation are read and followed as for a sketch outline.
- `start`: `{ "kind": "profilePlane" }`, `{ "kind": "offset", "offset": mm }` (`OffsetStartDefinition.offset`),
  `{ "kind": "fromEntity", "plane": PLANE or null, "entity_type": "...", "face_point": [..] }`
  (`FromEntityStartDefinition`, TARGET below). The API does not say which way Fusion measures a `start.offset` that
  is not zero, so `start_offset` decides it (see below). Without it the step is left out.
- `extent_type`: `one`, `two`, `symmetric`.
- EXTENT: `{ "kind": "distance", "distance": mm, "taper_deg": d }` (`DistanceExtentDefinition.distance`, the value
  as Fusion stores it, sign kept), `{ "kind": "throughAll", "positive": bool, "taper_deg": d }`
  (`ThroughAllExtentDefinition.isPositiveDirection`), `{ "kind": "all" }` (a legacy extent with no direction: only a
  measured end face gives one), `{ "kind": "toEntity", "plane": PLANE or null, "offset": mm, "chained": bool,
  "entity_type": "...", "face_point": [..] }` (TARGET below; `chained` is `ToEntityExtentDefinition.isChained`:
  true when Fusion also stops at the faces next to the face, false when it extends the face, null when it cannot be
  read; `face_outline` is the outline of a flat face for which `chained` is not false (`read_face.face_loops`: `{
  frame, loops }`, null when it cannot be read; for a face of another component it is in `ref`, in the part's
  coordinates); `outline_hits_face` is set only for a curved face of the part when `chained` is false: true when a
  ray along the sketch normal from every sample point of every outline meets the face, false when one misses it, null
  when Fusion gives no answer (`read_face_rays.py`, `Component.findBRepUsingRay`, at most 200 rays, with the marker
  before the step); its taper is only in the parameter `side_one.taper_deg` or `side_two.taper_deg`),
  `{ "kind": "other", "type": "..." }`
  (also a distance extent whose `distance` Fusion refuses to give; a symmetric one then has `symmetric` null, so the
  step is left out instead of stopping the copy).
- TARGET (the face or plane of a from or to entity): `plane` from the entity's `geometry` (its origin need not lie on
  the face), `entity_type` the entity's type name (`BRepFace`, `ConstructionPlane`, or null), and for a face
  `surface` (`Plane`, `Cylinder`, `Cone` or `other`, null when it cannot be read; older exports leave it out),
  `face_point` (`BRepFace.pointOnFace`) and `body` (`{ token, name }`, the body it lies on). These keys are optional;
  without `face_point` the translator cannot tell whether the face moves with sizes, and without `body` a step of a tool
  body cannot tell a face of the tool from a face of the part at the same place. For a `ConstructionPlane` or `ConstructionAxis` the record also has `token`
  (`entityToken`), which names the model parameters behind it (`created_by.token`). A construction plane of the body's
  component also has `origin`, or `made_by`, `definition` and `built_on` (`read_reference.describe_plane`). A face of
  the body's component has `token` too, so the size probe can read it again at every try (older exports leave it out).
- `symmetric`: `{ "distance": mm, "full_length": bool, "taper_deg": d }`
  (`SymmetricExtentDefinition.distance`, `isFullLength`, `taperAngle`). A symmetric extrude through all has no
  distance: `symmetric` is null and `side_one` holds `extentOne` when that is a through all extent, with the taper of
  `taperAngle`, so the translator writes a cut through all both ways. A cut through all both ways with a taper, or with
  a taper that cannot be read, is left out; an untapered one marks the sizes behind its taper.
- `target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet.
- `target_flat_faces` (only for a join or new body through all to one side; optional): `[[offset, facing], ...]`,
  one pair per flat face of the target body, with the marker before the item, whose outward normal is parallel to the
  first outline's sketch normal: `offset` is its signed distance (mm) along that normal from the sketch origin,
  `facing` +1 when its outward normal points along the normal, -1 when against it. Null when the body or a face cannot
  be read (`BRepBody.faces`, `BRepFace.geometry`, `pointOnFace`, `evaluator.getNormalAtPoint`;
  `fusion_reader/read_flat_faces.py`). The translator copies a join through all only when the body has material on
  the plane of the measured end (`translator/extrude/through.py`).
- `end_offset`: signed distance along the first profile's sketch `z` from its sketch plane to `pointOnFace` of the
  measured end face, or null. The measured end face is the first face of `endFaces` whose normal is parallel to the
  sketch normal (an end cap), else the first face. Captures made before `end_normal` was read always measured the
  first face. The measured check of the direction and of the length (`design_model/steps/extrude.py`, `end_check`):
  measured from the start (`end_offset - start shift`), the face must lie at the end of the side on its side of the
  sketch within 1e-3 mm (half the length either way for a symmetric extrude). A face nearer than 1e-3 mm to the start
  shows no direction. A side of a cut that ends past the whole `target_box_before` makes no end face of its own, so a
  nearer face on the way of a side is accepted when that same side passes the whole part (the Orca output also when
  the part it built has no material there); the other side does not count. A two sided extrude has faces on both
  sides of its sketch, so the measured face turns its direction only when it lies out of reach of the stored one. A
  side to a face or plane goes toward it, and the measured face does not turn it. A face that is not an end cap
  (`end_is_cap`: by `end_normal`, else by `end_area` against the outline areas within 0.1 % plus 0.001 mm2; no
  answer for a tapered or thin extrude) is not used: the stored direction and lengths stand, and a one way extrude
  whose face would turn the stored direction is left out.
- `start_offset` (only for a start `fromEntity`; null when none was measured): signed distance along the first
  profile's sketch `z` from its sketch plane to `pointOnFace` of the first face of `startFaces` that is parallel to
  the sketch plane. With a `start.offset` that is not zero, exactly one sign of the offset must put the start there
  (within 1e-3 mm), else the step is left out (`design_model/steps/extrude.py`, `start_of`).
- A side up to a tilted or curved `BRepFace` of the body is written as `extent: { upTo: { near: [face_point] } }`
  for an extrude of one side, without taper and without `offset`. A curved face needs `end_offset` on the same side
  of the sketch as `face_point`, `surface` that is not `Plane` or null, `chained` false and `outline_hits_face`
  true; the sizes that may move the face or the outline are then marked. A face without `plane` whose `surface` is
  `Plane` or unknown is left out.
- A side up to a flat face for which `chained` is not false (also a face square to the sketch) is copied only when
  every outline, moved along the sketch normal, lies in the region of `face_outline` (outer loop less its holes, no
  edge of the face crossing it, touching within 0.001 mm; `outline_on_face`); the sizes that may move the face or the
  outline are then marked. See the developer guide, section "Extrudes: a tilted or curved end face,
  a start at a distance from a face, an intersect to two sides".
- `end_normal` (optional; null when it cannot be read): the unit normal of the measured end
  face at `pointOnFace` (`BRepFace.evaluator.getNormalAtPoint`). Older captures do not have it.
- `side_leans` (optional): per face of `ExtrudeFeature.sideFaces` (at most 256), the outward normal at
  `pointOnFace` along the first profile's sketch `z`, which is the sine of how far that wall leans. The taper check:
  a wall that narrows away from the sketch leans its outward normal along the travel; a cut lists the part's walls,
  which face the other way. Every measured wall must match a side of the plan (within 1e-4), and each tapered side
  must have a wall that shows it, else the translator refuses.
- `thin_wall` (only when `thin` is true): `{ "location", "thickness", "location_two", "thickness_two",
  "profile_type" }` from `thinExtrudeWallLocationOne` and `thinExtrudeWallLocationTwo` (`ThinExtrudeWallLocation`:
  `side1`, `side2`, `center`, else `other`; null when unreadable), `thinExtrudeWallThicknessOne` and
  `thinExtrudeWallThicknessTwo` (mm, null when unreadable) and the type name of `ExtrudeFeature.profile` (`Path`
  for an open line). The thickness of side one also names its parameter as `params["thin.thickness"]`. The
  translator copies one closed outline without holes, or one open line (see `path`), one way or symmetric, without a
  taper. Side one and side two are not taken for inside and outside (the API does not say):
  `end_area`, the area of the wall's end face, is compared with the expected area of each side of the outline,
  worked out from its lengths and corners, and decides the side. The area is used rather than the volume change
  because a wall that joins or cuts an existing part overlaps it, while the end face stays the wall's cross section.
- `path` (only when `ExtrudeFeature.profile` is a `Path`, the open line of a thin extrude): the path as a sweep
  path is read (`read_sweep.path_record`, see **SweepFeature**): its sketch curves in path order, each with `flat`
  (the curve in the sketch's own 2D frame) and `opposed` (the path runs against the curve). `profiles` then holds
  one `{ "kind": "other", "type": "Path" }`. Captures of older versions list one `other` record per path
  entity and no `path`; the translator refuses those. The probe follows the path like a sweep path (`PATH` in the
  step kind table). The translator copies a chain of sketch lines of one sketch, each starting where the one before
  ends and none `opposed`, as an `open` loop from the first point to the last, with `thin.ends` square and
  `thin.corners` sharp (recipe version 17; `translator/extrude/thin_line.py`).
- `wall_faces` (only with `path`, after the item; null when `faces` cannot be read or it has more than 64 faces):
  `[{ "surface", "point", "normal" }]` for each face of `ExtrudeFeature.faces`: `surface` as for a face record
  (`Plane`, `Cylinder`, `Cone` or `other`), `point` its `pointOnFace` (mm) and `normal` the unit normal there (null
  when unreadable). Fusion lists no `startFaces` and no `endFaces` for a thin extrude of an open line (Fusion 2706),
  so `end_offset` and `end_area` stay null. The translator builds the wall for each side Fusion's location allows
  and each direction, and copies the step only when exactly one of them holds every face: each face flat, between
  the two ends of the wall, a face across the sketch normal at an end and on the wall's outline, a face along it on
  a side of the outline and square to that side (within 1e-3 mm and a sine of 1e-4). A face that is not so counts
  when it lies on the plane of a face in `target_faces_before` and of a face of the wall, both facing its way (a face
  Fusion merged), and at least one face must be on the wall. That direction must be the one the extrude reader found,
  and side one must be the left of the line and side two its right, whichever way the extrude goes (Fusion 2706).
- `target_faces_before` (only with `path`, for a join or a cut; null when the target body or its faces cannot be
  read or it has more than 512 faces): the faces of the target body before the step (`BRepBody.faces`), as
  `wall_faces` records. `target_faces_body` is `{ token, name }` of that body (null when there is none). The
  translator uses the faces only in the walk that builds that body, not in the walk of a tool body.
- `profile_area`, `end_area` (optional, mm2): the area of the first profile and of the measured end face (see
  `end_offset`). Without
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
  (`lib/geometry/outlines.py`), since Fusion extrudes and tapers their whole region at once. Outlines that stay
  apart are written so that each step touches what is already built (the part, or an outline written before it).
- `bodies_before` (optional, on any item): root bodies at the marker before the item. With it the driver finds a
  body the item made or split off (refused); without it the driver compares `bodies_after` with the bodies the item's
  data names (`participants`, `tools`, `target`).

**RevolveFeature** (`operation`, `profile`, `axis`, `isProjectAxis`, `extentDefinition`, `startFaces`, `endFaces`,
`faces`):

```json
{
  "operation": "newBody",
  "profiles": [ ... ],
  "axis": { "point": [..], "dir": [..] },
  "project_axis": false,
  "extent": { "kind": "angle", "angle_deg": 360, "symmetric": false },
  "participants": [ ... ],
  "start_face_normal": null,
  "end_face_normal": null,
  "made_box": null
}
```

- `axis` from a `SketchLine` (`worldGeometry`), a `ConstructionAxis` (`geometry`, an `InfiniteLine3D`), a linear
  `BRepEdge` (`geometry`, a `Line3D`) or a `BRepFace` that turns about an axis (`geometry`, a `Cylinder`, `Cone` or
  `Torus`: `origin` and `axis`); else `{ "kind":
  "other", "type" }` with the entity type, plus `geometry` (the curve or surface type) for an edge or face, or `error`
  when reading the revolve axis raised. The translator's refusal says which of these the axis is. An axis from a sketch line also has `entity` (the line's token), `sketch_token` and `sketch` (the
  sketch's token and name); one from a construction axis has `token`. Circular pattern axes are read the same way.
- The axis also says what it is, with the keys of a mirror plane record (`entity_type`, `origin`, `face_point`,
  `edge_points`, `made_by`, `definition`, `built_on`; see MirrorFeature below, `read_reference.axis_with_reference`).
  An axis from a sketch line of the body's component also has `sketch_reference`, what its sketch sits on (as a
  profile's `reference`, null when it cannot be read), and `sketch_projected`, true when that sketch holds projected
  curves or points other than projections of its own component's origin point, axes and planes
  (`read_sketch.holds_projection`; null when that cannot be read). Older captures leave these keys
  out; the translators then count the axis as one that may move with every size read before the step (a record
  with `entity` and `sketch_token` counts as a sketch line whose plane and projections are unknown).
- `extent`: `{ "kind": "angle", "angle_deg", "symmetric" }` (`AngleExtentDefinition.angle`, `isSymmetric`),
  `{ "kind": "twoSidesAngle", "angle_one_deg", "angle_two_deg" }`, `{ "kind": "other", "type" }`. For a symmetric
  revolve `angle_deg` is the turn to each side (`RevolveFeatures.setAngleExtent`): the whole turn is twice it, and 180
  degrees or more to each side closes the ring.
- `start_face_normal`, `end_face_normal`: outward normal of `startFaces[0]` and of `endFaces[0]` at its `pointOnFace`
  (surface evaluator), or null when Fusion gives no such face (a full turn, a cap that a join merged into a face of
  the part). `made_box`: `{ "min", "max" }` around the boxes of the faces the revolve made (`faces`), or null. Absent
  for a full turn; older captures have only `start_face_normal`. The measured check of the turning sense
  (`design_model/steps/revolve.py`): the caps decide, and when they do not (a quarter turn ends with the same cap
  normal either way) the made faces must fit the box the outline sweeps one way only. After a join the made faces
  can include faces of the part that the revolve merged with; then the made faces and the body after the step (the
  item's `target_after`) must fit the body before it (`target_before`) together with the swept box. For two sides
  `start_face_normal` is the end face of one side, which tells which side each angle turns to (`back_sides`).

**HoleFeature** (`holeType`, `holeTapType`, `holeDiameter`, `tipAngle`, `counterboreDiameter`, `counterboreDepth`,
`countersinkDiameter`, `countersinkAngle`, `position`, `direction`, `extentDefinition`, `holePositionDefinition`,
`sideFaces`, `endFaces`, `thread`):

```json
{
  "hole_type": "simple",
  "tap_type": "simple",
  "thread_modeled": null,
  "thread": null,
  "diameter": 5.0,
  "tip_angle_deg": 118,
  "counterbore": null,
  "countersink": null,
  "direction": [0, 0, -1],
  "positions": [[10, 10, 10]],
  "extent": { "kind": "distance", "depth": 8.0 },
  "side_cylinders": [{ "origin": [..], "axis": [..], "radius": 2.5, "span": [0.0, 8.0] }],
  "end_points": [[10, 10, 2.0]],
  "end_face_types": ["cone"],
  "participants": [ ... ]
}
```

- `hole_type`: `simple`, `counterbore`, `countersink`. `tap_type`: `simple`, `clearance`, `tapped`,
  `taperTapped`. `thread_modeled`: `thread.isModeled` for a tapped hole, else null.
- `thread`: for a tapped hole, the thread info (the keys of `ThreadFeature` below: `thread_type`, `designation`,
  `thread_class`, `internal`, `right_hand`, `pitch`, `major_diameter`, `minor_diameter`, `pitch_diameter`,
  `angle_deg`) from
  `HoleFeature.tappedHoleInfo` and the hidden thread feature `HoleFeature.thread` (its `threadInfo` and
  `isRightHanded`), plus `full_length` (`thread.isFullLength`, bool or null), `depth` (`thread.threadLength` in mm,
  how deep the thread runs when it is not full length, or null) and `offset` (`thread.threadOffset` in mm, or null);
  every key is null when it cannot be read. With a modeled thread, `made_span` (read after the hole): how deep below
  the mouth of the first hole the vertices of the thread's faces (`thread.faces`) reach along `direction`, `[low,
  high]` in mm, or null. Null for a hole that is not tapped. `params["thread.depth"]` holds the length parameter. A
  modeled thread is copied as a hole at the minor diameter plus an internal `thread` step for each position when its
  faces start at the mouth of the thread and, for a thread over part of the hole, end `depth` below it. The mouth is
  the hole's position, the bottom of a counterbore, or the depth where the cone of a countersink narrows to the
  minor diameter (`design_model/steps/thread.py`, `thread_mouth`).
- `counterbore`: `{ "diameter", "depth" }`; `countersink`: `{ "diameter", "angle_deg" }`.
- `positions`: one point per `SketchPointsHolePositionDefinition.sketchPoints` item, or the one
  `SketchPointHolePositionDefinition.sketchPoint` (`worldGeometry`), else `[position]`. Points of another component's sketch are brought into the target's coordinates; such a hole gets
  `position_refs` (one measured reference per point, slot `positions.<n>`) and no `sketch_token`, `sketch` or
  `point_tokens`, so the size probe leaves the sketch alone. When a point cannot be brought in, the hole is marked
  `foreign`. A hole placed on a face, plane or edge of another component (the `planarEntity`, `edge`, `face` and similar
  members of the position definition) is marked `foreign` and carries `position_refs` too.
- `sketch_token`, `sketch` (optional): token and name of the sketch of the first sketch point.
  `point_tokens` (optional): `entityToken` of each sketch point, same order as `positions`; absent when a token is
  missing or the points sit on more than one sketch. `sketch_frame` (optional, with `point_tokens` only): the frame of
  that sketch (`Sketch.transform`, the keys of a profile's `frame`), so a point's sketch coordinates can be told from
  its position; absent when it cannot be read. The Orca output uses it to let hole centres follow sizes.
  `reference` (optional): what that sketch sits on, the same record as a profile's `reference`
  (`Sketch.referencePlane`); absent when Fusion does not give it (Fusion 2706 gives none for some sketches on a face).
  The Orca output marks the sizes that may move it; a hole sketch without it counts as one on a face of the part.
- `extent`: `{ "kind": "distance", "depth" }`, `{ "kind": "throughAll" }` (also for the `All` kind), `{ "kind":
  "toEntity", ... }` with the record of the face or body the hole goes up to (`entity_type`, `plane`, `face_point`,
  `token`, `body`, `foreign`: the same keys as an extrude's `toEntity` side, plus `chained`), `{ "kind": "other" }`.
  Fusion gives a hole made up to a face or plane a `OneSideToExtentDefinition` (`toEntity`, `matchShape`; no offset;
  a class the API reference marks as retired). The record then has no `offset`, `match_shape` is `matchShape` as
  Fusion gives it (null when not read), and `chained` is null. The reference does not say clearly which value of
  `matchShape` extends the face and which one uses the faces next to it, so `chained` stays unknown until hand check
  93 settles it on a face. A reader treats `chained` null on a face as "Fusion may use the faces next to it"
  (`design_model/steps/extrude.py`, `joins_next_faces`). A hole with a `ToEntityExtentDefinition` gives `offset` (mm,
  null when not read) and `chained` (`isChained`, null when not read). An `offset` that is not zero or is null
  leaves the hole out. A hole up to an entity is copied as a blind hole of the depth measured from `end_points` (flat
  ends only, all holes of the step at the same depth, each end on the plane of the face or construction plane it goes
  up to: `design_model/steps/hole.py`, `to_face_depth`); the depth follows the face with
  `translator/faces/follow.py`. Fusion lists no `endFaces` for such a hole, so `end_points` and `end_face_types` come
  from the faces the hole made (`faces`) that are not `sideFaces`, told apart as entities (`same_entity`), not by
  their tokens.
- `side_cylinders`: every `sideFaces` item whose geometry is a `Cylinder` (`origin`, `axis`, `radius`, and `span`:
  `[low, high]` in mm of the face's vertices along `axis` from `origin`, or null). The far end of the cylinders on a
  hole's axis line is where a hole through all comes out of the part (`design_model/steps/hole.py`, `through_ends`).
  The narrowest one is the drill size of a tapped hole (Fusion drills it at the thread's minor diameter, which can be
  wider than `diameter`). A capture without `span` gives no exit, so the thread of a tapped hole through all is left
  out.
  `end_points`: `pointOnFace` of each `endFaces` item that is a `Plane` whose `normal` lies along `direction`, or a
  `Cone` whose `axis` does. Fusion also lists the helical faces of a modeled thread as end faces; they are left out.
  A hole through all has no end face. `end_face_types`: `"plane"` or `"cone"` for each of those faces, one per
  `end_points` entry; a flat or tipped bottom is decided from it, not from `tip_angle_deg`. Captures of earlier
  versions kept every end face, with `null` for another type. Measured checks of direction, count and diameter.

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
  `variable` (`VariableRadiusFilletEdgeSet`: `start_radius`, `end_radius` from `startRadius`, `endRadius`, and
  `mid_count`, the number of `midPositions`), `chordLength` (`ChordLengthFilletEdgeSet`: `chord_length` from
  `chordLength`), `asymmetric`, `other`. `continuity` is read for every kind but `other`. A value that cannot be
  read is null. The parameters are in `params` as `sets.<n>.radius`, `sets.<n>.chord_length`,
  `sets.<n>.start_radius` and `sets.<n>.end_radius`. Captures of add-in 0.13.0-preview.9 and older have none of the
  `variable` and `chordLength` keys.
- The reader expands the input: a face gives its `BRepFace.edges`; a tangent chain gives
  `BRepEdge.tangentiallyConnectedEdges`. A feature as input is listed in `input_kinds` as `feature` and not
  expanded.
- How the set picked its edges: `tangent_chain` is `isTangentChain`; with it on, each EDGE that was an input of the
  set (not one the chain added) has `"seed": true`. `faces` lists the face inputs, as the shell's `faces` records
  (`point` is `BRepFace.pointOnFace`); it is absent when the set has no face input or a face cannot be read. Captures
  of add-in 0.5.0 and older have none of these keys.
- A set whose inputs cannot be read (`edges` of the set raises) has `read_error` with the message, an empty
  `input_kinds` and an empty `edges` list; its kind, sizes, `tangent_chain` and parameters are read as usual. The
  other sets of the step are read as usual. Fusion 2706 does this for a face picked with Tangent Chain on that has no
  tangent neighbours. Captures of add-in 0.14.3 and older give the whole item `read_error` instead.
- EDGE: `{ "token", "closed": bool, "points": [[..]] }`. `points` holds the middle point for an open edge and the
  points at 0.25 and 0.75 of the parameter range for a closed edge (`startVertex` equal to `endVertex`), from
  `BRepEdge.evaluator`. A fillet or chamfer EDGE also has `box`, the box of the edge (`BRepEdge.boundingBox`,
  `minPoint` and `maxPoint`), and a fillet EDGE has `turn_deg`, the largest angle (degrees) between the outward
  normals of the edge's two faces (`BRepEdge.faces`, `SurfaceEvaluator.getNormalAtPoint`) at 0, 0.25, 0.5, 0.75 and
  1 of its parameter range. The translator uses them to tell whether two sets of one step lie apart
  (`docs/developer-guide.md`, "Sets of one step copied one after the other"). Each is absent when it cannot be read,
  and in captures of add-in 0.14.3 and older.
- An EDGE of a `variable` or `chordLength` set also has `curve`, the type of `BRepEdge.geometry` (`Line3D`, `Arc3D`,
  `NurbsCurve3D` and so on), and `samples`: one record per place along the edge, at 0, 0.25, 0.5, 0.75 and 1 of its
  parameter range (a closed edge leaves out 1):

  ```json
  { "at": 0.25, "point": [..], "tangent": [..], "sides": [[a], [b]], "radius": 1.5 }
  ```

  `point` and `tangent` (a unit vector) come from `BRepEdge.evaluator` (`getPointAtParameter`, `getTangent`).
  `sides` (`chordLength` only) are the outward normals of the edge's two faces at the point, as for chamfers. After
  the item, `radius` is the radius across the edge of the round face nearest to the point (`FilletFeature.faces`;
  `getParameterAtPoint`, `getPointAtParameter`, `isParameterOnFace`, then `SurfaceEvaluator.getCurvature`): of the
  two main curvatures there, the one whose direction lies more across the edge than along it, as 1 / curvature in
  mm; null when it cannot be measured. A `chordLength` EDGE also has `side_faces`: per face of the edge
  `{ "face_point", "surface", "normal" }` (`pointOnFace`, the surface kind, the outward normal there), which
  `design_model/edges.py` matches to the extrudes that made them. A `Cylinder` or `Cone` face also has `axis`, the
  unit direction of `Cylinder.axis` or `Cone.axis` (null when it cannot be read); the translator uses it to tell a
  face the edge goes round from one that curves across the edge. An EDGE whose samples cannot be read has none of
  these keys.

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
{ "faces": [{ "token": "...", "point": [..] }], "bodies_input": false, "inside": 2.0, "outside": 0.0, "shell_type": "sharp",
  "volume_before": 8000.0, "volume_after": 5200.0 }
```

`faces[].point` is `BRepFace.pointOnFace`; tangent chains expanded with `tangentiallyConnectedFaces`;
`bodies_input` true when the input is a body (a closed hollow). `shell_type`: `sharp`, `rounded` or `other` (a name
that is not known, or a member that cannot be read). `inside` and `outside` are in mm. Fusion gives no parameter (None,
not an error) for the side that has no wall, so an inward shell has `outside: 0.0` and an outward shell `inside: 0.0`.
A side is null only when its member raises or is missing, and the translator leaves such a shell out
(`read_finish._shell_side`). `volume_before` and `volume_after` are the target body's volume in mm3 before and
after the step (`read_geometry.target_volume`; null when it cannot be read); the translator checks that the shell
made the part smaller (inward) or changed it (outward).

**DraftFeature** (`inputFaces`, `isTangentChain`, `plane`, `isDirectionFlipped`, `draftDefinition`; read in
`read_finish.py`):

```json
{ "faces": [{ "token": "...", "point": [..], "box": BOX }], "tangent_chain": false, "plane": PLANE, "flipped": false,
  "two_angles": false, "symmetric": false, "angle_deg": 3.0, "angle_two_deg": null,
  "volume_before": 8000.0, "volume_after": 7900.0 }
```

- `faces` as for a shell, each with its box (`BRepFace.boundingBox`); `plane` with the keys of the mirror `plane`.
- `draftDefinition` is an `AngleExtentDefinition` (`angle`, `isSymmetric`: the faces are split at the plane and lean
  away from it on both sides) or a `TwoSidesAngleExtentDefinition` (`angleOne`, `angleTwo`; `two_angles` true).
  `params` holds `angle_deg` and `angle_two_deg`.
- `volume_before` and `volume_after`: the target's volume around the item.

The translator (`lib/translator/finishes/draft.py`) writes the recipe's `draft` step with the faces as `near` points, the
plane as `neutral` (its normal is the pull direction) and the angle as a size; the size ranges are cut where the
angle would reach 30 degrees, and two angles from different formulas stay a number with their sizes marked. Fusion's sign and flip are not
documented, so the sign is read from the part: with every face on one side of the plane, a draft that removes
material takes it off there (a positive recipe angle on the side the normal points to). A Symmetric draft with faces
on both sides of its plane leans both sides away from the plane (or both toward it) by the same angle, so the sign
comes from the change of volume alone and the step carries the angle twice: `angleDeg` and `angleTwoDeg` (recipe
version 17). A draft with faces on both sides of its plane that is not Symmetric, a Two Sides draft with two different
angles (the API does not say which angle belongs to the side the pull direction points to) or with faces on both
sides, an angle of 30 degrees or more, or no measured change of volume is left out.

**RectangularPatternFeature** (`patternEntityType`, `inputEntities`, `directionOne`, `directionTwo`,
`directionOneEntity`, `directionTwoEntity`, `quantityOne`, `quantityTwo`, `distanceOne`, `distanceTwo`,
`patternDistanceType`, `isSymmetricInDirectionOne`, `isSymmetricInDirectionTwo`, `patternElements`,
`suppressedElementsIds`):

```json
{
  "entity_type": "features",
  "sources": [4, 5],
  "direction_one": [1, 0, 0], "quantity_one": 3, "distance_one": 20.0,
  "direction_two": null, "quantity_two": 1, "distance_two": 0.0,
  "distance_type": "spacing",
  "symmetric_one": false, "symmetric_two": false,
  "elements": [{ "id": 0, "suppressed": false, "frame": FRAME, "faces": [FACE, ...] }, ...],
  "suppressed_ids": [],
  "source_faces": [FACE, ...]
}
```

`FACE` is `{ "center": [x, y, z], "area": 94.2 }`: the centroid of a face in mm (`BRepFace.centroid`) and its area in
mm2 (`BRepFace.area`).

- `entity_type`: `features`, `faces`, `bodies`, `occurrences`. `sources`: `timelineObject.index` of each input
  feature. A Combine of the target among the sources is repeated by the steps it wrote (its `toolBody` step, or its
  tool's steps written one by one) when every item that built its tools is a source too (`repeat.repeat_sources._combined_tools`;
  the same holds for a circular pattern and a mirror of features). Only some of those items, the items of a tool
  without its Combine, or an intersect Combine refuse the pattern.
- For `entity_type: bodies` (rectangular and circular patterns, and the mirror below) the item also has
  `source_bodies` and `result_bodies`: each a list of body records with `points` (see "Body records" below).
  `source_bodies` come from `inputEntities` with the marker before the item, `result_bodies` from `bodies` with the
  marker after it (null when they cannot be read). `PatternElement` has no `bodies` member, so the translator matches a
  copy to its source and element by the points.
- `distance_type`: `spacing` or `extent` (enum `PatternDistanceType`), `other` when unreadable. The translator then
  takes the kind whose grid holds every kept element.
- `elements`: every `PatternElement` (`id`, `isSuppressed`, `transform` as a frame, and `faces`: up to 8 of the faces
  that element made, `PatternElement.faces`, null when they cannot be read). Only up to 12 kept elements have
  `faces`: all of them in a smaller pattern, else the first three, the last two and copies spread evenly between.
  The face centroids are in the space of the face's own component (a face seen through an occurrence is read as its
  native face); the frames are in assembly space. The ids start at 0 (the original) and
  follow the order of the copies. The transform is not always right: in Fusion 2706 the transform of each copy of a
  circular pattern after the original is one step ahead (hand check CP1). So the translators take the places of
  one-sided circular copies from their ids and check every place against the faces
  (`design_model/steps/pattern_places.py`, developer guide 3.21). The original is the element with the identity
  frame; in a symmetric direction it is not the first one.
- `faces_skipped` (rectangular, circular and path patterns): `"unsafe inputs"` when the elements have no `faces`
  because `PatternElement.faces` is not proven safe for the inputs (it crashed Fusion 2706 for a pattern with a
  Combine among its inputs). Only a pattern of features whose inputs are all holes or one-sided extrudes that make a
  new body, join or cut has the faces of its elements read. Absent when they were read, and in older captures.
- `source_faces` (rectangular, circular and path patterns): up to 32 faces of the original, read with the marker
  before the item: the faces each source feature made (`Feature.faces`), the source faces of a pattern of faces, or
  the faces of the source bodies. Null when they cannot be read, absent in older captures. The frames are in assembly space, so for a
  part placed in the assembly the translator carries them into the component's frame first
  (`design_model/steps/repeat.py`, `data_in_component`, using the target's `placement`). The face centroids stay as
  they are. In a symmetric circular pattern the frames of the
  copies behind the original have been seen as unturned and the one ahead as turned too far, while the part itself
  had them centred; an odd count with every copy listed is therefore taken as centred (`repeat/repeat_circular.py`), but
  only when no copy is suppressed or left out by number (`suppressed_ids`), the original is among the copies and every
  copy turns by a whole number of steps. Otherwise the pattern is refused.
- `symmetric_one`, `symmetric_two`: the copies spread to both sides of the original along that direction (false when
  the flag cannot be read). In a symmetric direction an `extent` distance is the reach ahead of the original, and
  behind it too for an odd count, so the step is `distance / (count // 2)` (`2 * distance / (count - 1)` for an odd
  count); for an even count the copy behind stops one step short. A `spacing` distance is the step as usual. Seen in
  Fusion exports: with an even count the extra copy sits ahead of the original, along `direction_*` (counts 4 and 6 by
  spacing, 8 by extent). A direction whose distance is 0 (Fusion keeps a quantity of 3 in an unused second direction)
  makes copies on top of one another; the translator ignores that direction and merges such copies.
- `direction_one_sketch`, `direction_two_sketch` (optional): `{ "sketch_token", "sketch", "reference", "projected" }`
  when that direction is a sketch line, so the sketch is known to feed a pattern. `reference` is what the sketch sits
  on (as a profile's `reference`) and `projected` is true when the sketch holds projected curves or points; each is
  null when it cannot be read (`read_sketch.sketch_place`). Older captures have only `sketch_token` and `sketch`. The
  translators mark the sizes of the sketch and those that may move its plane; when `projected` is not false, or the
  reference is null or missing, also every size read before the sketch.
- `direction_one_place`, `direction_two_place` (optional): a direction taken from an axis, edge or face of another
  component. The entity is seen in the root's coordinates, so its direction is turned into the target's
  (`direction_one` holds the result) and the place is `{ "assembly": true, "dir": [..], "ref": REF }` (slot
  `direction_one` or `direction_two`, see "Measured references"). When the direction cannot be brought in, `direction_*`
  is null and the place is `{ "foreign": true, "ref": REF }`, so the pattern is refused. The sketch of a foreign sketch
  line is not named in `direction_*_sketch`.
  A direction taken from an edge, a construction axis or another entity of the target's own component (not a sketch
  line, which `direction_*_sketch` names) gets the place `{ "own": true, ...what it is }`: the description of
  `read_reference.reference_of` (`origin`, or `entity_type` with `edge_points`, `face_point`, `token`, `made_by`,
  `definition` and `built_on` as far as Fusion gives them). It holds no `ref`, so it is no measured reference. A
  direction whose entity cannot be described has no place, as in older captures. When the reader cannot tell whether
  the entity belongs to the target's component (the check raised), the place is `{ "unknown": true }`. The
  translators read it through `design_model.edges.direction_sizes`: the sizes that may turn the direction are marked,
  since both write the direction as a number. A direction the pattern uses (more than one copy along it) with an
  `unknown` place, or with neither a place nor a sketch, may turn with every size read before the step.

**CircularPatternFeature** (`inputEntities`, `axis`, `quantity`, `totalAngle`, `isSymmetric`, `patternElements`,
`suppressedElementsIds`):

```json
{ "entity_type": "features", "sources": [4], "axis": AXIS, "quantity": 6, "total_angle_deg": 360, "symmetric": false, "elements": [...], "suppressed_ids": [] }
```

`symmetric` (circular): the copies turn to both sides of the original. It matters for a part turn only; on a full
circle the copies are the ordinary full circle.

**PathPatternFeature** (`inputEntities`, `patternEntityType`, `path`, `quantity`, `distance`, `patternDistanceType`,
`startPoint`, `isFlipDirection`, `isSymmetric`, `isOrientationAlongPath`, `patternElements`, `suppressedElementsIds`):

```json
{ "entity_type": "features", "sources": [3], "path": PATH, "quantity": 3, "distance": 15.0, "distance_type": "spacing",
  "start_point": 0.0, "flip": false, "symmetric": false, "along_path": true, "elements": [...], "suppressed_ids": [],
  "path_place": { "own": true, "entity_type": "BRepEdge", "edge_points": [...] } }
```

`path` is read as the path of a sweep (`read_sweep.path_record`: `closed`, `kind`, `curves` with `opposed`, `edges`,
and for a sketch path `sketch`, `sketch_token`, `frame`, `reference`, `projected`; see SweepFeature below).
`start_point` is where on the path the distance is counted from (0 its start, 1 its end; null outside that range).
`flip`: the copies run toward the start of the path. `symmetric`: the copies spread to both sides of the start point.
`along_path`: each copy turns with the path; false when every copy keeps the direction of the original. `path_place`
is written only for a path of one body edge of the target's component (`read_reference.reference_of`). Each setting
that cannot be read is null, and the handler leaves the step out. `quantity` and `distance` have `params`. The
translator writes a path of one line as a rectangular pattern and a path of one arc or circle as a circular pattern
(`design_model/steps/path_pattern.py`, developer guide 3.14).

**MirrorFeature** (`inputEntities`, `mirrorPlane`, `isCombine`):

```json
{ "entity_type": "features", "sources": [4], "plane": PLANE, "combine": false, "target_box_before": { "min": [..], "max": [..] } }
```

The mirror `plane`, the circular pattern `axis` and the revolve `axis` also say what they are, so the translator can
tell whether sizes move them (`lib/fusion_reader/read_reference.py`). All keys below are optional and are added next to the plane or axis keys
(`point`, `normal` or `dir`, `token`); a record of another component gets none.

- `origin`: true for an origin plane or axis of the component. Nothing else is read then; it never moves.
- `entity_type`: the type name of the picked entity (`BRepFace`, `BRepEdge`, `ConstructionPlane`, `ConstructionAxis`,
  `SketchLine`).
- `face_point` and `surface` (`Plane`, `Cylinder`, ...) of a face; `edge_points` of an edge; `body` (`{ token, name }`),
  the body either lies on, left out when Fusion does not give it.
- Construction geometry also has `token`, `made_by` (the timeline index of the feature that made it), `definition` (the
  type name of how it is defined) and `built_on`, a list of the same descriptions for the entities that definition
  names (up to three levels deep). The definition members read are those of the `ConstructionPlane...Definition` and
  `ConstructionAxis...Definition` objects of the API: `planarEntity`, `planarEntityOne`, `planarEntityTwo`,
  `linearEntity`, `linearEntityOne`, `linearEntityTwo`, `tangentFace`, `circularFace`, `face`, `edgeEntity`,
  `pathEntity`, `point`, `pointEntity`, `pointEntityOne`, `pointEntityTwo`, `pointEntityThree`. An entity of another
  component is `{ "foreign": true }` in `built_on` (older captures leave it out), with the `component` that owns it
  (`{ token, name }`) and `root: true` when that is the root component, as far as Fusion gives them (older captures
  give `foreign` alone).

A reader that cannot read one of these leaves it out. The translators read a missing key as unknown, and unknown counts
as "may move": a plane or axis record without `origin` or `entity_type` may move with every size read before the step,
and construction geometry without `built_on` (none could be read, or the chain is deeper than three levels) counts
as built on the part. Construction geometry with a `{ "foreign": true }` entry in its chain is still the part's own:
a step that uses it does not reach into another component (`refs.is_foreign` does not look into `built_on`), and it
may move with every ticked size (`reach.built_on_other`). The same keys describe a construction plane a sketch
sits on and one an extrude starts from or reaches to (section 4 and TARGET); there a plane without them (an older
capture) marks the sizes that may move it.

`target_box_before`: the target body's box with the marker before the item, or null when it does not exist yet (as
for extrudes).

A mirror of the whole body joined to it (`combine` true) repeats every earlier step when the body lies on one side of
the plane and no cut reaches across it; otherwise (a round, chamfer, shell or Move among the steps, a gap, no
`target_box_before`) the translator gathers the steps into one `toolBody` and mirrors that (`repeat/repeat_mirror.py`).

`plane` from a `ConstructionPlane` (`geometry`, a `Plane`: `origin`, `normal`) or a planar `BRepFace`
(`geometry`). A construction plane adds `token`.

**SplitBodyFeature** (`splittingTool`, `isSplittingToolExtended`, `splitBodies` before the item; `bodies` after it;
`lib/fusion_reader/read_split.py`):

```json
{ "tool": { "kind": "plane", "plane": PLANE }, "extended": true,
  "bodies": [{ "token": "..", "name": "Body1", "box": BOX, "volume": 8000.0 }],
  "pieces": [{ "token": "..", "name": "Body1", "box": BOX, "volume": 2000.0 },
             { "token": "..", "name": "Body2", "box": BOX, "volume": 6000.0, "inside": false }] }
```

- `tool`: a construction plane or a flat face is `{ kind: "plane", plane }`, with the keys of the mirror `plane`; a body
  is `{ kind: "body", body: { token, name, box, volume }, solid }`; a curved face is `{ kind: "surface", type }`
  (the surface type name); anything else (a sketch curve) is `{ kind: "other", type }`.
- `bodies`: the bodies it splits, read with the marker before the item; `pieces`: every body the feature lists once
  computed. Each has its box and volume (mm3, null when unreadable).
- `inside` (a split by a solid body only): whether the piece lies inside the tool body, from
  `BRepBody.pointContainment` of a point 0.01 mm inside the piece under one of its first 16 faces. When no face tells,
  a temporary copy of the piece is intersected with a temporary copy of the tool body (nothing is added to the design):
  a result of about the whole piece means inside, about nothing means outside. A boolean that fails, or a tool and a
  piece seen in different coordinates (one through an occurrence), give null. Null also when neither tells or the tool
  body is not found. It is read with the marker after the item, where Fusion no longer gives `splittingTool`, so the
  tool body is found by the token read before the item. Exports before 0.10.6 have no `inside`.

The translator follows a body that a split made back to the body it was split from (`lib/capture_model/lineage.py`),
for the exported body and for a Combine tool body of its own component (`design_model.tool_chains.lineage_chain`): a piece belongs to the only split body, or to the one whose box holds its box. A split of the body it builds becomes the
removal of the other side (`lib/translator/bodies/split.py`): a cut by a large box beyond the plane, or a cut or intersect with
the tool body. The box reaches four half diagonals of the body plus 100 mm past it, times the largest ratio of a free
size's range end to its value (up to 25; a size past that is marked), so a part the sizes grow is still cut. It stops the copy unless the capture shows the piece is the whole of its side (one side of the plane, or
inside or outside the tool body, with every other piece of that body on the other side), the pieces add up to the
body's volume (within a thousandth: Fusion measures each curved piece on its own, to a few parts in 100 000), and no
later step changes another piece together with the part (`lib/translator/bodies/split_rules.py`, with the facts from
`lib/design_model/roles.py`). A split by a solid
body whose pieces lack an `inside` answer is completed only when the body came apart into exactly two pieces
(`lib/design_model/steps/split.py`): the missing answer is the opposite of the other piece's, else it comes from
the boxes and volumes of the tool and the pieces (a piece that does not fit the tool's box, or is larger than the tool,
cannot lie inside it). The boxes never replace an answer the reader gave: a disagreement stops the copy. With three or
more pieces only the reader's answers count, since part minus tool can leave several pieces on one side. A tool of
another component is not decided this way.

**CombineFeature** (`targetBody`, `toolBodies`, `operation`, `isKeepToolBodies`):

```json
{ "target": BODY, "tools": [BODY, ...], "operation": "cut", "keep_tools": false }
```

Optional `volume_before` and `volume_after` (mm3) hold the volume of the target with the marker before and after the
Combine (`read_geometry.target_volume`; null when it cannot be read). When both are present the translator refuses a Combine that changes the part by more than its tool steps can
fill (`lib/geometry/combine_volume.py`). Each tool also has `volume` (mm3, null when unreadable), read with the marker before the
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

- A tool whose steps only add material (`combine.step.adds_only`: `ExtrudeFeature` and `RevolveFeature` items whose recipe
  steps are `new` for the first and `add` for the rest) is written step by step at the Combine's place with the
  Combine's operation, as long as no tool step reaches to a face when the tool has more than one step or lives in
  another component. An intersect does this only for one tool of one step. The recipe stays at the version it had before tool steps existed.
- Any other tool is written as one `toolBody` step per tool, whose `features` are the tool's steps and whose `combine`
  is the Combine's operation. Its steps are those of rounds, chamfers, cuts, holes, shells, a Combine of the tool
  itself, `move` steps, and a pasted or patterned body (the steps of the source written again).
- Tool bodies nest 3 levels deep (`tool_walk.MAX_DEPTH`); deeper refuses the Combine. The level a tool step adds
  around other tools counts where it is made: the tools of an intersect with the model `any` are walked one level
  deeper, and a pattern of the whole body that gathers the body into one tool step refuses when that would pass the
  limit.
- An intersect with several tools has the model `every` (one `toolBody` per tool, each `intersect`) or `any` (one
  `intersect` step that holds the tools as inner steps, the first `new` and the rest `add`); `unknown` refuses.
- A pattern or mirror of bodies that the Combine takes whole is written as a `pattern` or `mirror` step over the tool
  steps (`body_pattern.groups`, `body_copies.write`); a subset of the copies, or a layout the `repeat` package refuses, is one tool per copy
  with a `move`. An intersect never uses the pattern form. A size the count reads is marked, since it is not known
  whether Fusion adds new copies to the Combine (hand test B6); spacing and angle follow without a mark.
- A later pattern or mirror of features may hold the Combine and the items that built its tools as sources; it then
  repeats the steps the Combine wrote (see RectangularPatternFeature above, hand test F2).
- A Combine whose result differs from the tools' own volumes by more than they can give (`combine_volume.exceeds_tools`
  for tool steps, `exceeds` for steps written one by one) is refused.
- A tool the Combine keeps (`keep_tools`) stays usable: a later Combine walks it again up to its own index. A tool
  the Combine does not keep is used up, and a second Combine that lists it is refused. A Combine that keeps the
  exported body as a tool and changes another body is skipped.
- A tool is refused when a step its walk cannot see may have changed it (`design_model/tool_chains.unseen_change`): a step of another
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
`capture_model/tool_items.py` picks are rolled to: the modeling steps before the Combine whose `bodies_after` list the tool
and that sit in the tool's component (the component a foreign body names, else the one of the item that holds the
body). Tools of the target's own component are planned the same way: their items are
already read, and only `body_states` is added. The Combines of a body the target was split from count like the
target's own, up to the split that made the next body of the chain (`lineage.py`). The plan follows the bodies behind a tool: the source of a Paste
(`sources`), the source bodies of a pattern or mirror of bodies (`source_bodies`) and the tools of a Combine that
changed the tool. A body held by several items is followed up to the latest of them, so steps added to a kept tool
between two Combines are read. Limits: `MAX_ITEMS` 120 steps for the whole capture, `MAX_TOOLS` 32 bodies counted by distinct
sources (the copies of a Paste or a body pattern count as their source, so a pattern of many copies is one), and
source depth 3 (`tool_items.MAX_DEPTH`). Each item of another component gets `helper_of` (the body's token) and
`bodies_before` of its component; their `in_target_component` stays false. An item past a limit keeps its data (empty
for another component) and gets `helper_unread` with the limit as the reason; a body of another component past the
tool limit has `place: { "error": reason }`. An item whose body or place could not be read keeps `data: {}` and gets
`helper_unread` too, unless a later round finds a body it serves whose place can be read and reads its data. A Paste
source or pattern source of another component carries `foreign`, `component`, `path` and
`place` like a tool does (the place is read with the marker just before the item that holds it, slot `tool<n>.<plane>`
with `n` its place in that item's list). The model parameters of the tool component and the components above it are
added to `parameters.model` (names already listed win).

The translator walks the steps of a `helper_of` item when a Combine takes its tool (`tool_walk.build`), like those of
another body of the target's component. The Combine moves them by the tool's frame and the inverse of the exported body's own
(`combine.step.tool_move`, with the move of `design_model.tool_chains.place_of`), plus a move that follows sizes: the offsets of the three origin planes along their normals
(`ref_motion.moves`, formulas of the sizes, or sizes marked loose where the probe could not follow, as for any
reference). A frame that is scaled or mirrored refuses the Combine, naming the component. Slabs of the moved steps are
copied with that move, so picks on them follow sizes; other placers (`faces/moved_placer.py`) answer `material_at` for the
moved points and cannot place a pick on their faces. The Orca output writes the same steps in the tool component's
coordinates and carries the tool with an Orca Transform by that move; it reads no size move and marks the sizes
that act on the tool component instead (`docs/orca-output.md`, "Other components").

**CopyPasteBody** (`sourceBody` with the marker before the item, `bodies` after it):

```json
{ "sources": [ BODY WITH POINTS ], "result_bodies": [ BODY WITH POINTS ] }
```

`sourceBody` is an `ObjectCollection`: `sources` has one record per body in it, and a single body is accepted too. It
is empty or shorter when a source is gone or cannot be read. A source of another component is `foreign` and has the
identity keys of a foreign tool. `result_bodies` is null when `bodies` cannot be read.

The handler (`translator/bodies/paste.py`) walks the source up to the paste (`tool_walk.build`) and writes its steps again,
with ids of their own, in the list of the pasted body. It needs as many sources as results, a result among
`result_bodies`, and a pasted body that has no steps yet. Several sources are paired with the results by their points:
one at the same place first, else one rigid move apart (`design_model/steps/paste.py`, `pair`); a result with no single source refuses. The first vertices of source and result must be the same points (a paste in place) or one
rigid move apart (`design_model/steps/move.py`, `fit`); then a `move` step in plain numbers follows, and the sizes that could change that place
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
- `boxes_before`, `boxes_after`: only when a body in `bodies` has no vertex points (a sphere, a torus, a closed
  revolve). Per body, its `boundingBox` as `{ "min": [x, y, z], "max": [x, y, z] }` in the body's own coordinates,
  null for a body that has vertex points; `boxes_after` is found again by token after the item and is null for a body
  that cannot be found. A box moves exactly with a shift and shows no turn, so the translator checks only a Move that
  shifts against it.
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

The handler (`translator/bodies/move.py`) writes a `move` step in the walk of the body it moves, and refuses a Move of faces
and one that does not map the measured points rigidly (a mirror or a scale). A body with no vertex points is measured
by its boxes: `translateXYZ`, and a `free` transform that only shifts, must move the box by their shift, and any other
Move of such a body is refused (cause `moveUnmeasured`). `translateXYZ`, `rotate` and `free` must
agree with the measured points, and `translateXYZ` and `rotate` write their distances and angle through the sizes. The
other types are written as the numbers of the fit. What they follow can move with any size, so every ticked size is
marked, and the parameters in their `params` are pinned. After the step the walk's
placers are carried by the move, so later picks follow sizes.

**ScaleFeature** (`inputEntities`, `point`, `isUniform`, `scaleFactor`, `xScale`, `yScale`, `zScale`, with the
marker before the item; the bodies again after it; `lib/fusion_reader/read_scale.py`):

```json
{ "input_kind": "bodies",
  "bodies": [{ "token": "t1", "name": "Body1", "box_before": BOX, "volume_before": 8000.0 }],
  "point": { "origin": true, "point": [0.0, 0.0, 0.0] },
  "uniform": true, "factor": 1.5, "factors": null,
  "after": [{ "box": BOX, "volume": 27000.0 }],
  "params": { "factor": PARAM } }
```

- `input_kind`: `bodies` when every input is a body, `sketches` when a sketch is among them, else `other`. `bodies`
  lists the body inputs in every case, each with its box (`box_before`, `{ min, max }` in mm) and volume (mm3)
  before the item; null for a value that cannot be read.
- `after`: per body in `bodies`, its `box` and `volume` with the marker after the item, found again by token (null
  when it cannot be found).
- `point`: the point that stays in place, in the component's coordinates. `{ "origin": true }` for the component's
  origin point. Else `entity_type` (`SketchPoint`, `ConstructionPoint` or `BRepVertex`) and `point`, with `sketch`,
  `sketch_reference` and `sketch_projected` for a sketch point (as for a sketch line axis), `token` and `made_by`
  for a construction point, and `body` for a corner. `{ "kind": "other", "type" }` for anything else, for a point
  that cannot be read and (with `foreign`) for a point of another component. Null when Fusion gives no point.
- `uniform`: `isUniform` (null when unreadable). A uniform scale has `factor` (`scaleFactor`) and params path
  `factor`; one per axis has `factors` (`xScale`, `yScale`, `zScale`, null for one that cannot be read) and params
  paths `factors.0`, `factors.1`, `factors.2`. The factors are plain numbers (Fusion keeps them without a unit).

The handler (`translator/bodies/scale.py`) writes a `scale` step (recipe version 17) in the walk of the body it scales:
`factor` is one value or `[x, y, z]`, through the sizes, and `point` is the measured point. It refuses a scale whose
inputs are not all bodies, a point or factor that cannot be read, a factor outside 0.001 to 1000, a scale before any
written step, factors per axis when the recipe is carried into the assembly by a turn that is not a quarter turn
(`place.axis_turn`; a Combine that carries a tool of another component with such a scale checks its own move with
`place.factors_fit` and is left out), and a scale whose measured volume and box disagree with the factors and the point. The sizes
that may move a point that is not the origin (`reach.reference_sizes`) are marked. After the step the earlier
placers place no picks (`faces/scaled_placer.py`). `place.place` puts per-axis factors on the axes its map turns
them to (the `factors` paths of the step kind table).

Body records (`lib/fusion_reader/read_bodies.py`): `{ "token", "name" }`, `foreign` and the identity keys of a foreign
tool for a body of another component, and `points`: up to 8 vertices in mm of the native body, in the body's vertex
order (empty when one cannot be read, since a gap would shift the order).

**ThreadFeature**: `{ "modeled": false }` for a cosmetic thread (`isModeled`). A modeled thread (read by
`lib/fusion_reader/read_thread.py`) holds:

```json
{
  "modeled": true,
  "thread_type": "ISO Metric profile", "designation": "M8x1.25", "thread_class": "6g",
  "internal": false, "right_hand": true,
  "pitch": 1.25, "major_diameter": 8.0, "minor_diameter": 6.5, "pitch_diameter": 7.19, "angle_deg": null,
  "full_length": true, "length": 10.0, "offset": 0.0,
  "faces": [{ "surface": "Cylinder", "origin": [..], "axis": [..], "radius": 4.0, "span": [0.0, 10.0],
              "face_point": [..], "outward": true }],
  "made_span": [0.0, 9.0],
  "params": { "length": { }, "offset": { } }
}
```

- `thread_type`, `designation`, `thread_class`, `internal` (`isInternal`), `right_hand` (`isRightHanded`), `pitch`
  (`threadPitch`), `major_diameter`, `minor_diameter`, `pitch_diameter` (`pitchDiameter`) and `angle_deg`
  (`threadAngle`, already in degrees): the `threadInfo` members, except `right_hand` (on the feature). Lengths in mm; each is null when it cannot be read.
  `angle_deg` is null when the API gives none: the profile name then decides (metric and Unified are 60 degrees).
- `full_length` (`isFullLength`), `length` (`threadLength`) and `offset` (`threadOffset`); `params` has the length and
  offset parameters. Fusion uses the length and the offset only for a thread that is not full length, and may give
  none for a full length one; a full length thread needs neither.
- `faces`: one entry per `inputCylindricalFaces` item (`inputCylindricalFace` when the collection is missing). A cylinder gives `origin`, `axis`, `radius`, `span` (the end vertices'
  distance along the axis from `origin`), `face_point` and `outward` (true when its normal points away from the axis:
  a bolt; false for a hole wall); another surface only `surface` and `face_point`. A face of another component is
  `foreign`.
- `made_span` (after the step): the same span for the faces the thread made; it tells which end a thread over part of the
  length starts at, and the faces of a full length thread must reach both ends.

The translator writes a recipe `thread` for a metric or Unified thread with a pitch of 0.2 to 10 mm, at most 100 turns
in all and 8 threads, and leaves other profiles, tapered threads and a thread inside a tool body out as gaps
(`threadProfile` and `threadLimits` hints). The step holds `diameter` (major), `minorDiameter` and, from recipe version
17, `pitchDiameter` (mm, the diameter where the ridge is half a pitch wide). The translator writes `pitchDiameter` only
when Fusion gave a value between the minor and the major diameter, and only when the recipe is version 17 or newer for
another reason; it never raises the version, and it removes the field from an older recipe.

**OffsetFacesFeature** (press pull; `inputFaces` (a list or a collection), else `faces`, read before the item;
`distance`; `faces` after it. When no face is readable before the item, `faces` holds the faces of `feature.faces`
read after it: a flat face moved back by `distance`, a cylinder as `{ "kind": "round", "token": "..." }` without
geometry, any other face as `{ "kind": "other", "type": ... }`; so the translator leaves the step out instead of moving only its flat faces):

```json
{
  "distance": 2.0,
  "faces": [
    { "token": "...", "frame": FRAME, "space": "sketch", "loops": [LOOP, ...], "sides": "square", "meets_offset": false },
    { "kind": "round", "token": "...", "origin": [x, y, z], "axis": [x, y, z], "radius": 2.5, "point": [x, y, z],
      "outward": false, "meets_offset": false,
      "ends": [{ "kind": "circle", "center": [x, y, z], "normal": [x, y, z], "radius": 2.5,
                 "face": { "frame": FRAME, "space": "sketch", "loops": [LOOP, ...] } }, ...] }
  ],
  "faces_after": [{ "point": [x, y, z], "normal": [x, y, z] }],
  "rounds_after": [{ "origin": [x, y, z], "axis": [x, y, z], "radius": 2.7 }]
}
```

- `distance`: mm, positive along the outward face normal.
- `faces[]`: a flat face as a profile record (section 4): `frame` is the face plane with `z` the outward normal
  (`SurfaceEvaluator.getNormalAtPoint`) and `x` the plane's `uDirection`; `loops` from `BRepFace.loops`
  (`isOuter`, `edges`, each `edge.geometry` mapped into the frame). A face that is not a plane is
  `{ "kind": "other", "type": "Cylinder" }`.
- `sides`: `square` when every face next to it (`edge.faces`) is a plane across it or a cylinder along its normal,
  else `other`. `meets_offset`: a face next to it is moved by the same step.
- A round face (`Cylinder` geometry): `origin`, `axis` (unit) and `radius` (mm) of the cylinder, `point`
  (`pointOnFace`), and `outward`: true when the outward normal at `point` points away from the axis (a pin or a boss),
  false when it points towards it (a bore), null when the normal cannot be read. `ends` has one entry per loop of the
  face: a loop of one `Circle3D` edge is `{ kind: circle, center, normal, radius, face }`, where `face` is the face
  across that edge: its outline (`frame` with `z` its outward normal, `loops`, as a flat moved face) when it is a
  plane, `{ kind: other, type }` when it is not, null when the edge has not exactly one other face. A loop of more
  edges is `{ kind: other, type: "edges" }`, a loop of one other curve `{ kind: other, type }`, an end that cannot be
  read null. When the axis, the radius or the point cannot be read, the record is `{ kind: round, token }` only.
- `faces_after`: a point and the outward normal of each flat face of `feature.faces` with the marker after the item.
  The translator copies a face only when one of them lies on the face plane moved by `distance`.
- `rounds_after`: `{ origin, axis, radius }` of each cylinder face of `feature.faces` with the marker after the item.
  The translator copies a round face only when one of them lies on its axis with the radius `radius + distance` (a
  pin) or `radius - distance` (a bore). The step is written as `offsetFaces` with one `near` point per face, and
  needs recipe version 17 when it moves a round face.

**CoilFeature** (`roles`, `volumes_before`, `made`, `faces`, `params`; `fusion_reader/read_coil.py`; Fusion's API gives
an existing coil no type, axis, hand, section or operation, so these are worked out from what the reader measures):
- `roles`: the `role` text of every model parameter the coil made. `params`: those of them the translator uses, by path
  (`diameter`, `section_size`, `taper_deg`, `revolutions`, `height`, `pitch`). Which two of the last three are present
  is the coil type; a spiral has revolutions and pitch too.
- `volumes_before`: `{ token, name, volume }` of each body of the component with the marker before the coil. `made`:
  the same for the bodies of `Feature.bodies` after it. They give the operation (`translator/coil/coil_operation.py`).
- `faces`: `{ flat, curved, edges }` with the marker after the coil. `flat` holds the flat end faces as outline records
  (`frame`, `loops`) with their `area`; `edges` holds 17 sampled points (mm) along each edge of the curved faces. Null
  when the faces cannot be read or are more than a coil can have. The translator finds the axis, the hand and the
  turns from them (`coil_fit.py`) and checks that the helix passes through every sampled point.

**PipeFeature** (`path`, `sectionType`, `sectionSize`, `isHollow`, `sectionThickness`, `distanceOne`,
`distanceTwo`, `operation`, `participantBodies` before the item, with the marker before the pipe, the only place
Fusion gives its path; `startFaces` and `endFaces` after it; `lib/fusion_reader/read_pipe.py`; the handler
`lib/translator/sweep/pipe.py` copies a circle section as a sweep):

```json
{
  "operation": "newBody", "participants": [], "target_box_before": null,
  "section": "circular", "section_size": 10.0, "hollow": true, "section_thickness": 2.0,
  "distance_one": 1.0, "distance_two": null,
  "path": PATH,
  "params": { "section_size": {..}, "section_thickness": {..}, "distance_one": {..} },
  "faces_after": { "start": [{ "point": [x, y, z], "normal": [x, y, z] }], "end": [ ... ] }
}
```

- `section` is `circular`, `square`, `triangular` or `other` (`PipeSectionTypes`). `section_size` is the diameter of
  a circle (the side of a square, the height of a triangle) in mm. `section_thickness` is the wall of a hollow pipe in
  mm, measured inward from the size, and null for a solid pipe. `distance_one` is the share of the path the pipe
  covers (1 is the whole path); `distance_two` is null when Fusion gives none (an open path), and
  `distance_two_unread: true` says the member raised. `path` is the path record of a sweep (below). The section sits
  where the first curve of the path starts, in the path's direction (`opposed`), square to the path and centred on it
  (`lib/design_model/steps/pipe.py`).
- A capture without `section` (an export of an add-in that did not read pipes) leaves the pipe out with "Export again
  with this version of the add-in".

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

- `profiles`: sketch profile records (section 4), including the outline records of a `SketchText`, and the outline
  record of a flat face (section 4, with `made_by`). Fusion may give them as a list, a collection or a vector.
  `areas` holds `Profile.areaProperties` of each, in mm2; for a text record it is the area of its outlines (outer less
  holes), computed by the reader, the face area for a face, null for a text marker.
- `faces`: the `inputFaces` the outline lands on. `surface` is `Plane`, `Cylinder`, `Cone` or `other` (from
  `BRepFace.geometry`); `plane` (origin and normal of the geometry), `outward` (`getNormalAtPoint` at `pointOnFace`) and
  `face_point` are null when they cannot be read. A lone face also has `outline`, its edges as an outline record
  (section 4, flat face) for an outline that reaches past it; left out when they cannot be read. `participants` are the
  bodies of these faces.
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

The translator (`lib/translator/extrude/emboss.py`) copies a flat face emboss as an extrude that starts on the face
(`start.kind` is `fromEntity`): `join` for a positive depth, `cut` for a negative one, going out of the face or into
it. The measured `end_offset` decides the direction when it is known. A flat face used as the outline follows the
rules of an extrude from a face (`sketch/face_outline.py`). It refuses a curved face, faces that are not on
one plane, a moved or turned outline, text, a sketch plane tilted to the face, Tangent Chain on (or unreadable) with a
tangent neighbour that is curved or not on the input plane (when the neighbours could not be listed: any curved made
face), and a measured volume change that is not
`sum(areas) * abs(depth)` within 1 percent in the direction the sign of `depth` says. When the change is
`end_area * abs(depth)` with `end_area` smaller than the outlines, the outline reaches past the face and Fusion trimmed
it there: the step is written with `within`, the face's `outline` (holes included, drawn like an extrude from a face),
so the extrude acts only on the face. That needs a lone input face with its `outline`, no flat tangent neighbour while
Tangent Chain is on, and edges the copy can write; otherwise the refusal says why ("reaches past the face it sits on").

**SweepFeature** and **LoftFeature** (`lib/fusion_reader/read_sweep.py`; the handlers `lib/translator/sweep/step.py` and
`lib/translator/loft/step.py` copy the simple cases, and a step they refuse becomes a gap that holds this data):

```json
{
  "operation": "join", "solid": true,
  "profiles": [ ... ], "areas": [120.5],
  "path": PATH, "rail": null, "guide_surfaces": [],
  "orientation": "perpendicular", "distance_one": 1.0, "distance_two": 0.0,
  "taper_deg": 0.0, "twist_deg": 0.0, "scaling": "scale", "extent": null,
  "participants": [{ "token": "...", "name": "Body1" }],
  "target_box_before": { "min": [..], "max": [..] },
  "params": { "distance_one": {..}, "taper_deg": {..}, "twist_deg": {..} },
  "faces_after": { "start": [{ "point": [x, y, z], "normal": [x, y, z] }], "end": [ ... ] }
}
```

- Sweep: `profiles` and `areas` are `SweepFeature.profile` read like an extrude's outline (section 4, a flat face
  included). `path` is `SweepFeature.path`; `rail` is `guideRail` read the same way, null when there is none and
  `{ "kind": "unread" }` when the member raised (the sweep is then left out). `guide_surfaces` is `guideSurfaces`,
  read with the marker just before the sweep: `[{ token, surface, body }]` per face (`surface` as in a face record,
  `body` the body it lies on or null; at most 16), empty when the sweep has none, and `{ "kind": "unread", "said": ...
  }` with Fusion's error text when the member raised or does not exist; older captures have no key. A listed guide
  surface leaves the sweep out ("Sweeps with a guide surface"). Without a list, a sweep whose `unread` names all of
  `orientation`, `twist_deg` and `taper_deg`, with an InternalValidationError for `orientation`, is left out as "likely"
  a guide surface sweep: Fusion answers this way for a "Path + Guide Surface" sweep. Several `profiles` are copied as one
  sweep each along the same path (the first with the sweep's operation, the rest joined to it for a new body), each
  checked on its own without the new body's volume, which Fusion measures for all of them; an intersect or a taper
  refuses.
  `orientation` is `perpendicular`, `parallel` or `other`. `distance_one` and `distance_two` are the unitless
  `distanceOne` and `distanceTwo` (the share of the path the sweep covers on each side of the outline; the translator
  takes 1 and 0 or null as the whole path, and on a closed path also 1 and 1, Fusion's default there, which makes the
  same ring unless it twists), `taper_deg` and `twist_deg` are
  `taperAngle` and `twistAngle` in degrees. `scaling` (`profileScaling`) is `scale`, `stretch`, `none` or `other`.
  `extent` is the `extent` setting as text. Every one of these is null when the member cannot be read or does not
  exist in the running Fusion build, which holds for `extent` in particular. `unread` (only when one of them is null)
  says per key of `orientation`, `taper_deg` and `twist_deg` what Fusion gave instead: the error text of the member,
  `none`, or `unusable <type>`; the sweep's reason names the missing settings and quotes it. `params` follows the usual rules (the
  scalar ones have kind `scalar`).
- Twist and taper (`lib/translator/sweep/step.py`): a twist, a taper or `parallel` along a path that turns makes a `sweep`
  step with `twistDeg`, `taperDeg` and `orientation: "fixed"` (a line becomes a corners path of its two points, an
  arc a flat path). `taperDeg` is Fusion's angle times `TAPER_SIGN` (-1, as for the extrude); `twistDeg` is Fusion's
  angle times `TWIST_SIGN` (1). Fusion does not document either convention, so while `TAPER_MEANING_CONFIRMED` and
  `TWIST_SIGN_CONFIRMED` are false every written twist or taper marks the sizes behind the angle and the outline and
  adds a note. For a new body along a straight path the made volume is compared with the offset and the scaled
  models (`translator/sweep/sweep_taper.py`): a match with the opposite lean flips the sign, a match with the scaled model
  only leaves the step out. Left out: a twist with a taper or `parallel`, a taper with `parallel`, a taper along
  free curves or more than 64 parts, a taper of 45 degrees or more, a twist over 3600 degrees, and a parallel
  outline along a path that turns back past its plane (every tangent must rise at least 0.05 along the outline's
  normal).
- Closed paths (`lib/design_model/paths/closed.py`): a closed chain in one plane becomes a flat path with `closed: true`. The
  chain is cut where it meets the outline's plane nearest to the outline (a line, an arc or a spline sample is split
  in two; a joint is used as it is), turned to start there, and its last segment ends exactly on the start. A sharp
  corner between two lines is mitred, as Fusion builds it (a 3 by 3 mm outline round the 40 by 40 mm top edges of a
  box made the volume of the mitred ring): it may turn up to 160 degrees, and the straight path on each side must be
  at least the outline's reach across the path's plane times tan(turn / 2). A cut at a sharp corner between two lines
  starts the path in the middle of the line the outline is square to instead (the chain is turned round when that
  line arrives at the corner), and the outline is written moved along that line by the same distance. Sharp corners
  next to a curve, and any sharp corner of a twisting path, are left out. The written directions at the seam must
  differ by at most 2 degrees (spline halves are fitted apart). A closed chain that bends in 3D, or a taper or `parallel` along a closed path, is left
  out. A full circle stays a revolve; with a twist it becomes a closed flat path of two half arcs. The twist must be
  whole turns and is written as a number. The overlap check measures the distance along the path round the loop. A
  new body must have the volume of Pappus: the area times the path length less the offset of the outline's centre
  towards the inside times the turn of the path (2 pi, where each mitred corner turning by t counts 2 tan(t / 2)); a
  twisting outline is checked only when its centre sits on the path.
- Arc and circle paths (`lib/design_model/paths/writing.py`): the revolve about the arc's axis builds an outline on the
  outer side of the arc however wide it is; only an outline that reaches the axis is left out (the reach toward the
  centre counts, along the radius). The check over the size ranges (`sweep/sweep_rules.py`) uses the same rule.
- Path sizes (`lib/translator/paths/path_motion.py`). A path of sketch lines and arcs that the probe measured (its
  `<item>/path` is in `Motion.curves`) follows the sizes. The probe covers such a path when every entity is a line,
  arc or circle of one sketch with a token and a `flat` record (`probe.plan`, kind `path`, and the request's
  `curves`); it keeps `<item>/path/c<n>/<field>` per entity in path order as captured (a line's `start.0`, `start.1`,
  `end.0`, `end.1`; an arc's also `mid.*`, `center.*`, `radius` and `turn`, the degrees it turns; a circle's `center.*`
  and `radius`) and `<item>/path/plane`. A state where the sketch plane turned, or its origin slid across the plane,
  is `turns`. The translator writes each written point (the start, every `to` and `through`) from the raw values of the
  curve point at that place, so a size behind a line length, an arc radius or a corner position becomes a formula:
  a straight path gives the extrude its distance, an arc path the revolve its axis point (the arc's centre) and its
  angle, a flat chain its `start`, `to` and `through` points and its placement origin along the sketch's normal, and a
  straight path that twists (a `sweep` step along two corner points) both points. Not
  followed, so written as measured with the sizes behind the sketch marked: a path with a free curve, a circle, 3D
  corner points, body edges or a taper, a path with a written point that is none of the sketch's points (a cut
  inside an arc), and a motion file without the path's prefix. A closed path cut open inside a straight line square
  to the outline's plane follows that line and the plane. The path start must stay on the outline's plane: a size that
  moves it away from the plane (the sketches are not tied together) is marked. The app's rules for the path
  (square start, no sharp corner, no touching itself, the outline clear of the tightest bend, a closed seam, an
  outline kept in one direction rising) are tested at the current values, at the ends of the size ranges (every corner
  for up to six sizes, else a fixed sample of them) and at the middles of the ranges (`sweep_rules._keep_path_valid`,
  `path_rebuilt.rebuilt_refusal`, `range_check.middles`). A rule that fails only between those settings is not seen. The
  ranges are cut where a rule stops holding (`kept_ranges.holding_ranges_where`); a size whose own cut would leave
  under a tenth of its range is marked, and the others are checked again without it. A size that another part of the
  copy already marked is held at its value in the check. When more than `MAX_PATH_TESTS` distinct settings or
  `MAX_PATH_SECONDS` seconds are needed, nothing is cut and the sizes are marked.
- `faces_after`: a point and the outward normal of the made start and end faces (`startFaces` and `endFaces` of a
  sweep, `startFace` and `endFace` of a loft), read with the marker after the item. Each side is null when the member
  cannot be read. The key is not a pick.
  The translator checks a sweep's `end` faces against the planned path end (`lib/design_model/steps/sweep.py`, `end_check`): each
  must lie on the plane through the path end that is square to the path's end direction (square to the outline's own
  normal when the outline keeps its direction) and face along it, and a new body's one end face must lie within the
  outline's reach of the path end (not checked with a taper). A mismatch leaves the sweep out; unreadable faces add a
  note; an empty list, a closed path and a full circle are not checked.

PATH, the record of a `Path` (a sweep's path or guide rail, a loft's rails and centre line):

```json
{
  "closed": false, "kind": "sketch",
  "sketch": "Sketch3", "sketch_token": "...", "frame": FRAME,
  "curves": [
    { "kind": "line", "start": [x, y, z], "end": [x, y, z], "opposed": false, "entity": "<token>",
      "flat": { "kind": "line", "start": [x, y], "end": [x, y] },
      "check": { "start": [x, y, z], "end": [x, y, z] } }
  ],
  "edges": [],
  "reference": { "kind": "constructionPlane", "token": "..." }, "projected": false
}
```

- `kind`: `sketch` (every entity is a curve of one sketch; only then `sketch`, `sketch_token`, `frame`, `reference` and
  `projected` are set),
  `edges` (every entity is a body edge), `mixed` (edges and sketch curves, or curves of several sketches) or `other`
  (an entity that is neither, or one that cannot be read). `closed` is `Path.isClosed`. `truncated` is true when the
  path has more than 256 entities: only the first 256 are read, and the sweep is not copied.
- `reference`: what the path sketch sits on, as on a profile record (`{ kind, token }` from `Sketch.referencePlane`,
  null when it cannot be read); `projected` is true when the sketch holds projected (reference) curves or points
  other than its origin point (`read_sketch.holds_projection`), null when that cannot be read. The translator marks the sizes that move such a plane, face or projection.
- `curves`: every `PathEntity` in path order, with the geometry in the target component's coordinates: `line`
  (`start`, `end`), `arc` (`start`, `end`, `mid`, `center`, `normal`, `radius`), `circle` (`center`, `normal`,
  `radius`) or `other` (`type` and dense 3D `samples`, as for a free profile curve, with `truncated` when the sampling
  was cut). A sketch curve is read from `SketchCurve.geometry` (sketch space) and mapped with the sketch's
  `transform`. `flat` is the same curve in the sketch's own 2D frame (a profile curve record), null for an edge and for
  a curve that leaves the sketch plane. `entity` is the token of the sketch curve or edge, `opposed` is
  `PathEntity.isOpposedToEntity`, and `check` holds the end points of `PathEntity.curve`, read only to compare with
  the mapped curve in a moved component (hand test SW13). An entity that cannot be read is `{ "kind": "other",
  "type": ... }`.
- `edges`: an edge record (`token`, `closed`, `points`, as for a round's edges, and `body`, the body the edge lies
  on, when Fusion gives it) for each body edge of the path. The key name makes them pick records, so a sweep along
  edges of a step that is left out is left out too.
- A curve or edge of another component carries `"foreign": true`, and so does the path record.

Loft `data`:

```json
{
  "operation": "newBody", "solid": true,
  "profiles": [ PROFILE, PROFILE ], "areas": [ .. ],
  "sections": [
    { "kind": "profile", "profile": 0, "end": "free" },
    { "kind": "profile", "profile": 1, "end": "direction", "angle": 10.0, "weight": 1.5 },
    { "kind": "point", "point": [x, y, z], "end": "pointSharp" },
    { "kind": "face", "face": FACE, "end": "free" },
    { "kind": "path", "path": PATH, "end": "free" },
    { "kind": "other", "type": "ObjectCollection", "items": ["BRepEdge"], "count": 1, "end": null }
  ],
  "rails": [ PATH ], "centerline": null,
  "closed": false, "merge_tangent": true,
  "participants": [ .. ], "target_box_before": { .. },
  "params": { "sections.1.angle": {..}, "sections.1.weight": {..} },
  "faces_after": { "start": [..], "end": [..] }
}
```

- `sections`: `LoftFeature.loftSections` in order, null when they cannot be listed. `kind` is `profile` (a `Profile`:
  its record is appended to `profiles` and `areas`, and `profile` is its place there, so the size probe follows the
  sketches under the usual keys), `point` (a sketch point, construction point or vertex, in the component frame),
  `face` (a `BRepFace`, as the face record of section 4, under a key the probe does not follow), `path` (a `Path`, a
  chain of edges or sketch curves, as the PATH record; a loop of the top edges of a box comes this way) or `other`
  (with the entity `type`). A section Fusion gives as a collection is the profile it holds when it holds one profile;
  otherwise it is `other` with `items` (the type names of up to 16 entries) and `count`, as is a `Path` that cannot
  be read.
- Loops of the part as sections (`lib/translator/loft/loft_sections.py`): a `path` section that is one closed chain of
  lines and arcs in one plane (or one circle), and a flat `face` section, are written as outlines measured where they
  are, the sizes that may move them marked (those the steps written so far read; any size for edges or a face of
  another body). The chain gets a frame on its plane turned like the other section's sketch. An open chain, a chain
  off one plane, another curve kind and a curved face are left out with their own reasons.
- `end`: the `LoftSection.endCondition` as `free`, `direction`, `tangent`, `smooth`, `pointSharp`, `pointTangent` or
  `other`; null when it cannot be read. `angle` (degrees) and `weight` are added where the condition has them, and
  the ones that are model parameters are in `params` as `sections.<n>.angle` and `sections.<n>.weight`.
- `rails` and `centerline` come from `centerLineOrRails`: `rails` is the list of rail paths (empty when there are
  none), `centerline` the path when `isCenterLine` is true (then `rails` is empty). Both are null when the member
  cannot be read. `closed` is `isClosed`, `merge_tangent` is `isTangentEdgesMerged`.
- Pairing check (`lib/design_model/steps/loft.py`): for a new body between two parallel outlines of straight lines of
  the same corner count, the measured volume must equal the volume of the loft the copy builds, with the corners
  paired as the app kernel pairs them (nearest corners about each outline's centre); another volume means Fusion
  paired them another way and the loft is left out. Where this cannot be told, corner outlines whose sketch frames
  are turned against each other get a note.

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

Old exports: add-ins before 0.10.6 marked the part's own sketches and planes seen through an occurrence as foreign.
When the capture names such a version in `addin`, a step whose only foreign records are sketch outlines, planes or
axes is left out with the cause `oldExport` and the tip to export again (`design_model/refs.py`, `from_old_export`).
A capture that names no version, or a later one, is never taken for old: a missing place key does not tell the
version. Edges and faces are never taken for old.

The translator also records which other components' sizes the copy follows (`TranslateResult.follows_components`,
`{ token, name }` each): a measured reference or a borrowed outline that moves with a size, and a sketch tied to a
component through projected geometry that the probe saw move. Steps inside a tool body walk do not add to it. A single
export names them in a note ("This part follows the sizes of Cover. Export both together so they change together.");
in a parts file a component whose body is among the parts is left out.

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
  reference is `<item index>.<slot>` (`params.geometry_links.ref_key`, `design_model.step_links.item_refs`). The holes' `position_refs` take
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

The shared layer (`lib/design_model/refs.py`) and the translator (`lib/translator/ref_motion.py`, the moves from the
motion file) read these records as follows. The Orca output reads no motion file: it keeps every such record where the
capture places it and marks the sizes that act on its component (`orca_translate/other_components.py`).

- `refs.bring_in` makes a flat face or plane of another component that an extrude starts from or reaches to usable: the
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
  - not measured (`probe.motion.refs` holds a reason, or the size was left without rows or set by no state), not
    looked at (no entry), or no motion file: every such size is marked loose with the step and the component named.
  The first translation of an export (`OPTIMISTIC`) marks nothing. An `origin` reference is handled like any other: it
  moves with the occurrence of its component. The sizes whose user parameter acts on a joint, another assembly item
  or a Move whose `input_kind` is not `bodies` or `faces` (a Move of occurrences) count for every reference of another
  component as well (`refs.acting_sizes`): the capture does not say which occurrence such an item places. A capture
  that lists no `dependents`, or a record without a component, does not say which sizes may move the record: the
  translator gives the step a note, and the Orca output marks every ticked size.
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
| RevolveFeature | `extent.angle_deg`; two sides: `extent.angle_one_deg`, `extent.angle_two_deg` |
| HoleFeature | `diameter`, `tip_angle_deg`, `extent.depth`, `counterbore.diameter`, `counterbore.depth`, `countersink.diameter`, `countersink.angle_deg` |
| FilletFeature | `sets.<n>.radius` |
| ChamferFeature | `sets.<n>.distance`, `sets.<n>.distance_two`, `sets.<n>.angle_deg` |
| ShellFeature | `inside`, `outside` |
| RectangularPatternFeature | `quantity_one`, `quantity_two`, `distance_one`, `distance_two` |
| CircularPatternFeature | `quantity`, `total_angle_deg` |
| PathPatternFeature | `quantity`, `distance` (on a round path the distance gives the angle; on a whole circle it is not followed) |
| CoilFeature | `diameter`, `section_size`, `taper_deg`, `revolutions`, `height`, `pitch` (each followed only where its formula gives the measured number; the taper is not followed) |
| EmbossFeature | `depth` (read like an extrude length; a negative depth is written negated), `offset_x`, `offset_y`, `rotation_deg` (not followed: the copy needs them to be zero, and a size behind them is pinned) |

Sketch dimensions, construction planes, axes and joints are not listed per item. They are model parameters whose
`created_by.kind` is `sketchDimension`, `constructionPlane`, `constructionAxis` or `joint`. The full list of kinds is
`feature`, `sketchDimension`, `sketchText` (the height of a sketch text), `constructionPlane`, `constructionAxis`,
`joint` and `other`.

How the translator uses them (`translate(capture, size_table=table, motion=motion)`):

- A value is written as `{ "expr": formula }` (never `{ "size": ... }`) when its expression translates, reads at least
  one free size and equals the measured number within 1e-6 once scaled to the unit of the field (a plain number in a
  length is read in the parameter's unit or the design's, whichever gives Fusion's number). Lengths written as absolute
  values (extrude and hole depths, spacing) must also stay above zero over the size range; counts at least 1. When
  one does not, the ranges of the untyped sizes it reads are cut where it does (above 0.005 mm, a count at least 1)
  and the formula is kept ("would leave its working range"); only when no cut keeps it is it a number with its sizes
  marked (`values._kept_above`).
  A negative parameter is written negated.
- Symmetric half length is written as `2 * (formula)`. An extent spacing is `(distance) / ((count) - 1)`. Hole
  tip outlines and counterbore or countersink sizes follow sizes point by point.
- Pattern counts that follow sizes must give whole numbers at every size value: the formula is rounded as a whole
  (`round`, `floor`, `ceil`), or it is built from whole numbers, count sizes, `+ - *`, `min`, `max`, `abs`, `mod`, `pow`
  to a whole literal and choices with whole results (`docs/expressions.md`, "Counts"). Otherwise the sizes are fixed.
  An extent spacing divides by `max((count) - 1, 1)`, so a count of 1 never divides by zero.
- A free size is a `count` (whole numbers, `step` 1, range 1 to twice its value, at most 64) only when it has no unit,
  its value is a whole number of 1 or more, and a pattern quantity reads it where a fraction would reach the quantity
  (`defaults.count_names`). A parameter that the quantity reads only inside `round`, `floor` or `ceil`, or only in a
  comparison (`ceil(Ratio * 4)`, `if(N > 2; 3; 5)`), can take a fraction in Fusion, so it is a `number` size with
  decimals. Every other size with no unit is a `number` too, also when its value is whole.
- Values that stay numbers while a size reaches them: construction geometry that a step uses itself (except the
  distance of an offset plane an extrude starts from or reaches to), the "up to" offset, a tip angle, a countersink angle, a full circular turn, a revolve that is not a plain
  part turn, and a pattern whose copies are left out by number or are rounds copied one by one. The sizes behind
  them are fixed.
- Picks and reaches that follow sizes (`lib/translator/faces/follow.py`). Every extrude step is kept with its placement,
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
    one, which one point per edge cannot, and both come before `featureEdges`. Tangent chain sets of different
    radii in one round write one point per seed with `"chain": "tangent"` and `edgeSizes` (the app gives each chain
    edge the size of its seed's point). A step with part of a set, mixed inputs, face sets of different sizes or chord
    length and changing radius sets keeps a point per edge (or `featureEdges`) and marks the sizes read before the step;
  - other points write the coordinate along the extrude as a formula (`0.5 * height` for a side point half way up);
  - a "to entity" reach to a moving end face writes its length as a formula. A construction plane follows what it is
    built on (`follow._plane_shift`): an offset plane its base plus its own distance when that is the only parameter
    it made that reads a ticked size (`design_model.reach.offset_param`; Fusion may give the plane a second parameter, a fixed
    extra offset, and the distance is followed only where it matches the measured plane), a midplane its two bases,
    through chains of planes. An origin plane, or one made from parameters alone, stays. Any other plane built on the part (at an angle, through an edge, tangent, along a
    path) marks the sizes read before the step, and so does a plane the capture does not describe (an older add-in).
    When the steps cannot place the face or plane (a side wall whose sketch line moves, a face of a step the copy
    does not model, a face of another body than the one walked (its `body` is not that body, also when it has that
    body's name under another token, `follow._another_body`), a plane built on
    such a face), or when the move they give differs from the probe's measure at a try that built, the probe's
    measure of it decides instead
    (`lib/translator/extrude/reach_motion.py`, "Measured references in the motion file"): its move is written as a formula, a
    size that does not move it is not marked, and only a size it cannot follow is marked. Without a measure, a face
    of another body marks every size the items before the step read (`design_model.reach.any_face_sizes`);
  - a start offset that follows sizes, or a "from entity" start on a moving end face, moves the sketch placement
    along its normal (`sketch.on.origin` as formulas), and the picks on that extrude follow it too. A side that
    reaches "to" a face from such a start keeps its end on the face: its length is the face's move less the start's.
  - a copy made by a pattern or mirror of an extrude is placed like the extrude and moved by the copy's motion: a
    linear spacing that follows sizes moves the point with it, a turn or a mirror moves it by numbers. A pick on a
    copy fixes the sizes behind that pattern's count (and a circular angle), since the list of points cannot grow.
    A copy has no `featureEdges` or `featureFace`: the app traces only extrudes, so copies are picked by points.
  - a point on the inner wall of a shell (`lib/translator/faces/shells.py`) is moved back out by the thickness and placed
    on the extrude whose outer wall it came from; its coordinates follow that extrude and the thickness.
  - an edge where the flat walls of two steps cross (`lib/translator/faces/crossings.py`), for example a cut's floor
    running into a rib, stays on both walls as they move; along the edge it follows the shorter wall.
  - a point on the far outline of a tapered extrude follows its length; a taper that follows a size is fixed.
  A point or face that no extrude explains may sit on geometry that moves, so every size read by the steps written
  before it is marked, with the step's name in the reason. Rounds and chamfers that a pattern or mirror copies take
  their source's written points (formulas included) through each copy's motion; their count is fixed, and a circular
  angle too. A copied uneven chamfer turns its `sizeOn` with the copy, and a tangent chain pick stays one. Without
  sizes the picks stay plain points. A rectangular pattern whose count follows sizes, with no copy left out, writes
  instead one round or chamfer step per copy for every count the size ranges allow (at most 64 copies), each with
  `when: "<count formula> >= n + 1"` for the copy n steps along a part, so the rounds and chamfers follow the count as
  Fusion repeats them (`repeat.repeat_rectangular._counted_finishes`); the count is not fixed for them. The app recipe cannot repeat a
  round or chamfer itself, nor pick the edges of every copy of a step.
- A round whose edges are exactly the four side edges of an earlier extrude with a plain rectangle outline, with a
  radius equal to half the rectangle's short side at every size setting, is drawn into that extrude: its outline
  becomes a `slot` (length the long side, width the short side, turned 90 degrees when the long side runs along the
  sketch y) and the round writes no step, with a note (`finish._slot_outline`). Not when a later pattern or mirror
  repeats the extrude without the round. Where the other side would get shorter than the short one, Fusion cannot make
  the round either, and the app refuses the slot.
- A formula longer than the app's cap (`MAX_FORMULA_LENGTH` in `lib/params/expressions/text.py`, 300 characters) has the
  equal terms of its outer sum added up first (`collected_sum`: a plane's move less the same move of another plane
  cancels; a coefficient that is a small fraction is written as one, any other with 12 decimals). The shorter formula
  reads only the sizes left in it. One still too long fixes the sizes it reads (they become plain numbers), also when
  a step builds it from several values.
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
  reason. The ranges are the table's, with two cuts. First, on a side where the probe saw Fusion fail to rebuild
  the design with only that size changed, an untyped range stops at the farthest value that built
  (`tried_ranges.built_ranges`, before the walk; a `size_table.Cut`, which keeps the nearest failure behind each cut
  end). A step of the part that shows a new warning at a try counts as a failure there (`spans.warned`, `Cut.warned`; the
reason says "Fusion shows a warning on Revolve1 at 12.5"). So does a try where a step of the part that is in error at
  the start builds (`spans.cleared`, `Cut.cleared`; the reason says "Fillet1, in error in Fusion now, builds at 80"). A failure counts only when its step is one the part is built from: an item of the target's component, a
  step that made a Combine tool body or an item with `body_states`, or a failure with no step name; a step of another
  component, or a name no capture item has, cuts nothing and the size keeps the "followed between A and B" mark. The
  step is told by its timeline position (the third number of a `spans.failed` entry, the capture item `index`), since
  Fusion names steps per component and two components can both have a "Chamfer1". An entry without a position (a
  record of an older version) counts when a step of the part has its name, also when a step of another component has
  it too. Where a followed sketch made
  a different outline with only that size changed, the range stops the same way at the farthest value that kept it
  (`spans.kept`, `Cut.changed`), and where Fusion built the part in several separate pieces, at the farthest value
  tried in one piece (`spans.split`, `Cut.split`, `tried_ranges.split_cut`; the reason says "the part comes apart into
  2 separate pieces in Fusion at 40"). Second, a value that
  Paramability refuses past some size value (a taper of 45 degrees or more) cuts the ranges of the untyped sizes it
  reads (`Context.cut`). `TranslateResult.cuts` lists each cut size as `{ name, reason, words, why, min, max }`
  (`translate._cut_notes`, `notes.cut_reason`: "Slope: the range stops at 0.5, since Fusion did not rebuild the
  design at 5 (Chamfer3)."). In a file with several bodies the table is cut once for all of them, to the narrowest
  cut over the probed bodies (`PartsPipeline._share_cuts` in `export_plan/pipeline/parts.py`), so every body writes the same range. A rule that may give
  a wrong shape inside a range (a count that a pick needs, a step that must keep meeting the part) marks the sizes it
  reads, with the value past which it fails where `kept_ranges` gives one. Only `TranslateResult.fixed` holds sizes that became
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
- A step with no handler is left out as a gap (`docs/recipe-gaps.md`), with two exceptions that the capture proves
  harmless: a step that lists no body and whose `target_changed` is false (a Remove of another body) is skipped, and so
  is a Split Face of the exported body with `target_changed` false, with the note that picks on its faces may not
  follow. In the walk of a tool, `target_changed` is false when `body_states` shows the tool's volume unchanged. A step
  of another body that has no handler is helper geometry and is skipped. A `target_changed` of true leaves the step out
  as a gap, and null stops the copy.
- A copied step that Fusion reports with a `warning` health gets a note with Fusion's message.
- The copy limits (`MAX_PATTERN_COPIES`, `MAX_FEATURES`, `MAX_NEAR_POINTS`) are checked at the current values; a pattern
  count that can pass its limit inside the size ranges (`range_check.sweep`) marks the sizes it reads.
- The recipe is version 12, or the lowest version that holds its steps and selectors (13 with an `offsetFaces` step, 14
  with a `chain` or `faceEdges` pick, 15 with a tool step, a `move` step, or a pattern whose copy count passes 64: a
  polar count or the two linear counts together, at the current values or anywhere in the size ranges; 16 with a `sweep` step that has `twistDeg`, `taperDeg`, `orientation` or a path with `closed`: `SWEEP_VERSIONS` and `SWEEP_PATH_VERSIONS` in `translator/translate.py`; 17 with a `scale` step, a `shell` step that has `outside` or `corners` or has no `openFaces`: `SHELL_VERSION`, a `draft` step that has `angleTwoDeg`: `DRAFT_VERSIONS`, or an `offsetFaces` step that moves a round face, which the step carries as `NewerStep.version`). It always carries `sizesAsWritten: true`; with a size table it also carries `sizes`: the sizes that a written
  formula reads, plus the sizes those formulas read. A ticked size that nothing reads is left out (see `dropped`).
  Without a table the recipe has no `sizes`.

### Sketch values that follow sizes (`lib/translator/sketch/sketch_motion.py`)

The export measures the sketches at other size values (probe states, next section) and fits each value the translator
writes as a sum over Fusion parameters, or marks it stuck (`lib/probe/`). That is the motion file, `sketch_values.motion`:
keys `<item>/p<profile>/l<loop>/<field path>` (loop 0 is the outer one, then the holes; `center.0`, `width`,
`segments.2.through.1`), `<item>/p<profile>/plane` (the sketch plane along its normal, from the component origin),
`<item>/positions/<n>/<0|1|2>` (hole points), `<item>/axis/point/<0|1|2>` (a revolve axis from a sketch line) and
`<item>/path/c<n>/<field>` with `<item>/path/plane` (the curves of a sweep path and its sketch plane; below).
`lib/sketch_values/keys.py` writes all keys; the probe and the translator both use it.

Measured references of other components (below) have their own keys, `<item>/r/<slot>/...`, and their own list `refs`.

The probe tries (`lib/probe/plan/`, at most 64 rows), in this order:

1. Near rows (`plan.probe_rows`): each ticked size that moves a covered sketch value or reaches a sketch dimension, a
   construction plane or, through another component, a sketch ("Geometry links" in section 2), or that may move the
   plane a covered sketch sits on (`probe/plane_sizes.py`), at 25 percent of its
   value below and above (`NEAR_SHARE`), inside its range; a count moves by whole numbers, a value of zero by that
   share of the way to the range ends. Then up to 8 ticked sizes that nothing ties to a sketch (`MAX_EXTRA_SIZES`, in
   `export_plan/probe_flow/sizes.py`, in table order) while rows are left: the person ticked them, so a sketch may follow them in a way the capture cannot
   show. Such a size left without rows is not listed as untried.
2. Near pair rows (`plan.pair_rows`), once the near rows have run: with two or more sizes tried, one row puts every
   tried size at its lower near value and one at its higher. A size whose own near row on that side did not build (or
   changed a followed outline) stays at its value; a row left with fewer than two sizes is not run.
3. The nearer rows below, for near rows that did not build.
4. Far rows (`plan.far_rows`): the range ends that differ from the value and from the near values, so the measured span
   grows. An end is not tried when a row of that size alone did not build (or changed a followed outline) at a value
   on that side: the range stops before that value anyway, so the try would only cost a rebuild. Nearer rows follow
   for the far rows that did not build.
5. Far pair rows (`plan.far_pair_rows`), after those nearer rows: with two or more sizes tried, every size at its
   minimum and every size at its maximum. A tried size goes only as far as it built on its own on that side (the
   farthest value that built and kept every outline), or stays at its value; a size without rows goes to its range
   end. The row runs only when a tried size goes past its near value.

A size that only feeds step values (a free size that moves no covered sketch value and reaches no sketch dimension or
reference) has no row: its formula is exact, and it is never reported as untried (only a moved size left without a
near row by the cap is). Each row has a `label`, the line of the progress window: "HolderWidth at 32 mm" (the value in
the parameter's own unit), "several sizes together", "checking if X changes this part" for a discovery row, or the
label with "The last value did not work, so this one is nearer." for a nearer row (a try that did not build, came apart
or changed an outline).

The rows of a size come in this order: the favourites of the design (`is_favorite`, the sizes the designer starred for
the form) first, then the others, in table order; the guessed sizes follow the moved ones the same way. Under a time
limit the near rows of every size run before any pair, far or check row, so a stop cuts the least useful tries first.

While the rows run, the timeline marker waits just after the last item the part needs (`lib/export_plan/marker_roll.py`),
so Fusion rebuilds fewer items per recompute. The items needed: any that may change the target, the sketches the steps
use (matched by name and component), the items of every other component a sketch link or measured reference depends
on that come before the step holding the link (Fusion builds the timeline in order, so a step never depends on a later
item), the steps of tool bodies of other components, and joints, rigid groups and items of unknown types (an unknown
type whose name ends in `Feature`, of another named component that did not change the target, is a body feature and
does not count). A sketch record without a name gives no roll; a reference without a component, or a link with an
unsourced reference, keeps every other component before its step (every one when its step cannot be found). The marker is moved only after the first read (E0), and only stays when a read
at the rolled marker gives the same sketches, points, lines, references and body box as E0. `report.json` keeps
`probe.timeline`: `{ rolled, items, of, reason?, suppressed, try_seconds }`, the items each try rebuilt out of the
items before the person's marker, why it did not move, the suppression record below, and the seconds from the start of
the tries to the end of the last one. A read while the marker sits before the rolled position counts as not read: the
probe is not used. The marker is put back when the tries end, also on cancel and error; Fusion builds the later items
as the marker passes them. The design is also rebuilt once (`computeAll`) when a parameter expression differs from the
one at the roll (a parameter that did not go back) or cannot be read (`DesignParameterStore.unroll_marker`).

Unless the person unticks "Faster tries" in the dialog (on by default), the items before the stop point (the items each
try rebuilds) that the tries do not use are also suppressed while the rows run (`lib/export_plan/timeline_trim.py`).
The evidence is the one above, with a component as the unit: an item is suppressed only when it is not suppressed
already, belongs to a named component other than the ones of the picked bodies, no item of that component is needed,
and it is not an assembly item. Nothing is suppressed when the roll's evidence cannot be matched, when a link or
reference leaves its component unnamed and its step cannot be found, when a needed item other than an occurrence has
no component, when an item before the stop point has a type the step kind table does not know and that is not a body
feature (a type ending in `Feature` of a named component), or when an assembly item other than an occurrence (a joint, a rigid group) comes
before the stop point. The store checks that each item still has the name the capture saw at its index before it
touches any. With the items suppressed, a read must give the same state as E0 and no step may show a new error;
otherwise every item is turned back on and the tries run as without the option. The items are turned back on before
the discovery rows read their base, when rows are left for them (those rows look for links to other components that
the capture cannot show, so every component must be built), and else after the parameters are put back and before the
last read, the restore check and the marker unroll, on every way out; every item the store tried to turn off goes back
on, also one whose state could not be read after.
`suppressed`: `{ asked, on, items, reason?, left_off? }`: whether the box was ticked, whether the tries ran with items
suppressed, how many, why not, and the names of items that would not turn back on. The end check of the timeline
steps (see "Timeline steps after the export") turns on again a step it reads off that was on at the start; an item it
brought back leaves `left_off`. The person gets a box of its own only for items the end check does not already name in
its own lines (`health.steps_changed`).

A row that Fusion cannot build is tried again nearer to the value now (`plan.nearer_rows`, `NEARER_STEPS`): half way
to that range end, then a quarter, then a tenth, one step per batch and per side, until a row on that side builds.
On a side with a value that built and a farther one that did not, rows half way between them follow (`plan.
_between`), until the two are within `BISECT_GAP` (a tenth) of the way from the value to the range end, at most
`BISECT_STEPS` times; the range then stops at the farthest value that built.
Sizes that no row built go first. A size that moved a sketch or a measured place with only one row that built, and
nothing left to try, gets one more row half way to that value, so the fit has two readings. These rows are at most
24 per export (`MAX_NEARER_ROWS`, each is a Fusion recompute) and stay inside the 64 row cap; the discovery rows get
what is left. The range ends come first for every size, also for one that reaches the part only through another
component: a far end that builds gives the widest span measured, and only a failed end costs the nearer rows. When
a value moves along a curve with one size on its own, or follows a `Terms` formula with an angle function (below),
once per export (`plan.check_rows`, inside the row cap, in this order): each such size half way to the lowest and to
the highest value it was measured at; each such size with each other size of those values, both low and both high
(products show there; the other sizes are those of the curved values, then those of every value of the same sketches,
`series.curve_sizes`, since a partner of a turn may move no curved value at the sizes now); then every other size at
the lowest and at the highest value it was measured at, the curved
ones at their value now, so the formula over those sizes is checked by a state that changes several of them. A state that did not build keeps the
first step that failed and that the part is built from, else the first step that failed (`failed`, the name, and
`failed_at`, its timeline position; records of older versions have no `failed_at`). A row that built while a step of the part showed a warning it did not show before
the tries is kept as a state that did not build, with that step in `failed` and `warned: true`. A row that built while a
step of the part that was in error before the tries built too is kept the same way, with `cleared: true`. A ticked size the probe set to other values that no formula reads at the end is dropped with
"it was tried at other values, and it changes nothing in this part" (`used` false, `tried` true), with "between A and
B; beyond that it could not be tried" when the rows that built cover less than its range, but only when the body's box
and volume (`volume_mm3` in each state read) read the same at every try that set it alone
(`Motion.body_changes`, `probe.build.body_changes`; a try on another sketch solution, `apart`, or past an outline limit
does not count, and a try counts as "the same" only when it and the first read hold the box and the volume). When
the body changed at such a try, it is dropped with "it changes this part in a way the copy does not follow" (`used`
true); when no such try read the box and the volume (an older export), it gets the plain "not used by any copied
step" reason without `tried`. A size that reaches a sketch
or a measured place (`design_model.reach.probed_sizes`) and whose rows all failed to build was not measured: it is
doubted up front with "the design does not rebuild in Fusion at A (step) or B (step), the nearest values tried, so it
could not be measured" (loose when a formula reads it, else dropped with `used` true), never called unchanging. A
free size measured over less than its range is loose with "it was followed between A and B; beyond that it could not
be tried" (added to its other reason when there is one; a note too long for 200 characters shortens the other
reason and keeps the span), unless the range was cut to the values
that built on every side the probe did not cover. Every state also
reads the body's box (and volume when the state has it): a size whose state alone changed the box but moved no
followed sketch or reference is kept in `Motion.body_moved` (`SizeProbe.finish`), unless it was tried only for a
sketch plane, or its only use is the distance of an offset plane a step places (`sizes.construction_only`): it feeds
step values, which follow it or mark it. A size that a value of the part's own steps reads is not kept either when
every other way it reaches the part is followed: the capture lists its `dependents`, it places no occurrence, every
model parameter behind it is a step value or a dimension of a followed sketch, every sketch of the part tied to
another component is followed, and every measured reference its geometry links name is read
(`export_plan/probe_flow/body_routes.py`). The translator treats it as doubtful
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
reason }`, and the result window counts those in its "More sizes" section (ticking one makes the export try it).
`also_changes` lists the parameters that moved the part; the result window says "These parameters also change this
part: ... Tick them and export again to get them as sizes." For a parts file the group is "Also change these parts" and
each parameter names the parts it changed (read from each part's `probe.discovery`).
In each state the read sketch profile whose arcs lie on the same side of their circles as the captured arcs (the
direction from centre to middle point) stands for the captured profile, the nearest one among those. Regions of one
sketch share curves (each piece of a cut circle bounds its own region), so a region that moved further than its
neighbour lies, or changed its shape, would otherwise pass for the neighbour.
The sketch curves of each profile have `<item>/p<profile>/c<loop>.<curve>/<field>` in the capture's loop and curve
order: a line's `offset` (its distance from the sketch origin along the left normal of its captured direction) and
`turn` (degrees it turned; Fusion lists a profile curve with its ends either way round, so where the loop's joins
tell, a read curve runs the way the captured one does along the loop), an arc's `center.0`, `center.1` and
`radius`; `curves` lists the profiles
(`<item>/p<profile>`) whose curves were measured. For a sketch the probe measured, a key that is not listed did not
move. `spans` gives, per size the probe set to other values, the lowest and highest value of the states that built
(the value now included) and `failed`, `[value, step, position]` for each value tried alone that did not build, with
the timeline position of the step (`[value, step]` in records of older versions or when Fusion gave no position)
(`probe.build.spans`), `warned`, the entries of `failed` where the step showed a new warning (only when there is
one), `cleared`, the entries of `failed` where a step in error at the start built (only when there is one), `split`, `[value, pieces]` for each value tried alone where Fusion built the part in several
separate pieces (only when there is one, see "Probe states"), and `kept` and `changed` for a size whose own row changed a followed outline (see the
different outline item below), and `unfinished` (only when there is one): per side (`low`, `high`) why the tries ended
before the nearer tries and the halving on that side ran (`stopped` after a broken design, `time` after the time
limit; `SizeProbe.note_unfinished`, `plan.nearer_left`). The cut on that side stays at the farthest value that built
(`Cut.unfinished`), and the cut reason adds "no value between was tried, as the tries stopped early. Tip: untick the
size that stopped them" or "as the tries ran out of time. Tip: raise the time limit" (`notes.untried_between_why`). A
side whose far try never ran before the tries ended (`plan.far_left`: a try of that size alone built, none reached the
range end and none failed on that side) is in `unfinished` too; with no try past the span on that side, the range is
cut to the span there (`tried_ranges.untried_cut`, a typed end kept) and the reason says "no value below A or past B
was tried" with the same tip. A sketch the probe could not measure (a step uses it in a way the probe cannot follow, its first read did not
match the capture, or there was no read at the current sizes) is listed in `unmeasured` (sketch name to reason), and
nothing is known about it. For one sketch and one size the motion file therefore gives one of three answers: measured
and still, measured and moved (the keys), or not measured (`translator.sizes.sketch_answer`). A size that no state
sets to another value (no `states[].values` names it) is not measured (`NOT_TRIED`, `coverage.tried`), never still: the
tries tell nothing about it. A motion file without `states` (written by hand) cannot tell which sizes were tried, so its
values are the answer. A motion file without `unmeasured` (written by hand) says nothing about such sketches. The translator uses it like this:

- `motion=None`: the rule above, sketch sizes fixed up front. `motion=OPTIMISTIC` (the export's first translation):
  sketch values are written as numbers and nothing is fixed for them, so the export can see which sizes to try.
- Each written value with a key becomes a formula over the sizes (`{ "expr": "0.5 * FilterBox_width_mm" }`); a model
  parameter in a sum is written through its own expression. Its number stays the captured one; a formula that misses
  it by more than 1e-3 mm fixes its sizes ("could not be read at other values"). A width, height or radius that would
  reach zero over the size ranges fixes its sizes ("would shrink to nothing").
- A value of an unmeasured sketch is stuck with cause `untried` for every size the sketch reads (`design_model.reach.sketch_sizes`:
  the sizes behind that sketch's dimensions, and the sizes that may reach it through the geometry of another
  component, "Geometry links" in section 2). The size is loose, with "it changes <sketch> and could not be tried at
  other values". A size that moves the sketch only through the plane it sits on is marked by the placement rule
  below.
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
  dropped. When that finds nothing and an angle size moved the value, every turn term is solved at once
  (`terms.turn_terms`: each size, and the sine and cosine of the angle, alone and times each length size), less those
  the states cannot tell apart from the ones before them, then pruned the same way: a corner on a turned leg moves by
  two to four such products, which one term at a time does not find. The turn terms also read partner sizes
  (`series.partners`): a free size that moved the value in a state that changes it and that angle alone, compared with
  a state that changes only the angle to the same value, while its own states did not move it (a leg lying along the
  line it moves, at the angle now). The sum is used only when every measured state follows from the others within 1e-4
  mm (solved without that state, it still gives it), and when no other term in place of a chosen one also gives every
  state but another value half way to an end or with every size at an end. The motion file keeps it as `{ const, sum:
  [{ k, of }] }` (`Terms`): `of` lists the factors `[function, name, scale]`, `function` empty for a size, scale 1 or
  0.5 for the half angle. The translator writes it as a formula with `sin`, `cos` and `tan` in degrees (`cot` as `cos
  / sin`), checked over the size ranges like any formula (a value that would reach zero, or a divisor that would cross
  zero, marks its sizes; a formula past the length cap fixes them). A `Terms` value holds the sizes that a stuck value
  of the same item names at their value now, so all values of the step's outlines follow the same sizes; values of
  other items still follow them. A stuck curve key (`<prefix>/c<loop>.<curve>/...`, such as a line's `turn`) holds
  nothing: a line's direction can turn along a curve while both its ends follow. A sketch can have more than one
  solution, and Fusion may land on another one after the rows run before (a row that did not build often leaves it
  there). A different outline blames a size only in that size's own row (the row that changes it alone), when the row
  started on the captured outline and the outline came back once the parameters were put back (`probe.build`): the
  read before the row (`start` of the state) or, without one, the row before it (E0 for the first) tells how it
  started, and the next row's `start` or read (or the read once all rows are done) tells whether it came back. A row
  of several sizes never blames one for a different outline. Every other state with a different outline blames no size
  (`apart` lists them, by number in `states`), and so do the states where a sketch reads as the same different outline
  in rows that change different sizes or one size to two values, unless both rows give some parameter the same new
  value (two sizes behind one formula), where alike reads are expected. A sketch is solved as a whole: in a state
  where one of its outlines reads differently, its other outlines give no values either, since they sit on that other
  solution too (a strip that only shifts there is no move). When the probe put the sketch back before a row, the read
  after that (`put_back` of the state) tells how the row started instead of `start`. A row run a second time from a
  checked start (`again`, see "Solver flips" below) blames its own size for another outline even when the outline did
  not come back. A sketch known to have stayed on its other outline after the parameters were put back, with a row run
  from it (a `start` read shows it and no `put_back` corrected it, or the same different read in rows of unrelated
  sizes) is named in `flipped`, and `health.flipped` gives the result window one line about it.
- A different outline that a size makes in its own row is a limit of its range, not a reason to drop the size
  (`probe.build.outline_windows`). On that side the range keeps the farthest value tried alone that built and kept
  every followed outline, nearer than the nearest value that changed one; the states that set the size past it are
  left out of the fit, and `spans` records `kept` (`[low, high]`, null on a side without a change or with a typed end)
  and `changed` (`[value, sketch]` of each such row). The translator cuts the range there like a failure in Fusion
  (`tried_ranges.outline_cut`; the cut reason says "LidRail makes a different outline at 2.5"). When this limit and the
  failures leave only the value now, nothing is left out: the size stays stuck, `kept` is the value now at both ends,
  and its reason says "no value other than 12 could be copied, since ..." with the nearest failure or different
  outline on each side. While the rows run, a row that changed an outline counts as one that did not build, so the
  nearer rows and the halving (`plan.nearer_rows`) look for the last value that keeps the outline, inside the same
  row budget. A stuck value's `rest` is fitted over the states that keep its blamed sizes at their value now.
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
  becomes a fixed direction from its centre. The rebuilt outline (and an outline of `Terms` values) must keep its
  crossings and the order of its corners at every mix of the size ends (up to 6 sizes; a bounded sample past that) and
  the probe's states. Where it keeps them only inside shorter ranges (a leg turned while shorter than another, so the
  outline would cross itself), the ranges are cut there (`sketch_crossings.order_ranges`: each check above zero over the
  cut ranges by the settings of `range_check.sweep`, so inner values and the places where a term changes sign too,
  plus the middles of the ranges and the probe's states inside them; `kept_ranges.holding_ranges_where`): "the range stops at A, since the outline of
  <sketch> would cross itself, lose a corner or have a hole reach its edge". When no shorter ranges keep them (a check that fails at the values
  now, or every size behind it has a typed range), its sizes are fixed ("along a curve"). A line that turns cannot
  carry its crossings.
- Any other written profile or polygon whose corners follow sizes, also with straight formulas only, is checked the
  same way for crossing edges (`sketch_crossings.simple_ranges`): at each mix of the size ends, the middles of the
  ranges and the probe's states inside them, the corners are worked out as written (a value that cannot follow keeps
  its number), and each loop is held to the app's rule for sketch loops: no two edges cross, touch (within 0.0001
  mm) or fold back, arcs drawn with the app's 16 chords. Where a loop breaks only past some values the ranges are cut
  with the same reason. This catches a corner that follows a size while the curve it meets is written as its number
  (it moves along a curve the probe could not fit). Rect and circle loops are checked too, and every hole must stay
  inside the outline of its sketch (every point the app samples on the hole inside the outline, 0.0001 mm clear of
  its edges), the app's own rule ("a hole in the sketch reaches outside its outline"). The same check runs on the
  loops of a flat face the probe read (a face used as an outline, the face an emboss is trimmed to). Outlines of
  more than 300 points are not checked. The far ends are cut first, and each setting is worked out once per check.
  When no shorter ranges keep the loops (they break at the values now, or a size behind them has a typed range), the
  sizes that move them are marked with the same reason instead. The checks of one translation share 20 seconds
  (`OutlineChecks`, timed as `timing.phases.outline_check`): an outline already checked over the same ranges is not
  checked again, and once the time is used up the sizes of an outline left unchecked are marked "there was no time
  left to check that the outline of X does not cross itself".
- A sketch plane that moves writes the placement origin along its normal (`sketch.on.origin`); a "to entity" reach is
  the face's move less the plane's move. Outlines of one step whose planes move differently fix those sizes.
- A sketch on a face, or on a construction plane built on the part (also a chain of planes), may move with every size
  an item of the body's component reads before the plane was made, and with the plane's own parameters
  (`design_model.reach.placement_sizes`; for a plane described only by its token, every such size unless the sketch frame lies on an
  origin plane). The probe tries those sizes (`probe/plane_sizes.py`), so the plane's move is measured whatever the
  plane's kind; a plane that turns is stuck with cause `turns`. Such a size that was not measured for the sketch (no
  probe, the sketch not measured, the size not tried) is marked: "it may move the plane <sketch> sits on, and that could
  not be tried at other values" (`sketch_motion.placement_doubts`).
- A reversed placement negates the y formulas of its loops.
- Hole points write `origin` as formulas (the drill tip revolve too); a revolve axis from a sketch line writes
  `axis.point` in the sketch plane. A symmetric revolve, and a revolve to two sides whose angle before the sketch is a
  number, turn the moving origin about the axis.
- Picks on an extrude whose outline moves follow it: a side corner moves with that corner, a point on an outline line
  between its two ends, a point on an arc with the arc's middle (or with the whole arc when it only shifts), on a
  circle with its centre and radius, and a face picked by a point inside an end face with the first of its 3 nearest
  outline corners whose move keeps the point inside the written outline, at least a quarter of its distance from the
  edges, at the corners and middles of the ranges (`inner_pick.anchor`; the ranges as an order cut above leaves them);
  else with the centre of the outline's corners. A corner gives a formula a few times shorter than the centre, which
  sums every corner (with turned corners past the 300 character cap). An edge picked inside an end face comes from
  another step, so it always moves with the centre of the corners: staying inside the face does not keep it on that
  edge. A round, a rect or an ellipse moves the point with its centre. A point on an arc that changes shape fixes
  those sizes. An edge inside one flat side wall, away from its corners, where no second flat wall crosses it (a round
  meets the wall), follows that wall: the outline curve under it and the length. The same holds for pattern and mirror
  copies, shell inner walls, crossing edges and faces an `offsetFaces` step moved (the point moves back by the
  distance, then follows what made the face; on a moved round face it moves back along the radius).
- A pick on a tapered wall follows the taper and the length: the wall leans in by `tan(taper)` times the height along
  the extrude, also when the taper is a size.
- Symmetric patterns (`lib/translator/repeat/symmetric.py`, `lib/translator/repeat/`). A symmetric direction is written as a forward and a
  backward pattern that both start at the original; the grids that result (one per choice of a part in each direction)
  skip the places another grid already makes when their counts are numbers. The copies follow this rule, and the
  measured copies must match it or the pattern is refused: for `n` copies, an odd `n` has `n // 2` steps each way and
  an even `n` has `n // 2` on one side and one less on the other, the longer side being the one measured. The two part
  counts are `floor(n / 2) + 1` and `floor((n - 1) / 2) + 1`, so a count formula keeps the pattern centred. A count
  measured odd that can be even inside its range takes the side of the extra step from the tries: each built state
  that read the pattern (`Motion.states[n].patterns`) is checked against the rule at the counts and spacing the sizes
  give there, and the even ones must agree on the side. Without an even try a rectangular pattern takes the side Fusion
  was seen to use (ahead of the original, the way the distance points, so against the direction for a negative
  distance; not yet confirmed in Fusion for a negative distance). The sizes are marked when a try breaks the rule or the even ones disagree,
  and for a circular pattern without an even try (Fusion's even circular places were not seen). The two part counts
  use the longer formula on that side. A pick on a copy
  off the middle of a symmetric direction fixes the sizes behind the count, since Fusion moves its copies when the
  count changes. A pattern whose original is not among the copies (it sits between two) is refused. The circular
  case turns the copies back and forth from the original by `k * total / (count - 1)`. Copies left out by number need
  a fixed count in the app, so the count is written as a number and its size is dropped with the reason.
- A pick on a copy of a rectangular pattern needs that copy at every size: copy n needs a count of n or more over
  the size range (count formulas such as `ceil(width_count) * 2` are evaluated at the range ends, `lib/translator/
  faces/copy_counts.py`). When the count can drop below that, the sizes it reads are marked ("a smaller value would leave
  that copy out"); the range stays. Copies of a circular pattern keep their count and angle.
- A taper that follows sizes should stay under 45 degrees either way, since Paramability refuses a steeper one: the
  ranges of the untyped sizes it reads are cut where it reaches 45 (`Context.cut`, `kept_ranges.holding_ranges`).
  When no cut keeps it under 45 (every size it reads has a typed range), those sizes are marked instead. The cut
  moves both ends of every size it reads by one share, then gives back each end the rule holds at, so a size that
  only helps one way, or cancels out, keeps that end.
- A "to entity" length that follows a moving face or plane would pass its own start at some sizes: the ranges of the
  untyped sizes it reads are cut where it stays positive ("would reach past the face it starts from"), the same way,
  with both sides of a two sided extrude in one cut; only when no cut keeps it are they marked.
- A through cut clears the part at the largest sizes tried (`box_max` of the motion file). A cut through all to one
  side without a measured end face cuts toward the side where its outline meets the part built so far (sampled on a
  grid over the outline, at even steps and at heights doubling from 0.02 mm, so a thin wall at the sketch counts);
  Fusion's stored direction is kept when both sides, or neither, hold material, or when the measured walls of a tapered
  cut lean the way it gives and not the other, and turned with a note otherwise. A tapered side keeps its outline at each height whatever its length: one that only widens gets the
  same length as an untapered cut, one whose walls lean in (at its taper, or at some size inside the ranges of a taper
  that follows sizes) ends 1 mm past the part's box, and is left out when the length times the tangent of the steepest
  such lean passes half the radius of the largest circle inside an outline (sampled on a grid, coarse first). The
  measured wall leans are compared with the side the cut goes, after it is turned toward the material.
- A construction plane or axis that a step uses itself (start from, reach to, turn about, mirror across, with `token`)
  marks the sizes of the model parameters it made (`created_by.token`); without a token, of every construction plane
  or axis. An offset plane that the step places, whose distance `design_model.reach.offset_param` names, follows that distance
  instead: where an extrude starts or reaches to, the plane of a mirror or a draft, and the plane a split cuts along
  (`sizes._placed_planes`).
- An angle the step needs above zero (a draft, a revolve) that reaches zero inside the size ranges cuts the ranges
  of the untyped sizes it reads where it stays above 0.005 degrees ("needs an angle above zero"), since the default
  range of an angle under 45 degrees starts at 0; only when no cut keeps it are they marked. A length or count that
  leaves its working range is cut the same way.

### Measured references in the motion file (`lib/probe/ref_fit.py`)

The probe reads every measured reference (`ref`, section 4) that has a place in the target's coordinates and fits how
far it moves from the captured place. A size that acts on the reference's component is probed like a size behind a
sketch (`reference` links, section 2). The values are moves, zero at the sizes the capture was read at.

A flat face or construction plane of the body's own component that an extrude starts from or reaches to is measured
the same way when it may move with the part (a face, or a plane built on the part) and has a `token`
(`design_model.reach.moving_reaches`, `plan.own_reaches`). Its request carries `"own": true`, and the reader reads it natively, in
the part's coordinates like the capture. The sizes tried for it are every size an item of the body's component reads
before the step (for a plane, before the plane was made) and the sizes behind the planes of a chain
(`design_model.reach.reach_sizes`, part of `plane_sizes.plane_driven`). The translator uses the measure when the steps written
before cannot place the face without a doubt, or when the move they give differs from the measure by more than 0.001 mm
at a try that built and set the free sizes inside their ranges, when no such try is left to compare them, or when the
measure is stuck (`reach_motion.target_shift`, `_agrees`); then those same sizes get the three
answers below, and the formula keeps its constant apart so the extrude length folds into one number.

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
rows or set by no state, `NOT_LOOKED` for a key not in `refs`). A size of a joint or of a move that places an
occurrence may move every reference of another component (`design_model.refs.acting_sizes`). When no state set it
(the row limit, a time limit, or a probe of an older add-in), the answer is `NOT_TRIED`, and the step marks the size.

### Probe states (`lib/fusion_reader/probe_state.py`)

The size probe sets other size values, recomputes and reads a state with `read_state(design, request, ctx)`.
`request` is `{ "sketches": [token], "points": [token], "lines": [token], "params": [name], "target": true }`, plus
`curves`, `borrowed`, `native`, `refs`, `faces` and `patterns` below. Every
entity is found with `Design.findEntityByToken` (the match without `assemblyContext`; for a proxy only, its
`nativeObject`), so values are in component coordinates like the capture. The result, mm and degrees except `params`:

```json
{
  "sketches": { "<sketch token>": { "frame": FRAME, "profiles": [PROFILE, ...], "curves": { "<curve token>": CURVE } } },
  "points": { "<sketch point token>": [x, y, z] },
  "lines": { "<sketch line token>": { "point": [x, y, z], "dir": [x, y, z] } },
  "params": { "d12": 2.0 },
  "box": { "min": [..], "max": [..] },
  "pieces": { "lumps": 1, "others": [{ "min": [..], "max": [..] }], "names": ["Body2"] },
  "refs": { "57.plane": { "point": [x, y, z], "normal": [x, y, z] } },
  "faces": { "15/face": { "frame": FRAME, "loops": [LOOP, ...] } },
  "patterns": { "17": { "count": [7, 1], "elements": [{ "id": 3, "suppressed": false, "frame": FRAME }, ...] } }
}
```

- `sketches`: `frame` from `Sketch.transform`; `profiles` are every `Sketch.profiles` item read like a capture
  profile (section 4, each curve with `entity`). A sketch with more than 200 profiles, or a profile whose space is
  `ambiguous`, is left out.
- `curves` (request): `{ "<sketch token>": ["<curve token>", ...] }`, the sketch curves of sweep paths. The sketch's
  `curves` then holds each asked curve that reads, by its token, as the `flat` record of a capture path curve (the
  curve in the sketch's own plane); a curve that is missing, leaves the plane or cannot be read is left out.
- `points`: `SketchPoint.worldGeometry`; `lines`: `SketchLine.worldGeometry` start point and unit direction.
- `params`: `value` of each named parameter in Fusion's own units (cm, radians), as in `parameters.*.value`. A name
  is looked up in the user parameters, then in the target component's model parameters.
- `box`: the target body's box, as `target.box`.
- `volume_mm3` (only with `box`): the target body's volume (`BRepBody.volume`, cm3 times 1000), absent when it cannot
  be read. It shows a change inside the box (a deeper pocket, a wider hole) when the probe asks whether a size changed the body (`Motion.body_changes`).
- `pieces` (only with `box`): `lumps`, how many solids the target body holds (`BRepBody.lumps`), `others`, the
  boxes of the other solid bodies of its component (left out when one cannot be read or there are more than 64), and
  `names`, the name of each of `others` in the same order (`BRepBody.name`; left out when a name is missing or two
  bodies share one; the end check compares the other bodies by them). The
  app builds a part only in one piece, so the probe works out from them how many pieces the part is in
  (`lib/probe/pieces.py`): the lumps, plus the other bodies whose box comes within 1 mm of the target's box at this
  state or at E0, less as many as did so at E0 (a cut that cuts a body in two, or a join that does not reach it, leaves
  new bodies next to it). A try where the part is in several pieces while it was one at E0 is kept as a try that did
  not build, with `pieces` (the count) in its state and an entry in `probe.dropped`: nothing is fitted to it, and the
  size's range stops at the farthest value tried in one piece (`Motion.spans` `split`, `tried_ranges.split_cut`).
  Reading them recomputes nothing.
- A sketch of another component that a step borrows is requested with the optional `borrowed`: `{ "<sketch token>":
  { "path": "<fullPathName the capture recorded>" } }`. It is found by token, read native, and its place is found
  again at every state: the occurrence of its component with that path (the only one when there is no path), then the
  placement check of section 4 (native sketch points against the same points through the occurrence). A sketch of
  the root (path empty) has the root's own frame. Its `frame` is
  brought into the target's coordinates (that place, then the inverse of the target's, read once per capture), so
  it compares with the capture profile's brought-in `frame`; it adds `native_frame` and `placement` (`{ path, source }`).
  When it cannot be read or placed, it has no key under `sketches` and `unread` (only then present) gives
  `{ token: reason }`.
- `native` lists the sketches of tool bodies from other components (the steps of `helper_of` items). They are read like
  the target's own sketches, in their own component's frame (not brought into the part's), since the translator writes
  those steps in that frame before it moves them.
- Measured references are requested with `refs`: `{ "<key>": { "token", "type", "path", "shape" } }` (`shape` is
  `plane`, `axis`, `direction` or `point`, from the record: `lib/probe/plan/references.py` `refs`). Each is found by the token of
  its native entity (`lib/fusion_reader/probe_refs.py`), shown through the occurrence with the recorded `path` as that
  occurrence sits now (`createForAssemblyContext`), read the way the capture read it (`plane_of`, `axis_of`,
  `direction_of`, `worldGeometry`), and brought into the target's coordinates with the inverse of the target's own
  place read again at this state (the body is shown through its occurrence again, so a size that moves the target's
  component is taken out). `refs` maps a key to `{ point, normal }`, `{ point, dir }`, `{ dir }` or `{ point }`; a
  reference that cannot be read has no key there and `unread` gives `{ key: reason }`. The reads change nothing in the
  design.
- A flat face a step uses as its outline (one face among an extrude's or emboss's outlines, or the face a trimmed
  emboss keeps to; `plan.outline_face`, a `token` and loops of lines, arcs, circles and ellipses) is requested with
  `faces`: `{ "<item>/face": { "token", "before" } }`, `before` the step's timeline index. The step changes or removes
  the face, so the reader moves the timeline marker to `before`, finds the face by its token, reads its `frame` and
  `loops` like the capture's face record (section 4) and moves the marker back (`read_face.read_faces`, read last). A
  `before` past the marker, a marker that does not move or a face that is not found gives `unread`. A marker that does
  not go back leaves every face unread and adds `"marker"` to `unread`, and the probe stops. The read of a try's own
  state asks to `park` the marker (`request.park`, when the store has `keep_marker`): the marker stays at the face's
  position, and the change that puts the try's values back moves it back to where the tries hold it. Fusion then
  rebuilds the steps after the face once, with the values back, instead of once with the try's values and once more
  with the values back. The marker is brought back (`keep_marker`) before any other read and when the rows of a batch
  end; when it does not go back the probe stops (`pipeline.ProbeRun`). In a file with several bodies only the last
  body's read parks the marker. A face is read only in a
  state that sets a size read before its step (`SizeProbe.read_now`); the other states take its E0 read. The probe
  pairs the edges with the captured ones by kind and place along each loop, writes the values under the keys of a
  profile (`<item>/face/...`) and tries every size an item reads before the step (`plane_sizes.plane_driven`). A
  different outline that one size makes on its own is a range limit, like a sketch's, named "the face <step> starts
  on". A face read on its own plane but facing the other way counts as another outline, not as a turned plane: the
  body behind it lies on its other side (an earlier extrude reached past its start), so the step goes the other way.
  A face whose first read does not match the capture is not read again; the motion file lists the measured ones in
  `faces`.
- A pattern that spreads copies to both sides of the original and whose count follows a parameter
  (`plan.symmetric_patterns`) is requested with `patterns`: `{ "<timeline index>": { "index", "kind" } }`, `kind`
  `rectangular` or `circular`. The reader finds the feature through `Timeline.item(index).entity` and gives the counts
  (`quantityOne` and `quantityTwo`, or `quantity`) and the `patternElements` as the capture reads them
  (`probe_patterns.read_patterns`). A pattern that cannot be read gives `unread` `{ key: reason }`. Built states keep
  these reads in `Motion.states[n].patterns`. The translator uses them to learn where Fusion puts the copies for an
  even count (`translator/repeat/symmetric.py`, "Symmetric patterns"). Like the captured copies, their frames are in assembly
  space; the translator carries them into the frame of the part (`design_model/steps/repeat.py`, `read_in_component`) before it
  compares them, so a part turned in the assembly reads the extra copy on its own side. The start reads of a flipped
  sketch skip them.
- Nothing raises. A part that cannot be read has no key, which the fit treats as unread.

## 6. Report and capture file

The export writes `report.json` into the package, as compact JSON without indentation (format it with a tool such as
`python3 -m json.tool` to read it): `{ "writer", "outcome": "recipe" | "stepOnly", "items": [ITEM VERDICT, ...],
"capture": CAPTURE }` (verdicts: see the translator, `lib/translator/result.py`; a Combine written as tool
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

The manifest `parameters` entry of a formula parameter (`lib/params/listing.py`) holds `expr`, the formula in the recipe
grammar, when the size table translated it. When it did not, the entry holds the plain `value` and two optional fields:
`expression` (Fusion's own text, at most 300 characters) and `untranslated` (the reason, at most 200); the report lists
them in `parameters.no_formula`. A reader that does not know the fields ignores them, so version 1 and 2 stay as they are.

`sizes` holds `free` (recipe size names), `fixed` and `loose` (`{ name, reason }` by recipe size name; `loose` here is
the doubts only, and the manifest `loose` the same; the cut sizes go in the manifest `cuts` list, `{ name, reason }`,
which the app shows as a quiet note, not a warning; `cuts` is an optional field of manifest version 1 and 2, so an
older app ignores it), `cut` (only when a range was cut: `{ name, reason, words, why, min, max, shared }` by recipe size
name, `min` and `max` the range left, `shared` true when several bodies of a parts file read the size), and `dropped` (`{ name, reason, used }` by Fusion name, plus `tried: true` for a size the probe set to
other values that changed nothing: the ticked parameters that are not sizes, from
`TranslateResult.dropped`; `used` is true when a step reads the parameter and the copy could not follow it). `loose` comes
from the translator and from the probe. `checks` in the manifest is
always empty. The report has a
`probe` when a sketch could be followed (the rows only recompute and the parameters are restored; its `timeline`
says how many timeline items each try rebuilt, section 5), `marker` and
`health`. `health.restore_unverified` is true when a followed sketch could not be compared with its first read after
the parameters were put back; `health.unchecked` then names each such sketch and why ("could not be read"), and the
result window says so (`probe.restore_unchecked` too). A followed sketch whose profile does not match its first read
by its entity tokens is compared by its curves (`probe.same_shape.shape_gap`: each profile, loop and curve paired
within 0.05 mm, in any order and either direction). When the curves pair, their gap counts in `sketch_gap_mm`. When
they do not, or the plane turned, `health.outlines_changed` names the sketch and why ("reads another outline", "lies
on a turned plane"; `probe.restore_changed` too), and the design counts as changed. Once every value, timeline item
and the marker are back, the target body is read once more (its box, volume and pieces) and compared with its read
before the first try (E0 when no try ran; the other bodies of the component always with E0, by name when both reads
name them): `probe.restore_body` lists what differs ("its volume (1601.25 mm3 before, 1618.42 mm3 now)", "its size or
place", "the number of its pieces (1 before, 2 now)", "the other bodies of its component"). A clear difference (a box
moved more than 0.01 mm, a volume changed by more than a thousandth, another number of pieces, another set of other
bodies) goes to `health.body_changed`, and the design counts as changed. A smaller difference, past 0.0001 mm or a
millionth of the volume, goes to `health.body_changed` when a parameter, a sketch, a step or a stop of the tries also
shows a change, else to `health.body_unconfirmed`. When the end check rebuilt the whole design, the body is read again
after it; a difference that only that rebuild brought goes to `health.body_unconfirmed` too. `health.body_unconfirmed`
means the design is not confirmed back. `health.body_unchecked` is true when the body could not be compared.
`health.flipped` names the sketches that stayed on their other outline after a restore during the rows (`Motion.flipped`);
the result window says that the tries made then were not used to judge any size. After a row that did not build, or
whose read showed a followed sketch on another outline, the design is read again once the parameters are back and
before the next row (`ProbeRun`); that read is the next state's `start` in `probe.states`. A probe row that Fusion cannot build is listed in `probe.dropped`; no size is fixed for it.

A try can leave the design changed after the values are put back: a step that lost its input stays in error, or a
sketch left on its other solution makes a later projection lose its source (a new warning). Every later try would then
run on a changed design. So after a try that did not build, showed a new warning on any step, or read a followed
sketch on another outline, with the values back and before the design is read again, the timeline steps (health and
message) are compared, step by step, with their read before the first try (`RowExport`). A warning or an error that
was there before the tries does not count. A step that is worse is first given one full recompute (the change that put
the values back rebuilds only the steps it touches). When a step is still worse, the export tries, at most twice, to
bring the design back the way the try took it away (`design_edit.walk_back`): the sizes of the try set a small step
past their start values on the other side and back, then the sizes walked from the try's values to the start values
in four steps. Only parameters change, and they are put back after each attempt. When a step is still worse, the
tries stop there and the changed design is not read again (no start read, no sketch put back, no discovery tries,
whose parameters are kept as not tried). A size that moves a sketch and whose own tries were planned but did not run
is listed in `probe.untried` and the motion's `untried`, so it is not taken as one that changes nothing.
`probe.stopped` (`{ after, items, steps? }`: the label of the try run last, the steps still worse and, in `steps`,
`{ name, before, after }` of each) and `health.tries_stopped` (the same) say so, and the motion is built from the tries
before. When every step still worse is outside what the tries need (it has a timeline position, no capture needs it for
the tries, no part is built from it, and it names its component) and the part reads as at the start with the values
back, only the tries of the sizes behind it end (`export_plan.pipeline.outside_damage`): the sizes the try moved and
every user parameter that drives a step or a sketch of that component. The other sizes go on, compared with a baseline
measured again. `probe.ended` and `health.tries_ended` list `{ after, items, steps, components, sizes }` for each such
try, the motion keeps `unfinished` "stopped" for the sides of those sizes whose nearer tries never ran, and a discovery
try of such a parameter is kept as "not tried: a try left a step of its component worse than before". The design is
changed, so the export is undone at its end. The Undo data of the tries is dropped (Lighter on memory) only before a try
that starts with no step worse and every followed sketch as at its first read, and after the tries only when the same
holds. At the end of every export the timeline steps are compared with the start (`design_edit.timeline_health`), see
"Timeline steps after the export" below; `health.broken` names the steps in error that were fine before (at most 5).

Time limit of the tries. The tries (the rows and the discovery rows, `ProbeRun`) have a time limit: the choice of the
dialog's list "Stop the size tries after" (`ExportRequest.probe_time_limit` in seconds, `None` for no limit; the default
is `export_plan.time_limit.DEFAULT_SECONDS`, 10 minutes). The clock starts when the try runner is made, just before the
first try, and covers the reads and put backs between tries. `RowExport` asks `stop_when` before each try; once the
limit is reached it ends the run there, with the parameters put back as at the end of any run, and no later try of the
job runs (`RowExport.halted`). A try that did not build is still checked first, so a design it left broken is noticed
(`probe.stopped`, `health.tries_stopped`) as in a stop on a broken design. The rows planned after the stop are not made
(`ProbeRun._left` is 0), the discovery tries are kept as not tried (`probe.discovery`, reason "not tried: the tries ran
out of time"), and the last read, the put back and the end check run as after tries that ended on their own. A time
stop is not a health problem: nothing is added to `health`, and the Undo step of the export is dropped as usual when
the end check confirms the design is as it was. `probe.time_limit` is `{ limit_seconds, hit, seconds?, left_out }`: the
limit in seconds (`null` for none), whether it stopped the tries, how long the tries had taken then, and the Fusion
names of the sizes that move a sketch or a measured place and have no try of their own that built (their rows did not
run, or their last row did not build and its nearer tries did not run). Such a size is in the motion's `untried` and
`timed_out`; the translator gives it the reason "the tries ran out of time before this size was tried. Tip: raise the
time limit in the export dialog, or untick sizes that need no change": loose ("may give unexpected results") when a
formula still reads it, "not a size" when only a sketch reads it. `timing.probe.time_limit` holds `limit_seconds`,
`hit` and, when hit, `left_out`. The result window adds a line to "Result" when the limit was reached (several-body
files count each size once). The progress window shows a third line under the try: the time spent and an estimate of
the time left, from the average try so far times the tries planned so far, never past the time the limit leaves
(`messages.time_note`).

Timeline steps after the export. Before anything is read (when the Export for Paramability dialog opens, before its
capture moves the marker; for Export size choices when OK is clicked) the add-in reads, for every timeline item before
the marker (groups left out), its name, type, `healthState` (`ok`, `warning`, `error`), `errorOrWarningMessage` and
whether it is suppressed. On every way out (saved, failed, cancelled), once the parameters, the suppressed items, the
sketches and the marker are back, it reads them again. When a step differs: steps that were on at the start and read
off are turned back on, and the whole design is recomputed once (the last rebuild may have been one change that rebuilt
only the steps it touched). When a step is then still worse than at the start (a higher level, turned off, gone, or new
and not fine), every parameter is set to its start expression once more, in one change, and the design is recomputed
again. A step that is only better (a warning gone) asks for no more. These `health` keys say what was found, each only
when it has something to say:

| Key | Meaning |
| --- | --- |
| `steps_changed` | The steps still not as at the start: `{ name, type, before, after, message, was_message?, suppressed? }`, at most 8. `before` is `new` for a step that was not there, `after` is `gone` for one that is not there now; `message` is Fusion's text now, `was_message` the text at the start when it differs; `suppressed` is the state now when it differs. |
| `steps_more` | How many more steps differ than `steps_changed` lists. |
| `steps_worse` | True when any step that differs is worse than at the start, also one past the steps `steps_changed` lists. |
| `steps_recovered` | Steps that differed and came back by the actions below (at most 8). |
| `end_actions` | What was done, in order: `marker_back` (the marker read elsewhere and was put back), `marker_lost` (it would not go back), `turned_back_on`, `full_compute`, `values_again`. |
| `steps_unread` | True when the steps could not be compared (the timeline could not be read). |
| `deferred_left` | Sketches whose compute stayed deferred after the keeper moved their points (`SketchKeeper.deferred_left`). |
| `left_off` | Items turned off for the tries that are still off (`TryTimeline.left_off`, at most 5). |
| `body_unconfirmed` | Small differences of the target body with nothing else changed, or differences that only the end rebuild brought (at most 5). The design is not confirmed back. |
| `body_unchecked` | True when the target body could not be compared at the end. After tries that stopped (`tries_stopped`) the design then counts as not confirmed back. |
| `undo_dropped` | True when Fusion forgot Undo data during the export (Lighter on memory, `timing.undo.applied`). The lines about a changed design then say to close the design without saving and open the saved version instead of using Undo. |
| `sketch_gap_after_rebuild_mm` | When `full_compute` or `values_again` ran and the sketches were followed: the gap of a read of the outlines after those rebuilds (`pipeline.put_back.PutBack.settle`). `sketch_gap_mm` and `sketch_drift` take the larger of this and the gap read before, so a sketch the end rebuild moved counts as a changed design. |

A step that is worse than at the start (`steps_worse`), or a sketch in `deferred_left`, counts as a changed design:
the person gets a message box first and the result window says which steps and to use Undo. A step that is only better
gets the line without the message box. When the export stops (an error or a cancel) the same lines come in a message
box. A step can read worse at the end only because Fusion shows some warnings only after a full recompute: the
add-in cannot tell this from a change it made, so the line says the design may be changed.

Solver flips. Putting the values back does not bring back a sketch that a try moved to its other solution: Fusion solves
a sketch from where its points are. So the export keeps the places of the followed sketches' own points at E0
(`fusion_reader.sketch_keep.SketchKeeper`; projected and fixed points stay). When the `start` read shows a followed
sketch otherwise than at E0 (another outline, or a value more than 0.05 mm or degrees off, `geometry.tolerances.FLIP_TOLERANCE`; Fusion's
own restore leaves about a hundredth), every kept point more than 0.0001 mm from its place (`MOVE_TOL_CM`) is moved back,
with its sketch's compute deferred and then set back to what it was when kept, and read again (a sketch whose points
are all in place is not touched), and the design is rebuilt once, also when no point
moved (the keeper matches the points by their entity token and skips a point that is gone); the read after that is
the state's `put_back`. Put backs that do not bring a sketch back are counted per sketch: when every sketch off its
start had two in a row, no more are tried for them, and a sketch that cannot be put back does not stop the put backs of
the others. A sketch with the same curves under other entity tokens, in another order or direction, is not off its
start (`probe.same_shape`). A sketch still off its start after the put back is brought back once the way the tries
took it away (`design_edit.walk_back`, as above): each try run since the sketch last read as at its start, the last
first, at most three tries. The read after that is the state's `put_back`. A row that needs its
start still reads it, since a try can bring the sketch back too. A start read and a put back read hold only the outlines
(sketches, points, lines and outline faces), not `params`, `refs` or `box`. A row whose start was not read (the row
before it ended right) and after which the sketch was found on its other solution (the row read another outline or did not build, and the next read with the values back shows
the flip) may have started there: it runs once more right after its batch, from a checked start, and its first run is
left out of the states. The second run carries `again`; another outline there is a range limit of its own size. Rows run
again count in the 64 rows. The sketch is also put back before the discovery rows (their base is the read after it, a full read) and
once after the tries, so the design is left on the solution it had; that last put back also runs when the tries fail or
are cancelled, and after tries that failed `health.sketch_gap_mm` and `health.sketch_drift` still say whether a sketch
stayed away from its first read. After the tries, a sketch the put back does not bring back is walked back one size
at a time: each size that the tries since the sketch last read as at its start moved, the last first, a small step
past its start value on the other side and back, at most 16 walks (`walk_back`). `probe.recovery` (`{ put_backs,
again, walked_back?, attempts? }`, only when one happened) counts the extra rebuilds: one per put back, two per row
run again (the row and its restore), and in `walked_back` the attempts of `walk_back`. `attempts` lists the first 24
attempts in the order they ran: `{ row, kind, set, at, failed?, back? }`, the key of the row walked back, `other side`
or `walk`, the values set in turn (by Fusion name, in each parameter's unit), where it ran (the key of the row about to
run, `steps` for the check after a row, or `end`), the walk steps Fusion refused or could not build, and whether the
sketches read as at their start after it.

A file with several bodies (package kind `parts`) has one `report.json` with a `parts` list, one record per body:
`{ name, outcome, items, notes, capture, probe, sizes, derived }`, plus `refusal` or `error` for a body saved as a fixed
shape (and `gaps`, `reach` for a body with left out steps). A body whose copy stopped also has `after_stop`, as the
single body report does: what a walk past the stop finds (`docs/recipe-gaps.md`, "report.json and the result
window"). The `sizes` record at the top is shared by all bodies;
`derived` is per body.

### Timing (`timing`)

Every `report.json` has a `timing` block that says where the export spent its time (`lib/timing/`). It is measured with
`time.perf_counter`, in seconds rounded to 0.01. A timing failure drops the block and changes nothing else; the
export, the recipe and the notes do not depend on it.

```json
{ "total": 61.52,
  "phases": { "step_export": 1.2, "capture": 40.1, "size_table": 0.0, "translate_first": 0.8, "reach": 0.0,
              "probe": 15.0, "translate_final": 0.9, "restore": 0.5, "package": 0.1, "after_stop": 0.5 },
  "capture": { "seconds": 40.1, "steps": 246, "cached": true,
               "marker_moves": { "count": 250, "seconds": 31.0, "walk": 247, "helper": 3 },
               "measure": { "target_state": 2.0, "body_states": 0.4 },
               "readers": { "count": 480, "seconds": 3.1 },
               "faces": { "count": 12, "seconds": 0.9 }, "split": { "count": 2, "seconds": 0.2 },
               "helper_pass": 1.5, "placement": 0.1, "restore_marker": 0.8, "tail": 0.4,
               "tail_parts": { "target": 0.1, "parameters": 0.2, "links": 0.05, "graphs": 0.05 },
               "by_type": { "ExtrudeFeature": { "steps": 60, "seconds": 12.4 } },
               "by_component": { "Cup": { "steps": 200, "seconds": 35.0 } },
               "slowest": [ { "index": 87, "name": "Extrude41", "type": "ExtrudeFeature", "component": "Cup",
                              "seconds": 1.9 } ] },
  "probe": { "tries": 9, "tries_seconds": 12.0, "rebuild": 10.5, "read": { "count": 14, "seconds": 3.1 },
             "read_parts": { "sketches": { "count": 14, "seconds": 2.2 }, "params": { "count": 9, "seconds": 0.4 } },
             "calls": { "computes": { "baseline": { "count": 1, "seconds": 0.8 }, "row": { "count": 0, "seconds": 0.0 },
                                      "walk_step": { "count": 3, "seconds": 2.4 } },
                        "param_sets": { "count": 9, "seconds": 7.1 }, "param_put_backs": { "count": 9, "seconds": 7.0 },
                        "health_passes": { "count": 27, "seconds": 0.4 }, "timeline_reads": { "count": 3, "seconds": 0.6 },
                        "check_cleared": 0,
                        "after_tries": { "computes": { "put_back_values": { "count": 1, "seconds": 0.8 },
                                                       "end_check": { "count": 1, "seconds": 0.8 } },
                                         "param_sets": { "count": 0, "seconds": 0.0 },
                                         "param_put_backs": { "count": 1, "seconds": 0.9 },
                                         "health_passes": { "count": 2, "seconds": 0.1 },
                                         "timeline_reads": { "count": 2, "seconds": 0.4 },
                                         "check_cleared": 0 } },
             "put_back": { "count": 0, "seconds": 0.0 }, "time_limit": { "limit_seconds": 600, "hit": false },
             "try_seconds": 13.2 } }
```

- `total`: from the start of the pipeline to the moment `report.json` is made. The dialog's own reading before the OK
  click and the write of the package file are not in it (the add-in logs the write time).
- `phases`: `step_export` (the STEP of the part), `capture` (reading the timeline), `size_table`, `translate_first`
  (the first translation, and the one after the reach is known), `reach` (asking Fusion which step made the faces later
  steps pick), `probe` (its start, tries, close and the `derived` shadow), `translate_final` (with the motion the probe
  found), `restore` (parameters, suppressed steps and the timeline marker put back), `package` (manifest, recipe and
  report assembled). `after_stop` is the second walk after a stop and `outline_check` the time spent checking that
  written outlines do not cross themselves (`sketch_crossings.OutlineChecks`); both are already inside the translate
  phases. A phase
  that did not run is 0.0. A several-body export has one `timing` block at the top of its `report.json`.
- `capture` (one body) or `captures` (several bodies: the same record plus `part`, the body's name): `seconds` is the
  whole read, `cached: true` marks a read the dialog made before the export. A step's time is the marker move that
  built it plus its measures and reads (moving the marker to position k makes Fusion build step k - 1). `marker_moves`
  counts every assignment of the timeline marker made by the read: `walk` is one per timeline position (steps before
  the marker + 1), `helper` the moves of the pass over the tool bodies of Combines. `measure.target_state` is the volume
  and box of the target at every position, `measure.body_states` the measures in the helper pass. `readers` is the sum
  of all feature readers (before and after each step); `faces` (outline face reads) and `split` (Split Body reads) are
  inside `readers`. `placement` is the place of the picked body, read once before the walk (the capture's
  `target.placement` is the same record; only the first few vertices of the body are fetched, so a body with many
  vertices costs no more). `restore_marker` is the move back to the person's marker, which makes Fusion build the
  later steps again; `tail` is what is read after the walk, with `tail_parts`: `target` (the body's volume and box),
  `parameters` (user and model parameters, with where each acts), `links` (sketch links) and `graphs` (sketch
  graphs). `by_type` and `by_component` sum the time of the steps, slowest first (a component is named by its name,
  or its token); `slowest` lists the 10 slowest steps.
- `probe`: `tries` is the rows run (rows run again included), `tries_seconds` the time inside them, `rebuild` that time
  without the state reads made inside it (setting sizes, Fusion rebuilding, putting them back), `read` the state reads of
  the tries (rows, starts, put backs, the discovery base; not the marker roll check or the read after the tries) with
  `read_parts`, the time of each part of those reads (`sketches`, `points` with the lines, `params`, `refs`, `box`,
  `pieces`, `faces`; a part no read held is left out; a face read that parks the marker does not count the move back, which
  happens in the change that puts the values back and so counts in `rebuild`), and `put_back` the sketch put backs
  (`probe.recovery`). `calls` is what the tries asked of Fusion, counted by the store the try runner gives the job
  (`lib/design_edit/metered.py`): `computes` has one `{ count, seconds }` per part of the export that asked for a
  full rebuild (`row`, `counting_warning`, `check_after_row`, `sketch_put_back`, `baseline`,
  `rebase`, `walk_step`, `put_back_values`, `other`; a part that asked never is left out), `param_sets` the sets of
  parameters for a try or a walk, `param_put_backs` the sets that put them back, `health_passes` the passes over the
  timeline items for errors and warnings, `timeline_reads` the reads of the whole timeline,
  and `check_cleared` the rebuilds of a check after which a step that read worse was fine. A rebuild made while one part
  runs inside another counts under the outer part. `after_tries` holds the same keys for the calls the put back makes
  once the tries are done (the values put back, and `end_check`, the rebuilds, sets and reads of the end check); it is
  set again at each point of the end, so it holds all calls so far. The totals leave out everything that does not go
  through the store the add-in gives the tries: the rebuilds made inside Fusion calls that turn items on or off or move
  the timeline marker, the capture, the state reads of the tries (`read`) and the marker moves of the reads. A try
  that builds costs about two counted rebuilds, so the counts can be compared between versions but do not sum to the
  time of the tries. `time_limit` is the time limit of the tries (`limit_seconds`, `null` for no limit), `hit` whether
  it stopped the tries and, when it did, `left_out` the sizes it left without a try (see "Time limit of the tries" under
  "Probe states"). `try_seconds` is the same value as in
  `probe.timeline` (from the first try to the end of the discovery rows).
- `undo`: the "Lighter on memory" box of the dialog (`lib/export_plan/undo_steps.py`). `{ "on": false }` when the box is
  off. When it is on: `{ "on": true, "applied": true, "steps": 12, "error": "" }`. `steps` counts the calls of
  `Command.beginStep(makeExistingStepNonUndoable=True)` that worked: one before each try (with every value back) and
  one after the tries. `applied: false` with `error` set means the call was missing, raised or answered False; then no
  further call was made and the export ran as with the box off. A call that worked once and failed later keeps
  `applied: true` and names the failure in `error`. After the export one more call drops the Undo data of its last part,
  only when `health` confirms the design is as it was (`health.back_as_it_was`: no value left, no sketch drift, no
  worse step, nothing left off or deferred, the steps read, the sketches compared and the marker back).

### Derived values (`derived`)

Shadow mode of reading sketches directly (`lib/probe/derived.py`, `derived_keys.py` and `lib/design_model/dimension_sizes.py`). When the
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
- Size settings (`dimension_sizes.override_sets`): the sizes the sketch's dimensions read, at most 12, each at 25 percent
  below and above its value (as the first tries), then all low and all high. Two dimensions that read one size move
  together. The solver checks its redundant rules and choices at these settings, and the formulas are fitted over them.
  Settings where a value has no number (a square root of a negative value) leave the key without a formula.
- Constants (`sketch_solve/constants.constants_of`): a projected entity from another component that no parameter reaches through
  `design_model.step_links.reach`, and an implicit line through the sketch origin (an origin axis). Other projected entities
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

Read in the same stubs on 2026-11-16 for Path Pattern: `PathPatternFeature` (`inputEntities`, `patternEntityType`,
`path`, `quantity`, `distance`, `startPoint`, `isFlipDirection`, `patternDistanceType`, `isSymmetric`,
`isOrientationAlongPath`, `suppressedElementsIds`, `patternElements`), `Path` (`count`, `item`, `isClosed`),
`PathEntity` (`entity`, `curve`, `isOpposedToEntity`), `PatternElement` (`id`, `isSuppressed`, `transform`). Hand
check PP1 (Fusion 2706): on a line, copies past the end run on along the line with no warning; on an arc that starts
at 0, the element transforms are the moves of the copies and agree with their faces; with a start point of 0.75 and
the flip, the copies land off the arc and the transforms do not agree with the faces, so the translator leaves a
round path pattern with a start point other than 0 or the flip out.

Read in the same stubs on 2026-11-16 for the places of pattern copies: `PatternElement` (`faces`, a list of
`BRepFace`; `transform`, documented as the identity for the first element), `Feature.faces`, `BRepBody.faces`,
`BRepFace` (`centroid`, `area`). Hand check CP1 (Fusion 2706, circular patterns): the ids follow the order of the
copies, the faces show where each copy is, and the transform of each copy after the original is one step ahead.

Read in the same stubs on 2026-11-12 for Split Body (hand tests SB1 and SB2; exports of 0.10.5 on Fusion 2706.1.17
confirm a split by an origin plane, by an offset plane and by a body, and that `splittingTool` gives nothing with
the marker after the feature, so `inside` was missing there):
`SplitBodyFeature` (`splittingTool` and `splitBodies`, both read with the marker before the feature as the stub
asks; `isSplittingToolExtended`; `bodies`), `BRepBody.pointContainment` (a `PointContainment` value: inside 0, on 1,
outside 2, unknown 3), `BRepBody.isSolid`. For drafts (hand test DR1): `DraftFeature` (`inputFaces`, `plane`,
`isTangentChain`, `isDirectionFlipped`, `draftDefinition`), `AngleExtentDefinition` (`angle`, `isSymmetric`),
`TwoSidesAngleExtentDefinition` (`angleOne`, `angleTwo`), `BRepFace.boundingBox`.

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
| Taper sign (Fusion positive grows or shrinks) | one constant `FUSION_TAPER_SIGN` in `extrude/taper.py`; the Extrude directions test |
| `ToEntityExtentDefinition`, `TwoSidesDistanceExtentDefinition`, `TwoSidesAngleExtentDefinition`, `FromEntityStartDefinition` field names | reader falls back to `other`; the Extrude directions test |
| Revolve turning sense | `start_face_normal`, `end_face_normal`, `made_box`; the Turned knob test, hand check RC1 |
| Hole `direction` points into the material; blind depth is measured to the shoulder, not the tip; how a flat drill point shows (`tipAngle` 180 or another member) | `end_points`; the Holes test |
| `patternElements` includes suppressed elements | a place with no element is skipped only when a copy is suppressed (an element marked suppressed or `suppressed_ids`); else the pattern is left out (`pattern_places.listed_places`); the Bin test |
| `PatternElement.transform` of rectangular, path and body patterns is the move of the copy | the translators check each place against the faces of the copy and refuse places that repeat or do not fill the count; hand checks PE1, PE2 and PE3 |
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
| A whole cylinder face has two loops of one `Circle3D` edge each (no seam edge); `Cylinder.origin`, `axis`, `radius`; `Circle3D.center`, `normal`, `radius`; `BRepEdge.faces` gives the face across an end circle; `feature.faces` after the item lists the moved cylinder | a face with a seam or part of a circle has other loops and is left out; `rounds_after` must hold the cylinder with the new radius, else the step is left out; hand check PF1 in `docs/hand-checks.md` |
| `EmbossFeature.profiles` (`Profile` and `SketchText` items; the area of a text is computed from its outlines), `inputFaces`, `faces` after the item, `isTangentChain`, `depth`, `horizontalDistance`, `verticalDistance`, `rotationAngle`; `BRepFace.area`, `BRepFace.body`; a positive `depth` raises and a negative one sinks; the feature exists only in Fusion builds from September 2025 and is marked preview in the API reference | `volume_after` must differ from `volume_before` by `sum(areas) * abs(depth)` with the sign of `depth`, else the translator refuses; the Emboss hand tests (section 10 of `docs/hand-tests.md`) |
| `SketchText.asCurves()` returns the text outline as closed `Curve3D` loops (lines, arcs, free curves) without changing the design; the points are in sketch space (Fusion 2706, a live check on a face of a plate and on a side face; the reference does not say); `SketchText.boundingBox` is in sketch space | `space` is decided by the sketch plane and the bounding box, and `ambiguous` or a failed read gives a text marker; an emboss checks the text area against the measured volume; the Text hand tests (section 11 of `docs/hand-tests.md`) |
| Free curves (`NurbsCurve3D`, `EllipticalArc3D`) evaluate through `CurveEvaluator3D.getPointAtParameter` over `getParameterExtents`, and `getTangent` gives the direction at an end | a curve that cannot be evaluated has no samples and is refused; a missing tangent is left out; the Spline hand tests (section 11 of `docs/hand-tests.md`) |
| `Sketch.parentComponent`, `ConstructionPlane.component`, `BRepFace.body`, `BRepEdge.body` | `foreign` reads them in a try; an unreadable one leaves the record unmarked |
| `SketchEntity.referencedEntity` of an entity projected from another component comes as a proxy whose `assemblyContext.component` is that component (confirmed by a real export: the pipe component was found); the `body` of such an edge and its `nativeObject` token equal the token `bodies_after` gives; `lineOne`, `lineTwo`, `line` and `curve` name the entities of the other line constraints; `ModelParameter.createdBy` of a parameter that `dependentParameters` gives names the same maker as when the parameter is listed from its component (`ModelParameter.component` answered the root for every one); `profile`, `path`, `guideRail`, `loftSections` and `holePositionDefinition` can be read with the marker before a step of another component | a wrong read only leaves a link out; the discovery tries still find a parameter that moves the part; the K10 hand test in `docs/hand-tests.md` |
| `Component.xYConstructionPlane` / `xZConstructionPlane` / `yZConstructionPlane` and `ConstructionPlane.createForAssemblyContext(occurrence)` (in the API reference) show a component's origin planes in the root's coordinates; the three tips 10 mm along the normals fix the occurrence frame | `tool_place` lands the frame on them within 1e-3 mm or records an error; the G tests in `docs/hand-tests.md` |
| The `entityToken` of a tool body's native body equals the token in `bodies_after` of the steps that made it, and `Design.findEntityByToken` finds it with the marker just before the Combine | an unmatched token leaves the steps unread and the Combine refused naming the step; G1 |
| `BRepBody.copyToComponent(proxy)` keeps the assembly place | the copy guard in `step_export.py` compares the bounding boxes (1e-3 mm) and refuses before writing |
| `MoveFeature.inputEntities` (only bodies or only faces) read with the marker before the item; the same bodies found by token after it, with their vertices in the same order | `points_before` and `points_after` are fitted by the translator; a mismatch is refused; the Move hand tests B3 to B5 |
| `BRepBody.boundingBox` (API reference: "Returns the bounding box of this body") of a moved body with no vertices moves by exactly the shift of a Move along X, Y and Z | a box that changes size or moves by another vector refuses the Move; a box that cannot be read is null and refuses it; the hand check of a sphere moved into a box (`docs/hand-checks.md`) |
| `MoveFeature.definition` has a class per type, and the type name contains `TranslateXYZ`, `Rotate`, `FreeMove`, `PointToPoint`, `PointToPosition` or `TranslateAlongEntity` | an unknown name reads `other` and the Move is refused; B3 to B5 |
| `xDistance`, `yDistance`, `zDistance` (model parameters in cm) and `isDesignSpace` of a translate move; `angle` (model parameter in radians) and `axisEntity` of a rotate move | a member that cannot be read is null, and the Move is refused; the sign and the space (component or design) come from the fit against the points; B4, B5 |
| `ScaleFeature.inputEntities` and `point` with the marker before the item; `isUniform`, `scaleFactor`, `xScale`, `yScale`, `zScale` as model parameters without a unit; the axis factors run along the component's own axes | a member that cannot be read is null and the scale is left out; the measured box and volume check the factors and the point; SC1 |
| `MoveFeatureFreeMoveDefinition.transform` answers for a free move | null when it cannot be read; the fit against the points decides alone; B3 |
| `CopyPasteBody.sourceBody`, an `ObjectCollection` in the API stubs, can be read with the marker before the item (and is empty or shorter when a source was consumed), `CopyPasteBody.bodies` after it, also when the source lives in another component | empty `sources` or null `result_bodies` refuse the Paste; B2, B8 |
| `inputEntities` of a rectangular, circular or mirror pattern of bodies with the marker before the item, `bodies` after it holding every copy (not the sources) | null `result_bodies` refuses the pattern; copies are matched to the elements by the points; B6 |
| `BRepBody.vertices` and `BRepVertex.geometry` of the native body: the first 8 in a stable order across a paste, a move and a pattern copy | fewer than 3 usable points refuses the fit; B2, B3, B6 |
| `BRepBody.volume` of a tool body with the marker before the Combine, and of any body the second pass finds by token (`Design.findEntityByToken`) | null in `tools[].volume` and `body_states`; the volume checks on a tool are left out; B1, B9 |
| `TemporaryBRepManager.get()`, `copy(body)`, `booleanOperation(targetBody, toolBody, booleanType)` (changes the target body in place and answers true or false), `BooleanTypes.IntersectionBooleanType` and `UnionBooleanType`, and the `volume` of a temporary body; none of it changes the design | any exception or a false answer gives null `intersect_volumes` and `intersect_model: unknown`, which refuses the Combine; B7 |
| Face outlines, to confirm by hand: `ExtrudeFeature.profile` gives the `BRepFace` with the marker before the step; `BRepFace.loops`, `BRepLoop.isOuter`, `BRepLoop.edges` and `BRepEdge.geometry` give the edges in the component's coordinates; `BRepEdge.evaluator` covers only the edge; `Plane.uDirection` lies in the face; `BRepFace.evaluator.getNormalAtPoint` points out of the body; `BRepFace.area`; `Component.features.extrudeFeatures` lists the earlier extrudes and `Feature.timelineObject.index` their places; `startFaces`, `endFaces` and `sideFaces` of an earlier extrude, read with the marker before the step, hold the face the step uses (the same entity or `entityToken`); a positive distance goes along the outward normal | a face that cannot be read refuses the step; a face no extrude lists is copied as measured with its sizes marked; `end_offset` and `side_leans` check the direction and taper; hand test F1 in `docs/hand-tests.md` |
| Reach, to confirm by hand: `Feature.faces` of the entity of a timeline item, read with the marker right after the step, lists every face that step created, and read with the marker just before a later step it still gives the same faces (the same entity or `entityToken`) as the ones a later pick finds through `BRepEdge.faces`, `findEntityByToken` or `findBRepUsingPoint`, for each feature type that can be a candidate (extrude, revolve, sweep, loft, round, chamfer, shell, pattern, combine, move); whether the list of a Move, a Combine join and a draft is empty; whether a face a later step trimmed or split drops out of the list; `Component.findBRepUsingPoint` with `BRepFaceEntityType` finds a face from a recorded point | a list that is empty, shorter than right after the step or unreadable counts as reached by every pick, a pick that cannot be found counts as reached, and the translator then leaves the later step out (safe side); hand tests L2, L3, L5 and L14 in "Check first in this version" of `docs/hand-tests.md` |
| An intersect with several tools keeps the part and every tool, or the part and any tool | measured per export from the volumes and written as `intersect_model`; B7 |
| Faster tries, to confirm by hand (checked against the installed stubs, never run): `Timeline.item(index)` gives the item the capture saw at that index; `TimelineObject.name`, `TimelineObject.isGroup`, and `TimelineObject.isSuppressed` get and set on an item before a rolled back marker; `Design.computeAll` after a change of `isSuppressed` rebuilds with the item off and leaves the marker in place; turning the item back on restores the design exactly, adds no item and keeps the order; whether the changes add entries to Undo or mark the document changed | the store touches nothing when a name does not match, counts only items that read suppressed, and names items that read suppressed after the restore; a read with the items off must equal E0 and show no new error; hand test U1 in "Check first in this version" of `docs/hand-tests.md` |
| One change for the sizes of a try, to confirm by hand (read in the installed stubs on 2026-11-13, never run): `Design.modifyParameters(parameters, values)` with `ValueInput.createByString` sets every expression or none, rebuilds the design once like an edit in the Parameters dialog, updates `TimelineObject.healthState` of the steps it changed, and leaves the timeline marker where it is, so no `computeAll` is needed after it | a call that is missing, raises or answers false sets the values one at a time and recomputes as before; the store puts the marker back after it in any case; hand tests SP2 and SP4 in `docs/hand-tests.md` |
