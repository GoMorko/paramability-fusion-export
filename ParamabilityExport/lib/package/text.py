"""Short plain sentences for the package and the dialogs. Pure."""

_DASHES = {chr(0x2014): "-", chr(0x2013): "-"}


def plain(text):
    """`text` on one line, with long dashes written as plain ones."""
    text = str(text or "")
    for dash, replacement in _DASHES.items():
        text = text.replace(dash, replacement)
    return " ".join(text.split())


def clip(text, limit):
    """`plain(text)` cut to `limit` characters; a cut text ends in "..."."""
    text = plain(text)
    return text if len(text) <= limit else text[: limit - 3].rstrip(" ,;:.") + "..."
