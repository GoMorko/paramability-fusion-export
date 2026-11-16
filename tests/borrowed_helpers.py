"""`sweep_borrowed` (a sweep of an outline of the sketch Rim of the component Lid) with the data on where its sizes
act, for the tests of the sizes that may move a borrowed outline in both outputs."""
from tests.probe_helpers import user


def known_movers(capture, graph=None):
    """The capture with `dependents` on every user parameter, the size lid_w that drives another sketch of Lid, cap_w
    that drives a sketch of a third component Cap, and a sketch graph of Rim found by its token (by default one
    without projected geometry; `graph` adds or replaces keys)."""
    users = capture["parameters"]["user"]
    for p in users:
        p.setdefault("dependents", [])
    users.append(dict(user("lid_w", "20 mm", 20), dependents=[
        {"name": "d8", "kind": "sketchDimension", "component": "cLid", "sketch": "LidTop", "sketch_token": "sT"}]))
    users.append(dict(user("cap_w", "5 mm", 5), dependents=[
        {"name": "d7", "kind": "sketchDimension", "component": "cCap", "sketch": "CapTop", "sketch_token": "sC"}]))
    capture.setdefault("sketch_graphs", []).append(dict({"sketch": "Rim", "token": "sR", "borrowed": True,
                                                         "component": {"token": "cLid", "name": "Lid"},
                                                         "points": [], "curves": []}, **(graph or {})))
    return capture


def projected(source, component=""):
    """Sketch graph keys with one point projected from `source` ("own": the part's component, "other": `component`)."""
    return {"points": [{"id": 0, "xy": [0, 0], "reference": {"source": source, "component": component,
                                                              "token": "e1"}}]}


def with_own_rim(capture):
    """`sweep_borrowed` with a sketch of the part also named Rim, whose dimension own_mm drives."""
    capture["parameters"]["user"].append(user("own_mm", "8 mm", 8))
    capture["parameters"]["model"].append({
        "name": "d9", "expression": "own_mm", "value": 0.8, "unit": "mm", "kind": "derived", "role": "",
        "dependency_parameters": ["own_mm"],
        "created_by": {"kind": "sketchDimension", "token": "tok_d9", "name": "", "sketch": "Rim", "component": ""}})
    capture["sketch_graphs"] = [{"sketch": "Rim", "token": "own_rim", "dimensions": [{"param": "d9"}]}]
    return capture
