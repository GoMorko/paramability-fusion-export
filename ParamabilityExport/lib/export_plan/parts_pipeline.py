"""The export of several bodies of one design into one parts package, from the captures to the manifest. Pure: no
Fusion imports.

The sequence is the one of `pipeline.run_pipeline`, for a list of bodies: a STEP and a capture per body, one size table
over all of them (`size_table.merged`), a first translation per body, one sketch scan whose rows are shared by all
bodies (`probe_flow.ProbeGroup`), a translation per body with its own motion, and the package. A body that cannot be
copied becomes a fixed shape; the others keep their recipes.

A size is one size for every body that reads it. A size that must be fixed for one body is fixed for all: the bodies
are translated again with it fixed until no body asks for more. A size that is loose for one body is loose for the
file (`recipe_export.plan_parts_export`).

Fusion is reached only through `PartsPort`. Parameters are put back on every way out, as in the single body export.
"""
import os
from dataclasses import dataclass, field
from typing import Protocol

from ..params import size_table as size_tables
from ..params.listing import list_parameters
from ..sketch_values.motion import OPTIMISTIC
from ..timing.export_timing import ExportTiming
from ..translator.kept_ranges import built_ranges
from ..design_edit.restore import restore_parameters
from ..design_edit.runner import ExportCancelled
from . import health as health_module
from .body_scope import body_links, scope_inputs
from .part_names import tagged, unique_names
from .pipeline import (ProbeRun, deferred_left, gap_after_settle, settle_after_tries, settle_steps, start_steps,
                       warn_left_off, warn_steps, with_try_seconds)
from .reach_pass import needs_reach, with_reach
from .probe_flow import ProbeGroup, SizeProbe, covers_a_sketch, extra_size_params, kept_size_names
from .recipe_export import PartInput, free_sizes, plan_parts_export, translate_capture
from .size_offers import discovery_sizes, labels, probe_sizes
from .timeline_trim import TryTimeline

# How many times the bodies are translated again because one more size had to be fixed for all.
MAX_SHARE_ROUNDS = 3


class PartsPort(Protocol):
    """What the parts pipeline needs from Fusion: `pipeline.ExportPort` for `count` bodies.

    store, units, progress, warn_unrestored, log: as in `ExportPort`.
    count: how many bodies are picked.
    body_names(): a name per body, for the file.
    export_step(index, path): write the STEP of body `index` as the design is now.
    read_capture(index): the capture dict of body `index`, or the exception that stopped the read.
    read_reach(index, capture, gaps): the `reach` of body `index` when the steps at the timeline indexes `gaps` are
      left out of its copy (`pipeline.ExportPort.read_reach`).
    probe_reader(index): a callable `read(request)` giving one probe state of body `index`, or raising.
    sketch_keeper(tokens): optional, as `pipeline.ExportPort.sketch_keeper`.
    """

    store: object
    units: dict
    count: int

    def body_names(self): ...

    def export_step(self, index, path): ...

    def read_capture(self, index): ...

    def read_reach(self, index, capture, gaps): ...

    def probe_reader(self, index): ...

    def progress(self, verb): ...

    def warn_unrestored(self, names): ...

    def log(self, text): ...


@dataclass
class PartsResult:
    """What `run_parts_pipeline` made: the package parts, the report, and the size table the export ended with."""

    manifest: dict
    files: dict
    report: dict
    table: object
    health: dict = field(default_factory=dict)


def run_parts_pipeline(port, request, tmp):
    """The package of one export of several bodies. `tmp` is a folder that holds the STEP files until the package is
    written. Raises what a failing step raises; the parameters are back by then and `port.warn_unrestored` has named
    any that are not."""
    return _PartsPipeline(port, request, tmp).run()


class _PartsPipeline:
    def __init__(self, port, request, tmp):
        self.port, self.request, self.tmp = port, request, tmp
        self.names = unique_names(port.body_names())
        self.captures = []
        self.steps = []
        self.saved = None
        self.unrestored = []
        self.table = None
        self.part_links = []  # the geometry links of each part's body, by part index
        self.group = None
        self.roll = None
        self.probed = []  # part indexes that have a probe, in the group's order
        self.probe_status = health_module.NOT_NEEDED
        self.probe_error = ""
        self.motions = {}
        self.doubtful = []
        self.also = []
        self.stopped = None  # `ProbeRun.stopped`
        self.keeper = None  # the sketch keeper of the tries (`pipeline.settle_after_tries`)
        self.steps_start = None  # the timeline steps at the start (`pipeline.start_steps`)
        self.settled = None  # `pipeline.settle_steps`
        self.timing = getattr(port, "timing", None) or ExportTiming()

    def run(self):
        self.saved = self.port.store.saved_expressions()
        self.steps_start = start_steps(self)
        done = False
        try:
            result = self._run()
            done = True
            return result
        finally:
            failed = self._restore()
            self._end_roll()
            if not done:
                if failed:
                    self.port.warn_unrestored(failed)
                warn_steps(self)
            warn_left_off(self.port, self.roll, self.settled)

    def _end_trim(self):
        """Turn back on the timeline items suppressed for the tries (a no-op when none were)."""
        if self.roll is not None:
            self.roll.end_trim()

    def _end_roll(self):
        """Turn the suppressed items back on and put the timeline marker back where the export found it (a no-op
        when nothing was changed)."""
        if self.roll is not None:
            self.roll.end()

    def _restore(self):
        """Put every parameter back to its saved expression. Returns the names that would not go back and keeps them for
        the health record. Safe to call at any time."""
        self.unrestored = restore_parameters(self.port.store, self.saved)
        return self.unrestored

    # ---- stages -----------------------------------------------------------------------------------------------

    def _run(self):
        port, request = self.port, self.request
        timing = self.timing
        for index in range(port.count):
            path = os.path.join(self.tmp, "part_%02d.step" % (index + 1))
            with timing.span("step_export"):
                port.export_step(index, path)
            self.steps.append(path)
            with timing.span("capture"):
                self.captures.append(port.read_capture(index))
        with timing.span("size_table"):
            self.table = self._merged_table()

        finals = self._translate_and_measure()

        with timing.span("restore"):
            self._restore()
            self._end_trim()
        with timing.span("probe"):
            gap = self._restore_gap()
        with timing.span("restore"):
            self._end_roll()
            settled = settle_steps(self)
        with timing.span("probe"):
            gap, gap_after = gap_after_settle(self, gap, self._outline_gap)
        reports = self.group.reports() if self.group is not None and self._measured() else []
        if self.roll is not None and self.roll.record is not None:
            for report in reports:
                report["timeline"] = self.roll.record
        probe_of = dict(zip(self.probed, reports))
        with timing.span("probe"):
            shadows = self.group.derived_records(port.log) if self.group is not None else []
        derived_of = dict(zip(self.probed, shadows))
        unchecked = self.group.restore_unchecked if self.group is not None else []
        flipped = ["%s (%s)" % (name, self.names[i]) for i, motion in self.motions.items() if motion is not None
                   for name in motion.flipped]
        health = health_module.make_health(self.unrestored, gap, self.probe_status, self.probe_error, unchecked,
                                           flipped, self.stopped, steps=settled,
                                           deferred_left=deferred_left(self), gap_after_mm=gap_after)
        inputs = [PartInput(self.names[i], self.steps[i], self.captures[i], finals.get(i), self.motions.get(i),
                            probe_of.get(i), derived_of.get(i)) for i in range(port.count)]
        manifest, files, report = plan_parts_export(
            inputs, request.title, request.writer, request.up_axis, size_table=self.table, listing=self._listing(),
            marker=request.marker, loose=[{"name": m["name"], "reason": m["reason"]} for m in self.doubtful],
            health=health, also=self.also, timing=self.timing)
        return PartsResult(manifest, files, report, self.table, health)

    def _merged_table(self):
        """One size table over the model parameters, pattern counts and geometry links of every body that was read."""
        request = self.request
        readable = [c for c in self.captures if isinstance(c, dict)] or [None]
        tables = []
        self.part_links = [body_links(c) if isinstance(c, dict) else [] for c in self.captures]
        for capture in readable:
            model, quantities = scope_inputs(capture, request.model_params)
            tables.append(size_tables.build(
                request.parameters, request.ticked, model, request.design_unit, quantity_params=quantities,
                ranges=request.ranges, links=body_links(capture)))
        return size_tables.merged(tables)

    def _translate_and_measure(self):
        """{part index: the translator's result} of the parts that were translated, after the sketch scan and after
        the sizes fixed for one part were fixed for all. A part missing from it (or None) is translated again by the
        plan, which reports what fails."""
        finals, firsts = {}, {}
        for index, capture in enumerate(self.captures):
            if not isinstance(capture, dict):
                continue
            motion = OPTIMISTIC if covers_a_sketch(capture) else None
            first = self._translation(index, motion, "translate_first")
            if needs_reach(first):
                first = self._with_reach(index, first, motion)
            if first is None:
                continue
            if first.recipe is None:
                if motion is None:
                    finals[index] = first
                continue
            firsts[index] = first
        if not firsts:
            return finals

        free = list(dict.fromkeys(name for first in firsts.values() for name in free_sizes(first.recipe)))
        extra = extra_size_params(self.table, free)
        keep = kept_size_names(self.table, free) | {self.table.size_name(n) for n in extra}
        sizes = probe_sizes(self.table, self.request.parameters, keep=keep)
        with self.timing.span("probe"):
            self._start_probes(list(firsts))
            if self.group is not None:
                self._measure(sizes, extra)
                self._share_cuts()
        for index in firsts:
            result = self._translation(index, self.motions.get(index), "translate_final")
            if result is not None:
                finals[index] = result
        return self._share_fixed(finals)

    # ---- translation ------------------------------------------------------------------------------------------

    def _part_table(self, index):
        """The merged table with only the geometry links of part `index`: sketch names repeat across components, so a
        link of one part must not reach a sketch of another."""
        links = self.part_links[index] if index < len(self.part_links) else []
        return self.table.with_links(links)

    def _translation(self, index, motion, phase):
        """The translator's result for part `index`, a refusal included, or None when it failed. Never raises. `phase`
        is the timing phase the time is added to."""
        try:
            with self.timing.span(phase):
                return translate_capture(self.captures[index], self.request.up_axis, self._part_table(index), motion,
                                         timer=self.timing)
        except Exception as exc:
            self.port.log("translation of %s failed: %r" % (self.names[index], exc))
            return None

    def _with_reach(self, index, first, motion):
        """The translation of part `index` again with the `reach` of the steps `first` left out. The capture of the
        part keeps the answer for the rest of the export."""
        def read(capture, gaps):
            return self.port.read_reach(index, capture, gaps)

        with self.timing.span("reach"):
            self.captures[index] = with_reach(read, self.captures[index], first, self.port.log)
        return self._translation(index, motion, "translate_first")

    def _share_cuts(self):
        """Cut the ranges of a size that several parts read to the narrowest cut over the parts that were probed, so
        every part writes the same range: the form takes one range for a size, from the first part that has it."""
        shared = {}
        for index, motion in self.motions.items():
            for name, cut in built_ranges(self._part_table(index), motion, self.captures[index]).items():
                shared[name] = shared[name].meet(cut) if name in shared else cut
        self.table = self.table.with_narrowed(shared)

    def _share_fixed(self, finals):
        """Translate the parts again with the sizes that one part had to fix fixed in all, until no part asks for more
        (at most `MAX_SHARE_ROUNDS` times). Each reason starts with the part that asked."""
        fixed = {}
        for _ in range(MAX_SHARE_ROUNDS):
            asked = {}
            for index, result in finals.items():
                if result is None or result.recipe is None:
                    continue
                for entry in result.fixed:
                    if entry["name"] not in fixed:
                        asked.setdefault(entry["name"], tagged(self.names[index], entry["reason"]))
            if not asked:
                break
            fixed.update(asked)
            self.table = self.table.with_fixed(asked)
            for index, result in list(finals.items()):
                if result is not None and result.recipe is not None:
                    redone = self._translation(index, self.motions.get(index), "translate_final")
                    if redone is not None:
                        finals[index] = redone
        return finals

    def _listing(self):
        """The design's parameters for the manifest, or None when they cannot be listed. Never stops the export."""
        try:
            return list_parameters(self.request.parameters, self.request.model_params, self.request.design_unit)
        except Exception as exc:
            self.port.log(f"parameter list failed: {exc!r}")
            return None

    # ---- the sketch probe -------------------------------------------------------------------------------------

    def _start_probes(self, indexes):
        """One probe per part that has a sketch to follow, and the group that runs them over shared rows. A probe that
        cannot start is noted for the person; it never stops the export."""
        probes, failed = [], False
        for index in indexes:
            capture = self.captures[index]
            if not covers_a_sketch(capture):
                continue
            problem = "The first read of the sketches of %s did not work." % self.names[index]
            try:
                probe = SizeProbe.start(capture, self._part_table(index), self.port.probe_reader(index))
            except Exception as exc:
                self.port.log("size probe of %s could not start: %r" % (self.names[index], exc))
                problem = repr(exc)
                probe = None
            if probe is None:
                failed = True
                self.probe_error = self.probe_error or problem
                continue
            probes.append(probe)
            self.probed.append(index)
        if probes:
            self.group = ProbeGroup(probes, [self.names[i] for i in self.probed])
        self.probe_status = (health_module.FAILED if failed
                             else health_module.MEASURED if probes else health_module.NOT_NEEDED)

    def _measured(self):
        return self.probe_status == health_module.MEASURED

    def _measure(self, sizes, extra):
        """Run the shared rows and build each part's motion; the sizes the probe cannot follow go to `self.doubtful`.

        The rows are the ones of `SizeProbe.probe_rows` for all sizes of all parts together, so the row limit is for
        the whole export. A failure other than a cancel leaves every part without a motion and is noted for the person.
        The parameters are put back, the suppressed items turned back on and a sketch left on another solution put
        back (`ProbeRun.settle`) before the last read, also when the tries fail or are cancelled."""
        group = self.group
        self.roll = TryTimeline(self.port.store, self.port.log, self.request.faster_tries)
        self.roll.begin([self.captures[i] for i in self.probed], lambda: group.matches_start(group.read_now()))
        run = ProbeRun(self.port, self.tmp, group, before_discovery=self._end_trim)
        tries = self._tries()
        settled = False
        try:
            run.measure(group.probe_rows(sizes, extra), sizes)
            self.also = run.discover(tries)
            self.roll.tries_done()
            settled = True
            settle_after_tries(self, run)
            found = group.finish(group.read_now(), labels(self.table))
        except ExportCancelled:
            raise
        except Exception as exc:
            self.port.log(f"size probe failed: {exc!r}")
            self.probe_status, self.probe_error = health_module.FAILED, repr(exc)
            self.motions = {}
            return
        finally:
            if not settled:
                settle_after_tries(self, run)
            self.stopped = run.stopped
            self.timing.note_probe(with_try_seconds(run.summary(), self.roll))
        self.motions = dict(zip(self.probed, group.motions))
        self.doubtful.extend(found)

    def _tries(self):
        """The unticked parameters worth one discovery try, over all probed parts, one entry per parameter."""
        found = {}
        for index in self.probed:
            for size in discovery_sizes(self.table, self.request.parameters, self.captures[index]):
                found.setdefault(size["param"], size)
        return list(found.values())

    def _restore_gap(self):
        """How far the sketches are from their start after the last restore, or None when that cannot be told; also
        after tries that failed, which can leave a sketch on another solution."""
        if self.group is None:
            return None
        try:
            return self.group.measure_restore(self.group.read_now())
        except Exception as exc:
            self.port.log(f"reading the sketches after the restore failed: {exc!r}")
            return None

    def _outline_gap(self):
        """The sketch gap from a read of the outlines only, or None without a probe."""
        if self.group is None:
            return None
        return self.group.measure_restore(self.group.read_now(outline=True))
