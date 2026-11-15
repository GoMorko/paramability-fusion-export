"""Plain texts about the timeline step that stops the copy. Pure: no Fusion imports.

The dialog shows them as soon as a body is picked, the message after the export repeats the same first line, and
the Fusion status line uses the short form. All of them name the step the same way: "Extrude9 (extrude)".
"""
from ..package.text import clip
from ..translator import CaptureError
from ..translator.notes import step_label
from ..export_plan.messages import recipe_saved_message
from ..export_plan.recipe_export import refusal_hint, translate_capture
from . import left_out_preview
from .left_out_preview import MAX_SHORT_REASON

MAX_LISTED_NOTES = 3
UNREAD = "The steps could not be read."
UNCOPIED = "The steps could not be copied."
LEFT_OUT_HEADING = "Likely left out of the copy:"


def _step_index(refusal):
    index = refusal.get("index")
    return index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else None


def fixed_shape_sentence(has_parameters=True):
    text = "The part will be saved as a fixed shape"
    return text + "; your parameters still come along as variables." if has_parameters else text + "."


def _title(label, reason, verb="stops"):
    """The first line: which step stops the copy, or a plain sentence when no step is to blame."""
    if label:
        return "Copy %s at %s." % (verb, label)
    return reason if reason in (UNREAD, UNCOPIED) else "The part cannot be copied."


def _stop_fields(refusal, has_parameters, hint=None):
    """The summary of a copy that stops. `hint` is what to change in Fusion so the stopping step copies, if known."""
    label = step_label(refusal.get("name"), refusal.get("type"))
    reason = " ".join(str(refusal.get("reason") or "").split())
    title = _title(label, reason)
    lines = [title]
    if reason and reason != title:
        lines.append(clip(reason, MAX_SHORT_REASON))
    if hint:
        lines.append("Tip: %s" % hint)
    lines.append(fixed_shape_sentence(has_parameters))
    return {"stops": True, "index": _step_index(refusal), "label": label, "title": title, "reason": reason,
            "hint": hint or "", "lines": lines}


def _noted_steps(items):
    """(labels, notes) of the steps that were copied with a note."""
    labels, notes = [], []
    for item in items or []:
        if item.get("verdict") != "translatedWithNote":
            continue
        label = step_label(item.get("name"), item.get("type")) or "A step"
        if label not in labels:
            labels.append(label)
        if item.get("note"):
            notes.append(item["note"])
    return labels, notes


def _noted_line(labels):
    if not labels:
        return ""
    shown = ", ".join(labels[:MAX_LISTED_NOTES])
    more = len(labels) - MAX_LISTED_NOTES
    return "Copied with a note: %s%s." % (shown, " and %d more" % more if more > 0 else "")


def summarize(capture, has_parameters=True):
    """What to warn about for a picked body, or None when the body is not read (nothing picked).

    `capture` is the reader's capture dict, or the exception that stopped the read. The translator runs once, with no
    sizes. Keys: stops, index (timeline position of the stopping step, or None), label, title, reason, hint (what to
    change in Fusion so the stopping step copies, "" when unknown), lines (what the dialog shows), tooltip (the full
    reason, the hint and the notes), noted (labels of steps copied with a note), left_out (the steps the copy will
    likely leave out, each `{index, name, reason, hint}`; empty when the copy stops) and more_may_show (True when the
    export may leave out more steps than listed).

    The left out steps are those the walk decides without Fusion's help (`left_out_preview`).
    """
    if capture is None:
        return None
    noted, notes, found = [], [], left_out_preview.Found()
    if not isinstance(capture, dict):
        summary = _stop_fields({"reason": UNREAD}, has_parameters)
    else:
        try:
            result = translate_capture(capture, capture.get("up_axis") or "z")
        except CaptureError:
            result = None
            summary = _stop_fields({"reason": UNREAD}, has_parameters)
        except Exception:
            result = None
            summary = _stop_fields({"reason": UNCOPIED}, has_parameters)
        if result is not None:
            noted, notes = _noted_steps(result.items)
            if result.refusal is not None or result.recipe is None:
                summary = _stop_fields(result.refusal or {"reason": UNCOPIED}, has_parameters,
                                       refusal_hint(result))
            else:
                summary = {"stops": False, "index": None, "label": "", "title": "", "reason": "", "hint": "",
                           "lines": []}
                found = left_out_preview.find(result)
                summary["lines"] += left_out_preview.lines(found, LEFT_OUT_HEADING)
    line = _noted_line(noted)
    if line:
        summary["lines"].append(line)
    summary["noted"] = noted
    summary["left_out"] = found.steps
    summary["more_may_show"] = bool(found.steps) and found.waits_for_faces
    tip = "Tip: %s" % summary["hint"] if summary["hint"] else ""
    summary["tooltip"] = "\n".join(t for t in [summary["reason"], tip, " ".join(notes)]
                                   + [left_out_preview.step_text(step, whole=True) for step in found.steps] if t)
    return summary if summary["lines"] else None


def summarize_many(named, has_parameters=True):
    """`summarize` for several picked bodies: `named` is [(body name, capture or the exception that stopped the read)].

    Each body that stops the copy or has a noted step gets its lines, led by its name; one closing line says that the
    stopped bodies are saved as fixed shapes. The steps a body will likely leave out are listed under its name. The keys
    are those of `summarize`; `index` is the first stopping step and `tooltip` joins the bodies' tooltips. None when
    there is nothing to warn about.
    """
    lines, tooltips, noted, index = [], [], [], None
    stopped = more_may_show = False
    for name, capture in named:
        summary = summarize(capture, has_parameters)
        if summary is None:
            continue
        if summary["stops"]:
            stopped = True
            index = summary["index"] if index is None else index
            lines.append("%s: %s" % (name, summary["title"]))
            if summary["reason"] and summary["reason"] != summary["title"]:
                lines.append(clip(summary["reason"], MAX_SHORT_REASON))
            if summary["hint"]:
                lines.append("Tip: %s" % summary["hint"])
        lines += left_out_preview.lines(
            left_out_preview.Found(summary["left_out"], summary["more_may_show"]),
            "%s: likely left out of the copy:" % name, closing=False)
        more_may_show = more_may_show or summary["more_may_show"]
        line = _noted_line(summary["noted"])
        if line:
            lines.append(line if summary["stops"] else "%s: %s" % (name, line))
        noted.extend(summary["noted"])
        if summary["tooltip"]:
            tooltips.append("%s: %s" % (name, summary["tooltip"]))
    if more_may_show:
        lines.append(left_out_preview.MORE_MAY_SHOW)
    if stopped:
        lines.append("These parts will be saved as fixed shapes; the other parts stay editable."
                     + (" Your parameters still come along as variables." if has_parameters else ""))
    if not lines:
        return None
    return {"stops": stopped, "index": index, "label": "", "title": lines[0], "reason": "", "lines": lines,
            "tooltip": "\n".join(tooltips), "noted": noted}


def saved_message(manifest, report, file_name):
    """The message box text after the export. A part saved as a fixed shape starts with the stopping step."""
    refusal = report.get("refusal")
    if not refusal:
        return recipe_saved_message(manifest, file_name)
    fields = _stop_fields(refusal, False)
    title = _title(fields["label"], fields["reason"], "stopped")
    shape = "The part is saved as a fixed shape."
    if manifest.get("parameters"):
        shape += " Your parameters still come along as variables."
    rest = " ".join(t for t in [fields["reason"], shape] if t)
    return "Saved %s. %s\n\n%s" % (file_name, title, rest)


def status_text(report):
    """The short line for Fusion's status area when the part was saved as a fixed shape, else ''."""
    if report.get("outcome") == "recipe":
        return ""
    refusal = report.get("refusal")
    if not refusal:
        return "Paramability: saved as a fixed shape. The part could not be copied."
    fields = _stop_fields(refusal, False)
    return "Paramability: saved as a fixed shape. %s" % _title(fields["label"], fields["reason"], "stopped")
