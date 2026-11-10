"""What the result dialog shows after a recipe is saved. Pure: no Fusion imports.

The view is built from the manifest and report that plan_single_export returned, and the size table of the export.
"""
from .dialog_rows import range_text
from ..export_plan.health import FAILED, health_lines, with_lines
from ..export_plan.messages import (
    MAX_LISTED_FIXED, also_changes_line, also_changes_parts_line, listed_lines, not_tried_line, recipe_saved_message)

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
    """Rows for ticked parameters that did not become sizes: fixed, no copied step reads them, or a step reads them and
    the copy could not follow."""
    sizes = report["sizes"]
    fixed_names = {f["name"] for f in sizes.get("fixed") or []}
    dropped = {d["name"]: d for d in sizes.get("dropped") or []}
    rows = []
    for name in ticked:
        if name in dropped:
            rows.append({"name": name, "range": "", "check": NOT_FOLLOWED if dropped[name]["used"] else NOT_USED})
        elif table.recipe_name(name) in fixed_names:
            rows.append({"name": name, "range": "", "check": KEPT_FIXED})
    return rows


def _probe_rows(report):
    """A row that says the sketches could not be measured, so no one reads the sizes as measured."""
    if (report.get("health") or {}).get("probe") == FAILED:
        return [{"name": SKETCHES, "range": "", "check": NOT_MEASURED}]
    return []


def _lines(table, entries):
    """"name: reason" for the first entries, then one line that counts the rest (`messages.listed_lines`). A reason
    that already starts with the name (Fusion's or the recipe's) is shown as it is."""
    return listed_lines(entries, {e.size_name: e.name for e in table.entries if e.size_name})


def _fixed_lines(table, report):
    return _lines(table, report["sizes"].get("fixed") or [])


def _loose_lines(table, report):
    return _lines(table, report["sizes"].get("loose") or [])


def _dropped_lines(table, report):
    """The reasons of the ticked parameters that a step reads and the copy could not follow, or that were tried and
    changed nothing. A parameter that no step reads has its own row and needs no reason."""
    return _lines(table, [d for d in report["sizes"].get("dropped") or [] if d["used"] or d.get("tried")])


ALSO_TITLE, ALSO_PARTS_TITLE = "Also change this part", "Also change these parts"


def _probe_records(report):
    """(part name or None, probe record) of the report: the file's own probe, then one per part that has one."""
    out = [(None, report["probe"])] if isinstance(report.get("probe"), dict) else []
    out += [(part.get("name") or "", part["probe"]) for part in report.get("parts") or []
            if isinstance(part, dict) and isinstance(part.get("probe"), dict)]
    return out


def also_lines(report):
    """The line for the unticked parameters the export saw changing this part, or none. In a parts file the line says
    which part each parameter changed."""
    names = report.get("also_changes") or []
    if not names:
        return []
    if "parts" not in report:
        return [also_changes_line(names)]
    where = {}
    for part, probe in _probe_records(report):
        for found in probe.get("discovery") or []:
            if found.get("moved") and part and part not in where.setdefault(found["param"], []):
                where[found["param"]].append(part)
    return [also_changes_parts_line([(name, where.get(name) or []) for name in names])]


def not_tried_lines(report):
    """The line for the parameters of other components that the export had no room to try, or none."""
    left = {found["param"] for _, probe in _probe_records(report) for found in probe.get("discovery") or []
            if found.get("tried") is False}
    return [not_tried_line(len(left), "parts" in report)] if left else []


def variables_line(manifest):
    count = len(manifest.get("parameters") or [])
    if not count:
        return ""
    noun = "parameter comes" if count == 1 else "parameters come"
    return "All %d %s along as variables, with their formulas and comments." % (count, noun)


def result_view(file_name, manifest, report, table, ticked):
    """Plain data for the result dialog, or None when the file holds no recipe (the message box tells that story).

    Keys: saved (first sentence), size_title, check_header (the title of the last column), rows ({name, range,
    check}), fixed (lines), loose (lines: sizes that stay free but may not follow every step, with why), dropped
    (lines: ticked parameters that a step reads but the copy could not follow, or tried and changed nothing, with
    why), also (a line naming unticked parameters that also change this part) with its title `also_title`,
    untried (a line counting the parameters of other components the export did not try), variables,
    warnings (what is wrong with the design or the sketch measuring, and what to do: empty when all is well),
    message (the whole story as plain text, for a message box, with the warnings below it).
    """
    if manifest.get("kind") != "recipe" or "sizes" not in report:
        return None
    notes = manifest.get("notes") or []
    rows = _size_rows(table, report)
    count = len(rows)
    dropped = _dropped_lines(table, report)
    story = recipe_saved_message(manifest, file_name)
    if dropped:
        story += "\n\n" + "\n".join("- " + line for line in dropped)
    also, untried = also_lines(report), not_tried_lines(report)
    for line in also + untried:
        story += "\n\n" + line
    return {
        "saved": ("Saved %s. %s" % (file_name, notes[0] if notes else "")).strip(),
        "size_title": "%d %s ready for the form" % (count, "size" if count == 1 else "sizes"),
        "check_header": STATUS_HEADER,
        "rows": rows + _left_out_rows(table, report, ticked) + _probe_rows(report),
        "fixed": _fixed_lines(table, report),
        "loose": _loose_lines(table, report),
        "dropped": dropped,
        "also": also,
        "also_title": ALSO_TITLE,
        "untried": untried,
        "variables": variables_line(manifest),
        "warnings": health_lines(report.get("health")),
        "message": with_lines(story, report.get("health")),
    }


def _reason_lines(entries):
    """The reasons of the first entries as they are (each already starts with its part and size), then one line that
    counts the rest."""
    lines = [e["reason"] for e in entries[:MAX_LISTED_FIXED]]
    if len(entries) > MAX_LISTED_FIXED:
        lines.append("and %d more (see report.json)." % (len(entries) - MAX_LISTED_FIXED))
    return lines


def part_lines(manifest):
    """One short line per part of a parts package: whether it is editable, how many sizes it has, or why it is a fixed
    shape."""
    lines = []
    for part in manifest.get("parts") or []:
        if part.get("recipe"):
            line = "%s: editable part." % part["name"]
            if part.get("loose"):
                line += " %d %s may give unexpected results." % (
                    len(part["loose"]), "size" if len(part["loose"]) == 1 else "sizes")
        else:
            line = ("%s: fixed shape. %s" % (part["name"], part.get("note") or "")).strip()
        lines.append(line)
    return lines


def parts_result_view(file_name, manifest, report, table, ticked):
    """`result_view` for a parts package (`recipe_export.plan_parts_export`), or None for any other file.

    The sizes are the file's: each is listed once, whatever number of parts read it. The extra key `parts` holds one
    line per part (`part_lines`). `fixed`, `loose` and `dropped` are for the whole file, each reason names its part."""
    if manifest.get("kind") != "parts" or "parts" not in report:
        return None
    sizes = report.get("sizes") or {"free": [], "fixed": [], "loose": [], "dropped": []}
    shaped = dict(report, sizes=sizes)
    notes = manifest.get("notes") or []
    rows = _size_rows(table, shaped)
    parts = part_lines(manifest)
    dropped = _lines(table, [d for d in sizes.get("dropped") or [] if d["used"] or d.get("tried")])
    fixed, loose = _reason_lines(sizes.get("fixed") or []), _reason_lines(sizes.get("loose") or [])
    story = "Saved %s. %s" % (file_name, " ".join(notes))
    for group in (parts, fixed, loose, dropped):
        if group:
            story += "\n\n" + "\n".join("- " + line for line in group)
    also, untried = also_lines(report), not_tried_lines(report)
    for line in also + untried:
        story += "\n\n" + line
    return {
        "saved": ("Saved %s. %s" % (file_name, notes[0] if notes else "")).strip(),
        "size_title": "%d %s ready for the form" % (len(rows), "size" if len(rows) == 1 else "sizes"),
        "check_header": STATUS_HEADER,
        "rows": rows + _left_out_rows(table, shaped, ticked) + _probe_rows(report),
        "parts": parts,
        "fixed": fixed,
        "loose": loose,
        "dropped": dropped,
        "also": also,
        "also_title": ALSO_PARTS_TITLE,
        "untried": untried,
        "variables": variables_line(manifest),
        "warnings": health_lines(report.get("health")),
        "message": with_lines(story, report.get("health")),
    }
