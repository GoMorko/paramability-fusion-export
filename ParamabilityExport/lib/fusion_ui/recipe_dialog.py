"""The Export for Paramability dialog: pick the body, see which parameters become sizes, export."""
import adsk.core

from ..fusion_reader.bodies import is_pickable_body

BODY_ID = "pm_body"
UP_ID = "pm_up"
GROUP_ID = "pm_recipe_sizes_group"
INTRO_ID = "pm_sizes_intro"
BOX_PREFIX = "pm_size_"
NOTICE_ID = "pm_notice"

UP_LABELS = {"z": "Z up", "y": "Y up"}


def build_blocked(command, text):
    """A dialog that only shows why the export cannot start."""
    command.isOKButtonVisible = False
    command.commandInputs.addTextBoxCommandInput(NOTICE_ID, "", text, 3, True)


def build(command, offers, body, up_axis):
    """Add the inputs. offers come from export_plan.size_offers.offers; body may be None.

    Check boxes are named by position, since a Fusion parameter name is not always a safe input id.
    """
    inputs = command.commandInputs
    selection = inputs.addSelectionInput(BODY_ID, "Body", "Pick the body to export.")
    selection.addSelectionFilter("SolidBodies")
    selection.setSelectionLimits(1, 1)
    if body is not None:
        selection.addSelection(body)

    group = inputs.addGroupCommandInput(GROUP_ID, "Sizes you can change in Paramability")
    group.isExpanded = True
    if not offers:
        group.children.addTextBoxCommandInput(
            INTRO_ID, "", "This design has no user parameters that can be sizes. The part is saved with fixed numbers.",
            2, True)
    else:
        group.children.addTextBoxCommandInput(
            INTRO_ID, "", "Ticked parameters become sizes. The others stay fixed numbers.", 2, True)
    for index, offer in enumerate(offers):
        box = group.children.addBoolValueInput(BOX_PREFIX + str(index), offer["text"], True, "", offer["ticked"])
        box.isEnabled = offer["enabled"]
        box.tooltip = offer["reason"]

    up = inputs.addDropDownCommandInput(UP_ID, "Design up direction", adsk.core.DropDownStyles.TextListDropDownStyle)
    for key in ("z", "y"):
        up.listItems.add(UP_LABELS[key], key == up_axis)
    up.tooltipDescription = (
        "Starts from the Fusion setting for new designs. Pick Y up if the part lies on its side in Paramability.")


def read_form(inputs, offers):
    """Plain dict: body, ticked (Fusion parameter names), up_axis."""
    selection = inputs.itemById(BODY_ID)
    body = selection.selection(0).entity if selection.selectionCount == 1 else None
    up_item = inputs.itemById(UP_ID).selectedItem
    ticked = []
    for index, offer in enumerate(offers):
        box = adsk.core.BoolValueCommandInput.cast(inputs.itemById(BOX_PREFIX + str(index)))
        if box is not None and offer["enabled"] and box.value:
            ticked.append(offer["param"])
    return {
        "body": body,
        "ticked": ticked,
        "up_axis": "y" if up_item and up_item.name == UP_LABELS["y"] else "z",
    }


def allow_preselect(args):
    """Any solid body can be picked, also one inside a component."""
    args.isSelectable = is_pickable_body(args.selection.entity)


def inputs_valid(inputs):
    selection = inputs.itemById(BODY_ID)
    return selection.selectionCount == 1 and is_pickable_body(selection.selection(0).entity)
