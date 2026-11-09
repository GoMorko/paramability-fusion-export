"""The timeline marker. The export works on the design as it is at the marker: steps after it are left out.

Reading the steps and the temporary copy move the marker for a while; it always goes back to where it was. Pure:
the timeline is any object with `markerPosition` (get and set), `count` and optionally `moveToEnd`.
"""


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


def put_back(timeline, position):
    """Move the marker to `position` unless it is there already. Returns True when it reads `position` after.

    At the end of the timeline `moveToEnd` is tried first. Never raises."""
    try:
        if timeline.markerPosition == position:
            return True
    except Exception:
        return False
    try:
        if position == timeline.count:
            timeline.moveToEnd()
    except Exception:
        pass
    try:
        if timeline.markerPosition != position:
            timeline.markerPosition = position
    except Exception:
        pass
    try:
        return timeline.markerPosition == position
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
