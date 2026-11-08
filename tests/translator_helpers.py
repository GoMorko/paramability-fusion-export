"""Shared helpers for translator tests."""
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
