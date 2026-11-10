"""Every size a copied step reads is followed or marked.

After a translation each user parameter that a copied step reads (in its values, its sketch or the geometry it points
at) must end in one of these states, all visible in the public result: it drives the recipe and the recipe changes
with it, or it is listed as loose with a reason, or as fixed with a reason, or as dropped with a reason that does not
claim "no step reads it". A parameter that stays a free size nothing reads, is dropped with the wrong reason, or can
push a written formula past zero inside its own range breaks the rule.

The reading of the capture below is written here on its own: it does not call the translator's audit.
"""
import copy
import glob
import os
import re
import unittest
from itertools import product

from tests import context  # noqa: F401
from tests.translator_helpers import FIXTURES, load_capture

from lib.params import size_table
from lib.params.expressions import ExpressionError, evaluate
from lib.sketch_values.motion import Motion
from lib.translator import translate

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Recipe keys whose formula must stay above zero for the shape to exist.
POSITIVE = ("distance", "thickness", "width", "height", "radius", "diameter", "depth")


def _walk(value, key=""):
    """Every (key, value) pair of a nested structure."""
    yield key, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key)


def _refs(item):
    """Model parameter names a capture item reads, and the names of the sketches behind it."""
    names, sketches = set(), set()
    for key, value in _walk(item.get("data") or {}):
        if key == "params" and isinstance(value, dict):
            for ref in value.values():
                if isinstance(ref, dict) and ref.get("name"):
                    names.add(ref["name"])
                    names.update(WORD.findall(ref.get("expression", "")))
        elif key == "sketch_params" and isinstance(value, list):
            for ref in value:
                names.add(ref.get("name", ""))
                names.update(ref.get("reads") or ())
        elif key == "sketch" and isinstance(value, str) and value:
            sketches.add(value)
    return names, sketches


def _drawn_around(capture):
    """{sketch name: user parameter names} of the parameters that act on a component a sketch is tied to through
    geometry (other than the part's own): through the component of a model parameter that reads them, or of a step
    that takes the sketch such a parameter sits on."""
    own = ((capture.get("target") or {}).get("component") or {}).get("token")
    takes = {}
    for item in capture["items"]:
        for used in item.get("sketch_inputs") or []:
            takes.setdefault(used.get("token"), set()).add(item.get("component"))
    out = {}
    for record in capture.get("sketch_links") or []:
        tied = {link.get("token") for link in record.get("links") or []} - {own, None, ""}
        for p in capture["parameters"]["user"]:
            homes = set()
            for dep in p.get("dependents") or []:
                homes.add(dep.get("component"))
                homes |= takes.get(dep.get("sketch_token"), set())
            if tied & homes:
                out.setdefault(record["sketch"], set()).add(p["name"])
    return out


def _reference_owners(node, found):
    """Tokens of the components that own the measured references (`ref`, a hole's `position_refs`) under `node`; an
    origin plane or axis only moves with its occurrence and counts for nothing."""
    if isinstance(node, dict):
        for key, value in node.items():
            refs = [value] if key == "ref" else value if key == "position_refs" else []
            for ref in refs:
                owner = ((ref or {}).get("component") or {}).get("token")
                if owner and not ref.get("origin"):
                    found.add(owner)
            _reference_owners(value, found)
    elif isinstance(node, list):
        for value in node:
            _reference_owners(value, found)
    return found


def _acting_on(capture, tokens):
    """User parameter names whose dimensions or features sit in one of the components `tokens`, or in a sketch that a
    step of such a component takes."""
    takes = {}
    for item in capture["items"]:
        for used in item.get("sketch_inputs") or []:
            takes.setdefault(used.get("token"), set()).add(item.get("component"))
    out = set()
    for p in capture["parameters"]["user"]:
        for dep in p.get("dependents") or []:
            homes = {dep.get("component")} | takes.get(dep.get("sketch_token"), set())
            if homes & tokens:
                out.add(p["name"])
    return out


def reads_by_step(capture, only=None):
    """{user parameter name: first step that reads it}, following dependencies through model parameters and the
    geometry of other components a sketch is drawn around. `only` is a set of item indexes to look at (the items the
    translator copied), else every item."""
    params = capture["parameters"]
    user = {p["name"] for p in params["user"]}
    everything = {p["name"]: p for p in params["user"] + params["model"]}
    around = _drawn_around(capture)
    found = {}
    for item in capture["items"]:
        if only is not None and item["index"] not in only:
            continue
        names, sketches = _refs(item)
        for sketch in sketches:
            names |= around.get(sketch, set())
        names |= _acting_on(capture, _reference_owners(item.get("data") or {}, set()))
        for p in params["model"]:
            made = p.get("created_by") or {}
            if made.get("kind") == "sketchDimension" and made.get("sketch") in sketches:
                names.add(p["name"])
        todo, seen = list(names), set()
        while todo:
            name = todo.pop()
            if name in seen or name not in everything:
                continue
            seen.add(name)
            todo.extend(everything[name].get("dependency_parameters") or ())
            todo.extend(WORD.findall(everything[name].get("expression", "")))
        for name in sorted(seen & user):
            found.setdefault(name, item.get("name", ""))
    return found


def _strings(value):
    return [v for _, v in _walk(value) if isinstance(v, str)]


def _recipe_names(recipe):
    """Size names a written formula reaches: named in a feature, or in the formula of a size one of those reads."""
    sizes = recipe.get("sizes", {})
    todo = [w for f in recipe.get("features", []) for s in _strings(f) for w in WORD.findall(s)]
    reached = set()
    while todo:
        name = todo.pop()
        if name in reached or name not in sizes:
            continue
        reached.add(name)
        todo.extend(WORD.findall(sizes[name].get("expr", "")))
    return reached


def _corner_offenders(recipe):
    """(size names, step) for a formula that reaches zero or less at a corner of its sizes' ranges."""
    sizes = recipe.get("sizes", {})
    out = []
    for feature in recipe.get("features", []):
        for key, value in _walk(feature):
            if key not in POSITIVE or not isinstance(value, dict) or "expr" not in value:
                continue
            used = sorted(set(WORD.findall(value["expr"])) & set(sizes))
            if not used or not all("min" in sizes[n] and "max" in sizes[n] and "value" in sizes[n] for n in used):
                continue
            try:
                low = min(evaluate(value["expr"], dict(zip(used, corner)))
                          for corner in product(*[(sizes[n]["min"], sizes[n]["max"]) for n in used]))
            except ExpressionError:
                continue
            if low <= 1e-9:
                out.append((used, feature.get("label", feature.get("kind", ""))))
    return out


def _plane_stays_put(capture, recipe):
    """Mirror planes written as numbers although the capture put them on a face; (size names, step) when an earlier
    step holds a formula, as that face may move with it."""
    on_face = any(((i.get("data") or {}).get("plane") or {}).get("face_point") for i in capture["items"])
    sizes = recipe.get("sizes", {})
    out = []
    for n, feature in enumerate(recipe.get("features", [])):
        origin = (feature.get("plane") or {}).get("origin") if feature.get("kind") == "mirror" else None
        if not on_face or not origin or any(not isinstance(c, (int, float)) for c in origin):
            continue
        used = {w for f in recipe["features"][:n] for s in _strings(f) for w in WORD.findall(s)} & set(sizes)
        out.extend(([name], feature.get("label", "mirror")) for name in sorted(used))
    return out


def offending_sizes(capture, motion=None):
    """[(parameter, step, what is wrong)] for every parameter the rule is broken for, with every user parameter
    ticked as a size."""
    capture = copy.deepcopy(capture)
    params = capture["parameters"]
    table = size_table.build(params["user"], [p["name"] for p in params["user"]], params["model"],
                             capture.get("design_units", "mm"))
    result = translate(capture, size_table=table, motion=motion)
    if result.recipe is None:
        return []
    marked = {m["name"] for m in result.fixed + result.loose if m.get("reason")}
    dropped = {d["name"]: d["reason"] for d in result.dropped if d.get("reason")}
    copied = {v["index"] for v in result.items if v["verdict"] in ("translated", "translatedWithNote")}
    reads = reads_by_step(capture, copied)
    reached = _recipe_names(result.recipe)
    by_size = {e.size_name or e.name: e.name for e in table.entries}
    offenders = []
    for entry in table.entries:
        step = reads.get(entry.name)
        if step is None or entry.name in marked:
            continue
        if entry.name in dropped:
            if "not used by any copied step" in dropped[entry.name]:
                offenders.append((entry.name, step, "dropped as unused although a step reads it"))
            continue
        if entry.state in (size_table.NOT_OFFERED, size_table.CONSTANT):
            if entry.state == size_table.NOT_OFFERED and not entry.reason:
                offenders.append((entry.name, step, "left out without a reason"))
        elif entry.state == size_table.DERIVED and entry.reads and set(entry.reads) <= marked | set(dropped):
            continue  # every size it reads is already marked or dropped, so it is a plain number now
        elif entry.size_name not in reached:
            offenders.append((entry.name, step, "free size no formula reads, or dropped"))
    for used, step in _corner_offenders(result.recipe) + _plane_stays_put(capture, result.recipe):
        for name in used:
            if by_size.get(name) not in marked:
                offenders.append((by_size.get(name, name), step, "formula or plane does not hold over the range"))
    return offenders


# ---- captures of the four cases ------------------------------------------------------------------------------


def _set_model(params, name, **changes):
    for m in params["model"]:
        if m["name"] == name:
            m.update(changes)


def _box_distance(expression, value_mm, depends):
    """The centred box with its extrude length written as `expression`."""
    capture = load_capture("sketch_rect_centred")
    extrude = next(i for i in capture["items"] if i["type"] == "ExtrudeFeature")["data"]
    ref = extrude["params"]["side_one.distance"]
    ref.update(expression=expression, value=value_mm)
    extrude["side_one"]["distance"] = value_mm
    extrude["end_offset"] = value_mm
    _set_model(capture["parameters"], ref["name"], expression=expression, value=value_mm / 10.0,
               dependency_parameters=depends)
    return capture


def corner_capture():
    """pipe_d_mm - 2 * wall_mm: with the pipe 6..24 and the wall 1..4 the length reaches below zero at a corner."""
    return _box_distance("pipe_d_mm - 2 * wall_mm", 8.0, ["pipe_d_mm", "wall_mm"])


def unparsed_capture():
    """The extrude length is written with a unit the parser cannot read, over a size."""
    capture = load_capture("filter_tray_sized")
    extrude = next(i for i in capture["items"] if i["type"] == "ExtrudeFeature")["data"]
    ref = extrude["params"]["side_one.distance"]
    expression = "FilterBox_height_mm * 1 kg / 1 kg"
    ref["expression"] = expression
    _set_model(capture["parameters"], ref["name"], expression=expression)
    return capture


def mirror_capture():
    """Mirror across the top face of the base extrude, a face the size h moves."""
    capture = load_capture("mirror_features")
    capture["capture"] = 3
    capture["parameters"] = {
        "user": [{"name": "h", "expression": "10 mm", "value": 1.0, "unit": "mm", "kind": "length",
                  "value_type": "numeric", "dependency_parameters": [], "comment": ""}],
        "model": [{"name": "d1", "expression": "h", "value": 1.0, "unit": "mm", "kind": "length",
                   "value_type": "numeric", "dependency_parameters": ["h"], "role": "Distance",
                   "created_by": {"kind": "feature", "token": "x", "name": "Extrude1"}}]}
    capture["items"][1]["data"]["params"] = {"side_one.distance": {"name": "d1", "expression": "h", "value": 10.0}}
    capture["items"][4]["data"]["plane"] = {"point": [0, 0, 10], "normal": [0, 0, 1], "face_point": [0, 0, 10]}
    return capture


def names_of(offenders):
    return sorted({name for name, _, _ in offenders})


class FollowOrFlagTest(unittest.TestCase):
    def test_every_fixture_follows_or_flags_what_its_steps_read(self):
        paths = sorted(glob.glob(os.path.join(FIXTURES, "*.json")))
        checked = 0
        for path in paths:
            name = os.path.basename(path)[:-5]
            capture = load_capture(name)
            if not (capture.get("parameters") or {}).get("user") or name in KNOWN_BREAKING:
                continue
            with self.subTest(fixture=name):
                checked += 1
                self.assertEqual(offending_sizes(capture), [])
        self.assertGreater(checked, 8)

    def test_a_fixture_with_a_probe_follows_or_flags_what_its_sketch_reads(self):
        from tests.test_translate_sketch_motion import motion_of
        for name in ("sketch_rect_centred", "sketch_offset_plane", "linked_pipe_hole", "component_ref_reach",
                     "component_ref_hole", "component_foreign_mirror"):
            with self.subTest(fixture=name):
                self.assertEqual(offending_sizes(load_capture(name), motion=motion_of(name)), [])

    def test_the_helper_sees_a_formula_that_reaches_zero_at_a_corner_of_its_ranges(self):
        sizes = {"w": {"value": 40, "min": 20, "max": 80}, "t": {"value": 5, "min": 2.5, "max": 10}}
        recipe = {"sizes": sizes, "features": [{"kind": "extrude", "label": "E", "distance": {"expr": "w - 2 * t"}}]}
        self.assertEqual(_corner_offenders(recipe), [(["t", "w"], "E")])
        sizes["t"]["max"] = 9
        self.assertEqual(_corner_offenders(recipe), [])

    # Each case below is a behaviour the rule demands.

    def test_a_range_corner_that_zeroes_a_formula_is_marked(self):
        # A length of cube minus two walls can reach zero inside the sizes' own ranges.
        self.assertEqual(offending_sizes(corner_capture()), [])

    def test_a_sketch_the_probe_skipped_leaves_its_sizes_loose(self):
        # A probe that ran and skipped the sketches gives no proof, so its sizes cannot silently vanish.
        skipped = Motion(unmeasured={"Sketch1": "not measured", "Sketch2": "not measured"})
        self.assertEqual(offending_sizes(load_capture("sketch_rect_centred"), motion=skipped), [])

    def test_a_formula_the_parser_cannot_read_leaves_its_size_loose(self):
        # A size behind a formula with an unreadable unit must be listed, not frozen without a word.
        self.assertEqual(offending_sizes(unparsed_capture()), [])

    def test_a_mirror_plane_on_a_face_a_size_moves_follows_it_or_is_marked(self):
        # The plane stays at its number while the size moves the face it lies on.
        self.assertEqual(offending_sizes(mirror_capture()), [])


# Fixtures that break the rule, with the behaviour; their sweep runs as an expected failure.
KNOWN_BREAKING = {}


if __name__ == "__main__":
    unittest.main()
