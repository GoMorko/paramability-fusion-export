"""Names of the parts of a several-body export, and the reasons that say which part they are about. Pure."""
from ..package.manifest import MAX_FIXED_REASON, MAX_PART_NAME
from ..package.text import clip, plain

DEFAULT_PART = "Body"


def unique_names(names):
    """`names` made fit for the manifest: one line, at most `MAX_PART_NAME` characters, not empty, and different from
    each other ignoring case (a repeat gets " 2", " 3" and so on)."""
    out, seen = [], set()
    for raw in names:
        base = plain(raw)[:MAX_PART_NAME].strip() or DEFAULT_PART
        name, number = base, 1
        while name.lower() in seen:
            number += 1
            suffix = " %d" % number
            name = base[:MAX_PART_NAME - len(suffix)].rstrip() + suffix
        seen.add(name.lower())
        out.append(name)
    return out


MAX_NAMED = 3


def parts_label(parts):
    """The names of the parts a reason is about, for the front of the reason: all of them up to `MAX_NAMED`, then a
    count of the rest. `parts` may also be a single name."""
    parts = [parts] if isinstance(parts, str) else list(parts)
    if len(parts) <= MAX_NAMED:
        return ", ".join(parts)
    return "%s and %d more" % (", ".join(parts[:MAX_NAMED]), len(parts) - MAX_NAMED)


def tagged(parts, reason):
    """`reason` with the part, or parts, it is about in front, cut to the manifest limit."""
    return clip("%s: %s" % (parts_label(parts), reason), MAX_FIXED_REASON)
