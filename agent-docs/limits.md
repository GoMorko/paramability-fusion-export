# Limits

What the copy can and cannot do, step by step. The README lists only the main limits. Each section gives the rule
first, then the detail, then the tip. Notes for developers come at the end of a section.

Contents:

- [Before you export](#before-you-export)
- [Size tries and ranges](#size-tries-and-ranges)
- [Putting the design back](#putting-the-design-back)
- [Steps that are left out](#steps-that-are-left-out)
- [Sketches](#sketches)
- [Extrudes and embosses](#extrudes-and-embosses)
- [Holes and threads](#holes-and-threads)
- [Rounds and chamfers](#rounds-and-chamfers)
- [Shells](#shells)
- [Patterns and mirrors](#patterns-and-mirrors)
- [Revolves](#revolves)
- [Thin walls, ribs and webs](#thin-walls-ribs-and-webs)
- [Axes, planes and faces that stay in place](#axes-planes-and-faces-that-stay-in-place)
- [Other components](#other-components)
- [Combine, paste, move and scale of bodies](#combine-paste-move-and-scale-of-bodies)
- [Sweeps and pipes](#sweeps-and-pipes)
- [Lofts](#lofts)
- [Coils, drafts, press pulls and other steps](#coils-drafts-press-pulls-and-other-steps)
- [Export size choices](#export-size-choices)
- [Versions](#versions)

## Before you export

- The design needs history (a parametric design).
- The add-in is made for the current Fusion release.
- One part holds one solid body. Several bodies go in one file as parts (see "Several bodies in one file" in
  `agent-docs/user-guide.md`).
- A recipe covers the picked body only.
  - Parameters made by steps or sketches of other bodies are left out where the add-in can match them by name.
  - Construction planes, axes and joints are read for the component of the body and for the components above it.
- The export works on the design as it is at the timeline marker.
  - If you drag the marker back, the steps after it are left out of the part.
  - The dialog then says so ("Exporting the design as it is at the timeline marker (step 48 of 120)").
  - To read the steps, the add-in moves the marker through the design. Then it puts the marker back where it was.
- The file holds the steps, the parameters and a STEP file of the body as Fusion made it. Paramability builds the part
  from the steps and compares it with the STEP shape.
- Paramability opens up to 256 MB per size and 1 GB per file. Above that, the export stops with a message.

## Size tries and ranges

The add-in changes your parameters for a short time and lets Fusion rebuild. These tries show how far each size can
go. `agent-docs/user-guide.md` describes the tries in full.

### Every try starts from your values

- Every size row and every sketch try starts from the saved values.
- Before each try after the first, the add-in puts the parameters back and recomputes.

### Sketches with two solutions

- A sketch with two solutions can land on its other solution after a try that did not rebuild. It can then stay
  there.
- After such a try, the add-in reads the design again before the next try.
- A size is blamed for a sketch that "makes a different outline" only in this case: its own try started from the
  right outline, and the outline came back after it.
- Such a size keeps its range up to the last value tried that kept the outline. The add-in halves toward that value,
  as for a value that does not rebuild.
- Only when no other value works is the size not a size. The reason then says why.
- The tries made while a sketch stayed on its other solution count against no size. The result window says so in one
  line.
- The add-in brings back a sketch that stays on its other solution. It does this the way the tries took the sketch
  away:
  - it sets the sizes a little past their values on the other side and back, or
  - it walks the sizes back in small steps.
- The tries walked back are all the tries since the sketch last read as it was, not only the last try.
- At the end of the tries, each size that those tries changed is walked back alone. This happens at most 16 times in
  all.
- When Fusion recomputes, it sometimes gives a projected curve a new name, or one curve two names. The add-in then
  compares the curves themselves. So this is not taken for another outline.

### Where a range ends

- A range stops at the last value that built.
- The add-in then halves toward the first value that did not build, up to four times.
- Each size gets this halving right after the try of its range ends, before the next size.
- A step in red can also end a range (see "Steps in red").

### When the tries end early

- The tries can end early, or run out of time, before that halving. Then the values between were never tried.
  - The tries end early when a try left the design broken with your values back.
  - The range can then be much shorter than the design allows.
- This can occur only for these sizes:
  - the size whose try stopped the tries;
  - a size whose tries ended because a try changed another component;
  - the size tried when the time ran out.
- Its reason says so, with a tip: untick the size that stopped the tries, or raise the time limit, and export again.
- The tries can also end before the range ends of a size were tried.
  - Then the range of that size stops at the values that built in its first tries. These are often a quarter below
    and a quarter above its value.
  - Its reason says that no value past them was tried, with the same tip.
- An end that you typed in the dialog is kept. That size then says "it was followed between A and B".

### When a try leaves a step broken

- A try can leave a step in a new warning or error that does not go away with the values back.
- The add-in first tries to bring the design back. It sets the sizes of the recent tries a little past their values
  from the other side and back, one try or one size at a time.
- When this does not bring the step back, the tries stop there.
  - Only the tries before it are used.
  - The sizes not tried yet are marked.
- The tries go on for the other sizes when all of these are true:
  - the step belongs to another component;
  - the part does not need that step;
  - the part reads as before.
- Then only the tries of the sizes behind the step end. These are the size of that try, and every size that changes
  that component. The other sizes are tried on.
- The sizes whose tries ended keep only the values tried before. Their reasons say that the values after them were
  not tried.
- Your design is changed then, so the export is undone at its end (see "Putting the design back").
- With "Lighter on memory" ticked, every try stops there as before, once the add-in let Fusion forget Undo data. The
  reason is that the export could not be undone.

## Putting the design back

- At the end of the export, the add-in compares the design with how it was before.
- A sketch can still read another outline after the export, or the body can have another volume or size than before.
  Then:
  - the result window says that your design is changed;
  - the add-in asks Fusion to undo the export.
- A very small difference of the body, with nothing else changed, means that the add-in could not confirm the
  design. So does a difference that appears only after the add-in rebuilt the whole design at the end. The export is
  undone then too.
- A try that left a step of another component broken (see "When a try leaves a step broken") also changes your
  design. The export is undone at its end.

### With "Lighter on memory" ticked

- After the add-in let Fusion forget Undo data, the export cannot be undone.
- When the design was saved in the cloud, the result window gives the steps to get the design back as it was saved:
  close it without saving, then open it again from the Data Panel.
- The add-in does not close or open the design itself. Fusion does not support that inside a command event.
- Fusion can show unsaved changes when the export dialog opens. The window then says that closing without saving
  loses every change since that save.
  - Fusion also counts the add-in's own marker moves as unsaved changes: those of an earlier export, or of the
    dialog.
  - So the add-in cannot tell them from your changes, and you decide.
- A design that was never saved gets the advice to close it without saving instead.

## Steps that are left out

- When the add-in cannot copy a step, it leaves the step out and tells you why.
- A part with left out steps is exported the same way as any other part. So it takes as long as a full export.
- At most 256 steps can be left out of one part. A longer list stops the copy.
- Every step type that this document does not name is left out.
- A step that the add-in cannot read from Fusion:
  - is left out of the copy when the part changed around it;
  - makes the part a fixed shape when the part could not be measured around it.
- `agent-docs/user-guide.md`, "When a step cannot be copied", tells what you see in Paramability.

### Steps in red

- A step that Fusion shows in red (an error) is not copied.
  - When the part is the same before and after the step, the copy leaves it out with a note and goes on.
  - When the part changed (Fusion keeps an older result of the step), it is left out like a step that cannot be
    copied.
  - When the part could not be measured around it, the part is saved as a fixed shape.
- A try of a size can make a red step of the part build. The range of that size then stops before that value.
- A size that may make the red step build, and that was not tried, stays fixed.
- A red step of another component changes no range.

### Steps copied with a note

These steps are copied, with a note:

- setback corners;
- a cosmetic thread (cut as a plain hole);
- a round or chamfer with more than 32 edges (picked in groups);
- a direction or a size that Fusion stored two ways;
- a step that Fusion shows a warning on.

## Sketches

### Splines, ellipses and other free curves

- A sketch outline that is one full ellipse is written as an ellipse outline.
- Sketch outlines with a spline edge, an elliptical arc or another free curve are copied as spline segments.
  - The add-in reads the Fusion curve as a fine chain of points.
  - It picks points for the app's own smooth curve. That curve stays within 0.005 mm of the chain, also between its
    points.
  - A long or tight curve is split into several segments.
- A size that moves a sketch with such a curve cannot be followed. The points of the curve are not a formula of the
  sizes. So the size stays loose with the reason, or is left out of the sizes.
- An outline of more than 1000 points is not copied.
- A text or spline outline that is too big or too complex is left out.

### Text

- Sketch text (`Text` in a sketch) is read as outlines. Extrude and Emboss copy it like any other outline.
  - Each letter shape is one outline step.
  - A hole in a letter (the inside of an "o") is kept.
- Text on a sketch on a face of the part (the top of a plate, a side face) is copied in both exports.
- A text is not copied when it has one of these ("This text has too many outline points to copy"):
  - more than 400 outlines;
  - more than 1000 points in one outline;
  - more than 256 holes in one letter.
- A size that moves the sketch of a text, or sets the height of the text, cannot be followed. It stays loose or is
  left out of the sizes, with the reason.
- An emboss of text must grow or shrink the part by the text area times the depth, as for other outlines.
- Earlier versions left out text on a face of the part ("The place of this text on its sketch could not be told with
  certainty"). They also left out text whose letters have straight edges, because the letter area came out too
  small. Export again.

### Points that move along a curve

- A sketch value that one size moves along a curve is copied only with these formulas:
  - the sine, cosine, tangent or cotangent of an angle size, or of half of it, alone or times a length;
  - products of two lengths;
  - at most 3 such terms per value.
- Other curves leave that size loose or not a size. Examples are a square root, a power, or an angle divided by a
  length.
- A size that turns a sketch plane, moves a point along a curve, or changes the shape of an outline may give
  unexpected results.

### Formulas with `%`

- A formula that uses `%` is copied only when its left side stays at or above zero over the size ranges.
- The app and Fusion may give different results for negative values.

## Extrudes and embosses

### Cut through all

- A cut through all to one side cuts on the side of its sketch where it meets the part.
- Fusion's stored direction can point to a side without material there. Then the other side is used, with a note.
- A tapered cut through all is copied as a tapered cut that ends past the part.
- A tapered cut whose walls lean in ends just past the part. It is left out when its outline would come close to
  closing there.

### Join through all

- A join through all to one side is copied as an extrude to the far side of the part.
- It is copied only when it joins the picked body alone. With more bodies, the export cannot tell where Fusion ends
  it.
- The export must also show that Fusion ended it on the far side of that body:
  - its end face lies on the far side of the body, and
  - the body has a flat face on that plane, or the end face merged with one.

  Else it is left out with a reason.
- These are left out too:
  - a join through all onto a curved top (it adds nothing in Fusion);
  - a join through all after a step that the copy left out;
  - a join through all that builds the tool body of a Combine;
  - a join through all both ways, with a taper, or with a thin wall;
  - a new body through all.
- Each size that may change the body before the join, or move its outline, is marked "may give unexpected results",
  with the step named. The export cannot check that Fusion and the copy still end the join at the same place at
  other sizes.
- This marks more sizes than needed, for example a hole size or a fillet radius that cannot move the far side. The
  export cannot tell which sizes move the body along the extrude.
- Tip: give the extrude a distance or end it on a face, to keep these sizes unmarked.

### Which way an extrude goes

- Fusion does not record which way some steps go, for example a join whose end merges into the part.
- The add-in then tells the way from where the body grew. When that does not show it, the add-in leaves the step out.
- These extrudes are left out:
  - an extrude that starts at a distance from a face or plane, when Fusion gives no start face that shows which way,
    and the end of the extrude does not show it either;
  - an extrude with two sides that both end on faces or planes on the same side of the sketch;
  - an extrude whose stored direction is not confirmed by the face that Fusion measured, when that face is not the
    end of the extrude and the part it joined does not show the way;
  - a join with one side whose stored direction points away from where the part grew;
  - a join up to a curved face, when Fusion gives no end face and the part after it does not lie wholly on one side
    of where the extrude starts;
  - a cut whose measured end lies short of its side, when that side ends inside the part.

### Extrudes that start or end on a face

- An extrude that starts on a tilted or curved surface is left out.
- An extrude that ends on a tilted or curved surface is left out in these cases:
  - it has two sides, a taper, or an offset past the surface;
  - the surface is a face of another body;
  - it comes after a left out step;
  - a size may move the face, and no copied extrude made the face.
- An extrude that ends on a flat face that Fusion joins with the faces next to it (Chain Faces on):
  - is left out when the outline does not land on that face alone. A slot or hole of the face under the outline
    counts as not landing;
  - is copied when the outline lands on that face alone. The sizes that may move the face or the outline are then
    marked.
- An extrude that ends on a curved face with Chain Faces on is left out.
- An extrude that ends on a curved face with Chain Faces off:
  - is left out when the outline reaches past that face;
  - is copied when it does not. The sizes that may move the face or the outline are then marked.
- An extrude that ends on a face whose surface could not be read is left out.
- For a face or plane of another component or of another body, see "Other components" and "Axes, planes and faces
  that stay in place".

### Extrude of a face of the part

- An extrude whose outline is a flat face of the part is copied.
- The copy draws the outline of an earlier extrude again on the face when all of these are true:
  - the face is the top or bottom face of that earlier extrude;
  - that extrude has no taper;
  - no round, cut or join changed that face.

  The outline and the face then follow the sizes of the earlier extrude: its length, its start and its sketch.
- Any other flat face (the top of a tapered extrude, a face after a round) is copied as Fusion measured it. The sizes
  of the steps before it are marked "may give unexpected results", since they may change that face.
- In both cases, the length, the taper and the operation of the face extrude follow its own parameters.
- Sketch outlines on the plane of the face may come with the face. The face is then copied as measured.
- These are left out:
  - an extrude of a curved face;
  - an extrude of several faces;
  - an extrude of a face together with sketch outlines on another plane.
- Exports made with version 0.8.0 or older did not read the face. Export again.

### Emboss

- An Emboss of sketch outlines on a flat face is copied as an extrude that starts on the face.
  - It raises the outline when its depth is positive.
  - It sinks the outline when its depth is negative.
  - The depth follows a parameter.
- The copy checks that the part grows or shrinks by the outline area times the depth.
- An outline can run past its face (over a hole or off an edge). Fusion then trims it to the face.
  - The copy then checks the area of the end face times the depth.
  - It limits the extrude to the outline of that face, holes included.
  - This works for one flat face with no flat neighbour that follows it.
  - The edges of the face are exact when it is an untapered end of an earlier extrude. Else they are measured, and
    the sizes are marked loose.
  - Older exports do not have these edges and stop the copy.
- An emboss whose outline is a flat face of the part is copied like an extrude from that face (see "Extrude of a face
  of the part").
- These embosses are left out:
  - an emboss on a curved face;
  - an emboss that is moved or turned on its face;
  - an emboss drawn on a plane that is tilted to its face;
  - an emboss set to follow tangent faces that are rounded.
- For developers: in the recipe, the limit to the outline of the face is `within`.

## Holes and threads

### Hole "To" a face or plane

- A hole "To" a face or plane is copied as a hole of the depth Fusion made, in both exports.
- Its end must lie on that face or plane. A hole that Fusion ended on another face (a face next to the picked one) is
  left out.
- When the face is smaller than the hole, Fusion can extend the face, or it can use the faces next to it. The export
  cannot tell yet which one Fusion did. So the sizes that may move such a face are marked "may give unexpected
  results".
- A construction plane has no faces next to it, so it follows its sizes.

### Tapped hole through all

- The modeled thread of a tapped hole through all runs to where the hole comes out of the part.
- The add-in measures that point from the wall of the hole. An export made with an earlier version leaves such a hole
  out: export again.
- The thread is left out when the thread Fusion made does not reach that point. An example is a hole through two
  walls, with a thread in one wall only. The tip is to make the thread cosmetic.
- The thread length follows the sizes only in a plain part that is equally thick wherever the hole can go.
- In any other part (a boss or a step near the hole), the thread keeps its length. The sizes that could move the hole
  or the part around it are marked "may give unexpected results".

### Threads that are left out

These threads are left out:

- threads that are not metric or Unified 60 degree threads;
- tapered threads.

A cosmetic thread is copied with a note, as a plain hole (see "Steps copied with a note").

### Export for Orca

- In the Orca copy, the depth of a hole with a counterbore or countersink must stay deeper than the recess. The
  parameter's line says how far the size may go.
- The Orca copy starts the thread of a counterbore hole at the counterbore floor. It keeps that start as a number. So
  a size that changes the counterbore depth is followed only in part there.
- The Orca copy leaves out a tapped hole with a countersink and a modeled thread.

## Rounds and chamfers

### Rounds that the copy writes another way

- A round on the four side edges of a rectangle (a slot cut, a block) can have a radius of half the short side at
  every size. It then makes round ends. The copy draws that outline as a slot and writes no round. This builds the
  same part.
- A round or chamfer that picks an edge inside one flat side wall of an extrude (where a round meets the wall)
  follows that wall.

### Rounds and chamfers on pattern copies

- The rounds and chamfers on the copies of a rectangular pattern follow its count.
- The copy writes them for every count that the size range allows. Each one is kept only while the count makes its
  copy.
- Paramability cannot repeat a round itself yet.
- Paramability may still leave these out on some copies, because Fusion rolls over such edges:
  - a round that is wider than the face next to it;
  - a chamfer as big as a whole face.

### Round set by chord length

- A round set by chord length is copied as a plain round. Its radius is the one that the chord length gives at the
  angle where the two faces meet.
- That angle must be the same along each edge. The radius that Fusion made must match.
- The radius follows the chord length size only when both of these are true:
  - both faces are flat, or round faces that the edge goes round (the top edge of a round boss);
  - no size can turn the faces (faces of plain extrudes of the part).
- Otherwise the copy writes the radius as a number. The chord length is not a size. Each size that may turn or bend
  the faces is marked "may give unexpected results".
- On a ball shaped or ring shaped face, and on a round face along the edge, the radius also depends on how the face
  curves.
- A round set by chord length is left out when the faces meet at an angle that changes along the edge.

### Round whose radius changes along the edge

- Such a round is copied only when all of these are true:
  - it is on one straight or arc edge;
  - it is alone in its fillet, or apart from the other sets of its fillet (see "Several sets of edges in one step");
  - no radii are set between the two ends;
  - the radius that Fusion made changes evenly from one end to the other. Fusion may blend it in a curve.
- The copy cannot repeat it in a pattern or mirror. It leaves it out inside a tool body.
- A size that may swap which end of the edge lies lowest along x, y and z is marked "may give unexpected results".
- Other rounds whose radius changes along the edge are left out.

### Edges picked from faces or chains

- Fusion can pick the edges of a round or chamfer from faces, or from a chain of edges that touch smoothly. The copy
  picks them the same way where it can:
  - sets of one size that are picked only by faces or only by chains;
  - chains of different radii in one round.
- Otherwise the copy picks the edges one by one. The sizes read before the step are then marked "may give unexpected
  results". At other sizes, the faces or the chain may hold other edges, which the copy does not round.
- The copy picks the edges one by one for:
  - a round set by chord length;
  - a round whose radius changes along the edge;
  - a chamfer with two different sizes whose edges take the first size on different faces;
  - sets picked by faces and sets picked by chains in one step, when those sets meet at a corner or come near one
    (see "Several sets of edges in one step");
  - sets of different sizes picked by faces, when those sets meet at a corner or come near one.

### Several sets of edges in one step

- One fillet or chamfer step can hold several sets of edges.
- The copy makes the sets one step after the other when they stay apart. The rule: the edges of every two sets stay
  further apart than twice the distance that the two sets reach along their faces together.
- These steps come in the order of the sets in Fusion:
  - one step for the sets picked by faces (one step for each size);
  - one step for the sets picked by chains;
  - one step for the edges picked one by one;
  - one step for each other set.
- Each step then picks its edges as Fusion did.
- A round reaches further than its radius where its faces meet at a sharp angle. Between faces 30 degrees apart, it
  reaches 3.7 times the radius. The copy counts this.
- When a radius or a distance follows a size, the largest value in the range of that size counts.
- A round whose radius changes along the edge gets its own step this way.
- When one set cannot be copied, only that set is left out.
  - The result window lists the step with the reason of that set.
  - The other sets are in the copy.
  - A pattern or mirror of such a step is left out too.
- Where the sets meet or come near, Fusion makes one blend there. Steps one after the other do not make that blend.
  So the copy keeps the sets in one step as before. A set that cannot be copied then leaves the whole step out.
- A set whose reach is not known also keeps the whole step as before. This is a set with:
  - two radii;
  - curvature continuity;
  - radii between the ends of a changing radius;
  - faces that fold back on each other;
  - a chamfer size that cannot be read.
- The size tries do not show whether a size moves the edges of two sets near each other. So the sizes read before
  such a step are marked "may give unexpected results", as for a step whose edges are picked one by one.
- Exports made with add-in 0.14.3 or older do not hold what this needs. Their sets stay in one step.

### Faces picked with Tangent Chain

- Fusion cannot give the edges of a set that picks a face with Tangent Chain on, when no other face meets that face
  smoothly. Fusion does not round or cut anything for it. So the set cannot be read.
- The whole step is left out. The tip is to pick the edges of that set, to turn Tangent Chain off for its face, or to
  remove the set.
- The steps before and after it are copied.
- A face that other faces meet smoothly (the side of a box with rounded corners) reads and copies as usual.

### Rounds and chamfers that are left out

- A round with two different radii (Fusion's "asymmetric" rounds) is left out by both exports.
- Rounds with curvature continuity are left out.
- A chamfer with two different sizes whose sides could not be measured is left out.

For rounds and chamfers on revolves, sweeps and lofts, see "Revolves", "Sweeps and pipes" and "Lofts".

### Export for Orca

- The Orca export leaves out rounds set by chord length and rounds whose radius changes along the edge.

## Shells

- A shell that grows outward, or a shell with rounded corners, is copied only when the volume of the part changed as
  the shell says.
- A shell that grows both inward and outward is left out.
- For a shell, round or chamfer that picks faces of a revolve, see "Picks on a revolve".

## Patterns and mirrors

### Patterns to both sides

- A rectangular or circular pattern that spreads copies to both sides of the original is copied as two patterns from
  the original: one forward and one backward. The copies are at the places Fusion measured.
- Its count and spacing can follow sizes.
- A count can be measured odd and become even inside its size range.
  - For a rectangular pattern, the count follows the sizes. Fusion puts the extra copy of an even count ahead of the
    original, as seen in its exports.
  - A circular pattern may give unexpected results at an even count.
  - A pattern whose tries show the copies elsewhere may give unexpected results too.
- A pattern to both sides of the start is left out when the original sits between two copies, or when the copies do
  not follow the usual places.

### Where the copies are

- Fusion does not always say correctly where the copies of a pattern are. In Fusion 2706 it gives the copies of a
  circular pattern one step too far round.
- So the add-in places the copies of a circular pattern by their order. It checks every copy against its faces.
- A pattern is left out when:
  - the faces of a copy are not where Fusion says the copy is;
  - two copies have one place;
  - a place has no copy, and no copy is suppressed.
- The add-in looks at the faces of each copy only when the pattern repeats holes, or one-sided extrudes that make a
  new body, join or cut.
  - For other patterns (for example a pattern that repeats a Combine), Fusion can close when the add-in asks for these
    faces.
  - Without the faces, a circular pattern can turn a way that Fusion's other numbers do not show. It is then left out
    with "Which way this pattern turns its copies could not be read."
- A circular pattern over part of a circle, in an export from an older add-in version, has no faces to tell which way
  it turns. So it is left out: export the design again.

### Path patterns

- A path pattern is copied when its path is one straight line, one arc or one circle.
  - On a line, it becomes a row of copies along the line.
  - On an arc or a circle, the copies must turn with the path. It becomes a pattern round the centre of the arc.
- Its count and distance can follow sizes.
- The copies must stay on the path. When a size can move them past an end of the path, its range stops there.
- The path itself is copied as it is now. So a size that moves or turns the path may give unexpected results.
- For a straight line, only a size that turns the line or changes its length is marked. A size that only moves the
  line is not marked.
- These path patterns are left out:
  - a path of another curve, or of more than one curve;
  - copies on both sides of the start point;
  - copies that keep their direction on a round path;
  - copies on a round path that start part way along it, or that run against it (Fusion can put them off the path);
  - copies past the end of the path.

### Patterns and mirrors that are left out

These are left out:

- patterns of faces;
- mirrors of faces.

For patterns of bodies and patterns that hold a Combine, see "Combine, paste, move and scale of bodies". For a
pattern axis or mirror plane that stays in place, see "Axes, planes and faces that stay in place".

### Export for Orca

- Export for Orca copies the same path patterns. It also copies an arc whose copies keep their direction. The distance
  then keeps its number.
- The parameter's line says how far the count and the distance may go before the copies leave the path.

## Revolves

### Picks on a revolve

- A shell, round or chamfer that picks a face or an edge made by a revolve follows the outline, the axis and the angle
  of the revolve. For example, the open top of a cup and a round on its outer rim follow its height and its diameter.
- A round or chamfer on the inside of a shelled revolve that turns a full circle follows these sizes and the
  thickness of the shell. Examples are the inner rim of a cup, its inner bottom edge and the floor inside.
- A pick on a flat end face of a revolve that does not turn a full circle follows the outline. This is true when the
  angle of that face does not change with a size.
- The range of a size stops before:
  - a picked side of the outline would shrink to nothing;
  - an inside wall or the opening of the shell would close up;
  - a revolve that does not turn a full circle would no longer reach the picked place.
- Outlines of one revolve that share a line count as one outline for these picks. An example is a lid and its rim,
  drawn as two outlines and revolved together. This is also true where they meet and inside a shell.
- These picks are not followed:
  - a pick on an end face whose angle changes with a size;
  - a pick on the inside of a shelled revolve that does not turn a full circle;
  - a pick on the inside where a line of the outline turns with a size;
  - a pick on the inside where the inside wall meets a curved wall at an angle;
  - a pick on the inside where another step lies against the outside wall;
  - a pick where outlines of one revolve meet, in these cases:
    - the outlines overlap;
    - the outlines lie on both sides of the axis;
    - a size in its range moves one outline so that they meet in another way (the tip of one outline passes the end
      of the line it stands on);
  - a pick where the revolve meets a step made before it;
  - a pick that lies on two sides of the outline at once;
  - picks on an intersect revolve;
  - picks on a revolve to two sides whose angle before the sketch follows a size.
- When sizes move the face under such a pick, the pick keeps its place. The sizes that the steps before it use are
  marked "may give unexpected results".

### Revolve axis

- The copy cannot use some revolve axes. The revolve is then left out of the copy, and the reason says which case it
  is:
  - an edge that is not straight;
  - a face that is not round;
  - an axis that cannot be read.
- A face is round when it is a cylinder, a cone or a torus. A sphere or a free-form face has no axis.
- A circular pattern about such a face is left out for the same reason.
- A revolve whose axis is not in the plane of its sketch, or is not square to that plane, is left out too. The
  exception is when Fusion itself projects the axis onto the sketch plane.
- For an axis that stays in place, see "Axes, planes and faces that stay in place".

### Which side a revolve turns to

- Fusion turns a revolve toward one side of its sketch plane. It does so also when a size moves the axis, or the
  outline, to the other side of the outline.
- The turn about the axis then reverses, but the copy turns one way only. So the range of such a size stops just
  before the outline would reach the axis.
- An outline drawn on the axis may stay on it.
- When you typed the ranges of all the sizes that move it, the revolve is left out instead.
- A quarter turn revolve joined to the part is left out when both of these are true:
  - its ends do not show the way;
  - the material it added lies inside the box of the part before it.

### Revolve to two sides

- A revolve to two sides with two angles is copied when its start face shows which side each angle turns to.
- When one angle is 90 or 270 degrees and the other is not the same, the start face can fit both sides. The revolve is
  then left out, with the tip to make two revolves.
- Both angles follow sizes while their sum stays at 360 degrees or less.
- Two equal angles keep their numbers. The copy cannot tell their sides apart at other sizes.
- The angle on the far side of the sketch keeps its number when the axis is projected onto the sketch or moves with
  sizes.

## Thin walls, ribs and webs

### Thin extrude of one closed outline

- A thin extrude of one closed outline is copied with its wall thickness as a size. Examples are a wall along a
  rectangle or a circle, for lids and boxes.
- The side of the wall (inside, outside or both ways) is taken from the measured end face. The API does not say which
  of Fusion's side one and side two is which.
- Where Fusion keeps the corners of the wall sharp, the copy rounds them and says so.
- A later pick on the faces of the wall is placed on earlier steps, or its sizes may give unexpected results.

### Thin extrude of an open line of straight lines

- A thin extrude of an open line of straight lines is copied with square ends and sharp corners, as Fusion builds it.
  Examples are a fence, a divider, or a rib along a plate.
- The wall thickness and the sizes that move the line are sizes.
- The side of the wall is checked against the faces that Fusion made. This also works where a face of the wall merged
  with a face of the part (a wall flush with the edge of a plate).
- When the faces do not show one side, the step is left out.
- Draw the lines one after the other, each from the end of the one before.
- These leave the step out:
  - a line drawn the other way;
  - a free curve;
  - a corner that turns more than 135 degrees (a V sharper than 45 degrees).
- A range stops before a corner takes a whole line, before a corner turns past 135 degrees, or before two lines come
  too near.

### Thin extrude of an open line with arcs

- A thin extrude of an open line with arcs (a curved fence, a U clip) is copied as the outline of its wall: lines and
  arcs, with the numbers it has now.
- The line and the wall thickness are marked. Only the height follows its size.
- Each arc must meet the line or arc next to it smoothly (tangent). Each arc must turn by at most half a circle.
- These leave the step out:
  - a corner next to an arc;
  - an arc whose inner side has a wall as thick as its radius, or thicker;
  - a wall whose volume is not exactly its outline times its height.
- So a join or a cut that overlaps the part (a wall that runs into another wall) is left out too.

### Thin extrudes that are left out

These thin extrudes are left out:

- thin extrudes of an open line with free curves, or with a corner next to an arc;
- thin extrudes of several outlines;
- thin extrudes of an outline with holes;
- thin extrudes that go two ways, reach to a face, or have a taper.

### Rib and Web along straight lines

- A Rib or a Web is copied in both exports when its straight sketch lines are drawn one after the other, with no
  draft and no fillet.
- It is copied as a thin wall along each line, as for a thin extrude of an open line.
- For a rib, the depth is the width of the wall in the sketch plane. The thickness is its length along the sketch
  normal.
- For a web, the thickness is the width. The depth is the length.
- Fusion does not say which side or which way it builds the wall. So the faces that Fusion made decide it, as for a
  thin extrude.
- Fusion stops the wall where it meets the part, also for a depth that you type. So the step is copied only when the
  part grew by the whole wall.
- These are left out:
  - a wall that runs into the part (a rib drawn into a corner with a depth);
  - a web whose lines Fusion stretches to the part (Extend on, lines that stop short of the faces);
  - a wall flush with a side of the part (Fusion merges their faces), since the copy cannot check it;
  - a wall on a body whose volume was not measured, since the copy cannot check it.

### Rib with To Next filled into a corner

- Fusion can fill a rib with To Next up to the part (a gusset in the corner of a bracket). The copy then writes the
  outline that Fusion made, extruded by the thickness.
- The copy checks that outline:
  - both ends of the wall show the same corners;
  - the other edges lie on faces of the part that stand square to the sketch plane;
  - each line of the rib has its side face;
  - the part grew by the area of the outline times the thickness.
- The outline keeps its numbers. So every size that the steps before it read may give unexpected results.
- The thickness follows its size, and it is marked too. A much thicker gusset may reach past the part.
- When the check fails, the rib is left out.

### Rib or Web with To Next to a flat face

- To Next is copied when the wall reaches one flat face of the part all along its line. Examples are a rib across a
  channel down to its floor, or a divider web down to the floor of a tray.
- Its depth keeps the number that Fusion measured. Every size that the steps before it read may give unexpected
  results.
- A wall inside the box of the part could run into the part at a larger depth. So its depth, the thickness of a web
  and the sizes before it may give unexpected results too.

### Rib or Web that grows away from the part

- A wall that grows away from the part (a rib standing on a plate, a web up from a plate) follows its own sizes.
- The sizes before it are marked too. The exception is a wall that stands on the face of the part that its sketch is
  drawn on.
- The reason: a size that moves the part can move the part into the wall (where Fusion stops it), or away from it (the
  wall floats).

### Ribs and webs that are left out

These ribs and webs are left out:

- ribs and webs with a draft or a fillet;
- ribs and webs along arcs or curves;
- ribs and webs that the faces or the volume Fusion measured do not show as a whole wall.

### Export for Orca

- Export for Orca copies a thin wall along one rectangle, one circle, or one line of lines and arcs.
- The side of the wall comes from what Fusion measured, as for the other export.

## Axes, planes and faces that stay in place

### Places that the copy keeps where they are now

- Some places of the part are kept where they are now. The sizes do not move them. These places are:
  - a revolve or pattern axis;
  - a mirror or split plane;
  - a pattern direction.

  Such a place can be an edge, a face, a construction axis or plane, or a line of a sketch.
- Each size that may move such a place is marked "may give unexpected results", with the step named.
- Sometimes the export cannot tell what such a place is, or what a construction plane or axis is built on (for
  example in a file from an older add-in). Then every size that the steps before it use is marked.
- A revolve axis on a line of another sketch than the outline's follows the sizes that were tried.
  - Each other size that may move or turn that line is marked the same way. This is a size of its sketch, of the
    plane or face that sketch sits on, or of part edges projected into it.
  - With no tries, every such size is marked.

### Faces of a helper body

- A flat face of another body of the part (a helper body) can be where an extrude starts or reaches to. It follows the
  sizes the tries measured.
- A face of this body that lies at the same place is never used instead.
- Where the tries could not measure the face, the sizes that the steps before the extrude use are marked "may give
  unexpected results", with the extrude named.
- The tries can see a face or plane move in another way than the copied steps say. Then the copy follows what the
  tries saw.

For places of other components, see "Other components".

## Other components

### Bodies inside components

- A body inside a component, at any depth, exports as a recipe with sizes, like a root body. It lands where Fusion
  shows it.
- If you moved the part by hand, capture its position first (Position, Capture Position). The export asks for it.
- A component used several times exports the copy you picked.

### What stays a fixed shape

- These stay a fixed shape, with a note:
  - a part from a linked design;
  - a place in the assembly that cannot be read;
  - a step of another component that changes the body;
  - a body made in another component and moved in.
- A step of the body that reaches into the edges, bodies or curved faces of another component is left out of the copy.

### Steps that make a new component

- An extrude, revolve or loft made with the operation New Component makes its body in the new component. Its sketch
  stays in the component that was active. The copy of that body places the sketch through the assembly.
- A sweep made this way is left out, since its path stays in the other component.

### Sketches of another component

- A step that uses a sketch of another component is copied where Fusion shows it. It follows the sizes that the tries
  saw move it.
- Where it could stop meeting the part, the size may give unexpected results. Examples are a slot that no longer
  reaches its wall, or a rail that comes off. The reason gives the value past which this starts.

### Places of another component

- These are copied, and follow the sizes that the tries measured (see "Places that the copy keeps where they are
  now"):
  - a mirror plane, or a pattern or revolve axis;
  - a flat face or plane that an extrude starts from or reaches to;
  - a hole on sketch points, or on a flat face of another component;
  - a pattern direction taken from one of these.
- Where the tries could not measure the place, or the place turns, the size that may move it is marked "may give
  unexpected results", with the step named.
- An origin plane or axis of another component is treated the same way, since it moves with that component.
- A parameter of a joint, or of a move that places a component, counts as one that may move every such place. It also
  counts for every sketch of the part drawn around another component. The export cannot tell which component it
  places.
- These are left out of the copy:
  - a hole placed on an edge of another component;
  - an extrude that starts from or reaches to a curved face of another component.

### Planes of the part built on another component

- A plane or axis of the part's own component can be built on another component. Examples are an offset from the XY
  plane of the root, or a plane on a face of another part. It belongs to the part.
- A step that uses it is copied, also when the part sits in an assembly.
- The export cannot tell which sizes move what the plane is built on.
  - For a plane that an extrude starts from or reaches to, the tries measure the plane with every size. A size that
    the tries could not measure is marked "may give unexpected results".
  - The tries measure a sketch on such a plane the same way.
  - For a mirror plane, or a pattern or revolve axis, built this way, every ticked size is marked.

### Parameters shared with another component

- A parameter that the part shares with another component is a normal size when both of these are true. Examples are
  a width, a wall or a print tolerance that a box and its lid share.
  - It reaches the part only through the values of the part's own steps (an extrude distance, a taper, a fillet
    radius).
  - It reaches the part only through the sketches that the tries follow.
- It keeps the mark "may give unexpected results: it changes this part in a way the copy does not follow" in this
  case: the part changed in its tries, and the export cannot rule out another way. Other ways are:
  - a sketch drawn around another component that the tries do not follow;
  - a construction plane, axis or joint behind the parameter;
  - a place of another component that was not read;
  - a capture that does not say where the parameter acts.

### How a link to another component is found

- A link to another component is found only through the sketch itself:
  - a projected curve or point;
  - a constraint to one;
  - a sketch drawn on a face of that component.
- A sketch that follows another component in another way is not linked. Examples are a construction plane or axis
  built on it, or a pattern that reaches into it.
- The tries of unticked parameters may still name such a sketch. A parameter you tick by hand is tried.

## Combine, paste, move and scale of bodies

### Combine

- A Combine (join, cut, or keep only the shared part) is copied with its tool bodies.
- A tool made only by steps that add material is written step by step, each with the operation of the Combine. An
  example is a new body, then extrudes or revolves that join it.
- Any other tool becomes one tool step. It holds all the steps that made the tool: its cuts, rounds, chamfers, holes,
  shells, a Combine of its own, a pasted body, a Move and a pattern of bodies.
- The sizes and sketches of those steps are sizes of the part like any other. A later round or chamfer on the result
  follows them.
- A tool that the Combine keeps can serve a later Combine. That Combine gets the tool with the steps added since.
- Tools made from tools are followed 3 levels deep.
- The export reads up to 120 steps and 32 tool bodies in all. A pattern of many copies counts as one body.
- The message after the export names the tool body and the step that stops it. For example: "The tool body Body3
  cannot be copied because of its step Coil1". So you know what to change in Fusion.
- A tool may miss only rounds, chamfers, drafts and embosses. When any other step of a tool cannot be copied (a Move,
  an extrude, a cut), the whole Combine is left out. A tool at the wrong place or with the wrong material would give a
  wrong part.
- The Combine that takes such a tool then counts as one missing step.
- A tool step that starts from or reaches to a face of the part follows that face where the add-in can place it. It
  marks the sizes that it cannot follow.
- A Combine whose result is more than its tool bodies can give is left out. An example is a cut that removes more than
  the tools hold.

### Keep only the shared part, with several tools

- Fusion does not say what this Combine keeps: the part and every tool, or the part and any tool.
- The export tries it on temporary copies, which are never added to your design. It compares the volumes with the
  result Fusion made, and copies the Combine that way.
- The Combine is left out with "This combine keeps a shared part that the copy could not work out" when:
  - the volumes fit neither way, or
  - a tool lives in another component.
- When both ways give the same volume, the export cannot tell which one Fusion used. So the sizes of the tools are
  marked "may give unexpected results".

### Tool body from another component

- The tool body may be made in another component. The add-in then reads the steps that made it in that component.
  These steps count in the 120.
- It writes them where the tool component sits in the assembly, turned and moved as Fusion shows it.
- The sizes of those steps, including sketch dimensions of the tool, are sizes of the part like any other.
- A size that moves the tool's component is followed when the tries can measure it. One that they cannot follow may
  give unexpected results ("puts its tool at the place of Rod that turns with it").
- The message after the export names the step and the component of a tool that cannot be copied.
- A tool from another component that reaches to a face becomes a tool step.
- Inside such a tool, a Combine can take a body from yet another component. The Combine that takes the tool is then a
  left out step.

### Pattern or mirror that holds a Combine

- A pattern or mirror of features can hold a Combine of the part, together with every step that built its tool
  bodies. It then repeats the Combine as it was copied. Its count, spacing and skipped copies follow sizes, as for any
  pattern.
- These are left out of the copy:
  - a pattern that holds only some of those steps;
  - a pattern of the steps of a tool without its Combine;
  - a pattern of a Combine that keeps only the shared part.

### Pattern and mirror of bodies

- A rectangular, circular or mirror pattern of bodies is copied when a Combine takes the copies.
- When the Combine takes the whole pattern (the original and every copy), the pattern is written as a pattern. So its
  count and spacing follow sizes. For a join, the original may be the part itself.
- In these cases each copy is written as a tool with its place as numbers, and the sizes behind the layout are marked:
  - the Combine takes only some of the copies;
  - the layout is uneven;
  - the Combine keeps only the shared part.
- A count that follows a size is written as if the Combine also takes the new copies. It is not known whether Fusion
  does this, so that size is marked "may give unexpected results".
- A mirror of bodies is copied only in a Combine, together with its source.
- A body that is a copy in a pattern is copied by writing the steps of its source and a Move.

### Copy Paste Body

- Copy Paste Body is copied by writing the steps of the source again, as the source stood at the paste.
- The pasted body must be a new body. A paste that lands on a body that already has steps is left out of the copy.
- A copy that sits where its source sits keeps the sizes.
- A copy that sits elsewhere gets a plain-number Move. The sizes that could change its place are marked "may give
  unexpected results".
- A paste of several bodies is copied when each pasted body can be matched to its source by its corners.

### Move of bodies

- A Move of bodies is copied when the body moves as one solid.
- A Move along X, Y and Z, a Rotate and a free Move follow their distances and angles as sizes.
- The other kinds (point to point, to a position, along an entity) are written as the numbers Fusion measured. What
  they follow can move with any size. So every ticked size is marked, or left out with the reason.
- A Move of faces, and a Move that mirrors or scales, are left out of the copy.
- A body with no corners (a sphere, a torus, a closed revolve) is copied when a Move along X, Y and Z or a free Move
  only shifts it.
- A Rotate, or any other Move that turns such a body, is left out. The tip is to draw the sketch of the body where the
  body should be.

### Scale of bodies

- A Scale of bodies is copied. The factor, or the three factors of a scale that differs per axis, follow sizes.
- A factor whose formula could go under 0.001 or over 1000 keeps its number. Its sizes are marked.
- The point that stays in place keeps the place Fusion measured.
  - When it is the origin, nothing is marked.
  - When it is a sketch point, a construction point or a corner of the part, the sizes that can move it are marked
    "may give unexpected results".
- The add-in checks the scale on the measured body, by its volume and its box. A scale that does not agree is left
  out.
- These are left out:
  - a scale that also scales sketches;
  - a scale with factors per axis, in a component that is turned at an angle that is not a quarter turn;
  - a scale before the first copied step of the body.
- A tool body with such a scale can be joined or cut into a part that is turned at an angle. The combine is then left
  out.
- A round, chamfer or offset after the scale that picks faces made before it keeps its measured place. The sizes are
  marked.

### Export for Orca

- Export for Orca copies a Combine of a pattern of bodies only when it takes the whole pattern. The copies become one
  Orca Pattern or Mirror.
  - The spacing and the angle follow your parameters. The count keeps its number.
  - A Combine that takes only some of the copies is left out.
  - A Combine that keeps only the shared part is left out.
  - A Combine whose copies a later step changes one by one is left out.
- Export for Orca leaves every scale out. Orca has no step that scales a body.

### For developers

- Whether Fusion's Combine takes the new copies of a pattern of bodies at a larger count is hand test B6.

## Sweeps and pipes

### Sweeps that are copied

- A sweep is copied when both of these are true:
  - its outline is one closed sketch outline (holes allowed). Several outlines become one sweep each, along the same
    path;
  - its path starts at the outline, square to it, and runs one way.
- The path decides what the copy writes:
  - a straight path becomes an extrude;
  - one arc or a full circle becomes a revolve;
  - a chain of lines, arcs and spline curves in one plane becomes a sweep step;
  - a chain of lines joined by tangent arcs in 3D becomes a sweep step.
- A path of body edges is copied as measured. Such a step cannot be repeated by a pattern.

### Sizes of a sweep

- The outline follows sizes like an extrude outline.
- A path of sketch lines and arcs that the size tries measured follows sizes too.
  - A size behind a line length, an arc radius or a corner position becomes a formula.
  - The formula is the distance of the extrude, the axis point and angle of the revolve, the points of the flat path,
    or both corner points of a straight path that twists.
- The rules of the path are tested over the size ranges. The ranges are cut where the rules stop holding. Past that
  value, the path would cross itself, bend tighter than the outline, or turn sharply.
- The path start must stay on the plane of the outline. A size that moves one without the other is marked "may give
  unexpected results".
- These paths stay as measured. The sizes behind their sketch, or behind the plane, face or projected edges that the
  sketch sits on, are marked:
  - a path with a spline curve, a full circle, 3D corner points, body edges or a taper;
  - a closed path cut open inside an arc.

### Twists, tapers and closed paths

- These become a sweep step too:
  - a twist;
  - a taper;
  - a parallel orientation on a path that keeps moving away from the plane of the outline.
- A twist or a taper is copied with a note to check the shape. Fusion does not document how it measures them.
- A closed chain of lines, arcs and spline curves in one plane becomes a sweep step along a closed flat path. It is
  cut open where the path meets the plane of the outline.
- A full circle stays a revolve, unless a twist needs the sweep step.
- Sharp corners between lines of a flat path, closed or open, are mitred, as Fusion builds them.
  - This is not done when the sweep twists, tapers or keeps the outline in one direction.
  - Each line next to such corners needs room for their mitres.
- On a closed path, an outline that sits on such a corner is moved to the middle of the next side. The copied path
  starts there.
- A twist along a closed path must be whole turns. It is copied as a number, not as a size.
- A twist along a closed path turns as Fusion walks the path.
- A twist or taper that follows a size marks the size past the values where it would reach the limits.
- A new body must have the volume that the outline and the path give. For a parallel outline, this is its area times
  the rise of the path. Else the sweep is left out.
- A tapered sweep whose volume fits neither an offset nor a scaled outline is left out.

### Sweeps that are left out

These sweeps are left out:

- a twist together with a taper or a parallel orientation;
- a taper along spline curves, or along a scaled outline;
- a taper that would close part of the outline, or a hole;
- a taper of 45 degrees or more;
- a twist over 3600 degrees;
- a guide rail;
- a guide surface. When Fusion does not list the guide surfaces, some sweeps are taken as having one ("likely"). See
  "For developers" below;
- parallel orientation on a path that turns back. The direction of the path must keep a rise of 0.05 along the normal
  of the outline at every point, ends and arc points included;
- several outlines at once that intersect the part or taper;
- an outline that is a face of the part;
- a path of sketch curves mixed with edges;
- a closed path that bends in 3D, or that tapers or keeps the outline in one direction;
- a twist along a closed path that is not whole turns;
- a sharp corner in a path that twists, tapers or keeps the direction of the outline;
- a sharp corner next to a curve;
- a sharp corner inside a spline curve (a spline drawn as a polyline that turns, or one with a corner point);
- a sharp corner in a 3D path;
- corners too close together for the outline;
- a path that crosses itself, or bends tighter than the outline allows;
- a path in 3D with splines or arcs that are not tangent;
- an outline in the middle of the path, or not square to it;
- a sweep along only part of the path;
- a surface sweep;
- a sweep that makes a new component (its path stays in another component).

### Rounds and chamfers on a sweep

- A later round or chamfer on all edges of the start or end cap of a sweep names the step. It follows its sizes, as
  on an extrude.
- The end cap is placed on a path in one plane, or for an outline kept in one direction.
- After a twist, a taper, or a path that leaves one plane, only the start cap is placed.
- A closed path, or an outline with holes, has no cap placed.
- These picks keep their points, and mark only the sizes that the sweep reads:
  - a pick on part of a cap;
  - a pick on a side edge at a corner of the outline, along a path of lines and arcs.
- Any other pick on a sweep marks every size written before it.

### Pipes

- A pipe is copied when its section is a circle, solid or hollow, and it runs once along its whole path.
- It is written as the sweep of that circle (a ring when hollow). The circle is square to the path where the path
  starts, and centred on it. So the sweep rules above hold for its path.
- Sharp corners are mitred, as Fusion builds them.
- The section size follows a size as the diameter of the circle.
- The wall of a hollow pipe goes inward. The ranges stop where the wall would close the hole.
- A size that moves the start of the path is marked "may give unexpected results". The copy keeps the section where
  it was measured.
- These pipes are left out:
  - a square or triangle section (Fusion does not say which way the section turns);
  - a pipe along only part of its path;
  - a closed path that starts on a sharp corner. A closed path of lines only always does.

### Export for Orca

- The Orca output copies a pipe with a round section as a sweep of its circle.

### For developers

- The sweep step of a twist, a taper or a parallel orientation, and of a closed flat path, needs recipe version 16.
- Fusion can fail the orientation of a sweep with an InternalValidationError and give no twist and no taper. Such a
  sweep is taken as one with a guide surface, "likely".
- `agent-docs/orca-output.md`, "Pipes", describes the Orca pipe.

## Lofts

- A loft is copied when it joins two closed outlines with free ends, and has no rails and no centre line.
- An outline is a sketch outline, a closed loop of edges in one plane, or a flat face.
  - A loop of edges or a face is copied as measured.
  - The sizes that may move it are marked.
- It is written with straight faces between the outlines.
- Both outlines need the same number of holes. Their planes must not cross.
- Outlines of different shapes are copied with a note, since Fusion may pair the corners differently.
- These lofts are left out:
  - three or more outlines;
  - a point end;
  - a curved face, or a loop of edges that is open or not flat;
  - tangent or direction ends;
  - rails;
  - a centre line;
  - a closed loft;
  - a surface loft.
- A round or chamfer on all edges of an outline of a loft (no holes) names the loft and follows its sizes.
- A pick on part of an outline keeps its points and marks the sizes that the loft reads.
- A pick on the side of a loft marks every size before it.

## Coils, drafts, press pulls and other steps

### Coils

- A coil is copied when all of these are true:
  - it has a round, square or triangle section;
  - it has no taper;
  - its end faces and helical edges read back as one plain helix.
- At most 8 coils are copied. Coils and threads together can have at most 100 turns, counted in timeline order. Later
  ones are left out.
- A coil is never copied as a tool with other steps.
- These coils are left out: a spiral, a taper, and a count of revolutions with a half turn.
- The Orca output leaves every coil out (`agent-docs/orca-output.md`, "Coils").

### Drafts

- A draft is copied when all of these are true:
  - its faces all lie on one side of its plane;
  - it has one angle under 30 degrees, or the same angle on both sides;
  - the volume of the part changes (this tells which way the faces lean).
- The angle follows a size only when both sides use the same formula, and the size range stays above 0 and below 30
  degrees.
- A Symmetric draft with faces on both sides of its plane is copied the same way, as two equal angles.
- These drafts are left out, since Fusion does not say which angle leans which side:
  - a draft with two different angles;
  - a draft with faces on both sides that is not Symmetric.
- For developers: the Symmetric draft needs recipe version 17, and so a Paramability build that opens version 17.

### Press Pull of a round face

- A Press Pull (offset faces) of a curved face is copied only for a whole round face. This is a pin, a boss or a bore
  that goes all the way round, between two flat ends square to its axis.
- It is copied only when the new radius that Fusion made agrees.
- These are left out, or keep the distance as a number:
  - part of a circle;
  - an end on a slope, or with a round or chamfer;
  - a round face that also moves a face next to it;
  - a round face whose new radius would reach another edge of its end faces, at the current sizes or anywhere in the
    size range of its distance.
- The whole step is left out, also when it moves flat faces too. So the copy never moves only part of what Fusion
  moved.
- The end faces are checked as exported. So when other sizes move an edge near the ring, Paramability may refuse the
  move at those sizes.
- Export for Orca copies such a Press Pull of one round face as a ring that it adds to the part or cuts from it. The
  distance follows its parameter.

### Box, Cylinder, Sphere and Torus

- A Box, Cylinder, Sphere or Torus step is left out in both exports. Fusion does not tell add-ins where it sits or how
  it joins the part.
- Draw the shape in a sketch, and extrude or revolve it instead.

### Steps that do not stop the copy

These steps do not stop the copy:

- a Remove of another body;
- a Split Face (the solid stays the same, so picks on its faces may not follow);
- steps of other bodies that are never joined to the picked body.

## Export size choices

- Only plain number parameters can be columns.
- A parameter worked out by a formula cannot be a column.
- A parameter in a unit that this export cannot convert cannot be a column. The units it converts are mm, cm, m, in,
  ft, deg, rad and none.

## Versions

- This is version 0.14.6.
- It writes recipe version 17 when a step needs it:
  - a scale;
  - an outward or closed shell;
  - a draft with two angles;
  - a press pull of a round face;
  - a thin wall along an open line;
  - a join through all.

  A thread then also carries its pitch diameter.
- Version 17 needs Paramability 1.7.0 or newer.
- Version 0.13.0-preview.13 is the last version that writes at most recipe version 16.
- A package with left out steps holds a gaps file of version 3. Each step in it says whether it only finishes
  surfaces. This needs a Paramability build that reads version 3. An older build opens the part as a fixed shape.
- The hand checks in `agent-docs/hand-checks.md` list what was checked in Fusion.
