"""The parameter check list and the sizes table of the export dialog.

The table is a view of export_plan.sizes_table.SizesTable. Cell inputs hold values in Fusion internal units
(cm, rad), the same units the table data keeps, so no unit conversion happens here.
Fusion keeps removed inputs registered, so every id that can be created twice carries a running number.
"""
import itertools

import adsk.core

from ..export_plan.sizes_table import (
    add_row, column_label, parameter_note, remove_row, set_row, toggle_column)
from ..export_plan.sizes_text import settable_parameters

PARAMS_GROUP_ID = "pm_params_group"
SIZES_GROUP_ID = "pm_sizes_group"
INTRO_ID = "pm_sizes_intro"
PARAM_PREFIX = "pm_param_"
TABLE_PREFIX = "pm_table_"
ADD_PREFIX = "pm_add_size_"
REMOVE_PREFIX = "pm_remove_size_"
_HEADER_ROWS = 1
_serial = itertools.count(1)


def _uid(prefix):
    return f"{prefix}{next(_serial)}"


def _input_unit(param):
    """Unit text for a value input: the parameter's own unit, empty for counts."""
    return param["unit"] if param["kind"] in ("length", "angle") else ""


def build_parameter_list(inputs, params, table):
    """A collapsible group with one check box per user parameter."""
    group = inputs.addGroupCommandInput(PARAMS_GROUP_ID, "Parameters that change between sizes")
    group.isExpanded = True
    if not params:
        group.children.addTextBoxCommandInput(
            "pm_no_params", "", "This design has no user parameters, so every size would be the same.", 2, True)
        return
    settable_names = {p["name"] for p in settable_parameters(params)}
    for p in params:
        settable = p["name"] in settable_names
        box = group.children.addBoolValueInput(
            PARAM_PREFIX + p["name"], column_label(p), True, "", settable and p["name"] in table.columns)
        if settable:
            box.tooltip = "Give each size its own value for this parameter."
        else:
            box.isEnabled = False
            box.tooltip = parameter_note(p)


def build_sizes(inputs, params, table):
    group = inputs.addGroupCommandInput(SIZES_GROUP_ID, "Sizes")
    group.isExpanded = True
    group.children.addTextBoxCommandInput(
        INTRO_ID, "", "Each row becomes one size in Paramability's dropdown.", 2, True)
    rebuild_table(inputs, params, table)


def _children(inputs):
    return inputs.itemById(SIZES_GROUP_ID).children


def _find_table(children):
    """Newest table in the group, or None."""
    for i in range(children.count - 1, -1, -1):
        item = children.item(i)
        if item.id.startswith(TABLE_PREFIX):
            return adsk.core.TableCommandInput.cast(item)
    return None


def rebuild_table(inputs, params, table):
    """Replace the table with one that has a column per checked parameter. Row data comes from table."""
    children = _children(inputs)
    old = _find_table(children)
    if old is not None:
        old.deleteMe()
    by_name = {p["name"]: p for p in params}
    ratio = ":".join(["2"] + ["1"] * len(table.columns))
    grid = children.addTableCommandInput(_uid(TABLE_PREFIX), "", 1 + len(table.columns), ratio)
    grid.minimumVisibleRows = 3
    grid.maximumVisibleRows = 8
    headers = ["Name"] + [column_label(by_name[c]) for c in table.columns]
    for col, text in enumerate(headers):
        cell = children.addTextBoxCommandInput(_uid("pm_header_"), "", text, 1, True)
        grid.addCommandInput(cell, 0, col)
    for index in range(len(table.rows)):
        _add_row_cells(children, grid, by_name, table, index)
    grid.addToolbarCommandInput(children.addBoolValueInput(_uid(ADD_PREFIX), "Add size", False, "", False))
    grid.addToolbarCommandInput(children.addBoolValueInput(_uid(REMOVE_PREFIX), "Remove size", False, "", False))


def _add_row_cells(children, grid, by_name, table, index):
    row = table.rows[index]
    position = index + _HEADER_ROWS
    name = children.addStringValueInput(_uid("pm_name_"), "", row["name"])
    grid.addCommandInput(name, position, 0)
    for col, column in enumerate(table.columns, start=1):
        param = by_name[column]
        value = children.addValueInput(
            _uid("pm_value_"), "", _input_unit(param), adsk.core.ValueInput.createByReal(row["values"][column]))
        grid.addCommandInput(value, position, col)


def sync_from_cells(inputs, table):
    """Copy what is typed in the cells into the table data. Skipped when the grid and the data disagree."""
    grid = _find_table(_children(inputs))
    if grid is None or grid.rowCount != len(table.rows) + _HEADER_ROWS:
        return
    for index in range(len(table.rows)):
        position = index + _HEADER_ROWS
        name = adsk.core.StringValueCommandInput.cast(grid.getInputAtPosition(position, 0)).value
        values = {}
        for col, column in enumerate(table.columns, start=1):
            values[column] = adsk.core.ValueCommandInput.cast(grid.getInputAtPosition(position, col)).value
        set_row(table, index, name, values)


def handle_change(inputs, changed, params, table):
    """React to the check boxes and the Add and Remove buttons. Cell edits only need sync_from_cells."""
    sync_from_cells(inputs, table)
    changed_id = changed.id
    if changed_id.startswith(PARAM_PREFIX):
        on = adsk.core.BoolValueCommandInput.cast(changed).value
        toggle_column(table, params, changed_id[len(PARAM_PREFIX):], on)
        rebuild_table(inputs, params, table)
        return
    if not changed_id.startswith((ADD_PREFIX, REMOVE_PREFIX)):
        return
    children = _children(inputs)
    grid = _find_table(children)
    selected = grid.selectedRow - _HEADER_ROWS if grid.selectedRow >= _HEADER_ROWS else None
    if changed_id.startswith(ADD_PREFIX):
        index = add_row(table, selected)
        _add_row_cells(children, grid, {p["name"]: p for p in params}, table, index)
    else:
        removed = remove_row(table, selected)
        if removed is not None:
            grid.deleteRow(removed + _HEADER_ROWS)
