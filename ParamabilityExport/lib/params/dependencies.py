"""Which parameters a parameter reads, through formulas at any depth. Pure: plain parameter dicts.

    graph = dependencies.Graph(user_params, model_params)
    graph.closure(["d12"])        # d12 and every parameter it reads, at any depth
    graph.usage(["d12"], linked)  # the user parameters a body reads, and through which formulas

A parameter reads the names in its expression and the names in Fusion's own list (`dependency_parameters`, which
Fusion fills through every formula on the way). A user parameter also names what reads it: `dependent_parameters` and
the model parameters in `dependents`. Both directions go into one graph, so a chain through a parameter the capture
does not hold (a model parameter of another component) is still followed.

An expression the parser refuses (a unit it cannot read, a text form) still gives its names: the words of the text
that name a known parameter (`names_in`). A cycle ends at the first parameter seen twice.
"""
from .expressions import ExpressionError, parse, referenced_names, scanned_names


def _read(expression, known):
    """(names, exact): the names an expression reads, and whether the parser read it (else they come from its words)."""
    text = expression or ""
    try:
        parse(text)
    except ExpressionError:
        return [w for w in scanned_names(text) if known is not None and w in known], False
    return referenced_names(text), True


def names_in(expression, known=None):
    """Parameter names an expression reads, in order of first use. When the parser refuses the text, the words of the
    text that are in `known` (a set of parameter names) are taken instead; without `known`, none."""
    return _read(expression, known)[0]


class Usage:
    """What a body reads among the user parameters.

    `used`: every user parameter reached, at any depth. `direct`: the ones a model parameter of the body names in its
    formula (through other model parameters too) or that reach the body through another component (`linked`).
    `through`: {name: [derived user parameter]} for a user parameter the body reads only through the formulas of
    other user parameters; the list holds the outermost of them (the ones the body reads itself), in parameter
    order."""

    def __init__(self, used, direct, through):
        self.used, self.direct, self.through = frozenset(used), frozenset(direct), dict(through)


class Graph:
    """What each user and model parameter (plain dicts) reads. A user parameter wins over a model one of its name."""

    def __init__(self, params=(), model_params=()):
        self.params = {m["name"]: m for m in model_params}
        self.params.update({p["name"]: p for p in params})
        self.user = [p["name"] for p in params]
        self._user = set(self.user)
        known = set(self.params)
        self._text = {}  # name: the names its expression reads, for an expression the parser read
        self._reads = {}  # name: everything it reads (the text, Fusion's lists and the reverse of `dependents`)
        for name, p in self.params.items():
            text, exact = _read(p.get("expression"), known)
            if exact:
                self._text[name] = [n for n in text if n != name]
            self._add(name, text + list(p.get("dependency_parameters") or ()))
        for p in params:
            readers = list(p.get("dependent_parameters") or ())
            readers += [d.get("name") for d in p.get("dependents") or () if isinstance(d, dict)]
            for reader in readers:
                if isinstance(reader, str) and reader:
                    self._add(reader, [p["name"]])
        # Every name the graph knows: parameters and the readers their `dependents` name.
        self.names = frozenset(self.params) | frozenset(self._reads)

    def _add(self, name, reads):
        found = self._reads.setdefault(name, [])
        for read in reads:
            if isinstance(read, str) and read and read != name and read not in found:
                found.append(read)

    def reads(self, name):
        """The names one parameter reads directly (as far as the capture tells), in order."""
        return tuple(self._reads.get(name, ()))

    def is_derived(self, name):
        """True for a user parameter whose value is a formula."""
        return name in self._user and self.params[name].get("kind") == "derived"

    def walk(self, starts, stop=None):
        """The start names and every name they read, at any depth. A name for which `stop(name)` is true is listed
        but not followed further."""
        seen, stack = set(), list(starts)
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            if stop is None or not stop(name):
                stack.extend(self._reads.get(name, ()))
        return seen

    def closure(self, starts):
        """The start names and everything they read, at any depth."""
        return self.walk(starts)

    def user_reads(self, name):
        """User parameters a parameter reads at any depth, itself left out, in parameter order."""
        reached = self.closure([name]) - {name}
        return [n for n in self.user if n in reached]

    def _direct(self, starts):
        """User parameters a start names in its formula, also through other model parameters, without passing through
        a user parameter. Where a formula cannot be parsed, Fusion's list stands in for it."""
        out, seen, stack = set(), set(), list(starts)
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            exact = self._text.get(name)
            for read in exact if exact is not None else self._reads.get(name, ()):
                if read in self._user:
                    out.add(read)
                else:
                    stack.append(read)
        return out

    def usage(self, starts, linked=()):
        """The `Usage` of a body whose model parameters are `starts`; `linked` are user parameters that reach it
        through another component."""
        starts, linked = list(starts), list(linked)
        used = self.closure(starts + linked) & self._user
        firm = self._direct([s for s in starts if s not in self._user]) | (set(starts) & self._user)
        tops = firm | (set(linked) & self._user)
        below = {}
        for top in tops:
            if self.is_derived(top):
                for name in self.user_reads(top):
                    if name not in firm:
                        below.setdefault(name, set()).add(top)
        through = {}
        for name, outer in below.items():
            # Name only the outermost formulas: one that is itself read through another is left out.
            picked = [n for n in self.user if n in outer and n not in below] or [n for n in self.user if n in outer]
            through[name] = picked
        direct = (tops - set(through)) | firm
        return Usage(used, direct, through)
