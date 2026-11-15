"""The form label of a size: plain words made from what the designer wrote in Fusion.

A short comment on the parameter (its first sentence) is the label, since the designer wrote it for people. Without
a usable comment the label is the parameter name in words: `BaseCup_midExtrude_offset__mm` gives "Base cup mid
extrude offset". Sizes of one recipe never share a label. The Fusion name is kept elsewhere (the recipe size name and
the manifest `parameters` list), so the label is only text for the form.
"""
import re

from . import defaults

# A comment longer than this is a description, not a label.
COMMENT_LABEL_MAX = 48
# Unit words dropped from the end of a name; the form shows the unit itself.
_UNIT_WORDS = frozenset({"mm", "cm", "deg", "degrees", "rad", "unitless"})

_SENTENCE_END = re.compile(r"[.!?:;](?:\s|$)")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NOT_WORD = re.compile(r"[^A-Za-z0-9]+")


def comment_label(comment):
    """The first sentence of a comment when it is short enough to be a label, else ''. A trailing `[min..max]` is
    the range of the size and is not part of the text."""
    text, _ = defaults.split_comment(comment)
    text = " ".join(text.split("\n", 1)[0].split())
    found = _SENTENCE_END.search(text)
    if found:
        text = text[:found.start()]
    text = text.strip(" .,;:-")
    if not 0 < len(text) <= COMMENT_LABEL_MAX or not any(c.isalpha() for c in text):
        return ""
    return text[0].upper() + text[1:]


def name_words(name, unit=""):
    """A parameter name in plain words: split at underscores, symbols and camelCase, the unit word at the end
    dropped, the first word capitalised. Acronyms such as `ID` stay. A name written all in capitals is lowercased."""
    words = [w for w in _CAMEL.sub(" ", _NOT_WORD.sub(" ", name or "")).split() if w]
    own = (unit or "").lower()
    if len(words) > 1 and (words[-1].lower() in _UNIT_WORDS or (own and words[-1].lower() == own)):
        words.pop()
    if not any(c.islower() for c in "".join(words)):
        words = [w.lower() for w in words]
    text = " ".join(w if w.isupper() else w.lower() for w in words)
    if not text:
        return name or ""
    return text[0].upper() + text[1:]


def assign(items):
    """{Fusion name: label} for `items`, a list of `(name, comment, unit)` of the parameters that become sizes.

    The comment label is used when there is one. When two sizes end up with the same label, those whose label came
    from a comment fall back to their name in words, and sizes that still share a label get the Fusion name in
    brackets, so the form never shows two fields alike. Labels are cut to the label length before they are compared.
    """
    found = {}
    from_comment = set()
    for name, comment, unit in items:
        text = comment_label(comment)
        if text:
            from_comment.add(name)
        found[name] = _cut(text or name_words(name, unit))
    units = {name: unit for name, _, unit in items}
    for group in _repeats(found):
        for name in group:
            if name in from_comment:
                found[name] = _cut(name_words(name, units[name]))
    for group in _repeats(found):
        for name in group:
            found[name] = _with_name(found[name], name)
    for group in _repeats(found):  # names so long that the cut made them alike: number them
        for number, name in enumerate(group, start=1):
            found[name] = "%s %d" % (found[name][:defaults.LABEL_MAX - len(str(number)) - 1].rstrip(), number)
    return found


def _cut(text):
    return text[:defaults.LABEL_MAX].strip()


def _with_name(text, name):
    """`text (name)` within the label length: the text is cut to leave room for the name, so the name always shows."""
    suffix = " (%s)" % name
    room = defaults.LABEL_MAX - len(suffix)
    return text[:room].rstrip() + suffix if room > 0 else _cut(name)


def _repeats(found):
    """Groups of names (two or more) whose labels are the same, ignoring case."""
    by_text = {}
    for name, text in found.items():
        by_text.setdefault(text.lower(), []).append(name)
    return [group for group in by_text.values() if len(group) > 1]
