# Schema copies

Copies of the files published by the Paramability app. Re-copy them when the app bumps a format.

- `paramability.recipe.v10.schema.json`: the recipe schema (copied).
- `paramability.recipePackage.v1.schema.json`: the package manifest schema. Not copied yet. Copy it from
  `schemas/` in the app repository once it exists.
- `v1.json`: the app's `valueRows` manifest fixture
  (`src/features/project/savedFormats/fixtures/recipePackage/v1.json`). Not copied yet. The manifest test
  uses it when present.
