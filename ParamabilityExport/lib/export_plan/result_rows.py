"""What the result dialog shows after a recipe is saved. Pure: no Fusion imports.

The view is built from the manifest and report that plan_single_export returned, and the size table of the export.
"""
from .dialog_rows import range_text
from .messages import listed_lines, recipe_saved_message

MATCHES, NOT_CHECKED, KEPT_FIXED, NOT_USED = "matches Fusion", "not checked", "kept fixed", "not used"
DOUBTFUL = "may be unexpected"


def _size_rows(table, report):
    """One row per size the recipe holds: its Fusion name, range and what the check found. A range the translator
    shortened or a smallest value it raised (so a picked pattern copy stays) is shown that way."""
    sizes = report["sizes"]
    unchecked = set(sizes.get("unchecked") or [])
    loose = {f["name"] for f in sizes.get("loose") or []}
    raised = {r["name"]: r["min"] for r in sizes.get("raised") or []}
    narrowed = {n["size"]: (n["min"], n["max"]) for n in sizes.get("narrowed") or [] if "min" in n and "max" in n}
    by_size = {e.size_name: e for e in table.entries if e.size_name}
    rows = []
    for size_name in sizes.get("free") or []:
        entry = by_size.get(size_name)
        size = dict(table.sizes.get(size_name) or {})
        if size_name in narrowed and "min" in size:
            lo, hi = narrowed[size_name]
            size["min"], size["max"] = max(size["min"], lo), min(size["max"], hi)
        if size_name in raised and "min" in size:
            size["min"] = max(size["min"], raised[size_name])
        rows.append({
            "name": entry.name if entry is not None else size_name,
            "range": range_text(size, size.get("min"), size.get("max")) if "min" in size else "",
            "check": DOUBTFUL if size_name in loose else NOT_CHECKED if size_name in unchecked else MATCHES,
        })
    return rows


def _left_out_rows(table, report, ticked):
    """Rows for ticked parameters that did not become sizes: fixed after a check, or no copied step reads them."""
    sizes = report["sizes"]
    fixed_names = {f["name"] for f in sizes.get("fixed") or []}
    dropped = set(sizes.get("dropped") or [])
    rows = []
    for name in ticked:
        if name in dropped:
            rows.append({"name": name, "range": "", "check": NOT_USED})
        elif table.recipe_name(name) in fixed_names:
            rows.append({"name": name, "range": "", "check": KEPT_FIXED})
    return rows


def _fixed_lines(report):
    return listed_lines(report["sizes"].get("fixed") or [])


def _loose_lines(report):
    return listed_lines(report["sizes"].get("loose") or [])


def _narrowed_lines(report):
    return [n["note"] for n in report["sizes"].get("narrowed") or [] if n.get("note")]


def variables_line(manifest):
    count = len(manifest.get("parameters") or [])
    if not count:
        return ""
    noun = "parameter comes" if count == 1 else "parameters come"
    return "All %d %s along as variables, with their formulas and comments." % (count, noun)


def result_view(file_name, manifest, report, table, ticked):
    """Plain data for the result dialog, or None when the file holds no recipe (the message box tells that story).

    Keys: saved (first sentence), size_title, rows ({name, range, check}), fixed (lines), loose (lines: sizes that
    stay free but may not follow every step, with why), narrowed (lines: sizes whose
    range was shortened because Fusion could not build the part or a step would no longer meet it), variables,
    message (the whole story as plain text, for a message box).
    """
    if manifest.get("kind") != "recipe" or "sizes" not in report:
        return None
    notes = manifest.get("notes") or []
    rows = _size_rows(table, report)
    count = len(rows)
    return {
        "saved": ("Saved %s. %s" % (file_name, notes[0] if notes else "")).strip(),
        "size_title": "%d %s ready for the form" % (count, "size" if count == 1 else "sizes"),
        "rows": rows + _left_out_rows(table, report, ticked),
        "fixed": _fixed_lines(report),
        "loose": _loose_lines(report),
        "narrowed": _narrowed_lines(report),
        "variables": variables_line(manifest),
        "message": recipe_saved_message(manifest, file_name),
    }
