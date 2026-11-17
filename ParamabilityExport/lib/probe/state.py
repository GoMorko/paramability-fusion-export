"""One probe state: the sizes a row set and what the design read there. `build` and `plan` take states as these records
or in their `report.json` form; `json` writes that form."""
from dataclasses import dataclass, field

from ..geometry.tolerances import BODY_TOLERANCE_MM

# The parts of a read that a state keeps in `report.json`.
REPORT_READ_KEYS = ("sketches", "points", "lines", "params", "box", "volume_mm3", "area_mm2", "pieces", "refs", "faces",
                    "patterns", "unread")
# Two reads of the volume of a body agree (mm3, or this share of the volume).
VOLUME_TOLERANCE_MM3 = 1e-4
VOLUME_RELATIVE = 1e-6
# Two reads of the area of a body agree (mm2, or this share of the area).
AREA_TOLERANCE_MM2 = 1e-4
AREA_RELATIVE = 1e-6


@dataclass(frozen=True)
class ProbeState:
    """A state of the probe (see `build` for how the fit uses it).

    values: Fusion name to the manifest number the row set; a size that is missing stays at its value now.
    built: False when Fusion could not build the part there; `failed` then names the first step in error. Also False
      when Fusion built it in several separate pieces while it was one at E0 (`probe.pieces.came_apart`): `pieces`
      then holds how many, `failed` is empty and `read` is None.
    read: the probe state read there (`fusion_reader.probe_state`), or None.
    e0: True for the first read, at the values now, before any size changed.
    start: the read with the values back, before the row ran, or None when it was not read.
    put_back: the read once a sketch left on its other solution was put back before the row ran, or None.
    again: True for a row run a second time from a checked start.
    changed: True when the row's own size changed a followed outline (set by `marked_states` for `plan`).
    warned: True when Fusion built the part there but a step it is built from shows a new warning: the state counts as
      one that did not build, `failed` names that step.
    """

    values: dict = field(default_factory=dict)
    built: bool = True
    read: object = None
    e0: bool = False
    failed: object = None
    start: object = None
    put_back: object = None
    again: bool = False
    changed: bool = False
    pieces: object = None
    warned: bool = False

    @classmethod
    def from_json(cls, data):
        """The record of a state in its `report.json` form (other keys are ignored)."""
        start, put_back = data.get("start"), data.get("put_back")
        return cls(values=data.get("values") or {}, built=data.get("built") is not False, read=data.get("read"),
                   e0=bool(data.get("e0")), failed=data.get("failed"),
                   start=start if isinstance(start, dict) else None,
                   put_back=put_back if isinstance(put_back, dict) else None,
                   again=bool(data.get("again")), changed=bool(data.get("changed")), pieces=data.get("pieces"),
                   warned=bool(data.get("warned")))

    def json(self):
        """The state as `report.json` keeps it: the reads only with `REPORT_READ_KEYS`."""
        out = {"values": self.values, "built": self.built}
        if self.failed:
            out["failed"] = self.failed
        if self.pieces:
            out["pieces"] = self.pieces
        if self.warned:
            out["warned"] = True
        if self.e0:
            out["e0"] = True
        if self.again:
            out["again"] = True
        for key, read in (("read", self.read), ("start", self.start), ("put_back", self.put_back)):
            if isinstance(read, dict):
                out[key] = {k: v for k, v in read.items() if k in REPORT_READ_KEYS}
        return out


def as_states(states):
    """`states` as records: a record stays as it is, a dict is read as its `report.json` form."""
    return [s if isinstance(s, ProbeState) else ProbeState.from_json(s) for s in states]


def box_numbers(read):
    box = read.get("box") if isinstance(read, dict) else None
    if not isinstance(box, dict):
        return None
    low, high = box.get("min"), box.get("max")
    if not all(isinstance(v, (list, tuple)) and len(v) == 3 for v in (low, high)):
        return None
    numbers = list(low) + list(high)
    return numbers if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers) else None


def _number(read, key):
    value = read.get(key) if isinstance(read, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _differs(a, b, tolerance, relative):
    return a is not None and b is not None and abs(a - b) > max(tolerance, relative * abs(a))


def body_changed(before, now):
    """True when the body reads differently in two probe states: its box moved, or its volume or area changed when
    both states read it. False when they agree or the body cannot be compared (a state without a box)."""
    a, b = box_numbers(before), box_numbers(now)
    if a is not None and b is not None and any(abs(x - y) > BODY_TOLERANCE_MM for x, y in zip(a, b)):
        return True
    return (_differs(_number(before, "volume_mm3"), _number(now, "volume_mm3"), VOLUME_TOLERANCE_MM3, VOLUME_RELATIVE)
            or _differs(_number(before, "area_mm2"), _number(now, "area_mm2"), AREA_TOLERANCE_MM2, AREA_RELATIVE))


def body_compared(before, now):
    """True when two probe states read enough of the body to tell that it did not change: a box and a volume in
    both. A box alone misses a change inside it (a deeper pocket, a wider hole)."""
    return all(box_numbers(r) is not None and _number(r, "volume_mm3") is not None for r in (before, now))
