"""The inputs both export dialogs start with: the body picker and the line about the timeline marker."""
from ..dialog_model.dialog_rows import escape, text_rows

BODY_ID = "pm_body"
MARKER_ID = "pm_marker"


def add_body_inputs(inputs, body, marker_note=None):
    """Add the body picker (with `body` picked when it is not None) and, when the timeline marker is not at the end,
    the line that says so (`design_edit.marker.marker_note`)."""
    selection = inputs.addSelectionInput(BODY_ID, "Body", "Pick the body to export.")
    selection.addSelectionFilter("SolidBodies")
    selection.setSelectionLimits(1, 1)
    if body is not None:
        selection.addSelection(body)
    if marker_note:
        inputs.addTextBoxCommandInput(MARKER_ID, "", escape(marker_note), text_rows([marker_note]), True)
    return selection
