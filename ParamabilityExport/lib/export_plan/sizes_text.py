"""The sizes text of the dialog: prefill, reading and checks."""
import csv
import io
from dataclasses import dataclass, field

from ..package.rows import parse_rows_csv
from .expressions import format_number


@dataclass
class SizesRead:
    rows: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def settable_parameters(params):
    """Parameters a size row may set: plain numbers, not formulas."""
    return [p for p in params if p["kind"] != "derived"]


def prefill_sizes_text(params):
    """Header with the favourite parameters and one Default row holding their current values."""
    chosen = [p for p in settable_parameters(params) if p["is_favorite"]]
    header = ",".join(["name"] + [p["name"] for p in chosen])
    row = ",".join(["Default"] + [format_number(p["display_value"]) for p in chosen])
    return header + "\n" + row + "\n"


def others_line(params, columns):
    """Short line naming the user parameters that are not columns yet, with their units."""
    rest = [p for p in params if p["name"] not in columns]
    if not rest:
        return "No other user parameters."
    parts = []
    for p in rest:
        label = p["name"]
        if p["kind"] == "derived":
            label += " (formula)"
        elif p["unit"]:
            label += f" ({p['unit']})"
        parts.append(label)
    return "Other user parameters: " + ", ".join(parts)


def header_columns(text):
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    header = next(csv.reader(io.StringIO(lines[0]), skipinitialspace=True))
    return [c.strip() for c in header[1:] if c.strip()]


def read_sizes(text, params):
    """Parse the sizes text against the design parameters. Problems are plain sentences."""
    csv_params = [{"name": p["name"], "value": p["display_value"]} for p in params]
    rows, problems = parse_rows_csv(text, csv_params)
    if problems:
        return SizesRead(problems=problems)
    columns = header_columns(text)
    by_name = {p["name"]: p for p in params}
    for col in columns:
        if by_name[col]["kind"] == "derived":
            problems.append(f"\"{col}\" is worked out by a formula, so it cannot be a column.")
    if len(rows) > 1 and not columns:
        problems.append("Add at least one parameter column, or the sizes would all be the same.")
    if problems:
        return SizesRead(problems=problems)
    return SizesRead(rows=rows, columns=columns)


def pick_default_index(rows, default_name):
    """Index of the default row; the first row when the name is not found."""
    for i, row in enumerate(rows):
        if row["name"] == default_name:
            return i
    return 0
