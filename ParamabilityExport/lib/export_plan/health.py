"""How the design came out of an export, and what to tell the person about it. Pure: no Fusion imports.

An export changes parameters many times and puts them back. After that the design must be as it was, and the sketch
measuring must have worked. `make_health` records what is known, `health_lines` says in plain words what is wrong and
what to do, and `measuring_doubtful` tells when the recipe rests on measurements that cannot be trusted.
"""
from ..package.text import clip

# Largest gap in mm between the sketches at the start and after the parameters were put back.
RESTORE_TOLERANCE_MM = 1e-4

MEASURED, NOT_NEEDED, FAILED = "measured", "not needed", "failed"
MAX_LISTED = 5
MAX_NOTE = 200
MAX_LINE = 400

UNDO_ADVICE = (
    "Use Undo in Fusion until the design looks as it did before the export, or reopen the design from its last "
    "save. Then export again.")


def make_health(unrestored=(), gap_mm=None, probe=NOT_NEEDED, probe_error="", unchecked=()):
    """The record kept in `report.json` under `health`.

    unrestored: Fusion names of the parameters that could not be put back.
    gap_mm: how far the sketches are from their start after the restore, None when that was not measured.
    probe: MEASURED, NOT_NEEDED (no sketch to follow) or FAILED (sketches exist but could not be measured).
    unchecked: why the restore could not be checked, one text per sketch ("Sketch3 reads another outline").
    """
    measured = probe == MEASURED
    out = {
        "unrestored": list(unrestored),
        "sketch_gap_mm": gap_mm,
        "sketch_drift": gap_mm is not None and gap_mm > RESTORE_TOLERANCE_MM,
        "restore_unverified": measured and gap_mm is None,
        "probe": probe,
        "probe_error": probe_error[:200],
    }
    if measured and gap_mm is None and unchecked:
        out["unchecked"] = list(unchecked)[:MAX_LISTED]
    return out


def design_changed(health):
    """True when the design may differ from before the export: a parameter not put back, or sketches that moved."""
    return bool(health and (health.get("unrestored") or health.get("sketch_drift")))


def measuring_doubtful(health):
    """True when sketch sizes were measured on a design that did not come back to its start."""
    return design_changed(health)


def _names(names):
    shown = ", ".join(names[:MAX_LISTED])
    return shown + (" and %d more" % (len(names) - MAX_LISTED) if len(names) > MAX_LISTED else "")


def health_lines(health):
    """Plain sentences for the result window, most important first. Empty when all is well."""
    if not health:
        return []
    lines = []
    if health.get("unrestored"):
        lines.append(
            "These parameters could not be set back to their values: %s. Your design is changed. %s"
            % (_names(health["unrestored"]), UNDO_ADVICE))
    if health.get("sketch_drift"):
        lines.append(
            "The sketches did not come back to their first shape after the tries (largest gap %.4g mm). "
            "Your design may be changed, and sizes that move a sketch may be off. %s"
            % (health["sketch_gap_mm"], UNDO_ADVICE))
    elif health.get("restore_unverified") and health.get("unchecked"):
        lines.append(clip("Could not check that the sketches came back to their first shape: %s. Please look at %s "
                          "in Fusion." % ("; ".join(health["unchecked"]),
                                          "it" if len(health["unchecked"]) == 1 else "them"), MAX_LINE))
    elif health.get("restore_unverified"):
        lines.append("Could not check that the sketches came back to their first shape. Please look at them.")
    if health.get("probe") == FAILED:
        lines.append(
            "The sketches could not be measured, so sizes that move a sketch may give unexpected results.")
    return lines


def measuring_note(health):
    """The package note for a recipe built on doubtful sketch measurements, else ''."""
    if not measuring_doubtful(health):
        return ""
    return clip("Sketch sizes may be off: the design did not come back to its start while they were measured.",
                MAX_NOTE)


def with_lines(text, health):
    """`text` with the health sentences added below it, for a message box."""
    lines = health_lines(health)
    return text + "".join("\n\n" + line for line in lines)
