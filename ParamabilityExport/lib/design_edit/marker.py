"""The timeline marker. The export works on the design as it is at the marker: steps after it are left out.

Reading the steps and the temporary copy move the marker for a while; it always goes back to where it was. Pure:
the timeline is any object with `markerPosition` (get and set), `count` and optionally `moveToEnd`.
"""


# The `unread` key of a probe state whose read moved the marker and could not put it back: every later read would
# happen at another timeline position, so the probe stops.
MARKER_LOST = "marker"


def read_marker(timeline):
    """{ position, count } of the marker now, or None when the design has no readable timeline."""
    try:
        position, count = timeline.markerPosition, timeline.count
    except Exception:
        return None
    if not isinstance(position, int) or not isinstance(count, int):
        return None
    return {"position": position, "count": count}


def at_end(marker):
    """True when the marker sits after the last step (or there is no timeline)."""
    return marker is None or marker["position"] >= marker["count"]


def put_back(timeline, marker):
    """Move the marker back to where `marker` (`read_marker`) found it. Returns True when it reads there after.

    A marker that was at the end goes to the end again (`moveToEnd`), also when the timeline has grown since: items
    left behind by a step must not end up after it. A position (an int) is taken as it is. Never raises."""
    if isinstance(marker, dict):
        if at_end(marker):
            return _to_end(timeline)
        marker = marker["position"]
    try:
        if timeline.markerPosition == marker:
            return True
        if marker == timeline.count:
            return _to_end(timeline)
    except Exception:
        return False
    try:
        timeline.markerPosition = marker
    except Exception:
        pass
    try:
        return timeline.markerPosition == marker
    except Exception:
        return False


def _to_end(timeline):
    try:
        if timeline.markerPosition == timeline.count:
            return True
    except Exception:
        return False
    try:
        timeline.moveToEnd()
    except Exception:
        try:
            timeline.markerPosition = timeline.count
        except Exception:
            pass
    try:
        return timeline.markerPosition == timeline.count
    except Exception:
        return False


def marker_note(marker):
    """The line for the dialog when the marker is not at the end, else None."""
    if at_end(marker):
        return None
    return ("Exporting the design as it is at the timeline marker (step %d of %d). Steps after the marker are left "
            "out." % (marker["position"], marker["count"]))


def not_put_back_message(marker):
    """What to tell the person when the marker could not be moved back."""
    if at_end(marker):
        return "The timeline marker could not be moved back to the end. Please move it there by hand."
    return ("The timeline marker could not be moved back to step %d. Please move it there by hand."
            % marker["position"])
