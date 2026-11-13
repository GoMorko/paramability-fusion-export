"""One probe row and the helpers every kind of row shares."""
from ...geometry.tolerances import SAME_SIZE
from ...package.manifest import MAX_NAME_CHARS
from ...package.units import display_from_manifest, unit_kind
from ...params.expressions.text import format_number

MAX_PROBE_ROWS = 64
# Added to the progress line of a row that tries again nearer after a value that did not build.
RETRY_NOTE = ". The last value did not rebuild, so this one is nearer."


def state_values(sizes, overrides=None):
    """Manifest value of every size (Fusion name) with `overrides` applied: the `values` of a probe state."""
    values = {s["param"]: s["value"] for s in sizes}
    values.update(overrides or {})
    return values


def _value_text(size, manifest_value):
    """The value as the person typed it: in the parameter's own unit, with the unit for a length or an angle."""
    unit = (size.get("unit") or "").strip()
    text = format_number(round(display_from_manifest(manifest_value, unit), 3))
    return "%s %s" % (text, unit) if unit_kind(unit) in ("length", "angle") else text


def _label(sizes, manifest, varied, retry):
    """The line the progress window shows for a row: one size at its value, or several sizes together."""
    if not varied:
        return ""
    if len(varied) > 1:
        return "several sizes together"
    size = next(s for s in sizes if s["param"] == varied[0])
    text = "%s at %s" % (size["param"], _value_text(size, manifest[size["param"]]))
    return text + RETRY_NOTE if retry else text


def probe_row(sizes, name, overrides, key=None, retry=False):
    manifest = state_values(sizes, overrides)
    current = {s["param"]: s["value"] for s in sizes}
    varied = sorted(p for p in overrides if abs(manifest[p] - current[p]) > SAME_SIZE)
    row = {
        "name": name[:MAX_NAME_CHARS],
        "key": "probe: " + (key or name),
        "values": {s["param"]: display_from_manifest(manifest[s["param"]], s["unit"]) for s in sizes},
        "step": False,
        "state": manifest,
        "varied": varied,
    }
    row["label"] = _label(sizes, manifest, varied, retry) or row["name"]
    return row


def tried_sizes(sizes, moved, extra):
    """The sizes that get rows: the ones that move a sketch or a measured reference, then those tried on a guess."""
    moved_sizes = [s for s in sizes if s["param"] in moved]
    return moved_sizes + [s for s in sizes if s["param"] in extra and s["param"] not in moved]


def value_toward(size, end, share):
    """The value `share` of the way from the size's value to `end`; a count is rounded to a whole number."""
    value = size["value"] + share * (end - size["value"])
    return float(round(value)) if size.get("kind") == "count" else value
