"""Zip the ParamabilityExport folder into dist/ for a GitHub release."""
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDIN = os.path.join(ROOT, "ParamabilityExport")


def main():
    with open(os.path.join(ADDIN, "ParamabilityExport.manifest"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"ParamabilityExport-{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, names in os.walk(ADDIN):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in names:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.join("ParamabilityExport", os.path.relpath(full, ADDIN)))
    print(out)


if __name__ == "__main__":
    main()
