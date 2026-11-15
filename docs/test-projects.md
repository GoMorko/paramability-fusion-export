# Test projects

A set of small, typical 3D printing projects. Together they cover the Fusion steps and modelling habits most projects
use, so the scoreboard measures how many kinds of projects the copy covers, not one design. Build each one with your
Fusion AI assistant from the first line, then export as the "Export:" line says. Start each file name with its number
(`P1_`, `P2_`, ...) so the scoreboard rows are easy to find.

Every project uses user parameters. Give each parameter a comment (it becomes the label people see) and make at least
one parameter a formula of others.

1. Electronics box with a lid, as two components "Box" and "Lid" in one design. Parameters: Length 80, Width 50,
   Height 30, Wall 2, Gap 0.3, LidHeight = Wall * 3. Box: rectangle extruded by Height, shell with the top open by Wall,
   round the vertical outside edges 4 mm, four screw posts in the corners (6 mm circles with 2.5 mm holes, from the
   floor up to Height - 2). Lid: sketch on the top face of the box, project the box outline, extrude LidHeight, add a
   lip inside offset by Wall + Gap, four counterbored holes over the posts.
    Export: the Box body, then the Lid body, then the whole design as parts. The lid uses a face of the box, so it shows
    what happens to steps that reach into another component.

2. Threaded jar. Parameters: Diameter 60, Height 70, Wall 2, NeckHeight 12. Revolve the jar profile, shell it from the
   top by Wall, add a modelled Thread on the outside of the neck. A second component, the cap, has a matching modelled
   inside thread.
    Export: the jar body, then the cap body. Expect the threads to copy and to follow Diameter.

3. Print-in-place hinge. Parameters: Length 60, LeafWidth 20, Thickness 3, Knuckles 5, Clearance 0.4. Two leaves, a
   row of knuckles made with a rectangular pattern of Knuckles copies, every other knuckle on the other leaf, a pin
   through them, and gaps of Clearance between the moving parts.
    Export: one leaf body. Expect Knuckles and Clearance on the form.

4. Cable clip. Parameters: CableDiameter 6, Thickness 2, ClipWidth 10, Opening = CableDiameter * 0.7. Sketch a C shape
   from arcs and lines around a circle of CableDiameter with an opening of Opening, extrude ClipWidth, add a flat foot
   with a screw hole, round the ends.
    Export: the clip. Expect CableDiameter to change the whole clip.

5. Spur gear. Parameters: Teeth 20, ToothSize 3, Thickness 8, Bore 5. Sketch one tooth (a trapezoid with arcs) on a
   base circle, extrude Thickness, circular pattern of Teeth copies, a bore of Bore with a key flat.
    Export: the gear. Expect Teeth on the form as a count.

6. Phone stand. Parameters: Angle 65 degrees, Width 70, BaseDepth 80, Thickness 5, LipHeight 12. Side profile sketch
   with the back rest at Angle and a front lip, extrude Width, cut a cable slot through the base, round the inside
   corners, chamfer the bottom edges 1 mm.
    Export: the stand. Expect Angle on the form as an angle.

7. Name tag. Parameters: TagLength 60, TagWidth 20, TagThickness 2, TextHeight 8. A plate with rounded corners and a key
   ring hole, sketch text on the top face, emboss the text 1 mm up. Make a second tag where the text is cut 0.6 mm
   into the plate.
    Export: each tag. Expect the text to copy, or a clear note before the export that it will not.

8. Spring and coiled handle. Parameters: CoilDiameter 20, Pitch 5, Turns 8, WireSize 2. A Coil with a round section of
   WireSize. A second design: a disk 30 mm wide with a Coil of square section joined on top.
    Export: each design. Expect the coils to copy and follow the parameters.

9. Wall bracket. Parameters: ArmLength 60, Height 60, BracketWidth 25, Thickness 5. An L shape extruded by
   BracketWidth, a round on the inside corner, two countersunk holes made with the Hole tool, a Rib between the arms,
   a 2 degree draft on the outside faces.
    Export: the bracket. Expect the holes and the rib to copy, and the draft to copy or to show a clear note.

10. Lamp shade and mug handle. Parameters: BaseDiameter 100, TopSize 60, ShadeHeight 120, Twist 30 degrees. Loft from a
    circle at the base to a hexagon at the top turned by Twist, shell open at both ends by 1.5 mm. A second design: a
    mug body (revolve) with a handle swept along a curved path.
    Export: the shade, then the mug. Expect the loft and the sweep to copy.

11. Plant pot with drain holes. Parameters: PotDiameter 120, PotHeight 100, Wall 2.5, Holes = floor(PotDiameter / 20).
    Revolve a tapered pot, shell open at the top, cut one drain hole in the floor, circular pattern of Holes copies.
    Export: the pot. Expect Holes to follow PotDiameter (a formula with a function).

12. Drawer organizer. Parameters: TrayLength 150, TrayWidth 100, TrayHeight 40, Wall 1.6, CellsX 3, CellsY 2,
    CellLength = (TrayLength - Wall * (CellsX + 1)) / CellsX. A box shelled open at the top, inside walls placed with
    rectangular patterns of CellsX and CellsY, round the inside floor edges.
    Export: the tray. Expect CellsX and CellsY on the form and the walls to stay evenly spaced.

13. Pen cup with a name. Parameters: CupDiameter 70, CupHeight 100, Wall 2. Revolve a cup, shell it open at the top,
    add sketch text on a plane that touches the side, and emboss the text onto the side 0.8 mm. Make a second one with
    the emboss turned and moved along the side.
    Export: the cup. Expect a clear note before the export that the wrapped text will not copy.

14. Lid with a centred label. Parameters: LidWidth 80, LidDepth 60, LidThickness 3. A lid plate whose top grows with
    LidWidth, sketch text centred on the top with a midpoint constraint, emboss 0.6 mm up.
    Export: the lid. Expect the label to stay centred when LidWidth changes.

15. Plate with a tuned hole. Parameters: PlateSize 50, HoleSize 5. A plate with a hole of HoleSize, then Press Pull on
    the hole wall by -0.2 mm.
    Export: the plate. Expect the looser hole to copy, or a clear note that it does not.
