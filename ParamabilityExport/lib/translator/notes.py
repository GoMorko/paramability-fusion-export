"""Plain sentences for the package notes. Each is at most 200 characters, with no dashes."""
from .words import type_words

MAX_NOTE = 200
MAX_NAME = 60
_DASHES = {chr(0x2014): "-", chr(0x2013): "-"}


def _plain(text):
    for dash, replacement in _DASHES.items():
        text = text.replace(dash, replacement)
    return " ".join(text.split())


def _cut(text, limit):
    text = _plain(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def recipe_note(step_count):
    return "%d %s copied from Fusion." % (step_count, "step" if step_count == 1 else "steps")


def step_label(name, type_name):
    """'Emboss1 (emboss)', or whichever of the two is known, or an empty string."""
    name = _cut(str(name or ""), MAX_NAME)
    words = type_words(type_name) if type_name else ""
    return "%s (%s)" % (name, words) if name and words else (name or words)


def step_only_note(refusal):
    """Note for a part that could not be copied. `refusal` is the translator's {index, name, type, reason}; a refusal
    that carries its own `note` is written as it is."""
    if refusal.get("note"):
        return _cut(refusal["note"], MAX_NOTE)
    reason = _plain(str(refusal.get("reason") or "").strip())
    label = step_label(refusal.get("name"), refusal.get("type"))
    if label:
        text = "Added as a fixed shape: %s could not be copied. %s" % (label, reason)
    else:
        text = "Added as a fixed shape: the part could not be copied. %s" % reason
    return _cut(text, MAX_NOTE)


def from_other_component_note(label):
    return ("Added as a fixed shape: %s changes this part from another component. "
            "Steps across components are not copied yet." % label)


def made_elsewhere_note():
    return "Added as a fixed shape: this body was made in another component and moved here later."


def reaches_component_note(label):
    return "Added as a fixed shape: %s reaches into another component, which is not copied yet." % label


def linked_part_note():
    return "This part comes from a linked design. Open that design in Fusion and export the part there."


def place_unreadable_note():
    return "Added as a fixed shape: the place of this part in the assembly could not be read."


def used_several_times_note(uses):
    return "Fusion uses this part %d times; the file holds the one you picked." % uses


def reader_failure_note():
    return "Added as a fixed shape: the steps could not be read."


def translate_failure_note():
    return "Added as a fixed shape: the steps could not be copied."
