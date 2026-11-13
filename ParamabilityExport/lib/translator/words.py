"""Feature type names in plain words."""
from ..capture_model.step_kinds import step_type


def type_words(type_name):
    """The words of the step kind table, else the type name split into words: 'SweepFeature' to 'sweep',
    'RectangularPatternFeature' to 'rectangular pattern'."""
    spec = step_type(type_name)
    if spec is not None:
        return spec.words
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
