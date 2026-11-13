"""Comparing probe states: the body's box and volume, the numbers of a read and the states a try marked."""
from dataclasses import replace

from ...probe import fit

BODY_TOLERANCE_MM = 1e-4
VOLUME_TOLERANCE_MM3 = 1e-4
VOLUME_RELATIVE = 1e-6


def box_numbers(read):
    box = read.get("box") if isinstance(read, dict) else None
    if not isinstance(box, dict):
        return None
    low, high = box.get("min"), box.get("max")
    if not all(isinstance(v, (list, tuple)) and len(v) == 3 for v in (low, high)):
        return None
    numbers = list(low) + list(high)
    return numbers if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers) else None


def _volume(read):
    value = read.get("volume_mm3") if isinstance(read, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


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
    return len(x) == len(y) and all(abs(p - q) <= fit.TOLERANCE for p, q in zip(x, y))


def body_changed(before, now):
    """True when the body reads differently in two probe states: its box moved, or its volume changed when both states
    read it. False when they agree or the body cannot be compared (a state without a box)."""
    a, b = box_numbers(before), box_numbers(now)
    if a is not None and b is not None and any(abs(x - y) > BODY_TOLERANCE_MM for x, y in zip(a, b)):
        return True
    va, vb = _volume(before), _volume(now)
    return va is not None and vb is not None and abs(va - vb) > max(VOLUME_TOLERANCE_MM3, VOLUME_RELATIVE * abs(va))


def marked_states(states, changed):
    """The states after E0, each one whose number is in `changed` marked `changed` for `plan.nearer_rows`."""
    return [replace(state, changed=True) if at in changed else state for at, state in enumerate(states) if at]
