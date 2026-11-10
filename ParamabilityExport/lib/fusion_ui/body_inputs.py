"""The inputs both export dialogs start with: the body picker and the line about the timeline marker."""
from ..dialog_model.dialog_rows import escape, text_rows

BODY_ID = "pm_body"
MARKER_ID = "pm_marker"


def add_body_inputs(inputs, bodies, marker_note=None, limit=1):
    """Add the body picker (with `bodies`, a body, a list of bodies or None, picked) and, when the timeline marker is
    not at the end, the line that says so (`design_edit.marker.marker_note`). `limit` is how many bodies can be
    picked."""
    prompt = "Pick the body to export." if limit == 1 else "Pick the body, or several bodies, to export."
    selection = inputs.addSelectionInput(BODY_ID, "Body", prompt)
    selection.addSelectionFilter("SolidBodies")
    selection.setSelectionLimits(1, limit)
    for body in bodies if isinstance(bodies, (list, tuple)) else [bodies] if bodies is not None else []:
        selection.addSelection(body)
    if marker_note:
        inputs.addTextBoxCommandInput(MARKER_ID, "", escape(marker_note), text_rows([marker_note]), True)
    return selection
