"""The restore check of a size probe: how far the followed sketches and the measured references read after the tries
are from their first read (E0). Pure: no Fusion."""
from ...geometry.tolerances import FLIP_TOLERANCE
from ...probe import match, ref_fit, same_shape
from ...sketch_values.motion import SHAPE, UNREAD
from .reasons import RESTORE_WHY

UNREAD_AFTER = "the design could not be read after the tries"


def restore_gap(targets, refs, e0, after):
    """`(gap, unchecked, changed)` between E0 and `after`, a read after the restore. `targets` are the followed targets
    (`SizeProbe._followed_targets`), `refs` the measured references.

    gap: the largest difference in mm over the covered values and the places of the references (one that cannot be
      read again is left out); None when a sketch cannot be compared.
    unchecked: "<sketch> <why>" for each sketch that could not be compared.
    changed: "<sketch> <why>" for each sketch found on another outline. A sketch whose outline does not pair with E0
      by its tokens is compared by its curves (`same_shape.shape_gap`): the same curves give their gap, other curves
      or a turned plane are a real change ("Sketch2 reads another outline")."""
    if not isinstance(after, dict):
        return None, [UNREAD_AFTER], []
    unchecked, changed = [], []
    gap = 0.0
    for ref in refs:
        before, _ = ref_fit.state_values(ref, e0)
        now, _ = ref_fit.state_values(ref, after)
        if before is not None and now is not None:
            gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
    for target in targets:
        before, _ = match.state_values(target, e0, e0)
        now, cause = match.state_values(target, after, e0)
        if before is not None and now is not None and before.keys() == now.keys():
            gap = max([gap] + [abs(now[k] - v) for k, v in before.items()])
            continue
        token = target["sketch_token"]
        shape = same_shape.shape_gap((e0.get("sketches") or {}).get(token), (after.get("sketches") or {}).get(token),
                                     FLIP_TOLERANCE) if target["kind"] == "profile" else None
        if shape is not None:
            gap = max(gap, shape)
            continue
        text = "%s %s" % (target["sketch"] or "a sketch", RESTORE_WHY.get(cause, RESTORE_WHY[SHAPE]))
        real = before is not None and cause != UNREAD
        (changed if real else unchecked).append(text)
    unchecked, changed = list(dict.fromkeys(unchecked)), list(dict.fromkeys(changed))
    return (None if unchecked else gap), unchecked, changed
