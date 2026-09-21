# Weekly boards

One directory per week. Each holds the board — `README.md` — plus the source text of every task
issue filed for that week, and the week's keyword reference.

**The GitHub issue is the thing you work from.** These files are where it came from, and they are
here so a task, its context and the week it belongs to are all reachable from the repository you
actually work in — not in a chat message that scrolled away.

| Week | Board | Theme | Lead | Milestone |
|---|---|---|---|---|
| 1 | [week-01](week-01/) | Walking skeleton — FastAPI, Postgres, Docker, migrations, a tenant | Zyad | [#1](https://github.com/emad-anwer/tem-platform/milestone/1) |
| 2 | [week-02](week-02/) | Identity we don't own, isolation we do — Zitadel, RBAC, tenant scoping | Tasneem | [#2](https://github.com/emad-anwer/tem-platform/milestone/2) |
| 3 | [week-03](week-03/) | Work leaves the request path — arq, the pipeline spine, first findings | Islam | [#3](https://github.com/emad-anwer/tem-platform/milestone/3) |
| 4 | [week-04](week-04/) | The platform sends its own packets — the ASM scanner | Arwa | [#4](https://github.com/emad-anwer/tem-platform/milestone/4) |

The eight-week arc is in [`../ROADMAP.md`](../ROADMAP.md); the reasoning behind the decisions it
rests on is in [`../DECISIONS.md`](../DECISIONS.md).

## How a week works

1. Read the board. It has the dependency order, who owns what, and what is deliberately **not** in
   the week.
2. Find your task's issue in the week's milestone. Branch `w<week>/<short-name>`, open a PR that
   closes the issue. [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md) has the conventions.
3. Review the PRs you are named reviewer on. That is a task, it is in your hours, and it is not
   optional.
4. Thursday: the week's lead drives a live demo.

## A note on the older boards

Weeks 1–3 are here as they were written. Where a board says something the code has since
outgrown — a deferred task, a decision that went the other way in review — that is the record
working as intended. Don't edit the past boards to match the present; the ADRs in
[`../adr/`](../adr/) are where a decision gets revised, with a date on it.
