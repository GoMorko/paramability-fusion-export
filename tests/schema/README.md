# Schema copies

Copies of the files published by the Paramability app. Re-copy them when the app bumps a format.

- `paramability.recipe.v<N>.schema.json`: the recipe schemas (copied from `schemas/` in the app repository). Keep the
  oldest version the translator writes and every newer one it can write: a recipe states the lowest version that
  holds its steps (`KIND_VERSIONS` in `lib/translator/translate.py`), and `tests/schema_check.py` checks each recipe
  against the copy of its own version. Its default for a recipe without a version is the highest one found here. Copy
  a new file when the translator starts to write a new version.
- `paramability.recipePackage.v1.schema.json`, `paramability.recipePackage.v2.schema.json`: the package manifest
  schemas (copied from `schemas/` in the app repository). The writer makes version 1, and version 2 only for a
  package that holds a gaps file.
- `paramability.recipeGaps.v1.schema.json`, `v2` and `v3`: the schemas of the gaps file (copied from `schemas/` in
  the app repository). The writer always makes version 3 (version 3 adds `finishing`); the tests validate against it.
  The older copies stay as the record of what an older add-in wrote.
- `v1.json`: the app's `valueRows` manifest fixture
  (`src/features/project/savedFormats/fixtures/recipePackage/v1.json`), written by `scripts/write_app_fixture.py`
  through the package writer. The manifest test uses it.
