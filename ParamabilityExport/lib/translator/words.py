"""Feature type names in plain words."""


def type_words(type_name):
    """'EmbossFeature' to 'emboss', 'RectangularPatternFeature' to 'rectangular pattern'."""
    base = type_name[: -len("Feature")] if type_name.endswith("Feature") and type_name != "Feature" else type_name
    words = []
    for ch in base:
        if ch.isupper() and words and not words[-1][-1].isupper():
            words.append(ch)
        elif words:
            words[-1] += ch
        else:
            words.append(ch)
    return " ".join(w.lower() for w in words) or type_name
