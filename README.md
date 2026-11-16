# Paramability export for Fusion

An add-in for Autodesk Fusion. It exports a body from your Fusion design to Paramability. Paramability opens the
body as a part that you can change. The sizes of the part are your Fusion user parameters.

Autodesk and Fusion are trademarks of Autodesk, Inc. Paramability is not affiliated with Autodesk.

## What it does

The add-in adds three buttons to Fusion:

- **Export for Paramability** saves one or more bodies with their modeling steps and your user parameters. In
  Paramability, you change a parameter and the part rebuilds.
- **Export size choices** saves fixed sizes of one body, for example S, M and L. In Paramability, you select a size
  from a list.
- **Export for Orca (experimental)** saves one body as an OrcaSlicer 2.5 project. The Design tab of OrcaSlicer
  rebuilds the part, and your user parameters become its variables (`docs/orca-output.md`).

Your Fusion licence applies to the files that you export. Personal is for non-commercial use. Education is for
learning only.

## How it works

1. The add-in reads the steps of the body in the Fusion timeline: sketches, extrudes, holes, fillets and more.
2. It changes your parameters for a short time and lets Fusion rebuild. This shows which sketches each parameter
   moves, and how much.
3. It sets all parameters back to their values. Your design does not change. A parameter that no copied step uses
   is reported as "changes nothing" only when the body stayed the same each time the add-in changed it.
4. It writes the steps and the parameters to a `.paramability` file. The file also holds a STEP file of the body as
   Fusion made it.
5. Paramability builds the part from the steps and compares it with the STEP shape.

The add-in cannot copy all Fusion steps. If it cannot copy a step, it leaves the step out and tells you why.
For some steps the add-in measures the shape that Fusion made, for example the radius of a round set by chord
length, or of a round whose radius changes along its edge. It copies such a step only when the measure agrees.
A shell that grows outward or has rounded corners is copied only when the volume of the part changed as the shell says.
Fusion does not record which way some steps go, for example a join whose end merges into the part. The add-in then
tells the way from where the body grew. When that does not show it, the add-in leaves the step out.
For example, a Pattern on Path is copied only when its path is one straight line, one arc or one circle, and a
Scale of a body is copied only when the body measured after it has the size and volume that its factors give. A Press
Pull on the wall of a hole or of a pin (to tune a fit) is copied only when the new radius that Fusion made agrees.
The add-in checks where Fusion says each copy of a pattern is against the faces of that copy, and leaves the
pattern out when the two do not agree.
Some places stay where they are in the copy, for example an axis or a plane that a step turns about or mirrors
across. The add-in marks each size that may move such a place "may give unexpected results". When it cannot tell
what a place is, it marks every size that the steps before it use (`docs/limits.md`).
The same holds when Fusion picked the edges of a round or chamfer from faces or chains of edges and the copy has to
pick the edges one by one: at other sizes those faces or chains may hold other edges.
Paramability then shows the original shape and a list of the missing steps.

## Install

1. Get the add-in: clone this repository, or download the release zip and unzip it.
2. In Fusion, click the **Utilities** tab, then **Scripts and Add-Ins**.
3. In the dialog, click the plus icon near the top of the list. Select **Script or add-in from device**.
4. Select the `ParamabilityExport` folder. Select the folder itself, not a file in it.
5. Find the add-in in the list and click **Run**. To load it each time Fusion starts, turn on **Run on Startup**.

The three buttons are in the **Utilities** tab, in the **Paramability** panel.

## Use

### Export for Paramability

1. Optional: in Fusion, mark the user parameters that you want to change in Paramability as favourites.
2. Click **Export for Paramability**.
3. Select the body. (*Upon initial selection there's a timeline rewind which can take its time.*) To put more bodies in one file, select up to 32 bodies.
4. Look at the parameter table. The add-in ticks the parameters that the body uses. Tick or untick parameters as
   necessary. Each ticked parameter becomes a size in Paramability. You can type a Min and a Max for it.
5. If a warning shows below the body picker, read it. It tells you which steps the copy cannot use and how to change
   them in Fusion.
6. Select the up direction of the design. Click **OK**.
7. Select where to save the file.
8. Read the result window. It shows which parameters are sizes and which steps the copy left out.
9. Open the file in Paramability.

### Export size choices

1. Click **Export size choices** and select the body.
2. Below "Parameters that change between sizes", tick the parameters that change from size to size.
3. In the Sizes table, add one row for each size. Type a name and a value for each parameter.
4. Type a name for the list of sizes ("Name of the dropdown in Paramability").
5. Select the default size and the up direction of the design.
6. Click **OK** and select where to save the file.
7. Open the file in Paramability.

After each export, the add-in sets your parameters back to their values. This also occurs if you cancel the export
or if an error occurs.

## Main limits

- The design must have history (a parametric design).
- The add-in cannot copy all Fusion steps. `docs/limits.md` gives the full list.
- Paramability opens up to 256 MB for each size and 1 GB for each file.
- This is version 0.13.0-preview.11. Use a current Paramability build to open its files.

## More information

| Document | Contents |
| --- | --- |
| `docs/user-guide.md` | All dialogs, the result window, several bodies, steps that the copy leaves out |
| `docs/orca-output.md` | Export for Orca: what it copies, what it leaves out, the report |
| `docs/limits.md` | What the copy can and cannot do, step by step |
| `docs/feature-support.md` | Which Fusion actions each export copies, and what could be copied later |
| `docs/development.md` | Code layout and tests |
| `docs/developer-guide.md` | How an export works step by step, the code map, worked examples, how to debug with `report.json` |
| `docs/capture-format.md`, `docs/expressions.md`, `docs/recipe-gaps.md` | File formats and how formulas are copied |
| `docs/adding-a-step-type.md` | How to copy one more kind of Fusion step |
| `docs/hand-checks.md`, `docs/hand-tests.md`, `docs/test-projects.md` | Checks by hand in Fusion |
| `docs/publishing.md`, `docs/create-remote.md` | Rules for sharing the add-in, releases |

## Licence

This add-in is free software under the GNU General Public License, version 3 (`LICENSE.txt`). You can share and
change it under the terms of that licence. It comes with no warranty: it is provided "as is". The licence covers this
add-in only, not the Paramability app. It applies to every version of the add-in, including the commits made before
`LICENSE.txt` held the licence text.
