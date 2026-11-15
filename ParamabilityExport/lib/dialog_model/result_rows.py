"""What the result dialog shows after a recipe is saved. Pure: no Fusion imports.

The view is a list of sections, each a `# Title` and its lines, built from the manifest and report that the export
returned and the size table of the export. A section with nothing to say is not in the list. Detail that only helps
debugging stays in `report.json`.
"""
import re

from .dialog_rows import range_text
from ..export_plan.health import FAILED, health_lines
from ..export_plan.messages import (
    ORIGINAL_KEPT_NOTE, ORIGINAL_KEPT_PARTS_NOTE, also_changes_line, also_changes_parts_line, left_out_lines,
    not_tried_line, time_stop_line)

KEPT_FIXED, NOT_USED = "kept fixed", "not used"
NOT_FOLLOWED = "not followed"
CUT = "range cut"
NOT_MEASURED = "not measured"
SKETCHES = "Sketches"
DOUBTFUL = "may be unexpected"
FREE = "size"

# The words of a reason that the status already says, so the line keeps only the part that adds something.
_STATUS_WORDS = ("may give unexpected results", "stays fixed", "is not a size")


def _tidy(text):
    return text.strip(" :.,;")


def _split_reason(reason, names):
    """`(condition, detail)` of a reason. The leading name and the words the status already says are cut away: "wall
    may give unexpected results past 1.8: Extrude5 may not meet the part." gives ("past 1.8", "Extrude5 may not meet
    the part"). A part tag in front of the name ("Lid: wall ...") stays at the start of the detail."""
    found = [(m.start(), m.end()) for words in _STATUS_WORDS for m in [re.search(re.escape(words), reason)] if m]
    if found:
        start, end = min(found)
        lead, rest = reason[:start], reason[end:]
        tag = _tidy(lead.rsplit(": ", 1)[0]) if ": " in lead else ""
    else:
        tag = ""
        rest = reason
        for name in sorted(names, key=len, reverse=True):
            if rest.startswith(name):
                rest = rest[len(name):]
                break
    condition, detail = "", rest
    if found and ": " in rest and not rest.lstrip().startswith(":"):
        condition, detail = rest.split(": ", 1)
    detail = _tidy(detail)
    return _tidy(condition), ("%s: %s" % (tag, detail) if tag and detail else tag or detail)


def size_line(row):
    """The one line of a size: "wall: 1 to 4 mm, may be unexpected past 1.8 (why)". A plain size shows only its range.
    A name never shows twice."""
    status = "" if row["check"] == FREE else " ".join(x for x in (row["check"], row["condition"]) if x)
    state = ", ".join(x for x in (row["range"], status) if x)
    return "%s: %s%s" % (row["name"], state, " (%s)" % row["why"] if row["why"] else "")


def _reasons(entries, names):
    """`{name: [(condition, detail)]}` of manifest style `{name, reason}` entries, in the order given."""
    out = {}
    for entry in entries:
        out.setdefault(entry["name"], []).append(_split_reason(entry["reason"], names | {entry["name"]}))
    return out


def _cut_text(entry):
    """What was seen where a range was cut, and that every part of a file has the same range when it is shared."""
    return entry["why"] + (", the same in every part that uses it" if entry.get("shared") else "")


def kept_number_lines(manifest):
    """One line per listed formula parameter that stayed a plain number, with Fusion's own formula and the reason."""
    return ["kept as a number: %s = %s (%s)" % (p.get("label") or p["name"], p["expression"], _tidy(p["untranslated"]))
            for p in manifest.get("parameters") or [] if p.get("expression") and p.get("untranslated")]


def _row(name, rng, check, found=()):
    """A size row: `condition` and `why` come from the reasons found for it (joined when there are several)."""
    return {"name": name, "range": rng, "check": check,
            "condition": "; ".join(c for c, _ in found if c), "why": "; ".join(dict.fromkeys(d for _, d in found if d))}


def _size_rows(table, report, ticked):
    """One row per size and per ticked or fixed parameter that is not a size, in this order: sizes that follow, sizes
    that may give unexpected results, parameters kept fixed, then parameters not followed or not used. Each row holds
    the reason, so no name is listed twice."""
    sizes = report["sizes"]
    shown = {e.size_name: e.name for e in table.entries if e.size_name}
    names = set(shown) | set(shown.values()) | set(ticked)
    loose = _reasons(sizes.get("loose") or [], names)
    fixed = _reasons(sizes.get("fixed") or [], names)
    cut = {entry["name"]: entry for entry in sizes.get("cut") or []}
    followed, doubtful, kept, dropped = [], [], [], []
    for size_name in sizes.get("free") or []:
        size = table.sizes.get(size_name) or {}
        if size_name in cut:
            size = dict(size, min=cut[size_name]["min"], max=cut[size_name]["max"])
        rng = range_text(size, size.get("min"), size.get("max")) if "min" in size else ""
        name = shown.get(size_name, size_name)
        if size_name in loose:
            row = _row(name, rng, DOUBTFUL, loose[size_name])
            if size_name in cut:
                row["why"] = "; ".join(x for x in (row["why"], "%s: %s" % (CUT, _cut_text(cut[size_name]))) if x)
            doubtful.append(row)
        elif size_name in cut:
            followed.append(_row(name, rng, CUT, [("", _cut_text(cut[size_name]))]))
        else:
            followed.append(_row(name, rng, FREE))
    for size_name, found in fixed.items():
        kept.append(_row(shown.get(size_name, size_name), "", KEPT_FIXED, found))
    for entry in sizes.get("dropped") or []:
        if entry["name"] not in ticked:
            continue
        found = [_split_reason(entry["reason"], names | {entry["name"]})] if entry["used"] or entry.get("tried") else []
        dropped.append(_row(entry["name"], "", NOT_FOLLOWED if entry["used"] else NOT_USED, found))
    return followed + doubtful + kept + dropped


def _probe_rows(report):
    """A row that says the sketches could not be measured, so no one reads the sizes as measured."""
    if (report.get("health") or {}).get("probe") == FAILED:
        return [_row(SKETCHES, "", NOT_MEASURED)]
    return []


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


def _left_out_entries(report):
    """`[(part name or None, gap record)]` of the steps left out of the copy. A parts report holds the gaps of each
    part in its record."""
    if "parts" in report:
        return [(part.get("name") or "", gap) for part in report["parts"] for gap in part.get("gaps") or []]
    return [(None, gap) for gap in report.get("gaps") or []]


def _left_out_lines(report):
    """The steps left out with their reasons and a closing sentence about how the file opens, or none."""
    entries = _left_out_entries(report)
    if not entries:
        return []
    return left_out_lines(entries) + [ORIGINAL_KEPT_PARTS_NOTE if "parts" in report else ORIGINAL_KEPT_NOTE]


def time_stop_lines(report):
    """The line that says the size tries stopped on their time limit, or none. A parts file counts each size once."""
    limit, left, hit = None, [], False
    for _, probe in _probe_records(report):
        record = probe.get("time_limit") or {}
        if record.get("hit"):
            hit, limit = True, record.get("limit_seconds")
            left += [name for name in record.get("left_out") or [] if name not in left]
    return [time_stop_line(limit, len(left))] if hit else []


def _count(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _result_lines(file_name, manifest, report, size_count, part_lines=()):
    """What the person can do next, what kind of file it is, and how many parameters came along as variables."""
    if size_count:
        lines = ["Saved %s. Open it in Paramability: %s ready for the form." % (
            file_name, _count(size_count, "size is", "sizes are"))]
    else:
        lines = ["Saved %s. Open it in Paramability. No parameter became a size, so the form is empty." % file_name]
    notes = manifest.get("notes") or []
    if "parts" in report:
        lines += part_lines
    else:
        kind = "Editable copy with steps left out (listed below)" if _left_out_entries(report) else "Editable copy"
        lines.append((kind + ". " + (notes[0] if notes else "")).strip())
    variables = len(manifest.get("parameters") or [])
    if variables:
        lines.append("%s along as variables." % _count(variables, "parameter comes", "parameters come"))
    return lines + time_stop_lines(report)


def _part_lines(manifest, report):
    """One short line per part of a parts package: an editable copy (with a mark when steps were left out of it), or a
    fixed shape with the reason."""
    left_out = {name for name, _ in _left_out_entries(report)}
    lines = []
    for part in manifest.get("parts") or []:
        if part.get("recipe"):
            line = "%s: editable copy%s." % (part["name"], ", some steps left out" if part["name"] in left_out else "")
        else:
            line = ("%s: fixed shape. %s" % (part["name"], part.get("note") or "")).strip()
        lines.append(line)
    return lines


def _section(key, title, lines, rows=None):
    """A section as plain data, or None when it holds nothing to show."""
    if not lines and not rows:
        return None
    return {"key": key, "title": title, "lines": list(lines), "rows": list(rows or [])}


def section(view, key):
    """The section of `view` with this key, or None when the view does not show it."""
    return next((s for s in view["sections"] if s["key"] == key), None)


def section_lines(view, key):
    """The lines of one section of `view`, empty when the section is not shown."""
    found = section(view, key)
    return found["lines"] if found else []


def view_message(sections):
    """The sections as plain text for a message box: each `# Title` and its lines."""
    return "\n\n".join("\n".join(["# " + found["title"]] + found["lines"]) for found in sections)


def _build(file_name, manifest, report, table, ticked, result_extra=()):
    rows = _size_rows(table, report, ticked) + _probe_rows(report)
    size_count = len(report["sizes"].get("free") or [])
    sections = [
        _section("check", "Check your design", health_lines(report.get("health"))),
        _section("result", "Result", _result_lines(file_name, manifest, report, size_count, result_extra)),
        _section("sizes", "Sizes", [size_line(r) for r in rows] + kept_number_lines(manifest), rows),
        _section("left_out", "Left out", _left_out_lines(report)),
        _section("more", "More sizes", also_lines(report) + not_tried_lines(report)),
    ]
    sections = [found for found in sections if found]
    return {"sections": sections, "message": view_message(sections)}


def result_view(file_name, manifest, report, table, ticked):
    """Plain data for the result dialog, or None when the file holds no recipe (the message box tells that story).

    Keys: `sections` and `message` (the same text for a message box). Each section is `{key, title, lines, rows}`;
    the keys, in this order, are `check` (what is wrong with the design or the sketch measuring, and what to do),
    `result` (open the file, kind of copy, variables), `sizes` (one line per size or parameter that is not a size,
    with its range or state and its reason, a cut range as "range cut" with what was seen at the cut; `rows` holds the
    same as data; then a "kept as a number: name = Fusion formula (reason)" line for each formula parameter that was
    not translated), `left_out` (steps with reasons) and `more` (unticked parameters that also change the part, and
    parameters not tried). A section without content is absent.
    """
    if manifest.get("kind") != "recipe" or "sizes" not in report:
        return None
    return _build(file_name, manifest, report, table, ticked)


def parts_result_view(file_name, manifest, report, table, ticked):
    """`result_view` for a parts package (`recipe_export.plan_parts_export`), or None for any other file.

    The sizes are the file's: each is listed once, whatever number of parts read it, and its reason names its part. The
    `result` section holds one line per part."""
    if manifest.get("kind") != "parts" or "parts" not in report:
        return None
    sizes = report.get("sizes") or {"free": [], "fixed": [], "loose": [], "dropped": []}
    return _build(file_name, manifest, dict(report, sizes=sizes), table, ticked, _part_lines(manifest, report))
