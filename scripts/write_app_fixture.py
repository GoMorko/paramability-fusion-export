"""Writes a valueRows manifest with every optional field set, through the package writer.

The app keeps the output as its frozen fixture. Usage: python3 scripts/write_app_fixture.py [output path]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))

from lib.package.manifest import build_value_rows_manifest, validate_manifest  # noqa: E402


def main():
    manifest = build_value_rows_manifest(
        name="Cable clip",
        writer="Paramability Fusion export 0.1.0, Fusion 2.0.21508",
        parameters=[
            {"name": "width", "label": "Clip width", "unit": "mm"},
            {"name": "angle", "unit": "deg"},
            {"name": "teeth", "unit": ""},
        ],
        rows=[
            {"name": "Small", "values": {"width": 20, "angle": 30, "teeth": 4}},
            {"name": "Medium", "values": {"width": 30, "angle": 30, "teeth": 6}},
            {"name": "Large", "values": {"width": 40, "angle": 30, "teeth": 8}},
        ],
        default_index=2,
        choice_name="Size",
        up_axis="y",
        notes=["3 sizes exported.", "Angles are in degrees."],
    )
    problems = validate_manifest(manifest)
    if problems:
        sys.exit("\n".join(problems))
    text = json.dumps(manifest, indent=2) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


main()
