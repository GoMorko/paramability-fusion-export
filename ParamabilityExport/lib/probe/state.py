"""One probe state: the sizes a row set and what the design read there. `build` and `plan` take states as these records
or in their `report.json` form; `json` writes that form."""
from dataclasses import dataclass, field

# The parts of a read that a state keeps in `report.json`.
REPORT_READ_KEYS = ("sketches", "points", "lines", "params", "box", "pieces", "refs", "faces", "patterns", "unread")


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

    @classmethod
    def from_json(cls, data):
        """The record of a state in its `report.json` form (other keys are ignored)."""
        start, put_back = data.get("start"), data.get("put_back")
        return cls(values=data.get("values") or {}, built=data.get("built") is not False, read=data.get("read"),
                   e0=bool(data.get("e0")), failed=data.get("failed"),
                   start=start if isinstance(start, dict) else None,
                   put_back=put_back if isinstance(put_back, dict) else None,
                   again=bool(data.get("again")), changed=bool(data.get("changed")), pieces=data.get("pieces"))

    def json(self):
        """The state as `report.json` keeps it: the reads only with `REPORT_READ_KEYS`."""
        out = {"values": self.values, "built": self.built}
        if self.failed:
            out["failed"] = self.failed
        if self.pieces:
            out["pieces"] = self.pieces
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
