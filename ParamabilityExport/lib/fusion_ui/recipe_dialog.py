"""The Export for Paramability dialog: pick the body, tick sizes in a parameter table, export.

One table row per parameter: tick, name, current value, Min and Max (the range of a size), and what the parameter
becomes. A text box under the table follows the picked row. The texts come from dialog_model.dialog_rows; this file
only places them in Fusion inputs.

A check box label cannot be changed after creation (Fusion raises on `.text`), so the row ticks carry no label.
"""
import adsk.core

from .body_inputs import BODY_ID, add_body_inputs
from .log import log

from ..dialog_model import dialog_rows as rows
from ..export_plan.size_offers import MAX_TICKED
from ..package.manifest import MAX_PARTS
from ..fusion_reader.bodies import is_pickable_body

UP_ID = "pm_up"
INTRO_ID = "pm_sizes_intro"
NOTICE_ID = "pm_notice"
TABLE_ID = "pm_params_table"
DETAILS_ID = "pm_details"
TICK_USED_ID = "pm_tick_used"
CLEAR_ID = "pm_untick_all"
WARN_ID = "pm_stop_warning"
SHOW_ID = "pm_show_in_timeline"
FASTER_ID = "pm_faster_tries"

TICK_PREFIX = "pm_tick_"
CELL_PREFIX = {"tick": TICK_PREFIX, "name": "pm_name_", "now": "pm_now_", "min": "pm_min_", "max": "pm_max_",
               "status": "pm_status_"}
_HEADER_ROWS = 1

UP_LABELS = {"z": "Z up", "y": "Y up"}


def build_blocked(command, text):
    """A dialog that only shows why the export cannot start."""
    command.isOKButtonVisible = False
    command.commandInputs.addTextBoxCommandInput(NOTICE_ID, "", rows.escape(text), rows.text_rows([text]), True)


def _safely(what, action):
    """Run one Fusion call. A failure is logged so the other lines still update."""
    try:
        action()
        return True
    except Exception as error:
        log("%s failed: %s" % (what, error))
        return False


def _cell_id(key, index):
    return CELL_PREFIX[key] + str(index)


def _bool(inputs, index):
    return adsk.core.BoolValueCommandInput.cast(inputs.itemById(_cell_id("tick", index)))


def _string(inputs, key, index):
    return adsk.core.StringValueCommandInput.cast(inputs.itemById(_cell_id(key, index)))


def _set_text(inputs, key, index, text):
    box = inputs.itemById(_cell_id(key, index))
    if box is not None:
        box.formattedText = rows.escape(text)


NO_SIZES_TEXT = "This design has no user parameters that can be sizes. The part is saved with fixed numbers."


def build(command, offers, body, up_axis, design_unit="mm", stop=None, marker_note=None):
    """Add the inputs. offers come from export_plan.size_offers.offers; body is the body or bodies already picked, or
    None.

    Cells are named by row number, since a Fusion parameter name is not always a safe input id. `design_unit` is the
    unit the Min and Max cells use for lengths. `stop` is the warning for the body already picked
    (dialog_model.stop_warning.summarize), if any. `marker_note` is the line shown when the timeline marker is not at
    the end (design_edit.marker.marker_note).
    """
    inputs = command.commandInputs
    add_body_inputs(inputs, body, marker_note, MAX_PARTS)
    warning = inputs.addTextBoxCommandInput(WARN_ID, "", "", 1, True)
    warning.isVisible = False
    button = inputs.addBoolValueInput(SHOW_ID, "Show in timeline", False, "", False)
    button.isVisible = False
    _safely("Button tooltip", lambda: setattr(
        button, "tooltip", "Selects the step in Fusion. The timeline marker does not move."))
    show_stop(inputs, stop)
    faster = inputs.addBoolValueInput(FASTER_ID, rows.FASTER_TRIES, True, "", False)
    _safely("Faster tries tooltip", lambda: setattr(faster, "tooltipDescription", rows.FASTER_TRIES_TOOLTIP))

    if offers:
        _safely("Dialog size", lambda: command.setDialogInitialSize(700, 700))
        _build_table(inputs, offers, design_unit)
        details = inputs.addTextBoxCommandInput(DETAILS_ID, "", "", 2, True)
        _safely("Details tooltip", lambda: setattr(details, "tooltipDescription", rows.HINT_TOOLTIP))
        _refresh_details(inputs, offers)
    else:
        inputs.addTextBoxCommandInput(
            INTRO_ID, "", NO_SIZES_TEXT, rows.text_rows([NO_SIZES_TEXT]),
            True)

    up = inputs.addDropDownCommandInput(UP_ID, "Design up direction", adsk.core.DropDownStyles.TextListDropDownStyle)
    for key in ("z", "y"):
        up.listItems.add(UP_LABELS[key], key == up_axis)
    up.tooltipDescription = (
        "Starts from the Fusion setting for new designs. Pick Y up if the part lies on its side in Paramability.")


def show_stop(inputs, summary):
    """Show the warning for the picked body, or hide it when `summary` is None.

    The box holds the short lines; the full reason is the tooltip. The button shows only for a step that can be
    pointed at."""
    box = inputs.itemById(WARN_ID)
    button = inputs.itemById(SHOW_ID)
    if box is None:
        return
    lines = summary["lines"] if summary else []
    if not lines:
        box.isVisible = False
        if button is not None:
            button.isVisible = False
        return
    head = "<b>%s</b>" % rows.escape(lines[0]) if summary["stops"] else rows.escape(lines[0])
    box.formattedText = "<br>".join([head] + [rows.escape(line) for line in lines[1:]])
    _safely("Warning rows", lambda: setattr(box, "numRows", rows.text_rows(lines)))
    box.isVisible = True
    if summary["tooltip"]:
        _safely("Warning tooltip", lambda: setattr(box, "tooltipDescription", summary["tooltip"]))
    if button is not None:
        button.isVisible = summary["index"] is not None


def _build_table(inputs, offers, design_unit):
    keys = rows.columns()
    table = inputs.addTableCommandInput(TABLE_ID, "", len(keys), rows.column_ratio(keys))
    _safely("Table rows", lambda: setattr(table, "minimumVisibleRows", rows.MIN_TABLE_ROWS))
    _safely("Table rows", lambda: setattr(table, "maximumVisibleRows", rows.MAX_TABLE_ROWS))
    _safely("Table width", lambda: setattr(table, "isFullWidth", True))
    for col, key in enumerate(keys):
        head = inputs.addTextBoxCommandInput("pm_head_" + key, "", rows.header(key, design_unit), 1, True)
        table.addCommandInput(head, 0, col)
    for index, offer in enumerate(offers):
        for col, key in enumerate(keys):
            table.addCommandInput(_make_cell(inputs, key, index, offer), index + _HEADER_ROWS, col)
    table.addToolbarCommandInput(inputs.addBoolValueInput(TICK_USED_ID, "Tick what the body uses", False, "", False))
    table.addToolbarCommandInput(inputs.addBoolValueInput(CLEAR_ID, "Untick all", False, "", False))


def _make_cell(inputs, key, index, offer):
    cell_id = _cell_id(key, index)
    cells = rows.row_cells(offer, offer["ticked"])
    if key == "tick":
        box = inputs.addBoolValueInput(cell_id, "", True, "", offer["ticked"])
        box.isEnabled = cells["tick_enabled"]
        return box
    if key in ("min", "max"):
        field = inputs.addStringValueInput(cell_id, "", cells[key])
        field.isEnabled = cells["range_enabled"]
        return field
    if key == "name":
        text, lines = rows.name_cell(offer["param"])
        box = inputs.addTextBoxCommandInput(cell_id, "", text, lines, True)
        _safely("Name tooltip", lambda: setattr(box, "tooltipDescription", rows.name_tooltip(offer)))
        return box
    return inputs.addTextBoxCommandInput(cell_id, "", rows.escape(cells[key]), 1, True)


def _ticks(inputs, offers):
    """The tick of each row as the person sees it; a greyed row never counts."""
    out = []
    for index, offer in enumerate(offers):
        box = _bool(inputs, index)
        out.append(bool(box is not None and offer["enabled"] and box.value))
    return out


def _range_texts(inputs, offers, key):
    out = []
    for index, offer in enumerate(offers):
        field = _string(inputs, key, index)
        out.append(field.value if field is not None else "")
    return out


def _show_row(inputs, index, offer, ticked, lo_text=None, hi_text=None):
    """Put one row's state into its cells."""
    cells = rows.row_cells(offer, ticked, lo_text, hi_text)
    _bool(inputs, index).isEnabled = cells["tick_enabled"]
    for key in ("min", "max"):
        field = _string(inputs, key, index)
        field.value = cells[key]
        field.isEnabled = cells["range_enabled"]
    _set_text(inputs, "now", index, cells["now"])
    _set_text(inputs, "status", index, cells["status"])


def _selected_index(inputs, offers):
    table = adsk.core.TableCommandInput.cast(inputs.itemById(TABLE_ID))
    if table is None:
        return None
    row = table.selectedRow - _HEADER_ROWS
    return row if 0 <= row < len(offers) else None


def _refresh_details(inputs, offers, index=None, over=False):
    """Fill the box under the table: the picked row (the hint when none) over the count or the problem line."""
    box = inputs.itemById(DETAILS_ID)
    if box is None:
        return
    ticks = _ticks(inputs, offers)
    _, problem = rows.read_ranges(
        offers, ticks, _range_texts(inputs, offers, "min"), _range_texts(inputs, offers, "max"))
    count = rows.count_line(sum(ticks), problem, over)
    index = _selected_index(inputs, offers) if index is None else index
    if index is None:
        text, needed = rows.details_panel(None, False, None, None, count)
    else:
        lo = _string(inputs, "min", index)
        hi = _string(inputs, "max", index)
        text, needed = rows.details_panel(
            offers[index], ticks[index], lo.value if lo is not None else None, hi.value if hi is not None else None,
            count)
    box.formattedText = text
    _safely("Details rows", lambda: setattr(box, "numRows", needed))


def apply_offers(inputs, offers, fresh):
    """Show the `fresh` offers (another body was picked) in the existing rows.

    The rows stay as built: each is matched to its parameter by name, and `offers` is updated in place since the
    export reads it later. A parameter missing from `fresh` keeps its old row. An entry changes only after its
    cells took the new state, so `offers` never disagrees with the dialog. Typed ranges go back to the defaults.
    """
    by_param = {o["param"]: o for o in fresh}
    merged = list(offers)
    for index, offer in enumerate(offers):
        new = by_param.get(offer["param"])
        if new is None:
            continue

        def update(index=index, new=new):
            _bool(inputs, index).value = new["ticked"]
            _show_row(inputs, index, new, new["ticked"])
            name = inputs.itemById(_cell_id("name", index))
            if name is not None:
                name.tooltipDescription = rows.name_tooltip(new)

        if _safely("Updating " + offer["param"], update):
            merged[index] = new
    offers[:] = merged
    _safely("Updating the details", lambda: _refresh_details(inputs, offers))


def _row_of(changed_id):
    """(key, row number) of a cell input id, else (None, None)."""
    for key, prefix in CELL_PREFIX.items():
        if changed_id.startswith(prefix) and changed_id[len(prefix):].isdigit():
            return key, int(changed_id[len(prefix):])
    return None, None


def _set_ticks(inputs, offers, wanted):
    """Tick the enabled rows named in `wanted` (a list of booleans), up to the limit. Typed ranges stay."""
    count = 0
    for index, offer in enumerate(offers):
        if not offer["enabled"]:
            continue
        on = bool(wanted[index]) and count < MAX_TICKED
        count += on

        def update(index=index, offer=offer, on=on):
            _bool(inputs, index).value = on
            _show_row(inputs, index, offer, on,
                      _string(inputs, "min", index).value, _string(inputs, "max", index).value)

        _safely("Ticking " + offer["param"], update)


def handle_change(inputs, offers, changed):
    """React to a tick, a typed Min or Max, or one of the two buttons; then refresh the count and the details."""
    key, index = _row_of(changed.id)
    if index is not None and index >= len(offers):
        key, index = None, None
    over = False
    if changed.id == TICK_USED_ID:
        _set_ticks(inputs, offers, [o["ticked"] for o in offers])
    elif changed.id == CLEAR_ID:
        _set_ticks(inputs, offers, [False] * len(offers))
    elif key == "tick":
        box = adsk.core.BoolValueCommandInput.cast(changed)
        if box.value and sum(_ticks(inputs, offers)) > MAX_TICKED:
            box.value = False
            over = True
        ticked = box.value
        _show_row(inputs, index, offers[index], ticked,
                  _string(inputs, "min", index).value, _string(inputs, "max", index).value)
    _refresh_details(inputs, offers, index if key in ("tick", "min", "max") else None, over)


def picked_bodies(inputs):
    """The bodies in the picker, in the order they were picked."""
    selection = inputs.itemById(BODY_ID)
    return [selection.selection(i).entity for i in range(selection.selectionCount)]


def picked_body(inputs):
    """The one picked body, or None when none or several are picked."""
    bodies = picked_bodies(inputs)
    return bodies[0] if len(bodies) == 1 else None


def restore_bodies(inputs, bodies):
    """Put `bodies` back in the picker when something else took their place (selecting a step can do that)."""
    selection = inputs.itemById(BODY_ID)
    current = [b.entityToken for b in picked_bodies(inputs)]
    if bodies and current != [b.entityToken for b in bodies]:
        selection.clearSelection()
        for body in bodies:
            selection.addSelection(body)


def read_form(inputs, offers):
    """Plain dict: bodies (the picked bodies), body (the one picked body, else None), ticked (Fusion parameter names),
    ranges ({name: (min, max)} of the ticked ones), range_problem ('' when every typed range is fine), up_axis and
    faster_tries (the box that turns off unused timeline steps during the tries)."""
    ticks = _ticks(inputs, offers)
    ranges, problem = rows.read_ranges(
        offers, ticks, _range_texts(inputs, offers, "min"), _range_texts(inputs, offers, "max"))
    up_item = inputs.itemById(UP_ID).selectedItem
    faster = inputs.itemById(FASTER_ID)
    bodies = picked_bodies(inputs)
    return {
        "bodies": bodies,
        "body": bodies[0] if len(bodies) == 1 else None,
        "ticked": [o["param"] for o, on in zip(offers, ticks) if on],
        "ranges": ranges,
        "range_problem": problem,
        "up_axis": "y" if up_item and up_item.name == UP_LABELS["y"] else "z",
        "faster_tries": bool(faster is not None and adsk.core.BoolValueCommandInput.cast(faster).value),
    }


def allow_preselect(args):
    """Any solid body can be picked, also one inside a component."""
    args.isSelectable = is_pickable_body(args.selection.entity)


def inputs_valid(inputs, offers):
    bodies = picked_bodies(inputs)
    if not 1 <= len(bodies) <= MAX_PARTS or not all(is_pickable_body(b) for b in bodies):
        return False
    form = read_form(inputs, offers)
    return len(form["ticked"]) <= MAX_TICKED and not form["range_problem"]
