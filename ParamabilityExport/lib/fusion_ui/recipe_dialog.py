"""The Export for Paramability dialog: pick the body, see which parameters become sizes, export."""
import html

import adsk.core

from .log import log

from ..export_plan.size_offers import MAX_TICKED, limit_message
from ..fusion_reader.bodies import is_pickable_body

BODY_ID = "pm_body"
UP_ID = "pm_up"
GROUP_ID = "pm_recipe_sizes_group"
INTRO_ID = "pm_sizes_intro"
BOX_PREFIX = "pm_size_"
NOTICE_ID = "pm_notice"
LIMIT_ID = "pm_sizes_limit"
FIXED_ID = "pm_sizes_fixed"
FIXED_MAX_ROWS = 6

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
    limit = group.children.addTextBoxCommandInput(LIMIT_ID, "", limit_message(), 1, True)
    limit.isVisible = False
    for index, offer in enumerate(offers):
        # A check box label is fixed at creation; the changing text goes in the tooltip and the fixed list below.
        box = group.children.addBoolValueInput(BOX_PREFIX + str(index), offer["param"], True, "", offer["ticked"])
        box.isEnabled = offer["enabled"]
        box.tooltip = _tooltip(offer)
    fixed = group.children.addTextBoxCommandInput(
        FIXED_ID, "", "", min(max(len(offers), 1), FIXED_MAX_ROWS), True)
    _show_fixed(fixed, offers)

    up = inputs.addDropDownCommandInput(UP_ID, "Design up direction", adsk.core.DropDownStyles.TextListDropDownStyle)
    for key in ("z", "y"):
        up.listItems.add(UP_LABELS[key], key == up_axis)
    up.tooltipDescription = (
        "Starts from the Fusion setting for new designs. Pick Y up if the part lies on its side in Paramability.")


def _tooltip(offer):
    return "%s. %s" % (offer["text"], offer["reason"]) if offer["reason"] else offer["text"]


def fixed_lines(offers):
    """Html lines for the parameters that cannot be ticked, each with its reason."""
    return "<br>".join(
        html.escape("%s: %s" % (o["text"], o["reason"])) for o in offers if not o["enabled"] and o["reason"])


def _show_fixed(box, offers):
    text = fixed_lines(offers)
    box.formattedText = text
    box.isVisible = bool(text)


def _boxes(inputs, offers):
    for index in range(len(offers)):
        box = adsk.core.BoolValueCommandInput.cast(inputs.itemById(BOX_PREFIX + str(index)))
        if box is not None:
            yield index, box


def _safely(what, action):
    """Run one Fusion call. A failure is logged so the other lines still update."""
    try:
        action()
        return True
    except Exception as error:
        log("%s failed: %s" % (what, error))
        return False


def apply_offers(inputs, offers, fresh):
    """Show the `fresh` offers (another body was picked) in the existing lines.

    The lines stay as built: each is matched to its parameter by name, and `offers` is updated in place since the
    export reads it later. A parameter missing from `fresh` keeps its old line. An entry changes only after its
    box took the new state, so `offers` never disagrees with the dialog.
    """
    by_param = {o["param"]: o for o in fresh}
    merged = list(offers)
    for index, box in _boxes(inputs, offers):
        offer = by_param.get(offers[index]["param"])
        if offer is None:
            continue

        def update(box=box, offer=offer):
            box.tooltip = _tooltip(offer)
            box.isEnabled = offer["enabled"]
            box.value = offer["ticked"]

        if _safely("Updating " + offer["param"], update):
            merged[index] = offer
    offers[:] = merged
    _safely("Updating the fixed list", lambda: _show_fixed(inputs.itemById(FIXED_ID), offers))
    _safely("Hiding the limit note", lambda: setattr(inputs.itemById(LIMIT_ID), "isVisible", False))


def keep_within_limit(inputs, offers, changed):
    """Untick the box just ticked when it would pass the limit of sizes, and say why. Else hide the message."""
    ticked = [box for _, box in _boxes(inputs, offers) if box.isEnabled and box.value]
    over = len(ticked) > MAX_TICKED
    if over and changed is not None and changed.id.startswith(BOX_PREFIX):
        changed.value = False
    inputs.itemById(LIMIT_ID).isVisible = over


def picked_body(inputs):
    selection = inputs.itemById(BODY_ID)
    return selection.selection(0).entity if selection.selectionCount == 1 else None


def read_form(inputs, offers):
    """Plain dict: body, ticked (Fusion parameter names), up_axis."""
    body = picked_body(inputs)
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


def inputs_valid(inputs, offers):
    selection = inputs.itemById(BODY_ID)
    if selection.selectionCount != 1 or not is_pickable_body(selection.selection(0).entity):
        return False
    return len(read_form(inputs, offers)["ticked"]) <= MAX_TICKED
