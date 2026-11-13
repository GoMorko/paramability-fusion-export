"""What the reader reads at each probe state."""
from ...params import defaults
from ...params.size_table import DERIVED, FREE
from ...capture_model.step_kinds import pattern_kind
from .covered import FACE, scan
from .references import refs


def _numeric_model(table):
    return [m for m in table.model_params.values() if defaults.dim_of_unit(m.get("unit")) is not None]


def _plain_number(text):
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def symmetric_patterns(capture):
    """`{ key: { "index", "kind" } }` of the patterns whose copies the reader reads again at every state: a pattern that
    spreads copies to both sides of the original and has a count that follows a parameter. The tries tell where
    Fusion puts the copies for the counts it can reach (`translator/repeat/symmetric.py`). `kind` is `rectangular` or
    `circular`; `key` is the timeline index as text."""
    out = {}
    for item in capture.get("items") or []:
        kind = pattern_kind(item.get("type"))
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if kind is None or item.get("suppressed") or not item.get("in_target_component", True):
            continue
        names = ("quantity_one", "quantity_two") if kind == "rectangular" else ("quantity",)
        sides = ("symmetric_one", "symmetric_two") if kind == "rectangular" else ("symmetric",)
        if not any(data.get(side) for side in sides):
            continue
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        if any(not _plain_number((params.get(name) or {}).get("expression")) for name in names if name in params):
            out[str(item["index"])] = {"index": item["index"], "kind": kind}
    return out


def request(capture, table, covered=None, wanted=None):
    """What the reader reads at each state, or None when no sketch is covered and no reference can be followed.

    `covered` limits the sketches to these tokens (the ones whose first read matched the capture) and the faces to these
    key prefixes. `wanted` limits the references to these keys.
    `{ "sketches": [token], "points": [token], "lines": [token], "params": [Fusion name], "target": True,
       "curves": { sketch token: [curve token] },
       "refs": { key: { "token", "type", "path", "shape" } },
       "faces": { key prefix: { "token", "before" } } }`; `curves` lists the sketch curves of sweep paths to read
       (left out when empty), `refs` is left out when empty (a face or plane of the part adds `"own": true`). `native`
       lists the sketches of tool bodies from other components, and is left out when there are none. `faces` are the
       flat faces steps use as outlines, read with the timeline marker at `before` (the step's timeline index), and is
       left out when empty. `patterns` are the symmetric patterns with a sized count (`symmetric_patterns`).
    """
    found = scan(capture)
    tokens = [t for t in found.covered if covered is None or t in covered]
    followed = {r["key"]: dict({"token": r["ref"]["token"], "type": r["ref"].get("type") or "",
                                "path": r["ref"].get("path") or "", "shape": r["shape"]},
                               **({"own": True} if r["ref"].get("own") else {}))
                for r in refs(capture) if r["shape"] and (wanted is None or r["key"] in wanted)}
    faces = {t["sketch_token"]: {"token": t["profile"]["token"], "before": t["item"]} for t in found.targets
             if t["kind"] == FACE and (covered is None or t["sketch_token"] in covered)}
    if not tokens and not followed and not faces:
        return None
    points, lines, curves = [], [], {}
    for target in found.targets:
        if target["sketch_token"] not in tokens:
            continue
        if target["kind"] == "hole":
            points.extend(target["point_tokens"])
        elif target["kind"] == "axis":
            lines.append(target["entity"])
        elif target["kind"] == "path":
            curves.setdefault(target["sketch_token"], []).extend(c["entity"] for c in target["path"]["curves"])
    names = [e.name for e in table.entries if e.state in (FREE, DERIVED)]
    names += [m["name"] for m in _numeric_model(table)]
    out = {"sketches": tokens, "points": list(dict.fromkeys(points)), "lines": list(dict.fromkeys(lines)),
           "params": list(dict.fromkeys(names)), "target": True}
    if curves:
        out["curves"] = {t: list(dict.fromkeys(names)) for t, names in curves.items()}
    native = [t for t in tokens if t in found.native]
    if native:
        out["native"] = native
    if followed:
        out["refs"] = followed
    if faces:
        out["faces"] = faces
    patterns = symmetric_patterns(capture)
    if patterns:
        out["patterns"] = patterns
    return out
