# Paramability export for Fusion

A Fusion add-in that saves a design as a `.paramability` file. Paramability opens it with a size dropdown, so one
file holds several sizes of the same part.

## Install

1. Get the folder: clone this repository, or download the release zip and unzip it.
2. In Fusion, open Utilities, then Add-Ins (or press Shift+S).
3. On the Add-Ins tab, click the green plus.
4. Pick the `ParamabilityExport` folder.
5. Select it in the list, click Run. Tick "Run on startup" to load it each time.

The button "Export for Paramability" shows in the Utilities tab.

## Use

1. In Fusion, mark the user parameters you want to vary as favourites.
2. Click Export for Paramability.
3. Pick the body, list your sizes (one per line), and name the dropdown.
4. Click OK and choose where to save the file.
5. Open the file in Paramability with Open.

One size saves a plain part. Two or more sizes save a part with a dropdown.

## Limits

- One solid body per export.
- Made for the current Fusion release.
- This is version 0.1.0. The dialog and the Fusion reading code arrive in later steps.

## Tests

The writer in `ParamabilityExport/lib/package/` does not need Fusion. From this folder:

```
python3 -m unittest discover -s tests -t .
```

Python 3.10 or newer, standard library only.
