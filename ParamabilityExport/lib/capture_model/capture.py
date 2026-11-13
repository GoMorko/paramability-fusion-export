"""Capture checks: the translator reads only a dict that passed these."""
from ..geometry import rigid

SUPPORTED_CAPTURES = (3,)
_ENVELOPE_KEYS = ("capture", "target", "items")
_ITEM_KEYS = ("index", "name", "type")
_NOT_NUMBERS = rigid.FRAME_NOT_NUMBERS


class CaptureError(Exception):
    """The capture is of another version or lacks keys the translator needs."""


def validate_capture(capture):
    if not isinstance(capture, dict):
        raise CaptureError("The capture is not an object.")
    for key in _ENVELOPE_KEYS:
        if key not in capture:
            raise CaptureError("The capture has no '%s'." % key)
    if capture["capture"] not in SUPPORTED_CAPTURES:
        raise CaptureError("Capture version %r is not supported." % (capture["capture"],))
    if not isinstance(capture["items"], list):
        raise CaptureError("The capture 'items' is not a list.")
    target = capture["target"]
    if not isinstance(target, dict) or not (target.get("token") or target.get("name")):
        raise CaptureError("The capture target has no token or name.")
    _check_targets(capture)
    _check_reach(capture.get("reach"))
    for position, item in enumerate(capture["items"]):
        if not isinstance(item, dict):
            raise CaptureError("Item %d is not an object." % position)
        for key in _ITEM_KEYS:
            if key not in item:
                raise CaptureError("Item %d has no '%s'." % (position, key))
    return capture


def _check_targets(capture):
    targets = capture.get("targets")
    if targets is not None and (
            not isinstance(targets, list) or not targets
            or not all(isinstance(t, dict) and (t.get("token") or t.get("name")) for t in targets)):
        raise CaptureError("The capture 'targets' is not a list of bodies.")
    placement = capture["target"].get("placement")
    if placement is None:
        return
    if not isinstance(placement, dict):
        raise CaptureError("The placement of the target is not an object.")
    if placement.get("error") or placement.get("linked"):
        return
    if not isinstance(placement.get("frame"), dict) or rigid.frame_problem(placement["frame"]) == _NOT_NUMBERS:
        raise CaptureError("The placement of the target has no frame of numbers.")


def _is_index(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_reach(reach):
    """`reach` (optional) says which earlier steps made the faces each step picks: `{ read: true, gaps: [indexes],
    makers: { "<index>": [indexes] } }`, or `{ read: false, error }` when that could not be read. `gaps` are the
    left out steps the read was asked about; without it no answer is trusted (gap_picks.picked_gaps)."""
    if reach is None:
        return
    if not isinstance(reach, dict) or not isinstance(reach.get("read"), bool):
        raise CaptureError("The capture 'reach' is not a read result.")
    if not reach["read"]:
        return
    makers = reach.get("makers")
    if not isinstance(makers, dict) or not all(
            isinstance(key, str) and isinstance(found, list) and all(_is_index(i) for i in found)
            for key, found in makers.items()):
        raise CaptureError("The capture 'reach' has no list of makers per step.")
    read_for = reach.get("gaps")
    if read_for is not None and not (isinstance(read_for, list) and all(_is_index(i) for i in read_for)):
        raise CaptureError("The capture 'reach' names its left out steps in a way that cannot be read.")


def outside_component(item):
    """The item was made in a component other than the target's."""
    return item.get("in_target_component") is False


def same_body(a, b):
    """Two body refs ({token, name}) name one body: tokens match, else names match."""
    if not a or not b:
        return False
    if a.get("token") and b.get("token"):
        return a["token"] == b["token"]
    return bool(a.get("name")) and a.get("name") == b.get("name")


def renamed_target(body, target):
    """A body with the target's name but another token: the target was probably re-tokened, so it is not safe to match."""
    if not body or not target:
        return False
    a, b = body.get("token"), target.get("token")
    return bool(a and b and a != b and body.get("name") and body.get("name") == target.get("name"))
