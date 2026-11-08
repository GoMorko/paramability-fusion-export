# Create the GitHub remote

Run these steps by hand. Nothing here is automated.

1. Pick a licence and replace `LICENSE.txt` (see the note at its top). Commit it.
2. On GitHub, create a new empty repository. Leave "Add a README" and "Add a licence" off.
3. In this folder:

   ```
   git remote add origin git@github.com:<you>/paramability-fusion-recipe.git
   git push -u origin main
   ```

4. Make a release zip:

   ```
   python3 scripts/make_release_zip.py
   ```

   The zip lands in `dist/`.
5. On GitHub, open Releases, create a release with a tag such as `v0.1.0`, and attach the zip.
