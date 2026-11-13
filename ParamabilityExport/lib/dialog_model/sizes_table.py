"""The sizes table of the dialog as plain data: columns, rows and the conversion to the CSV text.

Values are kept in Fusion internal units (cm, rad, plain), as the dialog inputs hold them. The conversion to the
unit of each parameter happens once, in table_to_csv, through package.units.
"""
import csv
import io
from dataclasses import dataclass, field

from ..package.units import internal_to_unit
from ..params.expressions.text import format_number
from .sizes_text import read_sizes, settable_parameters

DEFAULT_ROW_NAME = "Default"


@dataclass
class SizesTable:
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    # True when the dialog could not show the table and sizes are typed as CSV text instead.
    text_mode: bool = False


def new_table(params):
    """Favourite parameters as columns and one Default row at the current values.

    Every row keeps a value for all settable parameters, so a column that is switched off and on again
    comes back with what was typed.
    """
    settable = settable_parameters(params)
    current = {p["name"]: p["value"] for p in settable}
    return SizesTable(
        columns=[p["name"] for p in settable if p["is_favorite"]],
        rows=[{"name": DEFAULT_ROW_NAME, "values": current}])


def toggle_column(table, params, name, on):
    """Switch a parameter column on or off. Columns stay in the order of the parameters."""
    settable = settable_parameters(params)
    if name not in {p["name"] for p in settable}:
        return
    wanted = set(table.columns) - {name}
    if on:
        wanted.add(name)
    table.columns = [p["name"] for p in settable if p["name"] in wanted]
    for row in table.rows:
        for p in settable:
            row["values"].setdefault(p["name"], p["value"])


def next_row_name(table):
    """'Size N' with N one past the row count, moved on until the name is free."""
    taken = {row["name"].strip().lower() for row in table.rows}
    n = len(table.rows) + 1
    while f"size {n}" in taken:
        n += 1
    return f"Size {n}"


def add_row(table, copy_from=None):
    """Append a row copied from row copy_from (the last row when None or out of range). Returns its index."""
    source = table.rows[copy_from] if copy_from is not None and 0 <= copy_from < len(table.rows) else table.rows[-1]
    table.rows.append({"name": next_row_name(table), "values": dict(source["values"])})
    return len(table.rows) - 1


def remove_row(table, index=None):
    """Remove row index (the last row when None or out of range). The last remaining row stays. Returns the removed index or None."""
    if len(table.rows) <= 1:
        return None
    if index is None or not 0 <= index < len(table.rows):
        index = len(table.rows) - 1
    del table.rows[index]
    return index


def set_row(table, index, name, values):
    """Store what the person typed in one row. values maps parameter name to an internal value."""
    row = table.rows[index]
    row["name"] = name
    row["values"].update(values)


def column_label(param):
    """Parameter text for the check list and the table header: the name with its unit or the reason it is off."""
    unit = (param["unit"] or "").strip()
    if param["kind"] == "derived":
        return f"{param['name']} (formula)"
    if param["kind"] == "unsupported":
        return f"{param['name']} (unit {unit} not supported)"
    return f"{param['name']} ({unit})" if unit and param["kind"] in ("length", "angle") else param["name"]


def parameter_note(param):
    """Plain reason a parameter cannot change between sizes; '' when it can."""
    if param["kind"] == "derived":
        return "This parameter is worked out by a formula, so it cannot change between sizes."
    if param["kind"] == "unsupported":
        return f"The unit {param['unit']} is not supported. Use a parameter in mm, cm, m, in, ft, deg or rad, or one without a unit."
    return ""


def table_to_csv(table, params):
    """The text read_sizes expects: a name header with the columns, then one line per size."""
    by_name = {p["name"]: p for p in params}
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["name"] + table.columns)
    for row in table.rows:
        cells = [" ".join(row["name"].split())]
        for col in table.columns:
            value = row["values"].get(col, by_name[col]["value"])
            cells.append(format_number(internal_to_unit(value, by_name[col]["unit"])))
        writer.writerow(cells)
    return out.getvalue()


def read_table(table, params):
    """Read the table with the checks of the sizes text: returns a SizesRead (rows, columns, problems)."""
    return read_sizes(table_to_csv(table, params), params)
