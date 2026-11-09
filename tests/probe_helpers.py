"""Builders for the probe tests: parameters, captures with tokens, and sketch states as the reader gives them."""
import re

from tests import context  # noqa: F401  puts the add-in on the import path

from lib.params import size_table

IDENT = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def user(name, expression, mm, unit="mm"):
    """A user parameter as `list_user_parameters` gives it (internal cm or radians)."""
    plain = re.match(r"^\d+(\.\d+)?( \w+)?$", expression) is not None
    internal = {"mm": mm / 10.0, "deg": mm * 3.141592653589793 / 180.0}.get(unit, mm)
    kind = "derived" if not plain else {"mm": "length", "deg": "angle"}.get(unit, "count")
    return {"name": name, "expression": expression, "value": internal, "display_value": mm, "unit": unit,
            "comment": "", "is_favorite": False, "kind": kind, "value_type": "numeric",
            "dependency_parameters": []}


def model(name, expression, mm, kind="sketchDimension", sketch="", token=""):
    """A model parameter made by a sketch dimension, a construction plane, or a feature."""
    return {"name": name, "expression": expression, "value": mm / 10.0, "unit": "mm", "kind": "derived",
            "role": "", "dependency_parameters": [],
            "created_by": {"kind": kind, "token": token, "name": name, "sketch": sketch, "component": "c"}}


def table(params, ticked, model_params=()):
    return size_table.build(params, ticked, model_params=model_params)


def size(table_, name, unit="mm"):
    """A kept size dict (as `plan_checks` takes) for a ticked parameter of the table."""
    s = table_.sizes[table_.size_name(name)]
    return {"param": name, "size": table_.size_name(name), "unit": unit, "value": s["value"], "min": s["min"],
            "max": s["max"]}


def line(a, b, entity):
    return {"kind": "line", "start": list(a), "end": list(b), "entity": entity}


def rect_curves(prefix, x0, y0, x1, y1):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [line(corners[i], corners[(i + 1) % 4], "%s%d" % (prefix, i)) for i in range(4)]


def circle(center, radius, entity):
    return {"kind": "circle", "center": list(center), "radius": radius, "entity": entity}


def loop(curves, outer=True):
    return {"outer": outer, "curves": curves}


def profile(sketch, token, loops, frame=IDENT, reference=None):
    out = {"sketch": sketch, "sketch_token": token, "frame": frame, "space": "sketch", "loops": loops}
    if reference:
        out["reference"] = reference
    return out


def extrude(index, *profiles):
    return {"index": index, "name": "Extrude%d" % index, "type": "ExtrudeFeature", "data": {"profiles": list(profiles)}}


def capture(*items):
    return {"capture": 3, "items": list(items)}


def sketch_state(token, profiles, frame=IDENT):
    return {token: {"frame": frame, "profiles": profiles}}


def read(sketches=None, points=None, lines=None, params=None, box=None):
    out = {"sketches": sketches or {}, "points": points or {}, "lines": lines or {}, "params": params or {}}
    if box is not None:
        out["box"] = box
    return out


def state(values, state_read, built=True, e0=False):
    out = {"values": values, "built": built, "read": state_read}
    if e0:
        out["e0"] = True
    return out
