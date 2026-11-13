"""What the states tried so far show for one size set alone: which values built and kept every outline."""
from .rows import _SAME


def _side(size, value):
    """1 or -1: the side of the size's value `value` lies on (0 for the value itself)."""
    delta = value - size["value"]
    return 0 if abs(delta) <= _SAME else (1 if delta > 0 else -1)


def _fails_by(states, size, value):
    """True when a state that set only this size, on the side of `value` and not farther, did not build or changed
    an outline: a row at `value` would end past the range the size keeps."""
    side, reach = _side(size, value), abs(value - size["value"])
    return side != 0 and any(not ok and _side(size, v) == side and abs(v - size["value"]) <= reach + _SAME
                             for v, ok in _tried_alone(states, size["param"], size["value"]))


def _farthest_built(states, size, end):
    """The farthest value toward `end` at which a state that set only this size built and kept every outline, nearer
    than any value that did not, or None."""
    side = _side(size, end)
    if side == 0:
        return None
    tried = [(v, ok) for v, ok in _tried_alone(states, size["param"], size["value"]) if _side(size, v) == side]
    bad = min((abs(v - size["value"]) for v, ok in tried if not ok), default=None)
    good = [v for v, ok in tried if ok and (bad is None or abs(v - size["value"]) < bad - _SAME)]
    return max(good, key=lambda v: abs(v - size["value"])) if good else None


def _tried_alone(states, name, value):
    """`(value, kept)` of every state that set only `name` to another value than `value`: `kept` when it built and
    no followed outline changed there (`changed`)."""
    out = []
    for state in states:
        values = state.get("values") or {}
        if list(values) == [name] and abs(values[name] - value) > _SAME:
            out.append((values[name], state.get("built") is not False and not state.get("changed")))
    return out


def _changed_alone(states, name, value):
    """The values of the states that set only `name` and changed a followed outline (`changed`)."""
    return [v for v, state in ((s["values"][name], s) for s in states
                               if list(s.get("values") or {}) == [name] and s.get("changed"))
            if abs(v - value) > _SAME]
