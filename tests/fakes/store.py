"""The fake parameter store (`design_edit.store.ParameterStore`), and the stores that also hold the timeline marker
and turn timeline items off for the tries (the timeline controls)."""
import math
import re


class FakeStore:
    """Parameter store holding expressions as text. Values are the leading number as Fusion stores it (mm to cm, deg
    to rad). The options give the answers a test needs:

    bad_when(exprs): the timeline item `bad_item` is in error while it holds.
    breaks: `(name, above)`: a value of `name` above `above` leaves "RemoveBody1" in error for good, also once the
      values are back, as Fusion can leave a step that lost its input.
    reject: expressions that set_expression always refuses; flaky: names refused once, then accepted.
    stuck: names that change but are never set back to their first expression.
    answers: what recompute returns, in turn (the last one repeats); an answer that is an exception is raised.
    errors: `(index, name)` of the steps in error (`error_entries`), in place of `bad_when` and `breaks`.
    warns(exprs): `(index, name)` of the steps in warning (`warning_entries`) while the expressions are `exprs`.
    on_recompute(store): called at every recompute, before it answers.
    `sets` lists every `(name, expression)` asked of set_expression, `recomputes` counts the recomputes.
    """

    def __init__(self, expressions, bad_when=None, reject=(), flaky=(), bad_item="Fillet1", breaks=None, stuck=(),
                 answers=(True,), errors=None, on_recompute=None, warns=None):
        self.exprs = dict(expressions)
        self.first = dict(expressions)
        self.bad_when = bad_when or (lambda exprs: False)
        self.bad_item = bad_item
        self.reject = set(reject)
        self.flaky = set(flaky)
        self.breaks, self.broken = breaks, False
        self.stuck = set(stuck)
        self.answers = list(answers)
        self.errors = None if errors is None else list(errors)
        self.on_recompute = on_recompute
        self.warns = warns or (lambda exprs: [])
        self.sets = []
        self.recomputes = 0

    def saved_expressions(self):
        return dict(self.exprs)

    current_expressions = saved_expressions

    def set_expression(self, name, expression):
        self.sets.append((name, expression))
        if expression in self.reject:
            raise RuntimeError("refused")
        if name in self.flaky:
            self.flaky.discard(name)
            raise RuntimeError("busy")
        if name in self.stuck and self.exprs[name] != self.first[name] and expression == self.first[name]:
            raise RuntimeError("refused")
        self.exprs[name] = expression
        if self.breaks is not None and name == self.breaks[0]:
            self.broken = self.broken or float(expression.split()[0]) > self.breaks[1]

    def recompute(self):
        self.recomputes += 1
        if self.on_recompute is not None:
            self.on_recompute(self)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def read_value(self, name):
        number = float(re.match(r"\s*([-0-9.eE+]+)", self.exprs[name]).group(1))
        if "deg" in self.exprs[name]:
            return math.radians(number)
        return number / 10.0  # lengths are mm, stored as cm

    def error_items(self):
        if self.errors is not None:
            return [name for _, name in self.errors]
        if self.breaks is not None:
            return ["RemoveBody1"] if self.broken else []
        return [self.bad_item] if self.bad_when(self.exprs) else []

    def error_entries(self):
        if self.errors is not None:
            return list(self.errors)
        return {name: name for name in self.error_items()}

    def warning_entries(self):
        return list(self.warns(self.exprs))

    def set_expressions(self, expressions):
        return False

    def return_marker(self):
        return ""

    def marker_holds(self):
        return True


class RollingStore(FakeStore):
    """A store that can hold the timeline marker early for the tries (`roll_marker`); it records the marker position
    each recompute ran at (`at`) and every roll in `events` (and every parameter change with `note_sets`). `fail_roll`
    refuses the roll; `holds` is what `marker_holds` answers."""

    def __init__(self, expressions, fail_roll=False, note_sets=False, **options):
        super().__init__(expressions, **options)
        self.rolled, self.at, self.events, self.fail_roll, self.holds = None, [], [], fail_roll, True
        self.note_sets = note_sets

    def set_expression(self, name, expression):
        if self.note_sets:
            self.events.append(("set", name))
        super().set_expression(name, expression)

    def roll_marker(self, position):
        self.events.append(("roll", position))
        if self.fail_roll:
            return False
        self.rolled = position
        return True

    def unroll_marker(self):
        self.events.append(("unroll", self.rolled))
        self.rolled = None
        return True

    def marker_holds(self):
        return self.holds

    def recompute(self):
        self.at.append(self.rolled)
        return super().recompute()


class TrimStore(RollingStore):
    """A rolling store that also turns timeline items off and rebuilds once after each change, like the real one;
    `events` lists every roll and suppression in order and `off_at` the suppressed indexes at each recompute.
    `refuse` turns nothing off; `stays_off` are the names that do not come back on."""

    def __init__(self, expressions, refuse=False, stays_off=(), **options):
        super().__init__(expressions, **options)
        self.off, self.off_at, self.refuse, self.stays_off = (), [], refuse, list(stays_off)

    def suppress_items(self, items):
        self.events.append(("suppress", [i for i, _ in items]))
        if self.refuse:
            return 0
        self.off = tuple(i for i, _ in items)
        self.recompute()
        return len(self.off)

    def unsuppress_items(self):
        self.events.append(("unsuppress", list(self.off)))
        self.off = ()
        self.recompute()
        return self.stays_off

    def recompute(self):
        self.off_at.append(self.off)
        return super().recompute()
