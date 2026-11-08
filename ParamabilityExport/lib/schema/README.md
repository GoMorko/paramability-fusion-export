# Schema copies

Copies of the files published by the Paramability app. Re-copy them when the app bumps a format.

- `paramability.recipe.v10.schema.json`: the recipe schema (copied).
- `paramability.recipePackage.v1.schema.json`: the package manifest schema (copied from `schemas/` in the app
  repository).
- `v1.json`: the app's `valueRows` manifest fixture
  (`src/features/project/savedFormats/fixtures/recipePackage/v1.json`), written by `scripts/write_app_fixture.py`
  through the package writer. The manifest test uses it.
