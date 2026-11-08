"""Translate every capture fixture and write each recipe to dist/translator-samples/<case>.recipe.json.

Run from the add-in root: python3 scripts/write_translator_samples.py
Fixtures that refuse are listed and not written. Files that are not captures (the schema example) are ignored.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))

from lib.translator import CaptureError, translate  # noqa: E402


def main():
    out_dir = os.path.join(ROOT, "dist", "translator-samples")
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "captures", "*.json"))):
        case = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            capture = json.load(f)
        if not isinstance(capture, dict) or "capture" not in capture:
            continue
        try:
            result = translate(capture)
        except CaptureError as error:
            print("%s: capture error: %s" % (case, error))
            continue
        if result.recipe is None:
            print("%s: refused: %s" % (case, result.refusal["reason"]))
            continue
        with open(os.path.join(out_dir, case + ".recipe.json"), "w", encoding="utf-8") as f:
            json.dump(result.recipe, f, indent=2, sort_keys=True)
            f.write("\n")
        written += 1
    print("wrote %d recipes to %s" % (written, out_dir))


if __name__ == "__main__":
    main()
