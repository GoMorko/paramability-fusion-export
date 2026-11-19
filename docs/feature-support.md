# Feature support

The tables show which Fusion design actions each export copies, and what could be copied later.
They are for ParamabilityExport 0.14.5.
`docs/limits.md` (Export for Paramability) and `docs/orca-output.md` (Export for Orca) have the details.

The two exports:

- **Export for Paramability** writes a `.paramability` recipe. The Paramability app rebuilds the part, and the
  people who download it can change its sizes.
- **Export for Orca (experimental)** writes an OrcaSlicer 2.5 project. Orca's Design tab rebuilds the part, and its
  variables follow your user parameters.

The words in the cells:

- **Copied**: the step is copied, and its sizes follow the parameters.
- **Partly**: the step is copied, but some of it is left out or keeps a fixed number. The note says what.
- **Left out**: the step is not copied. The result window gives the reason and, when there is one, a tip.
- **Not read**: the add-in passes the item by. It changes no shape of the part.
- In the "possible later" columns: **Yes, add-in only** (the add-in can do it alone), **Yes, needs an app change**
  (the Paramability app cannot rebuild it yet), **Needs Orca** (Orca's Design tab has no such feature, or cannot tie
  it to a variable), **No** (the reason is in the note), **-** (it is copied already).

A step that one export leaves out makes the copy differ from the Fusion part. Later steps are still copied when they
can be.

## Sketch

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Line | Copied | - | Partly | Needs Orca | Orca: an outline of lines in an extrude without taper follows at its corners. Other outlines keep their numbers. |
| Rectangle | Copied | - | Copied | - | Orca: width and height follow in extrudes, sweeps and lofts. In a revolve it keeps its numbers. |
| Circle | Copied | - | Copied | - | Orca: the radius follows. A hole circle whose centre moves becomes an Orca hole. |
| Arc, sketch fillet | Copied | - | Partly | Needs Orca | Orca keeps arcs as numbers. |
| Polygon | Copied | - | Partly | Needs Orca | Orca: as for lines. |
| Slot | Copied | - | Partly | Needs Orca | Orca: the arcs keep their numbers. |
| Ellipse | Copied | - | Copied, fixed numbers | Yes, add-in only | Paramability: a full ellipse. An elliptical arc is copied as spline segments with fixed numbers. Orca: a full ellipse is written as an ellipse curve (centre, major radius, minor radius, direction of the major axis) with its current numbers; an elliptical arc is written as an elliptical arc curve with those and two angles, when its ends come out as Fusion measured them (else the outline is left out). The sizes that move them are marked as for other curves that keep numbers. |
| Spline, conic curve | Partly | No | Partly | No | The shape is copied as fixed numbers. The points of a free curve are not a formula of the sizes. Orca: only a spline that Fusion gives exactly. |
| Text | Partly | Yes, add-in only | Partly | Needs Orca | Paramability: each letter is an outline. The text height is not a size. At most 400 outlines. Orca: each letter is a fixed outline in a sketch of its own; only the depth follows. One side or symmetric, no taper, not with other outlines in one extrude. |
| Offset | Copied | - | Partly | Needs Orca | Orca: as for the curves it makes. |
| Project, Intersect, Include 3D geometry | Copied | - | Partly | Needs Orca | Paramability: follows what the size tries measure. From another component it may give unexpected results. Orca: keeps its place, and the sizes read before the sketch are marked. |
| Constraints | Copied | - | Partly | Needs Orca | Paramability: Fusion solves them during the size tries. Orca: the add-in solves them itself. It does not read smooth, polygon, sketch pattern or face constraints. |
| Sketch dimensions | Copied | - | Partly | Needs Orca | Paramability: lengths, and angles through sine and cosine, up to 3 terms per value. Orca cannot tie a sketch dimension to a variable. Only rectangle sides, circle radii and corners of straight outlines follow. |
| Construction lines and points | Copied | - | Partly | Needs Orca | They build nothing. They place other curves. |
| Sketch rectangular or circular pattern | Copied | - | Partly | Needs Orca | Orca: the copies keep their numbers. |
| Sketch on a face of the part | Copied | - | Partly | Needs Orca | Orca: the sketch plane keeps its place. Every size read before the sketch is marked. |

## Create

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Extrude: one side, distance | Copied | - | Copied | - | |
| Extrude: symmetric | Copied | - | Copied | - | |
| Extrude: two sides | Partly | - | Copied | - | Paramability: an intersect to two sides is one tool body of both sides. Both: two sides that end on the same side of the sketch are left out. |
| Extrude: To object, flat face or plane square to it | Copied | - | Copied | - | Paramability: follows the face. Orca: the measured distance; it follows an offset plane or the end face of a copied extrude. Both: with Chain Faces on, only when the outline lands on the face alone, and the sizes that may move the face or the outline are marked. |
| Extrude: To object, tilted or curved | Partly | Yes, add-in only | Left out | Needs Orca | Paramability: one side, no taper, no offset, a face of the same body; with Chain Faces on, a tilted flat face only when the outline lands on it alone. A face that a size may move is followed only when a copied extrude made it, else the step is left out. Orca names a face by its own numbering. |
| Extrude: All, cut or intersect | Copied | - | Copied | - | Orca: a one way cut with material behind its sketch is a 1000 mm cut. |
| Extrude: All, join or new body | Partly | - | Left out | Needs Orca | Fusion ends it where the part ends. Paramability: one way, no taper, no thin wall, the picked body the only body it joins, and Fusion's end on the far side of that body; the sizes that may change the body before it or move its outline are marked. A new body has no body before it, so it is left out. |
| Extrude: start offset | Copied | - | Partly | Needs Orca | Orca: the offset keeps its number. |
| Extrude: start From object | Copied | - | Partly | Needs Orca | Orca: the sketch plane moves to the face, but does not follow it. |
| Extrude: start From object with an offset | Copied | - | Partly | Needs Orca | Both: the start face that Fusion measured (or the end cap of a join) shows which way the offset goes; without it the step is left out. Orca: the sketch plane moves to the face plus the offset, and the offset keeps its number. |
| Extrude: taper | Copied | - | Partly | Needs Orca | Paramability: under 45 degrees. A tapered cut through all both ways is left out. Orca: not with holes in the outline, not through all. |
| Extrude: new body, join, cut | Copied | - | Copied | - | Both: a new body from several outlines that makes several bodies is left out. Orca: a cut that splits the part is left out. |
| Extrude: intersect | Partly | Yes, add-in only | Partly | Yes, add-in only | Both: one outline only. |
| Extrude, revolve or loft: new component | Copied | - | Copied | - | Both: the body it makes, with its sketch from the component that was active, placed through the assembly. A sketch of a component placed more than once is left out. A sweep made so is left out (its path stays in the other component). |
| Extrude of a flat face of the part | Copied | - | Partly | Needs Orca | Paramability: follows when the face is the end of an earlier extrude without taper; else measured, with sizes marked. Orca: the face as it is now. |
| Thin extrude: one closed outline | Partly | Yes, add-in only | Partly | Yes, add-in only | Paramability: one way, no taper, no To object. Sharp wall corners are rounded, with a note. Orca: one rectangle or one circle, one way or symmetric, no taper; the outer outline less the inner outline, their sizes the drawn sizes plus or minus the thickness. The end face Fusion measured must show the side of the wall and sharp corners. Other outlines are left out. |
| Thin extrude: open line | Partly | Yes, add-in only | Partly | Yes, add-in only | Paramability: straight lines drawn one after the other, one way or symmetric, no taper; square ends and sharp corners as in Fusion. The faces Fusion made must show the side of the wall. A line with arcs is left out. Orca: one straight line with the wall centred on it is a rectangle whose length and thickness follow; any other line is the outline of its wall, drawn with numbers (the line and the thickness are marked). |
| Thin extrude: several outlines, holes, two ways, To object, taper | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Revolve: full turn or angle | Copied | - | Copied | - | Paramability: a later shell, fillet or chamfer that picks its faces or edges follows its sizes, also on the inner walls a shell leaves on a full turn and on an end face whose angle stays. A pick on an end face that turns with a size, or inside a shelled part turn, keeps its place, and the sizes are marked. Orca: the axis in the sketch plane, each outline on one side of it. A cut that splits the part is left out. |
| Revolve: symmetric | Copied | - | Copied | - | Fusion's angle is the turn to each side; 180 degrees or more to each side closes the ring. Orca: an angle that follows a size is two turns, one to each side, and a later round or chamfer of a group of edges on that part is left out. The angle keeps its number for an intersect, and for a cut when one half would cut nothing. |
| Revolve: two sides with two angles | Copied | - | Partly | Needs Orca | Left out when one angle is 90 or 270 degrees and the start face fits both sides. Two equal angles keep their numbers. Orca: both angles keep their numbers. |
| Revolve: outline with holes, several outlines | Copied | - | Copied | - | Paramability: outlines that share a line make one outline for the picks of later steps, so a round or chamfer where they meet (also inside a shell) follows the sizes. When the outlines overlap, or a size moves one so that they meet in another way, such a pick keeps its place and the sizes are marked. Orca: each hole is turned and cut away, and each outline is turned by itself. Left out: a new body made of separate outlines, outlines that turn different ways (on two sides of the axis) unless the turn is a full circle, a join of outlines whose turns overlap, and a cut where one outline would cut nothing after the others (one whose turn lies inside the others' is dropped instead). A later round or chamfer of a group of edges on the part is left out. |
| Revolve or circular pattern: axis on a cone or torus face | Copied | - | Copied | - | A cylinder, a cone or a torus face turns about its own axis. A sphere or a free-form face has no axis and the step is left out. The sizes that may move the face are marked. |
| Sweep: path in one plane (lines, arcs, splines) | Copied | - | Partly | Needs Orca | Paramability: a path of lines and arcs follows sizes; a spline path is copied as measured. Orca: the path keeps its numbers, one outline without holes, no sharp corners. |
| Sweep: path in 3D | Partly | Yes, needs an app change | Left out | Needs Orca | Paramability: lines joined by tangent arcs, as measured. Splines in 3D are left out. |
| Sweep: twist, taper, parallel orientation | Copied | - | Left out | Needs Orca | Paramability: with a note to check the shape. A twist together with a taper is left out. |
| Sweep: guide rail, guide surface | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Loft: two outlines | Copied | - | Partly | Needs Orca | Both: free ends, no rails. Paramability: straight faces between the outlines. Orca: two circles, or two straight outlines in parallel planes whose corners pair up, no holes. |
| Loft: three or more outlines | Left out | Yes, add-in only | Left out | Needs Orca | The app lofts through many outlines; check that the smooth shape matches Fusion's. |
| Loft: rails, centre line, point or tangent ends, closed | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Rib, Web | Partly | Yes, add-in only | Partly | Yes, add-in only | Both: straight lines drawn one after the other, no draft, no fillet, as a thin wall along each line. The faces Fusion made must show the wall, and the part must grow by the whole wall: a wall that runs into the part (where Fusion stops it), a rib that Fusion fills up to the part (a gusset in a corner), and a web whose lines Fusion stretches to the part are left out. To Next keeps the depth Fusion measured, and the sizes before the step are marked. A wall that may run into the part at other sizes marks its depth. The sizes before the step are marked unless the wall stands on the face its sketch is drawn on. Orca: the thickness and depth follow as for a thin extrude of an open line. Orca's own Rib is not used yet. |
| Emboss: flat face | Copied | - | Partly | Yes, add-in only | Both: as an extrude from the face. Not moved or turned on the face. Orca: the depth follows; an outline that Fusion trims to its face is left out. |
| Emboss: curved face, tangent chain | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Hole: simple, counterbore, countersink | Copied | - | Copied | - | |
| Hole: depth distance or through all | Copied | - | Copied | - | |
| Hole: To face | Copied | - | Copied | - | Both: the face or plane must be flat, square to the hole, with a flat hole end. Orca: the measured depth; it follows an offset plane or the end face of a copied extrude. |
| Hole: drill point | Copied | - | Partly | Needs Orca | Orca: the drill point is left flat. |
| Hole: tapped, cosmetic thread | Copied | - | Copied | - | Cut at the drill size Fusion measured (the thread's minor diameter). |
| Hole: tapped, modeled thread | Copied | - | Partly | Needs Orca | Through all holes need an export with this version. Orca: simple and counterbore holes, right hand only; the thread start under a counterbore keeps its number. |
| Hole: taper tapped | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Thread: modeled | Copied | - | Partly | Needs Orca | Metric and Unified 60 degree threads. Paramability: at most 100 turns of threads and coils, not in a tool body. Orca: right hand only. |
| Thread: cosmetic | Copied | - | Copied | - | It changes no shape. |
| Thread: other forms, tapered | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Box, Cylinder, Sphere, Torus | Left out | Yes, add-in only | Left out | Yes, add-in only | Reason: Fusion does not tell add-ins where the step sits or how it joins the part. Tip: draw the shape in a sketch and extrude it (a rectangle or a circle) or revolve it (a half circle or a circle). The Fusion API reference and the API stubs (`adsk/fusion.py`, Fusion 2706) give `BoxFeature`, `CylinderFeature`, `SphereFeature` and `TorusFeature` only the members of `Feature` plus `deleteMe` and `dissolve`: no size, plane, centre, direction or operation. `BoxFeatures`, `CylinderFeatures`, `SphereFeatures` and `TorusFeatures` have only `item`, `itemByName` and `count`, so a script cannot make these steps either. The sizes may come from `ModelParameter.createdBy` and `role`, as for a coil, but no live check has shown that yet (hand check 101, PM1). A copy would have to measure the place and the operation from the faces and volumes, as the coil reader does. |
| Coil | Partly | Yes, needs an app change | Left out | Needs Orca | Paramability: round, square or triangle section, no taper, at most 8 coils. A spiral, a taper and half turns are left out. Orca: left out. Its sweep along a helix keeps the wire square to the helix, but Fusion keeps it on a plane through the axis, so the ends and the thickness of the wire differ. A sweep that keeps the axis direction, as Orca's thread does, would copy it. |
| Pipe | Partly | Yes, add-in only | Partly | Yes, add-in only | Paramability: a circle section, solid or hollow, along the whole path, as a sweep of the circle; sharp corners are mitred. A square or triangle section, and a closed path that starts on a sharp corner, are left out until a hand check shows how Fusion builds them. Orca: a circle section, solid or hollow, along the whole path, as a sweep of the circle; the path as for a sweep (in one plane, no sharp corners); the diameter and the wall follow variables, the path keeps its numbers. |
| Rectangular pattern of features | Copied | - | Copied | - | Count and spacing follow. Orca: no rounds or chamfers among the copied steps. |
| Circular pattern of features | Copied | - | Copied | - | Count and angle follow. Paramability: an even count may give unexpected results. |
| Pattern with suppressed copies | Copied | - | Left out | Needs Orca | Orca's pattern cannot leave copies out. |
| Pattern of bodies, joined by a Combine | Copied | - | Partly | Yes, add-in only | Orca: a rectangular or circular pattern, or a mirror, whose copies one Combine joins or cuts together with their source; spacing and angle follow, the count keeps its number. Left out when the Combine takes only some copies, intersects, or a step changes a copy on its own. |
| Pattern or mirror of faces | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Path pattern | Partly | Yes, needs an app change | Partly | Needs Orca | Paramability: a path of one line, arc or circle; count and distance follow, and their ranges stop where the copies would leave the path. Other paths need an app change. Orca: a path of one line, arc or circle, and also an arc whose copies keep their direction (then the distance keeps its number); count and distance follow, and the parameter's line says how far they may go before the copies leave the path. Orca's pattern along a curve does not space copies by length on other curves. |
| Mirror of features | Copied | - | Copied | - | Orca: the mirror plane keeps its place. |
| Mirror of bodies, joined to the part | Copied | - | Copied | - | |
| Thicken | Left out | Yes, needs an app change | Left out | Needs Orca | The app does not rebuild surfaces. |
| Boundary Fill | Left out | Yes, needs an app change | Left out | Needs Orca | |

## Modify

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Press Pull of a flat face (Offset Faces) | Copied | - | Left out | Needs Orca | Paramability: faces that meet and faces with a leaning or rounded side are copied too; the app lets the faces around them follow. |
| Press Pull of a whole round face (a pin, a boss or a bore) | Copied | - | Copied | - | Both: the face goes all the way round, both ends are flat and square to its axis, and the new radius stays clear of the other edges of the end faces. Paramability: needs an app that reads recipe version 17; checked over the size range of the distance. Orca: one round face per Press Pull, built as a ring joined to the part or cut from it; the distance follows its variable within the limits on the parameter's line, and the face's radius and its end faces keep their place. |
| Press Pull of another curved face, or of part of a round face | Left out | Yes, needs an app change | Left out | Needs Orca | The app moves flat faces and whole round faces only. |
| Fillet: constant radius | Copied | - | Partly | Needs Orca | Orca: only when the edges are all, top, bottom or side edges of the part, or corners of straight extrudes. Other edges are left out, because Orca names edges by its own numbering. |
| Fillet: variable radius | Partly | Yes, needs an app change | Left out | Needs Orca | Paramability: one straight or arc edge alone in its fillet or apart from its other sets, no radii between the ends, and only when the radius changes evenly along the edge. Radii between the ends need an app change. |
| Fillet: chord length | Partly | - | Left out | Needs Orca | Paramability: a plain round of the radius the chord gives, where the faces meet at the same angle along each edge. |
| Fillet: two radii, curvature continuity | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Fillet: setback corners | Partly | Yes, needs an app change | Partly | Needs Orca | Copied with rolling ball corners, with a note. |
| Fillet or chamfer with several sets picked in different ways (edges, faces, chains) | Copied | - | Partly | Needs Orca | Paramability: sets that lie apart become one step for each way of picking, each with the pick Fusion used, and a set that cannot be copied is left out alone; the sizes read before the step are marked, since the tries do not show whether a size brings the sets near each other. Sets that meet or come near (also through a sharp angle or a size range) stay one step, with their edges picked one by one. Orca: as in the rows above. |
| Fillet or chamfer set picked by a face with Tangent Chain on, no smooth neighbour faces | Left out | - | Left out | - | Fusion does not give the edges of such a set and builds nothing for it. The whole step is left out with a tip; the rest of the part is copied. |
| Rule Fillet, Full Round Fillet | Left out | Yes, add-in only | Left out | Needs Orca | The add-in does not read these step types yet. |
| Chamfer: equal distance | Copied | - | Partly | Needs Orca | Orca: the same edges as for a fillet. |
| Chamfer: two distances, distance and angle | Copied | - | Left out | Needs Orca | Orca makes only even chamfers. Paramability: two distances need sides that the add-in could measure. |
| Shell: inside, open faces | Copied | - | Left out | Needs Orca | Orca opens only a face that it picks by its own numbering. |
| Shell: outward, closed, rounded corners | Copied | - | Left out | Needs Orca | Paramability: needs a Paramability release that reads recipe version 17. The part's volume must change as the shell says. A shell that grows both inward and outward is left out. |
| Draft | Partly | Yes, add-in only | Left out | Needs Orca | Paramability: one angle under 30 degrees, faces on one side of the plane; a Symmetric draft with faces on both sides is copied as two equal angles (recipe version 17). Two different angles are left out because Fusion does not say which angle leans which side; a hand check can settle it. |
| Scale of bodies | Copied | - | Left out | Needs Orca | Paramability: the factors follow sizes. A point that sizes can move keeps its place, and those sizes are marked. Factors per axis in a component turned at an angle are left out. |
| Scale of sketches, or of a body and a sketch together | Left out | Yes, add-in only | Left out | Needs Orca | |
| Combine: join, cut, intersect | Copied | - | Copied | - | The tool bodies are copied from their steps, also from other components. Orca: an intersect with several tools that the add-in cannot work out is left out. |
| Replace Face | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Split Face | Copied | - | Left out | Yes, add-in only | Paramability passes it by when the solid stays the same, with a note: picks on the split faces may not follow. Orca leaves the step out, although the shape stays the same. |
| Split Body: plane or flat face | Copied | - | Partly | Needs Orca | The part keeps its piece. Orca: the plane keeps its place. |
| Split Body: solid body | Copied | - | Copied | - | |
| Split Body: surface or curved face | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Move/Copy of bodies: move, rotate, free move | Copied | - | Partly | Needs Orca | Orca: a turn about an axis follows its angle. Orca cannot tie a move distance to a variable. |
| Move/Copy of bodies: point to point, to position, along an entity | Partly | Yes, add-in only | Partly | Needs Orca | Written as the numbers Fusion measured. |
| Move/Copy of faces | Left out | Yes, needs an app change | Left out | Needs Orca | |
| Copy and paste a body | Copied | - | Copied | - | Paramability writes the steps of the source again. Orca: the same, as a body of its own; a paste of a body of another component is left out. |
| Align | Left out | Yes, add-in only | Left out | Yes, add-in only | A step type that the add-in does not know is left out. |
| Remove of another body | Not read | No | Not read | No | It changes nothing in the part. |
| Delete Face | Left out | Yes, needs an app change | Left out | Needs Orca | |

## Construct

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Construction planes | Copied | - | Partly | Needs Orca | Paramability: steps on them follow the places that the size tries measure. Orca: they keep their place, and the sizes that move them are marked. |
| Construction axes | Copied | - | Partly | Needs Orca | As for planes. |
| Construction points | Copied | - | Partly | Needs Orca | As for planes. |

## Assemble

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Body in a component | Copied | - | Copied | - | Placed where Fusion shows it. |
| Component moved by hand | Copied | - | Copied | - | Capture the position first (Position, Capture Position). The export asks for it. |
| Steps that use geometry of another component | Partly | Yes, add-in only | Partly | Needs Orca | Copied where Fusion shows it. Sizes that move that component may give unexpected results. Edges and curved faces of another component are left out. |
| Joints, As-built Joints, Rigid Groups | Not read | No | Not read | No | They change no shape. A joint parameter may move every place from another component, so its sizes are marked. |

## Parameters

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| User parameters | Copied | - | Copied | - | Lengths and angles in mm, cm, m, in, ft, deg, rad, or no unit. |
| Formulas of parameters | Copied | - | Partly | Needs Orca | Orca: a formula that Orca cannot write keeps its number. |
| `+ - * /`, `sqrt`, `abs`, `min`, `max`, `sin`, `cos`, `tan` | Copied | - | Copied | - | Orca: a whole power up to 4 is written as a product. |
| `ceil`, `floor`, `round`, `%`, `if`, comparisons, `and`, `or` | Copied | - | Partly | Needs Orca | Paramability: `%` only when its left side stays at zero or above. Orca keeps the number. |
| `asin`, `acos`, `atan`, `exp`, `ln`, `log`, other powers | Copied | - | Partly | Needs Orca | Orca keeps the number. |
| `random()`, text parameters, units other than lengths and angles | Left out | No | Left out | No | The formulas have no such values. |

## Surface, Form, Mesh, Sheet metal

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Surface steps that make separate surface bodies | Not read | No | Not read | No | They do not change the part. |
| Stitch, surface Offset, other surface steps that make the part | Left out | Yes, needs an app change | Left out | Needs Orca | The app does not rebuild surfaces. |
| Form (T-splines) | Left out | No | Left out | No | A free form has no sizes to rebuild from. |
| Mesh steps, mesh converted to a solid | Left out | No | Left out | No | A mesh has no steps or sizes to rebuild from. |
| Sheet metal: flange, bend | Left out | Yes, needs an app change | Left out | Needs Orca | |

## Insert

| Fusion action | Paramability now | Paramability possible later | Orca now | Orca possible later | Notes |
| --- | --- | --- | --- | --- | --- |
| Insert Mesh | Not read | No | Not read | No | Only solid bodies can be exported. |
| Insert SVG, Insert DXF | Partly | No | Partly | No | They make sketch curves with fixed numbers. Orca: splines only when Fusion gives them exactly. |
| Decal | Not read | No | Not read | No | It changes no shape. |
| Canvas | Not read | No | Not read | No | It changes no shape. |

## Could be added to Export for Paramability

Sorted by how many printing projects it helps:

1. Rounds and chamfers of more kinds: variable radius with radii between the ends (app change), two radii, Rule
   Fillet and Full Round Fillet.
2. Picks that follow sizes on the end faces of a revolve whose angle is a size, and on the inner walls a shell leaves
   on a part turn (add-in only).
3. Thin extrudes of an open line with arcs (add-in only, after a hand check of the side), and the Rib that Fusion
   fills up to the part, such as a gusset in the corner of a bracket (add-in only, as the outline Fusion measured):
   walls, brackets and stiffeners.
4. Box, Cylinder, Sphere, Torus, pipes with a square or triangle section or a closed path of lines (add-in only),
   and sweeps that make a new component (add-in only).
5. Join extrudes through all where the far side cannot be checked, and new body extrudes through all.
6. Lofts through three or more outlines (add-in only), and lofts with rails or tangent ends (app change).
7. Extrudes to a tilted or curved face with two sides (add-in only), or with a taper or an offset past the face (app
   change).
8. Coils with a taper or a spiral (app change), and half turns (add-in only).
9. Shells that grow both inward and outward (app change), and drafts with two different angles (add-in only, after a hand check of which side each angle leans).
10. Emboss on a curved face (app change).
11. Path pattern along other curves than one line, arc or circle, and patterns and mirrors of faces (app change).
12. Taper tapped holes and threads that are not 60 degree or are tapered (app change).
13. Sweeps along 3D splines, with a guide rail or a guide surface (app change).
14. Press Pull of curved faces other than whole round faces, Move of faces, Split Body by a surface, Delete Face, Replace Face, Thicken,
    Boundary Fill and sheet metal (app change).

## Orca does not support

These need a change in Orca's Design tab, so the Orca copy cannot do them while Orca stays as it is:

- Sketch dimensions that follow a variable. Only rectangle sides, circle radii and the corners of straight outlines
  can follow, through plane cuts.
- A sketch plane, a hole place or a construction plane that moves with a variable.
- Faces and edges picked by the person: Orca names them by its own numbering. This rules out shells, drafts, Press
  Pull, Delete Face, extrudes up to a face and rounds or chamfers on hand-picked edges.
- Rounds with a variable radius, chord length, two radii or curvature continuity, and chamfers with two sizes.
- A move distance that follows a variable.
- A pattern that leaves copies out.
- Sweeps that twist, taper or keep the outline in one direction, sweeps with a 3D path, and sweeps with a guide rail
  or surface.
- Lofts through more than two outlines, with holes, with rails, a centre line or shaped ends.
- Left hand threads, other thread forms, tapered threads and drill points.
- Coils: a sweep along a helix that keeps the wire on planes through the axis, as Fusion's coil does.
- Through all for a join or new body that ends where the part ends.
- Formula functions other than `sqrt`, `abs`, `min`, `max`, `sin`, `cos` and `tan`: no `if`, `round`, `ceil`,
  `floor`, `%` or comparisons.
- Scale, Replace Face, surfaces and sheet metal.
