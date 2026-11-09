"""Plain texts about the timeline step that stops the copy. Pure: no Fusion imports.

The dialog shows them as soon as a body is picked, the message after the export repeats the same first line, and
the Fusion status line uses the short form. All of them name the step the same way: "Extrude9 (extrude)".
"""
from ..package.text import clip
from ..translator import CaptureError
from ..translator.notes import step_label
from .messages import recipe_saved_message
from .recipe_export import translate_capture

MAX_SHORT_REASON = 110
MAX_LISTED_NOTES = 3
UNREAD = "The steps could not be read."
UNCOPIED = "The steps could not be copied."


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


def _stop_fields(refusal, has_parameters):
    label = step_label(refusal.get("name"), refusal.get("type"))
    reason = " ".join(str(refusal.get("reason") or "").split())
    title = _title(label, reason)
    lines = [title]
    if reason and reason != title:
        lines.append(clip(reason, MAX_SHORT_REASON))
    lines.append(fixed_shape_sentence(has_parameters))
    return {"stops": True, "index": _step_index(refusal), "label": label, "title": title, "reason": reason,
            "lines": lines}


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
    sizes. Keys: stops, index (timeline position of the stopping step, or None), label, title, reason, lines (what the
    dialog shows), tooltip (the full reason and the notes), noted (labels of steps copied with a note).
    """
    if capture is None:
        return None
    noted, notes = [], []
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
                summary = _stop_fields(result.refusal or {"reason": UNCOPIED}, has_parameters)
            else:
                summary = {"stops": False, "index": None, "label": "", "title": "", "reason": "", "lines": []}
    line = _noted_line(noted)
    if line:
        summary["lines"].append(line)
    summary["noted"] = noted
    summary["tooltip"] = "\n".join(t for t in [summary["reason"], " ".join(notes)] if t)
    return summary if summary["lines"] else None


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
