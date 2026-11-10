"""Plain sentences for the package notes. Each is at most 200 characters, with no dashes."""
from ..package.text import clip, plain
from .words import type_words

MAX_NOTE = 200
MAX_NAME = 60


def _ends(why):
    """The reason without a closing full stop, so the template's own stop does not double it."""
    text = str(why).rstrip()
    return text[:-1] if text.endswith(".") and not text.endswith("...") else text


def fixed_reason(name, why):
    """Why a size stays a fixed number: "<name> stays fixed: <why>."."""
    return clip("%s stays fixed: %s." % (name, _ends(why)), MAX_NOTE)


class Past(str):
    """A reason that applies only beyond some values of the size: `where` is the words for them ("past 2.05")."""

    def __new__(cls, where, text):
        out = super().__new__(cls, text)
        out.where = where
        return out


def number_text(value):
    """A size value as the reasons write it: at most 6 decimals, no trailing zeros."""
    return ("%.6f" % value).rstrip("0").rstrip(".")


def _nearest_failures(span):
    """The failed value nearest to the value now on each side, lowest first, as `(value, step)`."""
    now = span["low"]
    out = []
    for side in (-1, 1):
        found = [f for f in span.get("failed") or () if (f[0] - now) * side > 0]
        if found:
            out.append(min(found, key=lambda f: abs(f[0] - now)))
    return out


def not_built_why(span):
    """Why a size was not measured: Fusion rebuilt the design at none of the values tried. Names the value nearest to
    the value now on each side and the step that failed there."""
    tried = ["%s%s" % (number_text(v), " (%s)" % clip(step, MAX_NAME) if step else "")
             for v, step in _nearest_failures(span)]
    return "the design does not rebuild in Fusion at %s, the nearest values tried, so it could not be measured" % (
        " or ".join(tried) or "the values tried")


def narrow_span(span, low, high):
    """True when a size was measured over less than its range `low` to `high`, and at more than its value now."""
    return bool(span) and span["high"] - span["low"] > 1e-9 and (
        span["low"] > low + 1e-9 or span["high"] < high - 1e-9)


def span_words(span):
    return "between %s and %s" % (number_text(span["low"]), number_text(span["high"]))


def span_why(span, low, high):
    """A `Past` for a size measured over less than its range: "below 1.8", "past 3.6" or "outside 1.8 to 3.6"."""
    below, past = span["low"] > low + 1e-9, span["high"] < high - 1e-9
    a, b = number_text(span["low"]), number_text(span["high"])
    where = "outside %s to %s" % (a, b) if below and past else "below %s" % a if below else "past %s" % b
    return Past(where, "it was followed %s; beyond that it could not be tried" % span_words(span))


def with_span(why, span, low, high):
    """`why` with the measured span added, or the span reason alone when there is no `why`. A `why` that would grow
    past the note limit stays as it is."""
    if why is None:
        return span_why(span, low, high)
    text = "%s; it was followed %s, beyond that it could not be tried" % (_ends(why), span_words(span))
    if len(text) > MAX_NOTE - 80:
        return why
    return Past(why.where, text) if getattr(why, "where", None) else text


def loose_reason(name, why):
    """Why a size that stays free may not follow every step: "<name> may give unexpected results: <why>."., or
    "<name> may give unexpected results past 2.05: <why>." when the reason is a `Past`."""
    where = getattr(why, "where", None)
    return clip("%s may give unexpected results%s: %s." % (name, " " + where if where else "", _ends(why)), MAX_NOTE)


def dropped_reason(name, why):
    """Why a ticked size is not a size although a step reads it: "<name> is not a size: <why>."."""
    return clip("%s is not a size: %s." % (name, _ends(why)), MAX_NOTE)


def unused_reason(name):
    return clip("%s is not used by any copied step, so it is not a size." % name, MAX_NOTE)


def unmoved_reason(name):
    return clip("%s is not a size: changing it changes nothing in the copied steps." % name, MAX_NOTE)


def tried_unmoved_reason(name, span=None):
    where = " " + span_words(span) + "; beyond that it could not be tried" if span else ""
    return clip("%s is not a size: it was tried at other values, and it changes nothing in this part%s." % (
        name, where), MAX_NOTE)


# Why a size that moved the body in a try, but no sketch or reference the copy follows, cannot be followed.
BODY_MOVED_WHY = "it changes this part in a way the copy does not follow"


def unmoved_link_reason(name, component, span=None):
    where = " " + span_words(span) + "; beyond that it could not be tried" if span else ""
    return clip("%s is not a size: it changes %s, but nothing in this part moved with it%s." % (
        name, clip(component, MAX_NAME), where), MAX_NOTE)


def untried_link_reason(sketch, component):
    """Why a size that may reach a sketch through another component cannot follow: it was not tried."""
    return "it changes %s, which %s is drawn around, and could not be tried at other values" % (
        clip(component, MAX_NAME), clip(sketch, MAX_NAME))


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


def health_warning_note(label, message):
    """A step Fusion shows a warning on was copied as Fusion built it; the copy may not match what Fusion meant."""
    detail = _ends(plain(message or ""))
    return clip("Fusion shows a warning on %s%s. The copy follows what Fusion built, which may not be what was meant."
                % (label, ": " + detail if detail else ""), MAX_NOTE)


def split_face_note(label):
    return "%s only splits faces of the body, so it is not copied. Picks on those faces may not follow." % label


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
