# Schema copies

Copies of the files published by the Paramability app. Re-copy them when the app bumps a format.

- `paramability.recipe.v<N>.schema.json`: the recipe schema (copied from `schemas/` in the app repository). Keep
  only the version the translator writes; `tests/schema_check.py` reads the highest one found here. Copy the new file
  and remove the old one when the translator moves to a new recipe version.
- `paramability.recipePackage.v1.schema.json`: the package manifest schema (copied from `schemas/` in the app
  repository).
- `v1.json`: the app's `valueRows` manifest fixture
  (`src/features/project/savedFormats/fixtures/recipePackage/v1.json`), written by `scripts/write_app_fixture.py`
  through the package writer. The manifest test uses it.
