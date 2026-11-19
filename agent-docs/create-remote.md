# Create the GitHub remote

Run these steps by hand. Nothing here is automated.

1. The licence is GNU GPL version 3 (`LICENSE.txt`, chosen on 2026-11-15). The release zip carries a copy.
2. On GitHub, create a new empty repository. Its name carries no "Fusion" or "Autodesk" (for example
   `paramability-export`; see `agent-docs/publishing.md`). Leave "Add a README" and "Add a licence" off.
3. In this folder:

   ```
   git remote add origin git@github.com:<you>/paramability-export.git
   git push -u origin main
   ```

4. Make a release zip:

   ```
   python3 scripts/make_release_zip.py
   ```

   The zip lands in `dist/`.
5. On GitHub, open Releases, create a release with a tag such as `v0.1.0`, and attach the zip.
