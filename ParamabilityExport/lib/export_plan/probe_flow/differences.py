"""What differs between two reads of the design, as the discovery rows and the report name it. Pure: no Fusion."""
from ...probe import match, plan, ref_fit
from .states import body_changed, box_numbers, same_numbers


def sketch_names(capture, watch):
    """Sketch token to the name a reason uses: the followed sketches of `capture` (`plan.scan`) and the borrowed
    sketches in `watch` (token to `{ sketch, component }`), the latter with their component."""
    named = dict(plan.scan(capture).named)
    for token, hint in watch.items():
        named[token] = "%s of %s" % (hint["sketch"], hint["component"]) if hint.get("component") else (
            hint.get("sketch") or named.get(token, ""))
    return named


def comparable(read):
    """True when `read` holds anything the discovery compares."""
    return isinstance(read, dict) and bool(read.get("sketches") or read.get("refs") or box_numbers(read))


def read_differences(request, refs, names, base, read):
    """`(changed, unread)` between two reads of the design: names of the sketches, hole points and axis lines of
    `request`, the measured references `refs`, and "the body" (its box and volume), that read differently in `read`,
    and of those that one of the two reads does not hold. `names` is `sketch_names`. Sketches are compared as read
    (frame and curves within 1e-4 mm), so a sketch on another outline in both reads is the same."""
    changed, unread = [], []

    def sort(name, a, b, same):
        if a is None or b is None:
            unread.append(name)
        elif not same(a, b):
            changed.append(name)

    for token in request.get("sketches") or []:
        sort(names.get(token) or "a sketch", ((base or {}).get("sketches") or {}).get(token),
             ((read or {}).get("sketches") or {}).get(token), match.same_read)
    for kind in ("points", "lines"):
        for token in request.get(kind) or []:
            sort("a sketch %s" % kind[:-1], ((base or {}).get(kind) or {}).get(token),
                 ((read or {}).get(kind) or {}).get(token), same_numbers)
    for ref in refs:
        sort(ref["key"], ref_fit.state_values(ref, base)[0], ref_fit.state_values(ref, read)[0], same_numbers)
    if box_numbers(base) is None or box_numbers(read) is None:
        unread.append("the body")
    elif body_changed(base, read):
        changed.append("the body")
    return list(dict.fromkeys(changed)), list(dict.fromkeys(n for n in unread if n not in changed))
