"""A small JSON Schema checker for the keywords the pinned recipe schema uses.

It fails on any other keyword, so a schema copy that grows a keyword is noticed here instead of passing unchecked.
"""
import json
import os
import re

SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ParamabilityExport", "lib", "schema")


def _newest_recipe_schema():
    """The recipe schema copy with the highest version, so copying a new one from the app needs no code change."""
    found = []
    for name in os.listdir(SCHEMA_DIR):
        match = re.fullmatch(r"paramability\.recipe\.v(\d+)\.schema\.json", name)
        if match:
            found.append((int(match.group(1)), name))
    return os.path.join(SCHEMA_DIR, max(found)[1])


SCHEMA_PATH = _newest_recipe_schema()

HANDLED = {
    "type", "$ref", "$defs", "properties", "required", "additionalProperties", "const", "enum", "anyOf",
    "items", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum",
}
ANNOTATIONS = {"description"}


class UnsupportedKeyword(Exception):
    pass


def load_schema(path=SCHEMA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _type_ok(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise UnsupportedKeyword("type %s" % name)


def _resolve(root, ref):
    if not ref.startswith("#/"):
        raise UnsupportedKeyword("$ref %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(value, schema, root=None, path="$"):
    """Return a list of 'path: message' errors; empty when the value fits."""
    root = root if root is not None else schema
    errors = []
    for key in schema:
        if key not in HANDLED and key not in ANNOTATIONS:
            raise UnsupportedKeyword(key)
    if "$ref" in schema:
        return validate(value, _resolve(root, schema["$ref"]), root, path)
    if "anyOf" in schema:
        branches = [validate(value, b, root, path) for b in schema["anyOf"]]
        if not any(not b for b in branches):
            best = min(branches, key=len)
            return ["%s: no alternative fits (closest: %s)" % (path, best[0] if best else "?")]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            return ["%s: expected %s" % (path, "/".join(types))]
    if "const" in schema and value != schema["const"]:
        errors.append("%s: must be %r" % (path, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        errors.append("%s: %r is not one of %r" % (path, value, schema["enum"]))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append("%s: shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append("%s: longer than %d" % (path, schema["maxLength"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append("%s: below %s" % (path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append("%s: above %s" % (path, schema["maximum"]))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append("%s: fewer than %d items" % (path, schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append("%s: more than %d items" % (path, schema["maxItems"]))
        if "items" in schema:
            for i, element in enumerate(value):
                errors.extend(validate(element, schema["items"], root, "%s[%d]" % (path, i)))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append("%s: missing '%s'" % (path, name))
        for name, sub in value.items():
            if name in props:
                errors.extend(validate(sub, props[name], root, "%s.%s" % (path, name)))
            elif schema.get("additionalProperties") is False:
                errors.append("%s: unexpected '%s'" % (path, name))
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(sub, schema["additionalProperties"], root, "%s.%s" % (path, name)))
    return errors


def check_recipe(recipe, schema=None):
    schema = schema or load_schema()
    return validate(recipe, schema)
