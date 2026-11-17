"""Comparing probe states: the body (`probe.state`), the numbers of a read and the states a try marked."""
from dataclasses import dataclass, field, replace

from ...geometry.tolerances import BODY_TOLERANCE_MM, END_BODY_BOX_MM, END_BODY_VOLUME_SHARE, FIT_TOLERANCE
from ...probe.state import body_changed, body_compared, box_numbers

__all__ = ["BODY_REQUEST", "BodyCheck", "body_changed", "body_compared", "body_difference", "box_numbers", "marked_states",
           "same_numbers"]

# A probe read of the target body alone: its box, volume and pieces (`fusion_reader.probe_state.read_state`).
BODY_REQUEST = {"sketches": [], "points": [], "lines": [], "params": [], "target": True}


def _numbers(node, out):
    if isinstance(node, dict):
        for key in sorted(node):
            _numbers(node[key], out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _numbers(value, out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.append(float(node))
    return out


def same_numbers(a, b):
    """True when two records hold the same numbers in the same places, within the fit tolerance."""
    x, y = _numbers(a, []), _numbers(b, [])
    return len(x) == len(y) and all(abs(p - q) <= FIT_TOLERANCE for p, q in zip(x, y))


def marked_states(states, changed):
    """The states after E0, each one whose number is in `changed` marked `changed` for `plan.nearer_rows`."""
    return [replace(state, changed=True) if at in changed else state for at, state in enumerate(states) if at]


def _volume(read):
    value = read.get("volume_mm3") if isinstance(read, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _pieces(read):
    pieces = read.get("pieces") if isinstance(read, dict) else None
    return pieces if isinstance(pieces, dict) else {}


def _other_boxes(read):
    """`(names, boxes)` of the other bodies of the component: their box numbers, and their names when the read names
    them all (else None). None when they were not read."""
    pieces = _pieces(read)
    others = pieces.get("others")
    if not isinstance(others, list):
        return None
    boxes = [box_numbers({"box": box}) or [] for box in others]
    names = pieces.get("names")
    return (names if isinstance(names, list) and len(names) == len(boxes) else None), boxes


@dataclass
class BodyCheck:
    """What differs of the body between two reads with the same values (`body_difference`), as plain texts.

    clear: differences no rebuild of the same shape gives (`END_BODY_BOX_MM`, `END_BODY_VOLUME_SHARE`, another number
      of solids, another set of other bodies).
    small: differences past the tight tolerances of a read (`BODY_TOLERANCE_MM`, the volume tolerance of
      `probe.state`) but under the clear ones; they count as a change only with another change of the design.
    """

    clear: list = field(default_factory=list)
    small: list = field(default_factory=list)

    @property
    def texts(self):
        return self.clear + self.small


def _level(gap, tight, clear):
    """"clear", "small" or None for a difference `gap` with the two tolerances."""
    return "clear" if gap > clear else "small" if gap > tight else None


def _box_gap(a, b):
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0) if len(a) == len(b) else float("inf")


def _others_level(before, now):
    """The level of the difference between the other bodies of two reads (`_other_boxes`): by name when both reads
    name them, else in the order of their boxes."""
    if before is None or now is None:
        return None
    (names_a, a), (names_b, b) = before, now
    if len(a) != len(b):
        return "clear"
    if names_a is not None and names_b is not None:
        if set(names_a) != set(names_b):
            return "clear"
        pairs = [(box, b[names_b.index(name)]) for name, box in zip(names_a, a)]
    else:
        pairs = list(zip(sorted(a), sorted(b)))
    gap = max((_box_gap(x, y) for x, y in pairs), default=0.0)
    return _level(gap, BODY_TOLERANCE_MM, END_BODY_BOX_MM)


def body_difference(before, now, others_before=None):
    """What differs between the body in two reads of the design with the same values (`BodyCheck`): its volume, its
    box, the number of its solids and the boxes of the other bodies of its component (`fusion_reader.probe_state`),
    those compared by name when both reads name them. `others_before` is the read whose other bodies are the
    reference, when it is not `before`. None when the two reads cannot be compared: a box or a volume is missing."""
    if not body_compared(before, now):
        return None
    out = BodyCheck()
    a, b = _volume(before), _volume(now)
    if body_changed({"volume_mm3": a}, {"volume_mm3": b}):
        clear = abs(a - b) > END_BODY_VOLUME_SHARE * abs(a)
        (out.clear if clear else out.small).append("its volume (%.6g mm3 before, %.6g mm3 now)" % (a, b))
    level = _level(_box_gap(box_numbers(before), box_numbers(now)), BODY_TOLERANCE_MM, END_BODY_BOX_MM)
    if level:
        getattr(out, level).append("its size or place")
    lumps_a, lumps_b = _pieces(before).get("lumps"), _pieces(now).get("lumps")
    if isinstance(lumps_a, int) and isinstance(lumps_b, int) and lumps_a != lumps_b:
        out.clear.append("the number of its pieces (%d before, %d now)" % (lumps_a, lumps_b))
    level = _others_level(_other_boxes(others_before if others_before is not None else before), _other_boxes(now))
    if level:
        getattr(out, level).append("the other bodies of its component")
    return out
