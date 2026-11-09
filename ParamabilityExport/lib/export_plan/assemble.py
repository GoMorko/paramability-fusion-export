"""Turn row results into a manifest and the files for the writer."""
from ..package.manifest import (
    build_step_only_manifest,
    build_value_rows_manifest,
    row_step_path,
    validate_manifest,
)
from ..package.units import manifest_unit
from ..params.listing import list_parameters


MAX_LABEL = 120


def manifest_parameters(columns, params):
    """Manifest parameter entries for the columns, in column order (the value rows list)."""
    by_name = {p["name"]: p for p in params}
    out = []
    for name in columns:
        p = by_name[name]
        entry = {"name": name, "unit": manifest_unit(p["unit"])}
        comment = (p.get("comment") or "").strip()
        if comment:
            entry["label"] = comment[:MAX_LABEL]
        out.append(entry)
    return out


def build_package(title, writer, results, columns, params, default_index, choice_name, up_axis, design_unit="mm"):
    """Return (manifest, files). One result gives a stepOnly package, two or more give valueRows.

    A stepOnly package lists every user parameter in `parameters`. A valueRows package lists only the columns, by
    their Fusion names, and its rows are keyed by the same names.
    files maps entry path to the STEP file on disk. Raises ValueError when the manifest breaks the package rules.
    """
    if len(results) == 1:
        listing = list_parameters(params, design_unit=design_unit)
        manifest = build_step_only_manifest(title, writer, up_axis=up_axis, parameters=listing.entries)
        files = {"part.step": results[0]["step_file"]}
    else:
        rows = [{"name": r["name"], "values": r["values"]} for r in results]
        notes = [f"{len(results)} sizes exported."]
        manifest = build_value_rows_manifest(
            title, writer, manifest_parameters(columns, params), rows,
            default_index=default_index, choice_name=choice_name or None, up_axis=up_axis, notes=notes)
        files = {row_step_path(i): r["step_file"] for i, r in enumerate(results, start=1)}
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(" ".join(problems))
    return manifest, files
