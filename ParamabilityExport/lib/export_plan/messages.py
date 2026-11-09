"""Plain sentences about sizes for the package notes and the message after the export. No dashes."""
from ..package.text import clip

MAX_NOTE = 200
MAX_LISTED_FIXED = 5


def _count(n, one, many):
    return "%d %s" % (n, one if n == 1 else many)


def sizes_note(count):
    return "%s ready to put on the form." % _count(count, "size is", "sizes are").capitalize()


def fixed_note(names):
    """One note naming the parameters that stay fixed numbers, cut to the note limit."""
    text = "%s fixed: %s." % (_count(len(names), "number stays", "numbers stay"), ", ".join(names))
    return clip(text, MAX_NOTE)


def loose_note(names):
    """One note naming the sizes that stay free but may not follow every step, cut to the note limit."""
    text = "%s may give unexpected results: %s." % (_count(len(names), "size", "sizes"), ", ".join(names))
    return clip(text, MAX_NOTE)


def dropped_note(names):
    """One note naming ticked parameters that no copied step uses, so they are not sizes. Cut to the note limit."""
    text = "Not used by any copied step, so not sizes: %s." % ", ".join(names)
    return clip(text, MAX_NOTE)


def recipe_saved_message(manifest, file_name):
    """What the person reads after the file is written: the notes, why each fixed number stays fixed, then why each
    loose size may give unexpected results."""
    notes = " ".join(manifest.get("notes") or [])
    fixed = manifest.get("fixed") or []
    if manifest.get("kind") == "recipe":
        text = "Saved %s. %s" % (file_name, notes)
    else:
        text = "Saved %s.\n\n%s" % (file_name, notes)
    for entries in (fixed, manifest.get("loose") or []):
        if entries:
            text += "\n\n" + "\n".join("- " + line for line in listed_lines(entries))
    return text


def listed_lines(entries, other_names=None):
    """"name: reason" of the first entries, then one line that counts the rest. A reason that already starts with the
    name, or with its other name in `other_names` (a recipe name to its Fusion name), is shown as it is."""
    other_names = other_names or {}
    lines = []
    for f in entries[:MAX_LISTED_FIXED]:
        name, reason = f["name"], f["reason"]
        lines.append(reason if reason.startswith((name, other_names.get(name, name))) else "%s: %s" % (name, reason))
    if len(entries) > MAX_LISTED_FIXED:
        lines.append("and %d more (see report.json)." % (len(entries) - MAX_LISTED_FIXED))
    return lines
