# Paramability export for Fusion

An add-in for Autodesk Fusion. It exports a body from your Fusion design to Paramability. Paramability opens the
body as a part that you can change. The sizes of the part are your Fusion user parameters.

Autodesk and Fusion are trademarks of Autodesk, Inc. Paramability is not affiliated with Autodesk.

## What it does

The add-in adds three buttons to Fusion:

| Button | What it saves | What you get |
| --- | --- | --- |
| **Export for Paramability** | One or more bodies, their modeling steps and your user parameters | In Paramability, you change a parameter and the part rebuilds. |
| **Export size choices** | Fixed sizes of one body, for example S, M and L | In Paramability, you select a size from a list. |
| **Export for Orca (experimental)** | One body as an OrcaSlicer 2.5 project | The Design tab of OrcaSlicer rebuilds the part. Your user parameters become its variables. |

Both exports copy the common steps: sketches, extrudes, revolves, holes and threads, fillets and chamfers, shells,
patterns and mirrors, sweeps, lofts, pipes, ribs and Combine. `agent-docs/feature-support.md` lists each Fusion
step and which export copies it.

Your Fusion licence applies to the files that you export. Personal is for non-commercial use. Education is for
learning only.

## How it works

1. **Read.** The add-in reads the timeline steps that make the body.
2. **Try.** It changes each parameter for a short time and lets Fusion rebuild. This shows what each parameter
   moves, and how far it can go before a step fails. These tries give the Min and Max of each size.
3. **Put back.** It sets all parameters back and checks that the design is the same as before. If it cannot confirm
   this, it asks Fusion to undo the whole export. The result window tells you.
4. **Write.** It writes the steps, the parameters and a STEP copy of the body to a `.paramability` file.
5. **Rebuild.** Paramability builds the part from the steps and compares it with the STEP copy.

**When the add-in is not sure, it leaves a step out.** A wrong copy is worse than a missing step. Each step that is
left out has a reason and a tip. Paramability shows the original shape and the list of missing steps.

For some steps, the add-in measures the shape that Fusion made. It copies the step only when the measure agrees.

Some sizes can move a place that stays fixed in the copy, for example a mirror plane. The add-in marks these sizes
"may give unexpected results".

`agent-docs/user-guide.md` tells more about the tries, the size ranges and the put back. `agent-docs/limits.md`
gives the rules for each step.

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
3. Select the body. To put more bodies in one file, select up to 32 bodies. The add-in then moves the timeline back to
   read the steps. On a large design, this can take some time.
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

### Export for Orca

1. Click **Export for Orca (experimental)**.
2. Select the body. Tick the parameters that you want as variables in Orca.
3. Save the `.3mf` file.
4. In OrcaSlicer 2.5, turn on Preferences > General > Features > "CAD feature (experimental)". Restart Orca.
5. Open the file. Change the variables in the Design tab.

This export copies fewer kinds of steps than Export for Paramability. `agent-docs/orca-output.md` tells what it
copies.

After each export, the add-in sets your parameters back to their values. This also occurs if you cancel the export
or if an error occurs.

### When something goes wrong

Each export writes a short trail of what it does to the file `export-trail.log`. The file is in the folder
`ParamabilityExport` of your temporary folder (`%TEMP%\ParamabilityExport` on Windows). The file stays when Fusion
closes suddenly. Send it with your bug report (`agent-docs/user-guide.md`, "The export trail, for a bug report").

## Main limits

- The design must have history (a parametric design).
- The add-in cannot copy all Fusion steps. `agent-docs/limits.md` gives the full list.
- Export for Orca leaves out a coil. Both exports leave out a Box, Cylinder, Sphere or Torus step: draw the shape in a
  sketch and extrude or revolve it instead.
- Paramability opens up to 256 MB for each size and 1 GB for each file.
- This is version 0.14.6. It needs Paramability 1.7.0 or newer to open its files.

## More information

| Document | Contents |
| --- | --- |
| `agent-docs/user-guide.md` | All dialogs, the result window, several bodies, steps that the copy leaves out |
| `agent-docs/orca-output.md` | Export for Orca: what it copies, what it leaves out, the report |
| `agent-docs/limits.md` | What the copy can and cannot do, step by step |
| `agent-docs/feature-support.md` | Which Fusion steps each export copies, and what could be copied later |
| `agent-docs/development.md` | Code layout and tests |
| `agent-docs/developer-guide.md` | How an export works step by step, the code map, worked examples, how to debug with `report.json` |
| `agent-docs/capture-format.md`, `agent-docs/expressions.md`, `agent-docs/recipe-gaps.md` | File formats and how formulas are copied |
| `agent-docs/adding-a-step-type.md` | How to copy one more kind of Fusion step |
| `agent-docs/hand-checks.md`, `agent-docs/hand-tests.md`, `agent-docs/test-projects.md` | Checks by hand in Fusion |
| `agent-docs/publishing.md`, `agent-docs/create-remote.md` | Rules for sharing the add-in, releases |

## Licence

This add-in is free software under the GNU General Public License, version 3 (`LICENSE.txt`). You can share and
change it under the terms of that licence. It comes with no warranty: it is provided "as is". The licence covers this
add-in only, not the Paramability app. It applies to every version of the add-in, including the commits made before
`LICENSE.txt` held the licence text.
