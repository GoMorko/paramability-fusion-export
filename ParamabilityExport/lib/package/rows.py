"""CSV size rows typed in the dialog."""
import csv
import io
import math

MAX_ROWS = 32
MAX_NAME = 60


def parse_rows_csv(text, parameters):
    """Parse the sizes text.

    parameters: list of dicts with 'name' and 'value' (the current value, used for blank cells).
    Returns (rows, problems). rows: list of {'name', 'values'} in order. problems: plain sentences.
    """
    problems = []
    rows = []
    known = {p["name"]: p for p in parameters}
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], ["Add a header line and at least one size."]
    table = list(csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True))
    header = [c.strip() for c in table[0]]
    if not header or header[0].lower() != "name":
        return [], ["The first column of the header must be \"name\"."]
    columns = header[1:]
    seen_cols = set()
    for col in columns:
        if col not in known:
            problems.append(f"Header: \"{col}\" is not a parameter of this design.")
        elif col in seen_cols:
            problems.append(f"Header: \"{col}\" is listed twice.")
        seen_cols.add(col)
    if problems:
        return [], problems
    body = table[1:]
    if not body:
        return [], ["Add at least one size under the header."]
    if len(body) > MAX_ROWS:
        problems.append(f"Use at most {MAX_ROWS} sizes. You have {len(body)}.")
    seen_names = set()
    for index, cells in enumerate(body[:MAX_ROWS], start=1):
        number = f"Size {index}"
        name = (cells[0] if cells else "").strip()
        if not name:
            problems.append(f"{number}: the name is empty.")
        elif len(name) > MAX_NAME:
            problems.append(f"{number}: the name is longer than {MAX_NAME} characters.")
        elif name.lower() in seen_names:
            problems.append(f"{number}: the name \"{name}\" is used twice.")
        seen_names.add(name.lower())
        if len(cells) - 1 > len(columns):
            problems.append(f"{number}: there are more values than header columns.")
        values = {}
        for pos, col in enumerate(columns, start=1):
            raw = cells[pos].strip() if pos < len(cells) else ""
            if raw == "":
                current = known[col].get("value")
                if current is not None:
                    values[col] = current
                continue
            try:
                number_value = float(raw)
            except ValueError:
                problems.append(f"{number}: \"{raw}\" in column \"{col}\" is not a number. Use a dot for decimals.")
                continue
            if not math.isfinite(number_value):
                problems.append(f"{number}: \"{raw}\" in column \"{col}\" is not a usable number.")
                continue
            values[col] = number_value
        rows.append({"name": name, "values": values})
    if problems:
        return [], problems
    return rows, []
