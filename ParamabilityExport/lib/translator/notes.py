"""Plain sentences for the package notes. Each is at most 200 characters, with no dashes."""
from ..package.text import clip, plain
from .words import type_words

MAX_NOTE = 200
MAX_NAME = 60


def fixed_reason(name, why):
    """Why a size stays a fixed number: "<name> stays fixed: <why>."."""
    return clip("%s stays fixed: %s." % (name, why), MAX_NOTE)


class Past(str):
    """A reason that applies only beyond some values of the size: `where` is the words for them ("past 2.05")."""

    def __new__(cls, where, text):
        out = super().__new__(cls, text)
        out.where = where
        return out


def loose_reason(name, why):
    """Why a size that stays free may not follow every step: "<name> may give unexpected results: <why>."., or
    "<name> may give unexpected results past 2.05: <why>." when the reason is a `Past`."""
    where = getattr(why, "where", None)
    return clip("%s may give unexpected results%s: %s." % (name, " " + where if where else "", why), MAX_NOTE)


def recipe_note(step_count):
    return "%d %s copied from Fusion." % (step_count, "step" if step_count == 1 else "steps")


def step_label(name, type_name):
    """'Emboss1 (emboss)', or whichever of the two is known, or an empty string."""
    name = clip(str(name or ""), MAX_NAME)
    words = type_words(type_name) if type_name else ""
    return "%s (%s)" % (name, words) if name and words else (name or words)


def step_only_note(refusal):
    """Note for a part that could not be copied. `refusal` is the translator's {index, name, type, reason}; a refusal
    that carries its own `note` is written as it is."""
    if refusal.get("note"):
        return clip(refusal["note"], MAX_NOTE)
    reason = plain(str(refusal.get("reason") or "").strip())
    label = step_label(refusal.get("name"), refusal.get("type"))
    if label:
        text = "Added as a fixed shape: %s could not be copied. %s" % (label, reason)
    else:
        text = "Added as a fixed shape: the part could not be copied. %s" % reason
    return clip(text, MAX_NOTE)


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


# Why a size cannot follow a sketch value, by the probe's cause. Each ends without a full stop: the size table adds
# "<name> stays fixed: " in front.
_STUCK = {
    "curve": "it moves %s along a curve, which cannot be copied yet",
    "shape": "%s makes a different outline at other values",
    "turns": "it turns the plane of %s",
    "unread": "%s could not be read at other values",
    "untried": "it changes %s and could not be tried at other values",
    "apart": "it moves the outlines of %s apart from each other",
}


def stuck_reason(cause, sketch):
    """The reason a sketch value of `sketch` (a name, or empty) keeps its sizes fixed."""
    return _STUCK.get(cause, _STUCK["unread"]) % (clip(sketch, MAX_NAME) if sketch else "a sketch")


def shrinks_reason(sketch):
    return "an outline in %s would shrink to nothing" % (clip(sketch, MAX_NAME) if sketch else "a sketch")


def bends_reason(step, sketch):
    return "%s picks a point on a curved outline of %s that changes shape" % (
        clip(step or "a step", MAX_NAME), clip(sketch, MAX_NAME) if sketch else "a sketch")
