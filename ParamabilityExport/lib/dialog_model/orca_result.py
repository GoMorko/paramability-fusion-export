"""What the result dialog shows after an OrcaSlicer project is saved (Export for Orca). Pure: no Fusion imports.

The same `# Title` sections as `result_rows`: what to check in the design, the result, which parameters follow an
Orca variable and which stayed fixed, the steps left out, and what to do next in OrcaSlicer. Built from the report
of the export (`export_plan.orca_export`).
"""
from ..export_plan.rollback import NO_ROLLBACK, check_lines
from ..export_plan.messages import left_out_lines
from ..export_plan.orca_export import translate_for_orca
from . import left_out_preview
from .result_rows import short_message, view_message
from .stop_warning import LEFT_OUT_HEADING

TITLE = "Saved for OrcaSlicer"
NEXT_LINES = [
    "1. In OrcaSlicer, turn on Preferences > General > Features > \"CAD feature (experimental)\", then restart it.",
    "2. Open the file. The plate shows the part, and the Design tab holds its steps.",
    "3. In the Design tab, change the variables: the part follows them.",
    "4. Commit adds the changed part to the plate as a new object. Delete the old one.",
]
NOT_USED_LINE = "The Min and Max columns and the size tries are not used for Orca."
LEFT_OUT_END = "Orca builds the part without these steps, so its shape differs from the Fusion part."


def _count(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def _line(text):
    """One line of plain text, whole: the result window wraps long lines (`result_dialog`, `text_rows`)."""
    return " ".join(str(text).split())


def parameter_line(entry):
    """One line for a ticked parameter: the variable it follows and where, or why it stayed fixed."""
    name = entry["name"]
    reasons = "; ".join(dict.fromkeys(r.rstrip(".") for r in entry.get("reasons") or []))
    where = ", ".join(entry.get("follows") or [])
    outcome = entry.get("outcome")
    if outcome == "variable":
        return _line("%s: follows the Orca variable %s (%s)" % (name, entry.get("variable") or name, where))
    if outcome == "partly":
        return _line("%s: follows the Orca variable %s in %s, but not everywhere: %s" % (
            name, entry.get("variable") or name, where, reasons))
    if outcome == "fixed":
        return _line("%s: stays a fixed number in Orca (%s)" % (name, reasons))
    return _line("%s: not used by the copy (%s)" % (name, reasons or "no copied step uses it"))


def _formula_lines(orca, ticked):
    """A line for each variable that is a formula of others."""
    shown = {p.get("variable") for p in orca.get("parameters") or []}
    return ["%s = %s (a formula)" % (name, text) for name, text in (orca.get("variables") or {}).items()
            if name not in shown and name not in ticked]


def _result_lines(file_name, report):
    orca = report.get("orca")
    notes = list(report.get("notes") or [])
    if orca is None:
        return ["Saved %s. It holds the shape of the part only: nothing can be changed in the Design tab." % file_name
                ] + notes
    steps = sum(1 for f in orca.get("features") or [] if f.get("type") != 0)
    variables = len(orca.get("variables") or {})
    line = "Saved %s for OrcaSlicer 2.5: %s in the Design tab, %s." % (
        file_name, _count(steps, "step", "steps"), _count(variables, "variable", "variables"))
    return [line] + notes


def _left_out_lines(report):
    gaps = ((report.get("orca") or {}).get("left_out")) or []
    if not gaps:
        return []
    return left_out_lines([(None, gap) for gap in gaps]) + [LEFT_OUT_END]


def _section(key, title, lines):
    return {"key": key, "title": title, "lines": list(lines), "rows": []} if lines else None


def orca_view(file_name, report, ticked=(), rollback=NO_ROLLBACK):
    """Plain data for the result dialog: `title`, `sections` (`check`, `result`, `variables`, `left_out`, `next`)
    `message`, the same text for a message box, `summary` (a short text for it), `rolled_back` and `undo_unavailable`
    (as in `result_rows.result_view`). A section without content is absent."""
    orca = report.get("orca") or {}
    parameters = [parameter_line(p) for p in orca.get("parameters") or []]
    check = check_lines(report.get("health"), rollback)
    result = _result_lines(file_name, report)
    sections = [
        _section("check", "Check your design", check),
        _section("result", "Result", result),
        _section("variables", "Variables", parameters + _formula_lines(orca, set(ticked))),
        _section("left_out", "Left out", _left_out_lines(report)),
        _section("next", "Next in OrcaSlicer", NEXT_LINES + [NOT_USED_LINE]),
    ]
    sections = [s for s in sections if s]
    summary = short_message(result[0], len((orca.get("left_out")) or []), check)
    return {"title": TITLE, "sections": sections, "message": view_message(sections), "summary": summary,
            "rolled_back": rollback.abort, "undo_unavailable": rollback.undo_unavailable}


def preview(capture, up_axis="z"):
    """The warning under the body picker of the Export for Orca dialog (the dict of `stop_warning.summarize`: `lines`,
    `tooltip`, `left_out`, `stops` and the rest), or None when the picked body is not read or nothing is left out. One
    translation of the capture the dialog already read, with no sizes ticked."""
    if not isinstance(capture, dict):
        return None
    try:
        result = translate_for_orca(capture, capture.get("up_axis") or up_axis)
    except Exception:
        return None
    found = left_out_preview.find_orca(result)
    lines = left_out_preview.lines(found, LEFT_OUT_HEADING, closing=False)
    if not lines:
        return None
    tooltip = "\n".join(left_out_preview.step_text(step, whole=True) for step in found.steps)
    return {"stops": False, "index": None, "label": "", "title": "", "reason": "", "hint": "", "lines": lines,
            "tooltip": tooltip, "noted": [], "left_out": found.steps, "more_may_show": False}
