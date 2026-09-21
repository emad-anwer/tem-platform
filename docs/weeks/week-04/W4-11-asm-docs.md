# W4-11 · ASM scanner docs and the scope policy page

**Owner:** Tasneem · **Reviewer:** Arwa · **Effort:** 2h · **Depends on:** W4-10

## What

Two pages in `/docs`, in the same shape as W3-12's `docs/pipeline.md`.

**1. `docs/asm-scanner.md`** — how the scanner works, for the person who joins in week 6.

- The stage diagram from W4-10, and what each stage produces
- The four finding kinds, their fingerprints, and what makes each one unique — pointing at ADR-0004
  rather than restating it
- The knobs and their current values: semaphore limit, connect timeout, port list, rate limit,
  scan interval. Each with a sentence on what happens if you turn it up
- What change detection reports and how to read it
- How to run a scan against the lab from a clean clone, in commands that work

**2. `docs/scanning-policy.md`** — the page whose absence is the problem.

- What the platform is permitted to scan, and where that is configured
- What is blocked unconditionally and why — link-local, metadata endpoints, RFC1918
- What an intern does when they think they need to scan something new (answer: they don't; they ask)
- The politeness budget and what it is for

This second page is short and it is the one that matters. Right now the scope rules live in Islam's
head, in W4-02's code, and in a banner at the top of a task board. In week 6 somebody adds a target
and there needs to be a page that tells them what they just agreed to.

## Expected outcome

Someone who has never seen the repository can run a scan against the lab from `docs/asm-scanner.md`
alone, and can answer "may I scan this?" from `docs/scanning-policy.md` alone.

## Think about

Write it from the code, not from the plan. Four tasks landed this week and at least one of them
implemented something slightly different from what its task file said — that is normal, and the
document has to describe what the repository does. If you find a gap between the two, that is a
finding, and it belongs in the PR description rather than being silently papered over.

`docs/target-lab.md` already documents the ground truth. Link to it; do not copy the table. Two
copies of a table diverge, and the one in the newer file is the one people trust.

Keep the policy page short enough that somebody actually reads it before scanning something. A page
nobody finishes is the same as no page.

## Search for

- architecture documentation for newcomers structure
- documenting configuration knobs defaults rationale
- rules of engagement penetration test scope document
- mermaid sequence diagram markdown github
