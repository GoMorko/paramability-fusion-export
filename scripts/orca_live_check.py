"""Live check of the Orca output without Fusion: write a capture as an OrcaSlicer 2.5 project, then read back what
the Design tab built.

    python3 scripts/orca_live_check.py write <capture> <out.3mf> [--tick name ...] [--untick name ...]
    python3 scripts/orca_live_check.py check [<capture>] [--set name=formula ...]

`<capture>` is a fixture name of tests/fixtures/captures, a capture file, a report.json of an export (its `capture`
is used), `box_graph` (the centred box fixture with the graph of its sketch, tests/derived_fixtures.py) or
`plate_hole_graph` (a 40 by 20 plate with a hole placed from its edge, tests/test_orca_translate.py). Every
user parameter is ticked unless `--tick` names some. The plate gets a box of the part's size in place of the real
mesh (the Design body is what is checked).

`check` talks to a test OrcaSlicer started with the control socket (`ORCA_CAD_MCP=1 ... --datadir <test folder>
<out.3mf>`, socket /tmp/orca-cad-mcp.sock): it prints each body's box and volume, and with a capture the box and
volume the capture expects. `--set` changes a variable first (`set_variable`) and prints the body again.
"""
import argparse
import copy
import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ParamabilityExport"))
sys.path.insert(0, ROOT)

from lib.export_plan.orca_export import plan_orca_export, translate_for_orca, write_orca_package  # noqa: E402
from lib.geometry import mesh as meshes  # noqa: E402
from lib.orca_translate.place import Placement, moved_box  # noqa: E402
from lib.params import size_table  # noqa: E402

SOCKET = "/tmp/orca-cad-mcp.sock"
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "captures")


def load(name):
    if name == "box_graph":
        from tests.derived_fixtures import box_capture
        return copy.deepcopy(box_capture())
    if name == "plate_hole_graph":
        from tests.test_orca_translate import plate_with_hole
        return plate_with_hole()
    path = name if os.path.exists(name) else os.path.join(FIXTURES, name + ".json")
    with open(path, encoding="utf-8") as f:
        found = json.load(f)
    return found["capture"] if isinstance(found.get("capture"), dict) else found


def table_for(capture, tick=None, untick=()):
    params = (capture.get("parameters") or {}).get("user") or []
    if not params:
        return None
    names = [p["name"] for p in params] if not tick else list(tick)
    names = [n for n in names if n not in set(untick)]
    return size_table.build(params, names, (capture.get("parameters") or {}).get("model") or [],
                            capture.get("design_units") or "mm")


def expected(capture):
    """(box on the plate, volume) the capture says the body has, placed as the export places it (by the copy's own
    box when steps are left out and it differs)."""
    target = capture.get("target") or {}
    place = translate_for_orca(capture, capture.get("up_axis") or "z").place
    box = moved_box(place.to_orca, target["box"]) if target.get("box") else None
    return box, target.get("volume_mm3")


def write(args):
    capture = load(args.capture)
    table = table_for(capture, args.tick, args.untick or ())
    place = Placement(capture)
    root_box = moved_box(place.to_orca, capture["target"]["box"])
    # The plate box is given in root coordinates, so the turn and move of the output put it where the part is.
    back = place.root_to_orca.inverse()
    vertices, triangles = meshes.box_mesh(root_box)
    vertices = [tuple(sum(back.rows[i][k] * v[k] for k in range(3)) + back.offset[i] for i in range(3))
                for v in vertices]
    package = plan_orca_export(capture, (vertices, triangles), capture.get("design") or "Part", "live check",
                               capture.get("up_axis") or "z", size_table=table)
    write_orca_package(args.out, package)
    orca = package.report.get("orca") or {}
    print("wrote %s" % args.out)
    for f in orca.get("features") or []:
        print("  feature %-28s %s" % (f["name"], f["expr"] or ""))
    print("  variables %s" % orca.get("variables"))
    for p in orca.get("parameters") or []:
        print("  parameter %s: %s %s" % (p["name"], p["outcome"], "; ".join(p["reasons"])))
    for g in orca.get("left_out") or []:
        print("  left out %s: %s" % (g["name"], g["reason"]))
    box, volume = expected(capture)
    print("  expected box %s volume %s" % (box, volume))


class Orca:
    def __init__(self, path=SOCKET):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(60)
        self.sock.connect(path)
        self.file = self.sock.makefile("rwb")
        self.count = 0

    def call(self, method, **params):
        self.count += 1
        self.file.write((json.dumps({"jsonrpc": "2.0", "id": self.count, "method": method, "params": params})
                         + "\n").encode("utf-8"))
        self.file.flush()
        answer = json.loads(self.file.readline())
        if "error" in answer:
            raise RuntimeError("%s: %s" % (method, answer["error"].get("message")))
        return answer["result"]


def show(orca):
    scene = orca.call("describe_scene")
    if scene.get("error"):
        print("  Orca error: %s" % scene["error"])
    for body in scene.get("bodies") or []:
        mass = orca.call("mass_properties", body=body["index"])
        box = body["bbox"]
        print("  body %d %s: box %s .. %s, size %s, volume %.1f" % (
            body["index"], body["name"], _r(box["min"]), _r(box["max"]),
            _r([b - a for a, b in zip(box["min"], box["max"])]), mass.get("volume", float("nan"))))
    return scene


def _r(values):
    return "[%s]" % ", ".join("%.3f" % v for v in values)


def check(args):
    orca = Orca()
    if args.capture:
        box, volume = expected(load(args.capture))
        if box:
            print("expected: box %s .. %s, volume %s" % (_r(box["min"]), _r(box["max"]), volume))
    print("built:")
    show(orca)
    for change in args.set or []:
        name, formula = change.split("=", 1)
        orca.call("set_variable", name=name, expr=formula)
        print("after %s = %s:" % (name, formula))
        show(orca)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write")
    w.add_argument("capture")
    w.add_argument("out")
    w.add_argument("--tick", nargs="*")
    w.add_argument("--untick", nargs="*")
    c = sub.add_parser("check")
    c.add_argument("capture", nargs="?")
    c.add_argument("--set", nargs="*")
    args = parser.parse_args(argv)
    (write if args.command == "write" else check)(args)


if __name__ == "__main__":
    main()
