"""What the result dialog shows after a recipe is saved. Pure: no Fusion imports.

The view is built from the manifest and report that plan_single_export returned, and the size table of the export.
"""
from .dialog_rows import range_text
from .health import FAILED, health_lines, with_lines
from .messages import listed_lines, recipe_saved_message

KEPT_FIXED, NOT_USED = "kept fixed", "not used"
NOT_FOLLOWED = "not followed"
NOT_MEASURED = "not measured"
SKETCHES = "Sketches"
DOUBTFUL = "may be unexpected"
FREE = "size"
STATUS_HEADER = "In Paramability"


def _size_rows(table, report):
    """One row per size the recipe holds: its Fusion name, its range and whether it may give unexpected results."""
    sizes = report["sizes"]
    loose = {f["name"] for f in sizes.get("loose") or []}
    by_size = {e.size_name: e for e in table.entries if e.size_name}
    rows = []
    for size_name in sizes.get("free") or []:
        entry = by_size.get(size_name)
        size = table.sizes.get(size_name) or {}
        rows.append({
            "name": entry.name if entry is not None else size_name,
            "range": range_text(size, size.get("min"), size.get("max")) if "min" in size else "",
            "check": DOUBTFUL if size_name in loose else FREE,
        })
    return rows


def _left_out_rows(table, report, ticked):
    """Rows for ticked parameters that did not become sizes: fixed, no copied step reads them, or they change a sketch
    that could not be followed."""
    sizes = report["sizes"]
    fixed_names = {f["name"] for f in sizes.get("fixed") or []}
    dropped = set(sizes.get("dropped") or [])
    not_followed = set(sizes.get("not_followed") or [])
    rows = []
    for name in ticked:
        if name in dropped:
            rows.append({"name": name, "range": "", "check": NOT_FOLLOWED if name in not_followed else NOT_USED})
        elif table.recipe_name(name) in fixed_names:
            rows.append({"name": name, "range": "", "check": KEPT_FIXED})
    return rows


def _probe_rows(report):
    """A row that says the sketches could not be measured, so no one reads the sizes as measured."""
    if (report.get("health") or {}).get("probe") == FAILED:
        return [{"name": SKETCHES, "range": "", "check": NOT_MEASURED}]
    return []


def _fixed_lines(report):
    return listed_lines(report["sizes"].get("fixed") or [])


def _loose_lines(report):
    return listed_lines(report["sizes"].get("loose") or [])


def variables_line(manifest):
    count = len(manifest.get("parameters") or [])
    if not count:
        return ""
    noun = "parameter comes" if count == 1 else "parameters come"
    return "All %d %s along as variables, with their formulas and comments." % (count, noun)


def result_view(file_name, manifest, report, table, ticked):
    """Plain data for the result dialog, or None when the file holds no recipe (the message box tells that story).

    Keys: saved (first sentence), size_title, check_header (the title of the last column), rows ({name, range,
    check}), fixed (lines), loose (lines: sizes that stay free but may not follow every step, with why), variables,
    warnings (what is wrong with the design or the sketch measuring, and what to do: empty when all is well),
    message (the whole story as plain text, for a message box, with the warnings below it).
    """
    if manifest.get("kind") != "recipe" or "sizes" not in report:
        return None
    notes = manifest.get("notes") or []
    rows = _size_rows(table, report)
    count = len(rows)
    return {
        "saved": ("Saved %s. %s" % (file_name, notes[0] if notes else "")).strip(),
        "size_title": "%d %s ready for the form" % (count, "size" if count == 1 else "sizes"),
        "check_header": STATUS_HEADER,
        "rows": rows + _left_out_rows(table, report, ticked) + _probe_rows(report),
        "fixed": _fixed_lines(report),
        "loose": _loose_lines(report),
        "variables": variables_line(manifest),
        "warnings": health_lines(report.get("health")),
        "message": with_lines(recipe_saved_message(manifest, file_name), report.get("health")),
    }
