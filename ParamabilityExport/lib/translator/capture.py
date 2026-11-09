"""Capture checks: the translator reads only a dict that passed these."""
from . import place

SUPPORTED_CAPTURES = (1, 2, 3)
_ENVELOPE_KEYS = ("capture", "target", "items")
_ITEM_KEYS = ("index", "name", "type")
_NOT_NUMBERS = place.FRAME_NOT_NUMBERS

# Timeline items that are not modeling steps: they make no body and never change the shape of one in its component.
SKETCH_TYPES = ("Sketch", "ConstructionPlane", "ConstructionAxis", "ConstructionPoint")
ASSEMBLY_TYPES = ("Occurrence", "Joint", "JointOrigin", "AsBuiltJoint", "RigidGroup", "MotionLink",
                  "TangentRelationship", "Snapshot", "Canvas", "Decal")
NOT_MODELING_TYPES = SKETCH_TYPES + ASSEMBLY_TYPES


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
    if not isinstance(placement.get("frame"), dict) or place.frame_problem(placement["frame"]) == _NOT_NUMBERS:
        raise CaptureError("The placement of the target has no frame of numbers.")


def outside_component(item):
    """The item was made in a component other than the target's (capture 3), or not in the root (captures 1, 2)."""
    return item.get("in_target_component") is False or item.get("component_root") is False


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
