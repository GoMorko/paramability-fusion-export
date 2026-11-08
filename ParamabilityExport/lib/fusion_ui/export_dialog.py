"""The Export for Paramability dialog: builds the inputs and reads them back."""
import adsk.core

from ..fusion_reader.bodies import is_root_body
from ..export_plan.sizes_text import (
    others_line, pick_default_index, prefill_sizes_text, read_sizes, settable_parameters)

BODY_ID = "pm_body"
SIZES_ID = "pm_sizes"
OTHERS_ID = "pm_others"
STATUS_ID = "pm_status"
CHOICE_ID = "pm_choice"
DEFAULT_ID = "pm_default"
UP_ID = "pm_up"
NOTICE_ID = "pm_notice"

UP_LABELS = {"z": "Z up", "y": "Y up"}
DEFAULT_CHOICE_NAME = "Size"
MAX_CHOICE_NAME = 60


def build_blocked(command, text):
    """A dialog that only shows why the export cannot start."""
    command.isOKButtonVisible = False
    command.commandInputs.addTextBoxCommandInput(NOTICE_ID, "", text, 3, True)


def build(command, parameters, body, up_axis):
    """Add all inputs. parameters come from fusion_reader.parameters; body may be None."""
    inputs = command.commandInputs
    selection = inputs.addSelectionInput(BODY_ID, "Body", "Pick the body to export.")
    selection.addSelectionFilter("SolidBodies")
    selection.setSelectionLimits(1, 1)
    if body is not None:
        selection.addSelection(body)

    sizes = inputs.addTextBoxCommandInput(SIZES_ID, "Sizes", prefill_sizes_text(parameters), 8, False)
    sizes.tooltip = "One line per size."
    sizes.tooltipDescription = (
        "The first column is the size name. The other columns are user parameters. "
        "Leave a cell empty to keep the current value.")
    columns = [p["name"] for p in settable_parameters(parameters) if p["is_favorite"]]
    inputs.addTextBoxCommandInput(OTHERS_ID, "", others_line(parameters, columns), 2, True)
    status = inputs.addTextBoxCommandInput(STATUS_ID, "", "", 3, True)
    status.isVisible = False

    inputs.addStringValueInput(CHOICE_ID, "Dropdown name", DEFAULT_CHOICE_NAME)
    default = inputs.addDropDownCommandInput(DEFAULT_ID, "Default size", adsk.core.DropDownStyles.TextListDropDownStyle)
    default.listItems.add("Default", True)
    up = inputs.addDropDownCommandInput(UP_ID, "Design up direction", adsk.core.DropDownStyles.TextListDropDownStyle)
    for key in ("z", "y"):
        up.listItems.add(UP_LABELS[key], key == up_axis)
    up.tooltipDescription = (
        "Starts from the Fusion setting for new designs. Pick Y up if the part lies on its side in Paramability.")


def read_form(inputs):
    """Plain dict of what the person entered."""
    selection = inputs.itemById(BODY_ID)
    body = selection.selection(0).entity if selection.selectionCount == 1 else None
    default_item = inputs.itemById(DEFAULT_ID).selectedItem
    up_item = inputs.itemById(UP_ID).selectedItem
    return {
        "body": body,
        "sizes_text": inputs.itemById(SIZES_ID).text,
        "choice_name": inputs.itemById(CHOICE_ID).value.strip(),
        "default_name": default_item.name if default_item else "",
        "up_axis": "y" if up_item and up_item.name == UP_LABELS["y"] else "z",
    }


def refresh(inputs, parameters):
    """Rebuild the default size list from the sizes text and show the first problem, if any."""
    read = read_sizes(inputs.itemById(SIZES_ID).text, parameters)
    status = inputs.itemById(STATUS_ID)
    if read.problems:
        status.text = "\n".join(read.problems[:3])
        status.isVisible = True
        return
    status.isVisible = False
    dropdown = inputs.itemById(DEFAULT_ID)
    current = dropdown.selectedItem.name if dropdown.selectedItem else ""
    index = pick_default_index(read.rows, current)
    dropdown.listItems.clear()
    for i, row in enumerate(read.rows):
        dropdown.listItems.add(row["name"], i == index)


def allow_preselect(args, root):
    """Only bodies of the root component can be picked."""
    args.isSelectable = is_root_body(args.selection.entity, root)


def inputs_valid(inputs, parameters, root):
    form = read_form(inputs)
    if form["body"] is None or not is_root_body(form["body"], root):
        return False
    if not 1 <= len(form["choice_name"]) <= MAX_CHOICE_NAME:
        return False
    return not read_sizes(form["sizes_text"], parameters).problems
