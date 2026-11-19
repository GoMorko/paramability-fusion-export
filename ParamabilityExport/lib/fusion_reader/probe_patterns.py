"""The copies of a pattern at one probe state (agent-docs/capture-format.md, "Probe states").

A pattern that spreads copies to both sides of the original and whose count follows sizes is read again at each state:
how many copies Fusion makes and where, as the capture holds them (`elements`). The translator compares the places at
the counts the tries reached with the rule it writes (`translator/repeat/symmetric.py`). The feature is read through its
timeline item with the marker where the tries leave it (after the pattern). Nothing raises: a pattern that cannot be
read is named in the second result.
"""
from . import read_geometry as geo
from .read_repeat import pattern_elements

NOT_READ = "The copies of the pattern could not be read."
_COUNTS = {"rectangular": ("quantityOne", "quantityTwo"), "circular": ("quantity",)}


def _feature(design, index):
    timeline = geo.safe(lambda: design.timeline, None)
    return geo.safe(lambda: timeline.item(index).entity, None)


def _counts(feature, kind):
    return [geo.safe(lambda: int(round(geo.value_of(getattr(feature, name)))), None) for name in _COUNTS[kind]]


def read_patterns(design, wanted):
    """`({ key: { count: [n], elements } }, { key: reason })` for the patterns in `wanted`, `{ key: { index, kind } }`
    with the timeline index of the item and `kind` `rectangular` or `circular`. `count` has one number per direction
    of a rectangular pattern."""
    found, missed = {}, {}
    for key, ask in (wanted or {}).items():
        feature = _feature(design, ask.get("index"))
        kind = ask.get("kind")
        if feature is None or kind not in _COUNTS:
            missed[key] = NOT_READ
            continue
        counts = _counts(feature, kind)
        elements = geo.safe(lambda: pattern_elements(feature, faces=False), None)
        if elements is None or None in counts:
            missed[key] = NOT_READ
            continue
        found[key] = {"count": counts, "elements": elements}
    return found, missed
