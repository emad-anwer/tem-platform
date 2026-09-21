# W1-12 · ADR-0001: module boundaries

**GitHub issue:** [#12](https://github.com/emad-anwer/tem-platform/issues/12)

**Owner:** Zyad · **Reviewer:** all four **+ mentor** · **Effort:** 2h · **Depends on:** #1

🔑 **The most important document of week 1.** Expensive to get wrong, cheap to get right now.

## What

Write `docs/adr/0001-module-boundaries.md` covering:

- **What a module is** in this codebase, and what lives inside one
- **What `core` owns** — and what it must never own
- **The dependency rule**: modules depend on `core`, never on each other
- **How modules communicate** when they genuinely need to — through interfaces defined in `core`,
  not direct imports
- The folder layout, with a sentence on why it's shaped that way
- **One worked example** of a boundary violation and its correct fix

## Expected outcome

An ADR the team actually refers back to in week 6 when ASM needs CVE data from Threat Intel — and
which answers that question before it's asked.

## Write it as an argument, not a description

An ADR records a decision *and the reasoning behind it*, including what was rejected. "We chose X"
is not an ADR. "We chose X over Y because Z, accepting trade-off W" is.

If this reads like a task being satisfied rather than an argument being settled, it needs another
pass.

## Search for

- architecture decision record template
- MADR ADR format
- modular monolith module boundaries
- acyclic dependencies principle
