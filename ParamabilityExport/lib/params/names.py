"""Fusion parameter names to recipe size names.

A size name must match `^[A-Za-z_][A-Za-z0-9_]*$`, have at most 64 characters and not be one of the formula
keywords. Fusion names may hold other characters (for example `$`), so those are replaced.
"""
import re

NAME_MAX = 64
RESERVED = frozenset({"if", "elseif", "else"})
_VALID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OTHER = re.compile(r"[^A-Za-z0-9_]")


def is_valid(name):
    return bool(_VALID.match(name)) and len(name) <= NAME_MAX and name not in RESERVED


def sanitize(name):
    """A valid name made from any text: other characters become `_`, a leading digit gets `p_`, cut to 64."""
    text = _OTHER.sub("_", name or "")
    if not text or text[0].isdigit():
        text = "p_" + text
    text = text[:NAME_MAX]
    if text in RESERVED:
        text += "_"
    return text


def _with_suffix(base, n):
    suffix = f"_{n}"
    return base[:NAME_MAX - len(suffix)] + suffix


def assign(names):
    """Map each distinct Fusion name to a unique recipe name.

    Names that are already valid keep their spelling, so a renamed name never takes one away from them. Clashes get
    `_2`, `_3`. Names differing only by case stay different, as in the app grammar.
    """
    ordered = list(dict.fromkeys(names))
    result = {}
    taken = set()
    for name in ordered:
        if is_valid(name):
            result[name] = name
            taken.add(name)
    for name in ordered:
        if name in result:
            continue
        base = sanitize(name)
        candidate = base
        n = 2
        while candidate in taken:
            candidate = _with_suffix(base, n)
            n += 1
        result[name] = candidate
        taken.add(candidate)
    return result
