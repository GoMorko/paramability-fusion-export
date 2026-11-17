"""Comparing probe states: the body (`probe.state`), the numbers of a read and the states a try marked."""
from dataclasses import replace

from ...geometry.tolerances import BODY_TOLERANCE_MM, FIT_TOLERANCE
from ...probe.state import body_changed, box_numbers

__all__ = ["BODY_REQUEST", "body_changed", "body_difference", "box_numbers", "marked_states", "same_numbers"]

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


def _other_boxes(read):
    pieces = read.get("pieces") if isinstance(read, dict) else None
    others = pieces.get("others") if isinstance(pieces, dict) else None
    return others if isinstance(others, list) else None


def _lumps(read):
    pieces = read.get("pieces") if isinstance(read, dict) else None
    return pieces.get("lumps") if isinstance(pieces, dict) else None


def body_difference(before, now):
    """Plain texts of what differs between the body in two reads of the design with the same values: its volume, its
    box, the number of its solids and the boxes of the other bodies of its component (`fusion_reader.probe_state`),
    each within the body tolerances of `probe.state.body_changed`. A part that one of the reads lacks is not
    compared, so an unreadable body gives no difference."""
    out = []
    if box_numbers(before) is None or box_numbers(now) is None:
        return out
    a, b = _volume(before), _volume(now)
    if body_changed({"volume_mm3": a}, {"volume_mm3": b}):
        out.append("its volume (%.6g mm3 before, %.6g mm3 now)" % (a, b))
    if any(abs(x - y) > BODY_TOLERANCE_MM for x, y in zip(box_numbers(before), box_numbers(now))):
        out.append("its size or place")
    lumps_a, lumps_b = _lumps(before), _lumps(now)
    if isinstance(lumps_a, int) and isinstance(lumps_b, int) and lumps_a != lumps_b:
        out.append("the number of its pieces (%d before, %d now)" % (lumps_a, lumps_b))
    others_a, others_b = _other_boxes(before), _other_boxes(now)
    if others_a is not None and others_b is not None and not same_numbers(others_a, others_b):
        out.append("the other bodies of its component")
    return out
