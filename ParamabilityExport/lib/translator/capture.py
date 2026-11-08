"""Capture checks: the translator reads only a dict that passed these."""

SUPPORTED_CAPTURE = 1
_ENVELOPE_KEYS = ("capture", "target", "items")
_ITEM_KEYS = ("index", "name", "type")


class CaptureError(Exception):
    """The capture is of another version or lacks keys the translator needs."""


def validate_capture(capture):
    if not isinstance(capture, dict):
        raise CaptureError("The capture is not an object.")
    for key in _ENVELOPE_KEYS:
        if key not in capture:
            raise CaptureError("The capture has no '%s'." % key)
    if capture["capture"] != SUPPORTED_CAPTURE:
        raise CaptureError("Capture version %r is not supported." % (capture["capture"],))
    if not isinstance(capture["items"], list):
        raise CaptureError("The capture 'items' is not a list.")
    target = capture["target"]
    if not isinstance(target, dict) or not (target.get("token") or target.get("name")):
        raise CaptureError("The capture target has no token or name.")
    for position, item in enumerate(capture["items"]):
        if not isinstance(item, dict):
            raise CaptureError("Item %d is not an object." % position)
        for key in _ITEM_KEYS:
            if key not in item:
                raise CaptureError("Item %d has no '%s'." % (position, key))
    return capture


def same_body(a, b):
    """Two body refs ({token, name}) name one body: tokens match, else names match."""
    if not a or not b:
        return False
    if a.get("token") and b.get("token"):
        return a["token"] == b["token"]
    return bool(a.get("name")) and a.get("name") == b.get("name")
