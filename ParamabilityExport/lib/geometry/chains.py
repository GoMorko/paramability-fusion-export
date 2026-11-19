"""Open chains of curves: which curves run on from one another, and in which order. Pure.

A rib or a web takes a list of sketch curves in any order and direction. `open_chains` groups the curves whose ends
meet into chains and orders each chain from one free end to the other, so it can be read like a path.
"""
import math

# Two curve ends this close (mm) meet.
JOIN_TOL = 1e-4


def _key(ends, number, which):
    return ends[number][which]


def open_chains(ends, tol=JOIN_TOL):
    """The chains of curves, or None. `ends` lists one (start, end) point pair per curve. Each chain is a list of
    (curve number, reversed) from one free end of the chain to the other; `reversed` is True when the curve runs
    against the chain. Of the two directions, the chain takes the one whose first curve runs along it when there is
    one. None when a curve has no length, three or more curve ends meet at one point, or a chain closes on itself."""
    count = len(ends)
    if any(math.dist(a, b) <= tol for a, b in ends):
        return None
    # Each curve end meets at most one other curve end.
    partner = {}
    for n in range(count):
        for which in (0, 1):
            here = _key(ends, n, which)
            found = [(m, other) for m in range(count) for other in (0, 1)
                     if (m, other) != (n, which) and math.dist(here, _key(ends, m, other)) <= tol]
            if len(found) > 1 or any(m == n for m, _ in found):
                return None
            if found:
                partner[(n, which)] = found[0]
    seen, chains = set(), []
    for n in range(count):
        if n in seen:
            continue
        chain = _walk(n, partner)
        if chain is None:
            return None
        seen.update(number for number, _ in chain)
        chains.append(chain)
    return chains


def _walk(first, partner):
    """The chain through curve `first`, from a free end, or None when it closes on itself."""
    # Go back from `first` to a free end of its chain.
    number, which = first, 0
    steps = 0
    while (number, which) in partner:
        number, end = partner[(number, which)]
        which = 1 - end
        steps += 1
        if number == first:
            return None
        if steps > len(partner) + 1:
            return None
    # `which` is the free end of `number`: walk forward from there.
    chain = []
    while True:
        chain.append((number, which == 1))
        out = (number, 1 - which)
        if out not in partner:
            break
        number, which = partner[out]
    if chain[0][1] and chain[-1][1]:
        chain = [(n, not reverse) for n, reverse in reversed(chain)]
    return chain
