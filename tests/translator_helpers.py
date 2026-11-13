"""Shared helpers for translator tests."""
import copy
import json
import os

from tests import context  # noqa: F401  puts the add-in on the import path
from tests.schema_check import check_recipe

from lib.translator import translate

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "captures")


def fixture_path(name):
    return os.path.join(FIXTURES, name if name.endswith(".json") else name + ".json")


def load_capture(name):
    with open(fixture_path(name), encoding="utf-8") as f:
        return json.load(f)


def translate_fixture(name, handlers=None):
    return translate(load_capture(name), handlers)


def assert_schema_ok(test, recipe):
    test.assertEqual(check_recipe(recipe), [])


def steps_of(recipe, kind):
    return [s for s in recipe["features"] if s["kind"] == kind]


def close(a, b, tol=1e-9):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def verdict_of(result, index):
    """The verdict of the item at timeline `index`."""
    return [v for v in result.items if v["index"] == index][0]


def edited(name, edit):
    """Translate a fixture after `edit(capture)` changed a copy of it."""
    capture = copy.deepcopy(load_capture(name))
    edit(capture)
    return translate(capture)


def variant(name, edit):
    """Translate a fixture after `edit(data)` changed the data of its last item."""
    capture = load_capture(name)
    edit(capture["items"][-1]["data"])
    return translate(capture)


def _left_out(verdicts, index):
    for verdict in verdicts:
        if verdict["verdict"] == "leftOut" and index in (None, verdict["index"]):
            return verdict
        found = _left_out(verdict.get("tool_steps") or [], index)
        if found is not None:
            return found
    return None


def stopped(result):
    """The refusal `{index, name, type, reason}` when the copy stopped and no recipe was written, else None."""
    return result.refusal if result.recipe is None else None


def left_out(result, index=None):
    """`{index, name, type, reason}` of the step left out as a gap (the first one, at any depth, or the one at
    timeline `index`) when the copy went on and a recipe was written, else None."""
    if result.recipe is None:
        return None
    verdict = _left_out(result.items, index)
    if verdict is None:
        return None
    return {"index": verdict["index"], "name": verdict["name"], "type": verdict["type"], "reason": verdict["note"]}
