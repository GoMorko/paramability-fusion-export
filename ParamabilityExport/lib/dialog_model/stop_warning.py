"""Plain texts about the timeline step that stops the copy. Pure: no Fusion imports.

The dialog shows them as soon as a body is picked, the message after the export repeats the same first line, and
the Fusion status line uses the short form. All of them name the step the same way: "Extrude9 (extrude)".
"""
from ..package.text import clip
from ..translator import CaptureError
from ..translator.notes import step_label
from ..export_plan.messages import recipe_saved_message
from ..export_plan.recipe_export import translate_capture

MAX_SHORT_REASON = 110
MAX_LISTED_NOTES = 3
MAX_LISTED_LEFT_OUT = 3
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


def _own_left_out(verdicts, kept, found):
    """Fill `found` with `(index, label, reason)` of the steps left out for their own reason that the recipe keeps
    as gaps, at any depth. A step that is a gap only because it picks faces of another gap waits for the face read."""
    for verdict in verdicts:
        if verdict.get("verdict") == "leftOut" and verdict.get("cause") == "own" and verdict.get("gap") in kept:
            label = step_label(verdict.get("name"), verdict.get("type")) or "A step"
            found.setdefault(verdict.get("index"), (label, " ".join(str(verdict.get("note") or "").split())))
        _own_left_out(verdict.get("tool_steps") or [], kept, found)


def _left_out(result):
    """`[(label, reason)]` in timeline order of the steps the walk leaves out for their own reason."""
    found = {}
    _own_left_out(result.items or [], {gap.get("id") for gap in result.gaps or []}, found)
    return [found[index] for index in sorted(found, key=lambda i: i if isinstance(i, int) else -1)]


def _left_out_lines(entries, heading):
    """The heading, a line per step (at most MAX_LISTED_LEFT_OUT), then how many more. Empty without steps."""
    if not entries:
        return []
    lines = [heading]
    for label, reason in entries[:MAX_LISTED_LEFT_OUT]:
        lines.append(clip("%s: %s" % (label, reason) if reason else label, MAX_SHORT_REASON))
    more = len(entries) - MAX_LISTED_LEFT_OUT
    if more > 0:
        lines.append("and %d more." % more)
    return lines


def summarize(capture, has_parameters=True):
    """What to warn about for a picked body, or None when the body is not read (nothing picked).

    `capture` is the reader's capture dict, or the exception that stopped the read. The translator runs once, with no
    sizes. Keys: stops, index (timeline position of the stopping step, or None), label, title, reason, lines (what the
    dialog shows), tooltip (the full reason and the notes), noted (labels of steps copied with a note), left_out
    (`(label, reason)` of the steps the copy will likely leave out; empty when the copy stops).

    The left out steps are those the walk decides without Fusion's help. A later round or shell that picks faces of a
    left out step is decided by the face read at export time, so it is not listed.
    """
    if capture is None:
        return None
    noted, notes, left_out = [], [], []
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
                left_out = _left_out(result)
                summary["lines"] += _left_out_lines(left_out, "Likely left out of the copy:")
    line = _noted_line(noted)
    if line:
        summary["lines"].append(line)
    summary["noted"] = noted
    summary["left_out"] = left_out
    summary["tooltip"] = "\n".join(t for t in [summary["reason"], " ".join(notes)]
                                   + ["%s: %s" % entry for entry in left_out if entry[1]] if t)
    return summary if summary["lines"] else None


def summarize_many(named, has_parameters=True):
    """`summarize` for several picked bodies: `named` is [(body name, capture or the exception that stopped the read)].

    Each body that stops the copy or has a noted step gets its lines, led by its name; one closing line says that the
    stopped bodies are saved as fixed shapes. The steps a body will likely leave out are listed under its name. The keys
    are those of `summarize`; `index` is the first stopping step and `tooltip` joins the bodies' tooltips. None when
    there is nothing to warn about.
    """
    lines, tooltips, noted, index = [], [], [], None
    stopped = False
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
        lines += _left_out_lines(summary["left_out"], "%s: likely left out of the copy:" % name)
        line = _noted_line(summary["noted"])
        if line:
            lines.append(line if summary["stops"] else "%s: %s" % (name, line))
        noted.extend(summary["noted"])
        if summary["tooltip"]:
            tooltips.append("%s: %s" % (name, summary["tooltip"]))
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
