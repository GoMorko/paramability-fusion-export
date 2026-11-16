"""Captures whose step values read user parameters, for the Orca tests of patterns, revolves and moves, and for the
live check (`scripts/orca_live_check.py write <file>` with a capture these write)."""
import copy

from tests import context  # noqa: F401
from tests.derived_fixtures import box_capture, dimension
from tests.probe_helpers import user
from tests.sketch_solve_helpers import P, Sketch
from tests.translator_helpers import load_capture

from lib.params import size_table

_INTERNAL = {"mm": 0.1, "deg": 3.141592653589793 / 180.0}


def fixture(name):
    found = copy.deepcopy(load_capture(name))
    return found["capture"] if isinstance(found.get("capture"), dict) else found


def sized(capture, index, path, name, number, unit="mm", expression=None):
    """Make the value at `data.params[path]` of the item at timeline `index` read a new user parameter `name`
    (`number` in mm, degrees or a plain count for unit ""). Returns the capture."""
    params = capture.setdefault("parameters", {})
    params.setdefault("user", [])
    params.setdefault("model", [])
    text = expression or ("%g %s" % (number, unit) if unit else "%g" % number)
    params["user"].append(user(name, text, number, unit))
    model = "d_" + name
    params["model"].append({"name": model, "expression": name, "value": number * _INTERNAL.get(unit, 1.0),
                            "unit": unit, "kind": "derived", "role": "", "dependency_parameters": [name],
                            "created_by": {"kind": "feature", "token": "tok_" + model, "name": ""}})
    item = next(i for i in capture["items"] if i["index"] == index)
    item["data"].setdefault("params", {})[path] = {"name": model, "expression": name, "value": number}
    return capture


def table_of(capture, ticked=None):
    params = capture["parameters"]
    names = ticked if ticked is not None else [p["name"] for p in params["user"]]
    return size_table.build(params["user"], names, params["model"])


def circular_sized():
    """`cpattern_part` (four holes over 90 degrees) with its quantity and angle as parameters."""
    capture = fixture("cpattern_part")
    sized(capture, 4, "quantity", "hole_count", 4, unit="")
    return sized(capture, 4, "total_angle_deg", "spread_deg", 90, unit="deg")


def grid_sized():
    """`rpattern_grid_extent` (3 by 2 holes, the first direction over a 40 mm extent) with both counts and the
    distances as parameters."""
    capture = fixture("rpattern_grid_extent")
    sized(capture, 4, "quantity_one", "columns", 3, unit="")
    sized(capture, 4, "distance_one", "row_reach_mm", 40)
    sized(capture, 4, "quantity_two", "rows", 2, unit="")
    return sized(capture, 4, "distance_two", "row_gap_mm", 10)


def symmetric_sized():
    """`rpattern_symmetric_odd` (five holes 10 mm apart, centred on the first) with its count as a parameter."""
    return sized(fixture("rpattern_symmetric_odd"), 4, "quantity_one", "hole_count", 5, unit="")


B1, B2, B3 = ({"token": "t1", "name": "Body1"}, {"token": "t2", "name": "Body2"}, {"token": "t3", "name": "Body3"})


def _box(lo, hi):
    return {"min": list(lo), "max": list(hi)}


def split_by_plane(keep="t1"):
    """`extrude_plate` (40 by 20 by 10) split by the plane x = 25: Body1 keeps x 0 to 25, Body2 (new) is the rest.
    `keep` is the token of the exported piece."""
    capture = fixture("extrude_plate")
    near, far = dict(B1, box=_box((0, 0, 0), (25, 20, 10)), volume=5000.0), \
        dict(B2, box=_box((25, 0, 0), (40, 20, 10)), volume=3000.0)
    capture["items"].append({
        "index": 2, "name": "Split1", "type": "SplitBodyFeature", "suppressed": False, "health": "ok",
        "in_target_component": True, "bodies_before": [B1], "bodies_after": [B1, B2],
        "data": {"tool": {"kind": "plane", "plane": {"point": [25, 0, 0], "normal": [1, 0, 0]}}, "extended": True,
                 "bodies": [dict(B1, box=_box((0, 0, 0), (40, 20, 10)), volume=8000.0)], "pieces": [near, far]}})
    kept = near if keep == "t1" else far
    capture["target"] = {"token": kept["token"], "name": kept["name"], "box": kept["box"],
                         "volume_mm3": kept["volume"]}
    return capture


def split_by_body(inside=False):
    """`extrude_plate` split by a 10 mm cylinder (Body3, kept by Fusion) through x 20, y 10: the core and the plate
    with a hole. The exported piece is the core when `inside`, else the plate with the hole (Body1)."""
    capture = fixture("extrude_plate")
    circle = {"kind": "circle", "center": [20, 10], "radius": 5}
    capture["items"] += [
        {"index": 2, "name": "Sketch2", "type": "Sketch", "suppressed": False, "health": "ok",
         "in_target_component": True, "bodies_after": [], "data": {}},
        {"index": 3, "name": "Extrude2", "type": "ExtrudeFeature", "suppressed": False, "health": "ok",
         "in_target_component": True, "bodies_before": [B1], "bodies_after": [B3],
         "data": {"operation": "newBody", "profiles": [
             {"sketch": "Sketch2", "frame": {"origin": [0, 0, -5], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]},
              "loops": [{"outer": True, "curves": [circle]}]}],
             "start": {"kind": "profilePlane"}, "extent_type": "one",
             "side_one": {"kind": "distance", "distance": 20.0, "taper_deg": 0.0}, "side_two": None,
             "symmetric": None, "thin": False, "participants": [], "target_box_before": None, "end_offset": 20.0}}]
    core = 3.141592653589793 * 25 * 10
    plate = dict(B1, box=_box((0, 0, 0), (40, 20, 10)), volume=8000.0 - core, inside=False)
    middle = dict(B2, box=_box((15, 5, 0), (25, 15, 10)), volume=core, inside=True)
    tool = dict(B3, box=_box((15, 5, -5), (25, 15, 15)), volume=core * 2)
    capture["items"].append({
        "index": 4, "name": "Split1", "type": "SplitBodyFeature", "suppressed": False, "health": "ok",
        "in_target_component": True, "bodies_before": [B1, B3], "bodies_after": [B1, B2],
        "data": {"tool": {"kind": "body", "body": tool, "solid": True}, "extended": False,
                 "bodies": [dict(B1, box=_box((0, 0, 0), (40, 20, 10)), volume=8000.0)],
                 "pieces": [plate, middle]}})
    kept = middle if inside else plate
    capture["target"] = {"token": kept["token"], "name": kept["name"], "box": kept["box"],
                         "volume_mm3": kept["volume"]}
    return capture


def revolve_sized():
    """`revolve_quarter` with its angle as a parameter."""
    return sized(fixture("revolve_quarter"), 1, "extent.angle_deg", "turn_deg", 90, unit="deg")


UP = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}


def placed_hole_pattern():
    """The centred box of `box_capture` with its hole on Sketch2 placed `pipe_offset_mm` left of the sketch origin
    (so its centre follows that size), repeated once 20 mm along y by a rectangular pattern."""
    capture = box_capture()
    capture["items"] = [it for it in capture["items"] if it["type"] not in ("ShellFeature", "FilletFeature")]
    s = Sketch()
    point = s.point(-20.0, 0.0)
    dimension(s, "linear", [P(point), P(0)], 20.0, "d7", "pipe_offset_mm", "horizontal")
    s.con("horizontal_points", P(0), P(point))
    record = s.record()
    record.update(sketch="Sketch2", token="s2")
    capture["sketch_graphs"].append(record)
    hole = next(it for it in capture["items"] if it["type"] == "HoleFeature")
    hole["data"].update(sketch_token="s2", sketch="Sketch2", end_points=[[-20, 0, 32]], sketch_frame=UP)
    pattern = copy.deepcopy(fixture("rpattern_row")["items"][4])
    pattern["index"] = hole["index"] + 1
    pattern["data"].update(sources=[hole["index"]], direction_one=[0, 1, 0], quantity_one=2, distance_one=20.0,
                           elements=[{"id": n + 1, "suppressed": False, "frame": dict(UP, origin=[0, 20 * n, 0])}
                                     for n in range(2)])
    capture["items"].append(pattern)
    return capture
