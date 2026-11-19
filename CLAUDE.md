# CLAUDE.md

Paramability export for Autodesk Fusion: a Python add-in that copies a Fusion body, its timeline steps and its user
parameters into a `.paramability` package. The Paramability app opens the package as a part whose sizes people can
change. Read `README.md` first (what the add-in does and where the documents are), then `agent-docs/development.md` (code
layout, package layering, tests) and `agent-docs/developer-guide.md` (how an export works, step by step).
`agent-docs/user-guide.md` and `agent-docs/limits.md` describe what users see and what does not copy.

## Goal

The add-in and the recipe format must cover a wide variety of 3D printing projects, so a designer can export a
project from Fusion and the people who download it can change its sizes in Paramability.

- **Fix the class, not the file.** A problem seen on one design is a request for every project. Restate it as a
  general rule, check how the code handles the whole class, and fix that. Never tune the code to one export.
- **Never write a wrong copy.** When the add-in is unsure, it leaves a step out (a gap with a reason and a tip) or
  stops, and says why. A wrong but plausible copy is worse than a gap.
- **Always put the design back.** After an export, the Fusion design, its parameters, timeline marker and steps must
  be exactly as before (`PutBack` and the end check). A change that can leave the design changed is a blocker.
- Rank work by how many typical projects it helps: common Fusion features, common modelling habits, and the
  experience of the person who changes the sizes.

## Working with agents

Be concise, impersonal and to the point. Write sub agent prompts the same way.

1. **Clarify first.** Make the request concrete and ask when scope or intent is unclear. Keep plans in line with the
   layering and patterns of this repo; flag a pattern that looks wrong for the case and let the user decide.
2. **Orchestrate, don't implement.** Delegate to sub agents and change things yourself only when the change is tiny.
   Pick the model and effort by the weight of the task: light models for scans and mechanical edits, a mid model for
   well specified implementation, the strongest model for deep analysis of the probe or the translator and for plans.
   Tell the user the model and effort of every agent you start. Keep each agent's context small; split the work or
   start a fresh agent from a summary.
3. **Verify agent output.** Review each agent's changes and send fixes back to that agent. Check that comments describe
   the code for a later reader, not the session's work or plan.
4. **Parallelize** independent work, each agent in its own worktree and branch from `main`. Tell each agent which
   files its siblings change. Shared files (`capture_model/step_kinds.py`, `capture_model/gap_hints.py`,
   `translator/handlers.py`, `agent-docs/hand-checks.md`) take only small additive edits per branch. Limit heavy commands
   (the full suite) running at the same time.
5. **Code review** after a large change: a strict, adversarial reviewer focused on wrong copies, the design not put
   back, Fusion API members that may not exist, layering, and tests that check wording instead of outcomes. Act on
   its findings.
6. **Tests trim** before the final commit of a body of work: keep tests of real behaviour and real regressions, drop
   duplicates and wording checks.
7. **Cleanup** of worktrees and branches only after the user says the work is done.

## Repository rules

- **Git:** never push and never open pull requests unless the user asks. Sub agents never run `git reset`,
  `git checkout`, `git stash` or `git rebase`: the orchestrator owns git. Restate this ban word for word in every sub
  agent prompt. Never `rm -rf` a folder inside a worktree that an agent uses.
- **Commits:** plain English messages, one coherent change each. No session URLs or ids, no local paths.
- **Versions:** only the orchestrator bumps the add-in version (`ParamabilityExport/ParamabilityExport.manifest` and
  the version line in the docs) or a saved format (recipe, package, gaps file). A format change needs a Paramability
  release that reads it first.
- **Release zip:** `python3 scripts/make_release_zip.py` writes `dist/ParamabilityExport-<version>.zip`. Hand a zip out
  only when the released app can read what it writes.
- **Publishing:** keep to `agent-docs/publishing.md` (no Fusion or Autodesk in names, no Autodesk art, documented API only,
  leave the design as it was).
- **This repository is public.** Never commit exports of real designs (`.paramability` files), values or geometry
  taken from them, personal paths, or links to private repositories and notes. `tests/local/` is git-ignored and holds
  machine-local test data: `tests/test_local_captures.py` runs on it when `tests/local/captures.json` exists
  (`PARAMABILITY_LOCAL_CAPTURES` and `PARAMABILITY_LOCAL_REPORTS` point elsewhere).

## Code

- Python 3.10 or newer, standard library only. Anything that touches `adsk` stays in `lib/fusion_reader/`,
  `lib/fusion_ui/` and `commands/`; everything else is pure and tested with fakes.
- Layering and boundaries: `tests/test_boundary.py` (which package may import which, no underscore imports across
  modules) and `tests/test_interfaces.py` (declared store, port and probe members) must stay green.
- Fusion API members: check every member a reader uses against the Fusion API reference or the API stubs that Fusion
  installs, and make reader fakes use the real names. A member that may be missing reads as null and gives a gap,
  never a guess.
- New step type: follow `agent-docs/adding-a-step-type.md`. New gap cause: add its hint in `capture_model/gap_hints.py`.
- No god modules: split a module that grows past about 700 lines or mixes jobs, as a separate commit.
- Comments: short, standalone, for a developer opening the file cold. No notes about the current task.
- User-facing text (dialog, result window, reasons, tips): plain words for 3D printing hobbyists, no developer
  jargon, no em or en dashes.

## Tests

- Full suite from the repository root: `python3 -m unittest discover -s tests -t .` (about a minute). Run single
  modules while working and the full suite before the last commit. Tests assert outcomes and causes, one case per real
  branch, no wording checks.
- Fusion cannot run in tests. Anything only Fusion can prove goes into `agent-docs/hand-checks.md` as a short check: what to
  model, written so a Fusion AI assistant can build it, then an indented "Export:" line with what to pick, tick and
  expect.
- `agent-docs/test-projects.md` lists typical printing projects. Export them to see how many kinds of projects the copy
  covers.

## Docs to keep current

Every change updates, in the same round: `README.md`, `agent-docs/developer-guide.md` (ASD-STE100 Simplified Technical
English, never condensed: one sentence must not stand in for a concept that needs five), and the other files in
`agent-docs/` that the change touches (development, user guide, limits, capture format, gaps, hand checks). Tips in the
docs must match `capture_model/gap_hints.py`.

## Reports to the user

Plain, short paragraphs, one thought per line, simple grammar; many readers are not native English speakers. Say
what happens, not internal names. Use ASD-STE100 as baseline.
