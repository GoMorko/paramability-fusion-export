"""Plain sentences for the package notes. Each is at most 200 characters, with no dashes."""
from .translate import type_words

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


def step_only_note(refusal):
    """Note for a part that could not be copied. `refusal` is the translator's {index, name, type, reason}."""
    reason = _plain(str(refusal.get("reason") or "").strip())
    name = _cut(str(refusal.get("name") or ""), MAX_NAME)
    type_name = refusal.get("type") or ""
    if name or type_name:
        words = type_words(type_name) if type_name else ""
        label = "%s (%s)" % (name, words) if name and words else (name or words)
        text = "Added as a fixed shape: %s could not be copied. %s" % (label, reason)
    else:
        text = "Added as a fixed shape: the part could not be copied. %s" % reason
    return _cut(text, MAX_NOTE)


def reader_failure_note():
    return "Added as a fixed shape: the steps could not be read."


def translate_failure_note():
    return "Added as a fixed shape: the steps could not be copied."
