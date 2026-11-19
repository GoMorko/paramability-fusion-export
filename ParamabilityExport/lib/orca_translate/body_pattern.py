"""Patterns and mirrors of bodies whose copies a Combine joins to the part or cuts from it, as Orca Patterns and
Mirrors of one tool body.

A rectangular or circular pattern, or a mirror, of bodies leaves its copies as bodies of their own. When a later
Combine takes every copy and the body they copy, the shared layer gives the group (`design_model/steps/body_pattern`,
`groups`). The copy then writes the sources as one tool body, as they are just before the pattern (`tools.build`,
several sources joined), repeats that tool with Orca's Pattern or Mirror, which joins the copies into it, and adds the
tool to the part or cuts it away with one Boolean. The layout is worked out as for a pattern of features
(`repeat.rectangular_layout`, `circular_layout`), so the spacing and the angle follow variables. The Combine holds a
fixed list of bodies, and Fusion may not change that list when the count changes, so the count keeps its number.

When the source is the Combine's own target (the part), the copies are joined to the part itself: an Orca Pattern or
Mirror of the part, when no step changed the part between the pattern and the Combine.

Never a wrong copy: the Combine is left out when it takes only some copies or not their source, when a step changes
a copy or a source on its own before the Combine, when the copies are in another component, for an intersect, and when
the copies that Orca makes from the numbers written do not land on the bodies Fusion made. A cut whose copies miss the
part as the copy builds it is left out too.
"""
from ..capture_model import gap_hints, tool_items
from ..capture_model.capture import same_body
from ..capture_model.step_kinds import step_type
from ..design_model import design
from ..design_model import words as shared
from ..design_model.problem import is_problem
from ..design_model.steps import body_pattern as facts
from ..design_model.steps.move import FIT_TOL_MM
from ..design_model.steps.repeat import mirror_plane
from ..geometry import vec
from ..geometry.rigid import IDENTITY_ROWS, Move
from ..orca_recipe.enums import BooleanMode
from . import causes, kept_refs, repeat
from .solid import ADD, Moved
from .steps import Skip
from .tools import boolean, build, label, mark_copied

# The cause of each `Problem` of the shared layer for a Combine that does not take a pattern whole.
_CAUSES = {facts.UNMATCHED: causes.COPIES_UNEVEN, facts.ELSEWHERE: gap_hints.OTHER_COMPONENT,
           facts.SOURCE_LEFT: causes.COPIES_TAKEN, facts.SOME_COPIES: causes.COPIES_TAKEN,
           facts.SOURCE_CHANGED: causes.COPY_CHANGED, facts.COPY_CHANGED: causes.COPY_CHANGED}
_IDENTITY_TOL = 1e-9


def split(ctx, item, tools, mode):
    """`(groups, tools left)`: the `body_pattern.Group` of each pattern or mirror of bodies whose copies the Combine
    `item` takes, the one whose source is the part first, and the tools that no group holds; or a Skip. Inside a
    tool body of another component no pattern is looked for: the tools are built one by one there."""
    if any(tool_items.is_foreign_tool(body.target) for body in ctx.scopes):
        return [], tools
    found = facts.groups(ctx.capture["items"], item, tools, None, lambda body: same_body(body, ctx.target),
                         ctx.component_frame())
    if not found:
        return [], tools
    if mode == BooleanMode.INTERSECT:
        return Skip("This Combine keeps what the part shares with the copies made by %s, which is not copied to "
                    "Orca." % label(found[0][0]), causes.COPIES_INTERSECT)
    groups = []
    for pattern, group in found:
        if is_problem(group):
            return Skip(group.words, _CAUSES.get(group.code, gap_hints.REFUSED))
        if facts.overlaps(group, groups, tools):
            return Skip("This Combine takes copies of copies (%s), which is not copied to Orca." % label(pattern),
                        gap_hints.UNSUPPORTED)
        groups.append(group)
    own = [g for g in groups if _of_part(ctx, g)]
    if len(own) > 1:
        return Skip("This Combine joins copies of the part made by more than one pattern, which is not copied to "
                    "Orca.", gap_hints.UNSUPPORTED)
    left = [tool for tool in tools if not any(g.holds(tool) for g in groups)]
    return own + [g for g in groups if g not in own], left


def _of_part(ctx, group):
    return any(same_body(source, ctx.target) for source in group.sources)


def write(ctx, item, groups, mode):
    """Write each group (`split`) of the Combine `item`: a repeated tool body and its Boolean (`mode`), or a Pattern
    or Mirror of the part. Returns None, or a Skip; the caller rolls back on a Skip."""
    for group in groups:
        tag = "%s: %s" % (label(item), label(group.item))
        made = (_of_own(ctx, item, group, mode, tag) if _of_part(ctx, group)
                else _of_tools(ctx, group, mode, tag))
        if isinstance(made, Skip):
            return made
        mark_copied(ctx, [group.item["index"]], "Copied with %s." % label(item))
    return None


def _plan(ctx, item, data):
    """`(layouts, copies, used)` of the pattern or mirror `item` (`data`, its data), the count kept as a number; or a
    Skip. `copies(ctx, body, layout, name)` writes the Orca Pattern or Mirror of one layout on `body` and gives the
    `(rows, offset)` of every copy, the original included. `used` are the paths of the values the layout follows,
    for a rectangular pattern, else None."""
    spec = step_type(item.get("type"))
    kind = "mirror" if facts.is_mirror(data) else spec.pattern if spec is not None else None
    if kind not in ("rectangular", "circular", "mirror"):
        return Skip("This Combine takes copies made by %s, a kind of step whose copies are not copied to Orca."
                    % label(item), gap_hints.UNSUPPORTED)
    why = shared.BODY_COPIES_COUNT % label(item)
    if kind == "rectangular":
        found = repeat.rectangular_layout(ctx, item, data, why)
        return found if isinstance(found, Skip) else (found[0], repeat.linear_copies, found[1])
    if kind == "circular":
        found = repeat.circular_layout(ctx, item, data, count_why=why)
        return found if isinstance(found, Skip) else (found[0], found[1], None)
    found = data.get("plane") or {}
    if found.get("foreign"):
        return Skip("The mirror plane belongs to another component and could not be brought into the part's place, "
                    "which is not copied to Orca.", gap_hints.OTHER_COMPONENT)
    plane = mirror_plane(data)
    if plane is None:
        return Skip(shared.MIRROR_PLANE)
    kept_refs.mark(ctx, item, found, "mirrors across")
    image = repeat.reflection(plane["origin"], plane["normal"])

    def copies(ctx_, body, layout, name):
        ctx_.add(repeat.mirror_feature(ctx_, "%s: mirror" % name, plane, body))
        return [(repeat.IDENTITY, [0.0, 0.0, 0.0]), image]

    return [None], copies, None


def _read(ctx, pattern):
    """The resolved step of the pattern item, or a Skip when it cannot be read or fails in Fusion."""
    step = design.resolve(pattern, ctx)
    if step.has(design.FAILS):
        return Skip("%s, which made the copies, does not build in Fusion." % label(pattern), gap_hints.REFUSED)
    if step.has(design.UNREAD):
        return Skip("%s, which made the copies, could not be read from Fusion." % label(pattern), gap_hints.REFUSED)
    design.replay(step, ctx)
    return step


def _seed(body):
    """The shape of `body` as it stands now, with the shapes a cut may not count on."""
    found = body.solid.copy()
    found.unsure = list(body.solid.unsure)
    return found


def _repeated(ctx, body, seed, moves):
    """Join the copies `moves` (`(rows, offset)`) of the shape `seed` into the shape of `body`. The pieces already
    there stay, so the steps that made them still find them; the original among the moves adds nothing."""
    unsure = list(body.solid.unsure)
    for rows, offset in moves:
        if not _is_original(rows, offset):
            body.solid.add(ADD, Moved(seed, rows, offset))
            body.solid.unsure += [Moved(shape, rows, offset) for shape in seed.unsure]

    def undo():
        body.solid.unsure = unsure

    ctx.undo.append(undo)


def _of_tools(ctx, group, mode, tag):
    """The sources of `group` as a tool body for each layout, repeated, and a Boolean into the part. None, or a
    Skip."""
    step = _read(ctx, group.item)
    if isinstance(step, Skip):
        return step
    plan = _plan(ctx, step.brought, step.brought_data)
    if isinstance(plan, Skip):
        return plan
    layouts, copies, used = plan
    moves = []
    tools = []
    for number, layout in enumerate(layouts, start=1):
        name = tag if len(layouts) == 1 else "%s (%d)" % (tag, number)
        tool = _sources(ctx, group, name)
        if isinstance(tool, Skip):
            return tool
        seed = _seed(tool)
        made = copies(ctx, tool, layout, name)
        _repeated(ctx, tool, seed, made)
        moves += made
        tools.append((tool, name))
    if not _lands(group, moves):
        return Skip(_OFF % label(group.item), causes.COPIES_UNEVEN)
    if mode == BooleanMode.CUT and not any(ctx.solid.meets(tool.solid, sure=False) for tool, _ in tools):
        return _misses(ctx, group)
    for tool, name in tools:
        boolean(ctx, tool, mode, name)
    if used is not None:
        repeat.params_doubt(ctx, group.item, used, "%s: a direction without copies" % label(group.item))
    return None


def _sources(ctx, group, name):
    """One tool body of the sources of `group`, each built as it is just before the pattern, joined into the
    first; or a Skip that names the source and its step that stops it."""
    built = []
    for source in group.sources:
        body = build(ctx, source, group.item)
        if isinstance(body, Skip):
            return body
        built.append(body)
    ctx.push(built[0])
    for other in built[1:]:
        boolean(ctx, other, BooleanMode.ADD, "%s: sources" % name)
    ctx.pop()
    return built[0]


def _of_own(ctx, item, group, mode, tag):
    """The copies of the part joined to it: an Orca Pattern or Mirror of the part. Only a join of the copies of the
    part alone, in one layout, with no step that changed the part after the pattern. None, or a Skip."""
    pattern = group.item
    if mode != BooleanMode.ADD:
        return Skip("This Combine cuts copies of the part from the part itself, which is not copied to Orca.",
                    gap_hints.UNSUPPORTED)
    if len(group.sources) != 1:
        return Skip("This Combine joins the part with copies of it and of other bodies made by %s, which is not "
                    "copied to Orca." % label(pattern), gap_hints.UNSUPPORTED)
    if not facts.stays_as_copied(ctx.capture["items"], ctx.target, pattern, item["index"]):
        return Skip(shared.BODY_COPIES_SOURCE_CHANGED % label(pattern), causes.COPY_CHANGED)
    if not ctx.has_body:
        return Skip("The part this Combine works on is not in the copy.", gap_hints.AFTER_GAP)
    step = _read(ctx, pattern)
    if isinstance(step, Skip):
        return step
    plan = _plan(ctx, step.brought, step.brought_data)
    if isinstance(plan, Skip):
        return plan
    layouts, copies, used = plan
    if len(layouts) != 1:
        return Skip("%s spreads copies of the part to both sides, and Orca would copy the copies, so it is not "
                    "copied." % label(pattern), gap_hints.UNSUPPORTED)
    part = ctx.scope
    seed = _seed(part)
    moves = copies(ctx, part, layouts[0], tag)
    if not _lands(group, moves):
        return Skip(_OFF % label(pattern), causes.COPIES_UNEVEN)
    _repeated(ctx, part, seed, moves)
    if used is not None:
        repeat.params_doubt(ctx, pattern, used, "%s: a direction without copies" % label(pattern))
    return None


_OFF = "The copies that Orca would make from the numbers of %s are not where Fusion made them."


def _is_original(rows, offset):
    return all(abs(rows[i][j] - IDENTITY_ROWS[i][j]) <= _IDENTITY_TOL for i in range(3) for j in range(3)) \
        and vec.length(offset) <= FIT_TOL_MM


def _lands(group, moves):
    """True when the copies `moves` (`(rows, offset)`, the originals among them) put each source of `group` on each
    of its copies that Fusion made, one move per copy."""
    for source in group.sources:
        left = [c for c in group.copies if same_body(c.source, source)]
        for rows, offset in moves:
            if _is_original(rows, offset):
                continue
            found = next((c for c in left if facts.lands_on(Move(rows, offset), source, c.result)), None)
            if found is None:
                return False
            left = [c for c in left if c is not found]
        if left:
            return False
    return True


def _misses(ctx, group):
    gap = bool(ctx.left_out)
    return Skip("The copies made by %s do not meet %s as the Orca copy builds it%s, so this cut is left out." % (
        label(group.item), ctx.body_words, " (a step before it is left out)" if gap else ""),
        gap_hints.AFTER_GAP if gap else causes.MISSES_PART)
