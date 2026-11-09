"""The Export size choices dialog: the sizes table of value rows. Builds the inputs and reads them back."""
import html
import traceback

import adsk.core

from ..fusion_reader.bodies import is_pickable_body
from ..export_plan.sizes_table import read_table, table_to_csv
from ..export_plan.sizes_text import pick_default_index, read_sizes
from . import sizes_table_ui, sizes_text_ui
from .log import log

BODY_ID = "pm_body"
STATUS_ID = "pm_status"
CHOICE_ID = "pm_choice"
DEFAULT_ID = "pm_default"
UP_ID = "pm_up"
NOTICE_ID = "pm_notice"
MARKER_ID = "pm_marker"

UP_LABELS = {"z": "Z up", "y": "Y up"}
DEFAULT_CHOICE_NAME = "Size"
MAX_CHOICE_NAME = 60


def build_blocked(command, text):
    """A dialog that only shows why the export cannot start."""
    command.isOKButtonVisible = False
    command.commandInputs.addTextBoxCommandInput(NOTICE_ID, "", text, 3, True)


def build(command, parameters, body, up_axis, table, marker_note=None):
    """Add all inputs. parameters come from fusion_reader.parameters; body may be None; table is the sizes data.
    `marker_note` is the line shown when the timeline marker is not at the end (export_plan.marker.marker_note)."""
    inputs = command.commandInputs
    selection = inputs.addSelectionInput(BODY_ID, "Body", "Pick the body to export.")
    selection.addSelectionFilter("SolidBodies")
    selection.setSelectionLimits(1, 1)
    if body is not None:
        selection.addSelection(body)
    if marker_note:
        inputs.addTextBoxCommandInput(MARKER_ID, "", html.escape(marker_note), 2, True)

    try:
        sizes_table_ui.build_parameter_list(inputs, parameters, table)
        sizes_table_ui.build_sizes(inputs, parameters, table)
    except Exception:
        _use_text_box(inputs, parameters, table)
    status = inputs.addTextBoxCommandInput(STATUS_ID, "", "", 3, True)
    status.isVisible = False

    inputs.addStringValueInput(CHOICE_ID, "Name of the dropdown in Paramability", DEFAULT_CHOICE_NAME)
    default = inputs.addDropDownCommandInput(DEFAULT_ID, "Default size", adsk.core.DropDownStyles.TextListDropDownStyle)
    default.listItems.add("Default", True)
    up = inputs.addDropDownCommandInput(UP_ID, "Design up direction", adsk.core.DropDownStyles.TextListDropDownStyle)
    for key in ("z", "y"):
        up.listItems.add(UP_LABELS[key], key == up_axis)
    up.tooltipDescription = (
        "Starts from the Fusion setting for new designs. Pick Y up if the part lies on its side in Paramability.")


def _use_text_box(inputs, parameters, table):
    """Replace the table and the parameter list with the CSV text box. Sizes are read from the text from now on."""
    log("sizes table failed, using the text box:\n" + traceback.format_exc())
    for group_id in (sizes_table_ui.PARAMS_GROUP_ID, sizes_table_ui.SIZES_GROUP_ID):
        try:
            inputs.itemById(group_id).deleteMe()
        except Exception:
            pass
    table.text_mode = True
    sizes_text_ui.build(inputs, parameters)


def _sync(inputs, table):
    """Copy the cells into the table data; a failing grid is logged and the data is used as it is."""
    if table.text_mode:
        return
    try:
        sizes_table_ui.sync_from_cells(inputs, table)
    except Exception:
        log("could not read the sizes table:\n" + traceback.format_exc())


def _read_sizes(inputs, parameters, table):
    """The one read of the sizes, from the text box or the table; both end in read_sizes."""
    if table.text_mode:
        return read_sizes(sizes_text_ui.read_text(inputs), parameters)
    return read_table(table, parameters)


def read_form(inputs, parameters, table):
    """Plain dict of what the person entered. The sizes come as the CSV text read_sizes expects."""
    _sync(inputs, table)
    selection = inputs.itemById(BODY_ID)
    body = selection.selection(0).entity if selection.selectionCount == 1 else None
    default_item = inputs.itemById(DEFAULT_ID).selectedItem
    up_item = inputs.itemById(UP_ID).selectedItem
    return {
        "body": body,
        "sizes_text": sizes_text_ui.read_text(inputs) if table.text_mode else table_to_csv(table, parameters),
        "choice_name": inputs.itemById(CHOICE_ID).value.strip(),
        "default_name": default_item.name if default_item else "",
        "up_axis": "y" if up_item and up_item.name == UP_LABELS["y"] else "z",
    }


def on_input_changed(args, parameters, table):
    """Update the table for a changed check box or button, then refresh the status and the default size list."""
    if not table.text_mode:
        try:
            sizes_table_ui.handle_change(args.inputs, args.input, parameters, table)
        except Exception:
            _use_text_box(args.inputs, parameters, table)
    refresh(args.inputs, parameters, table)


def refresh(inputs, parameters, table):
    """Rebuild the default size list from the table and show the first problem, if any."""
    _sync(inputs, table)
    read = _read_sizes(inputs, parameters, table)
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


def allow_preselect(args):
    """Any solid body can be picked, also one inside a component."""
    args.isSelectable = is_pickable_body(args.selection.entity)


def inputs_valid(inputs, parameters, table):
    form = read_form(inputs, parameters, table)
    if form["body"] is None or not is_pickable_body(form["body"]):
        return False
    if not 1 <= len(form["choice_name"]) <= MAX_CHOICE_NAME:
        return False
    return not _read_sizes(inputs, parameters, table).problems
