"""The probe interface the try runner and both export pipelines call: `SizeProbe` for one part and `ProbeGroup` for
several parts over shared rows both have every member."""
from typing import Protocol


class Probe(Protocol):
    """What `pipeline.ProbeRun` and the pipelines ask of a probe. A read is what `read_now` gives (one probe state, or
    one per part for a group); the caller hands it back as it is. Rows are `probe.plan` rows; `sizes` are the probe
    size dicts (`size_offers.probe_sizes`) and `room` the rows the cap leaves.

    read_now(values, outline, park): read the design as it is now (`SizeProbe.read_now`).
    followed_sketches(): tokens of the sketches read at every row (the sketch keeper keeps them).
    left_start(read), off_start(read), off_outline(read), matches_start(read): what a read shows about the followed
      sketches (`off_start` gives the tokens of those that read otherwise than at the start).
    probe_rows(sizes, extra), pair_rows, far_rows, far_pair_rows, nearer_rows, check_rows (sizes, room): the rows of
      each phase, in the order `ProbeRun.measure` asks for them. `far_rows` and `nearer_rows` take `only`, the Fusion
      names of the sizes to plan (all when None); `far_rows` without it plans the far rows of every size not planned
      yet and ends the far phase.
    far_order(sizes, late): the Fusion names of the tried sizes in the order their far rows run, the sizes in `late`
      (trouble outside the part in their tries so far) last.
    add_states(entries): the states of the rows run (`ProbeRun.probe_states`).
    counts_warning(step): True when a new warning on the timeline item `step` (`(position, name)`) makes a row count
      as not built (a step a part is built from, `tried_ranges.part_step`).
    note_recovery(record), note_stop(record, unrun), note_time_limit(record, unrun): what the runner did, for the
      report (`note_time_limit`: the time limit of the tries, and the rows it kept from running).
    note_ended(record, unrun): a try left steps of another component worse with the values back and the tries of the
      sizes in `record` ended there while the others went on (`record` None when only `unrun` is new).
    reads_as_start(read): True when a read with every value back shows the part as at the start of the tries (the
      followed sketches, the references, the box and the body).
    note_unfinished(sizes): after the tries stopped early or ran out of time, keep the sides of the sizes whose search
      for the last value that builds was still to come (`Motion.spans` `unfinished`).
    time_left_out(): the sizes the time limit left without a try that built on its own.
    discovery_rows(candidates, room), set_discovery_base(read, put_back), discover(entries), also_changes: the
      discovery rows and the unticked parameters they showed changing the part.
    finish(after, labels): build the motion; returns the sizes the probe cannot follow.
    measure_restore(after), restore_unchecked, restore_changed: the gap to the first read once the values are back,
      the sketches that could not be compared and those found on another outline.
    keep_body_start(): read the body now and keep it as the start of the end check (after the first rebuild of the
      tries).
    measure_body(): what of the body differs from its start once the design is back (`states.BodyCheck`), or None
      when it cannot be compared.
    """

    also_changes: list
    restore_unchecked: list
    restore_changed: list

    def read_now(self, values=None, outline=False, park=False): ...

    def followed_sketches(self): ...

    def left_start(self, read): ...

    def off_start(self, read): ...

    def off_outline(self, read): ...

    def matches_start(self, read): ...

    def probe_rows(self, sizes, extra=()): ...

    def pair_rows(self, sizes, room): ...

    def far_order(self, sizes, late=()): ...

    def far_rows(self, sizes, room, only=None): ...

    def far_pair_rows(self, sizes, room): ...

    def nearer_rows(self, sizes, room, only=None): ...

    def check_rows(self, sizes, room): ...

    def add_states(self, entries): ...

    def counts_warning(self, step): ...

    def note_recovery(self, record): ...

    def note_stop(self, record, unrun=()): ...

    def note_ended(self, record, unrun=()): ...

    def reads_as_start(self, read): ...

    def note_time_limit(self, record, unrun=()): ...

    def note_unfinished(self, sizes): ...

    def time_left_out(self): ...

    def discovery_rows(self, candidates, room): ...

    def set_discovery_base(self, read, put_back=None): ...

    def discover(self, entries): ...

    def finish(self, after, labels): ...

    def measure_restore(self, after): ...

    def keep_body_start(self): ...

    def measure_body(self): ...
