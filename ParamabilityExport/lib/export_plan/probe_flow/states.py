"""Comparing probe states: the body (`probe.state`), the numbers of a read and the states a try marked."""
from dataclasses import replace

from ...geometry.tolerances import FIT_TOLERANCE
from ...probe.state import body_changed, box_numbers

__all__ = ["body_changed", "box_numbers", "marked_states", "same_numbers"]


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
