"""The far phase of the tries: the far rows run one size at a time, each size followed by its nearer rows
(`ProbeRun._far_by_size`). Which sizes go last, and how many nearer rows a size may take. Pure: no Fusion."""
from ...design_edit.apply import detail_steps
from ...design_edit.runner import row_key
from ...design_edit.walk_back import AT_CHECK

# The far rows of one size at most: one at each range end (`plan.far_rows`).
FAR_ENDS = 2


def late_sizes(rows, walks, counts_warning):
    """Fusion names of the sizes whose own rows in `rows` (`(row, result)` as `ProbeRun.rows` keeps them) showed
    trouble outside the part: a new warning on a step the part is not built from (`others_warned`), a step in error
    that the part is not built from (`counts_warning(step)` false), or a check after the row that found a step worse
    and walked the design back (an attempt at `walk_back.AT_CHECK` among `walks`, the attempts `RowExport` kept). A
    row that sets two or more sizes tells nothing of one size."""
    checked = {walk.get("row") for walk in walks if walk.get("at") == AT_CHECK}
    found = []
    for row, result in rows:
        varied = row.get("varied") or []
        if len(varied) != 1 or varied[0] in found:
            continue
        failed = detail_steps(result.get("detail")) if result.get("error") else []
        if result.get("others_warned") or row_key(row) in checked or any(not counts_warning(s) for s in failed):
            found.append(varied[0])
    return found


def nearer_share(nearer_left, to_come, rows_left):
    """How many nearer rows the size whose far rows just ran may take, at most: `nearer_left` nearer rows are left
    under `plan.MAX_NEARER_ROWS`, `to_come` sizes (this one included) still have their far phase to come, and
    `rows_left` rows are left under `plan.MAX_PROBE_ROWS`.

    The size gets the nearer rows left divided by `to_come`, rounded up: two or three sizes whose far tries fail
    cannot use up the rows of the sizes after them, and what a size does not use passes on to the sizes after it. It
    also leaves `FAR_ENDS` rows of the row limit for each size after it, so their far rows still fit, as when the far
    rows of every size came first."""
    if to_come <= 0:
        return 0
    share = -(-max(0, nearer_left) // to_come)
    return max(0, min(share, rows_left - FAR_ENDS * (to_come - 1)))
