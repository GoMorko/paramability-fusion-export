"""One JSON snapshot of what both translators write for every test capture, to compare two versions of the code.

    python3 scripts/output_snapshot.py <out.json> [capture or report .json ...]

Run it from the repository root before a change and again after it, then read the difference with
`python3 scripts/output_diff.py before.json after.json`. The output goes under /tmp or tests/local (git-ignored),
never into a tracked folder. Modes per capture (key "p" is the .paramability translator, "o" the Orca translator):
  plain    no size table (every file in tests/fixtures/captures);
  sized    every user parameter ticked (as `scripts/orca_live_check.table_for` does);
  motion   sized, with the file of the same name in tests/fixtures/motion;
  local    reports named in tests/local/captures.json, replayed with their own probe states as
           `tests/test_local_captures.replay` does (only when that file exists);
  orca     local Orca reports (any `*report.json` under tests/local whose `outcome` is "orcaRecipe"),
           with the parameters their report lists ticked.
A capture that raises is recorded as its exception type and message.
"""
import hashlib
import json
import os
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))
sys.path.insert(0, ROOT)

from lib import translator  # noqa: E402
from lib.orca_recipe.feature import FIELDS  # noqa: E402
from lib.orca_recipe.recipe import serialize  # noqa: E402
from lib.params import size_table  # noqa: E402
from lib.sketch_values.motion import Motion  # noqa: E402
from scripts.orca_live_check import table_for  # noqa: E402

try:
    from lib import orca_translate  # noqa: E402
except ImportError:
    orca_translate = None

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "captures")
MOTION = os.path.join(ROOT, "tests", "fixtures", "motion")
LOCAL = os.path.join(ROOT, "tests", "local")


def digest(obj):
    """sha256 of the canonical JSON of `obj`."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def plain(obj):
    """`obj` as JSON data: tuples as lists, enums and objects by their value or fields, keys sorted by `dump`."""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [plain(v) for v in obj]
        return sorted(items, key=json.dumps) if isinstance(obj, (set, frozenset)) else items
    if hasattr(obj, "__dict__"):
        return {k: plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def failed(exc):
    return {"error": "%s: %s" % (type(exc).__name__, exc)}


def paramability(capture, table, motion=None):
    try:
        return summary(translator.translate(capture, size_table=table, motion=motion))
    except Exception as exc:  # noqa: BLE001 - a raising capture is data
        return failed(exc)


def summary(r):
    """What is kept of a translation result `r`."""
    recipe = plain(r.recipe)
    items = [i for i in r.items if i["verdict"] != "skipped"]
    return {
        "recipe_sha": digest(recipe), "recipe": recipe,
        "verdicts": [[i["index"], i["name"], i["verdict"], plain(i["steps"])] for i in items],
        "skipped": sum(i["verdict"] == "skipped" for i in r.items),
        "refusal": plain(r.refusal),
        "gaps": [[g.get("index"), g.get("cause")] for g in r.gaps],
        "fixed": sorted(f["name"] for f in r.fixed),
        "loose": sorted(f["name"] for f in r.loose),
        "cuts": sorted([c["name"], c.get("min"), c.get("max")] for c in r.cuts),
        "dropped": sorted([d["name"], d["used"]] for d in r.dropped),
        "texts": {"notes": digest(r.notes), "fixed": digest(r.fixed), "loose": digest(r.loose),
                  "cuts": digest(r.cuts), "dropped": digest(r.dropped), "gaps": digest(r.gaps),
                  "item_notes": digest([i["note"] for i in r.items])},
    }


def feature_view(feature):
    """A feature as its type, name and the fields that differ from Orca's default."""
    fields = {f.name: plain(getattr(feature, f.name)) for f in FIELDS
              if f.name not in ("type", "name") and plain(getattr(feature, f.name)) != plain(f.default())}
    return {"type": int(feature.type), "name": feature.name, "fields": fields, "expr": dict(feature.expr)}


def orca(capture, table):
    if orca_translate is None:
        return None
    try:
        o = orca_translate.translate(capture, table)
    except Exception as exc:  # noqa: BLE001
        return failed(exc)
    return {
        "recipe_sha": hashlib.sha256(serialize(o.recipe)).hexdigest(),
        "features": [feature_view(f) for f in o.recipe.features],
        "variables": dict(o.variables),
        "verdicts": [[i["index"], i["name"], i["verdict"]] for i in o.items if i["verdict"] != "skipped"],
        "left_out": [[g["index"], g["cause"]] for g in o.left_out],
        "parameters": [[p["name"], p["outcome"]] for p in o.parameters],
        "bound": len(o.bound),
        "texts": {"notes": digest(o.notes), "left_out": digest(o.left_out), "parameters": digest(o.parameters),
                  "item_notes": digest([i["note"] for i in o.items])},
    }


def read_capture(path):
    with open(path, encoding="utf-8") as f:
        found = json.load(f)
    return found, (found["capture"] if isinstance(found.get("capture"), dict) else found)


def fixture_modes(path):
    _, capture = read_capture(path)
    table = table_for(capture)
    modes = {"plain": {"p": paramability(capture, None), "o": orca(capture, None)}}
    if table is None:
        return modes
    modes["sized"] = {"p": paramability(capture, table), "o": orca(capture, table)}
    motion_path = os.path.join(MOTION, os.path.basename(path))
    if os.path.exists(motion_path):
        with open(motion_path, encoding="utf-8") as f:
            try:
                modes["motion"] = {"p": paramability(capture, table, Motion.from_json(json.load(f)))}
            except Exception as exc:  # noqa: BLE001
                modes["motion"] = {"p": failed(exc)}
    return modes


def local_config():
    """The test module that replays private packages, or None when there is no local data."""
    if not os.path.exists(os.path.join(LOCAL, "captures.json")) and not os.environ.get("PARAMABILITY_LOCAL_CAPTURES"):
        return None
    from tests import test_local_captures
    return test_local_captures if test_local_captures.DATA else None


def local_modes(snap):
    """Replays of the private packages and report files that the local test file lists and that are present."""
    local = local_config()
    if local is None:
        return
    seen = set()
    for kind in sorted(local.DATA.get("cases", {})):
        for case in local.cases(kind):
            key = "package" if "package" in case else "file"
            name = case.get(key)
            if not name or name in seen or not local._present(case, key):
                continue
            seen.add(name)
            try:
                if key == "package":
                    report = local.package_report(case)
                    if (report.get("probe") or {}).get("states"):
                        entry = {"p": summary(local.replay(case)[0])}
                    else:  # an older package without probe states: the tests translate its capture as it is
                        entry = {"p": paramability(report["capture"], None)}
                else:
                    _, capture = read_capture(local._path(case, key))
                    entry = {"p": paramability(capture, None)}
            except Exception as exc:  # noqa: BLE001
                entry = {"p": failed(exc)}
            snap["local/" + name] = {"local": entry}


def orca_reports():
    """Paths of local Orca reports: any `*report.json` under tests/local whose `outcome` is "orcaRecipe"."""
    found = []
    for folder, _, names in os.walk(LOCAL):
        for name in sorted(names):
            if name.endswith("report.json"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    if json.load(f).get("outcome") == "orcaRecipe":
                        found.append(path)
    return sorted(found)


def orca_modes(snap):
    for path in orca_reports():
        try:
            found, capture = read_capture(path)
            listed = (found.get("orca") or {}).get("parameters") or found.get("parameters")
            listed = listed if isinstance(listed, list) else []
            user = {p["name"] for p in (capture.get("parameters") or {}).get("user") or []}
            ticked = [p["name"] for p in listed if p.get("name") in user]
            table = table_for(capture, ticked) if ticked else table_for(capture)
            entry = {"o": orca(capture, table)}
        except Exception as exc:  # noqa: BLE001
            entry = {"o": failed(exc)}
        snap["orca/" + os.path.relpath(path, LOCAL)] = {"orca": entry}


def build(extra):
    snap = {}
    paths = [os.path.join(FIXTURES, n) for n in sorted(os.listdir(FIXTURES)) if n.endswith(".json")] + list(extra)
    for path in paths:
        snap[os.path.basename(path)] = fixture_modes(path)
    local_modes(snap)
    orca_modes(snap)
    return snap


def counts(snap):
    out, errors = {}, []
    for key, modes in snap.items():
        for mode, sides in modes.items():
            out[mode] = out.get(mode, 0) + 1
            errors += [(key, mode, side) for side, r in sides.items() if r and "error" in r]
    return out, errors


def check_target(out):
    """Refuse an output path inside a tracked folder of the repository."""
    full = os.path.realpath(out)
    inside = os.path.commonpath([full, ROOT]) == ROOT
    if inside and os.path.commonpath([full, os.path.realpath(LOCAL)]) != os.path.realpath(LOCAL):
        sys.exit("Write the snapshot under /tmp or tests/local, not into a tracked folder: %s" % out)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    check_target(argv[0])
    started = time.time()
    snap = build(argv[1:])
    with open(argv[0], "w", encoding="utf-8") as f:
        json.dump(snap, f, sort_keys=True, indent=0)
    by_mode, errors = counts(snap)
    print("captures %d, modes %s, seconds %.1f, errors %d" % (len(snap), by_mode, time.time() - started, len(errors)))
    for key, mode, side in errors[:12]:
        print("  %s %s %s: %s" % (key, mode, side, snap[key][mode][side]["error"][:140]))


if __name__ == "__main__":
    main(sys.argv[1:])
