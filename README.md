# TEM Platform

A multi-tenant **Threat Exposure Management** platform, built as a modular monolith.

Four modules — **ASM**, **Threat Intelligence**, **Dark Web Monitoring**, **Brand Protection** —
plugged into one shared pipeline:

```
targets → jobs → findings → alerts → analytics
```

## Where the work is

Everything is tracked here, in this repository:

- **[Issues](https://github.com/emad-anwer/tem-platform/issues)** — one issue per task. Owner,
  reviewer, effort, dependencies and acceptance criteria are all on the issue, along with a
  **Search for** list of the concepts that task needs.
- **[Milestones](https://github.com/emad-anwer/tem-platform/milestones)** — one per week. Your
  week's scope is its milestone.
- **Pinned keyword issue** — each week has one, listing the concepts you're expected to be able
  to defend at Thursday's demo.

Picking up a task: assign yourself, move it in progress, branch as
`w<week>/<short-name>`, open a PR that closes the issue. [CONTRIBUTING.md](CONTRIBUTING.md) has
the details.

If a task's description is ambiguous, say so **on the issue** rather than guessing in silence —
that's a real engineering skill, not an admission of confusion.

## Stack

Python · FastAPI · PostgreSQL · Redis · ClickHouse · arq · SQLAlchemy 2.0 (async) · Alembic · Docker

## Getting started

> Not yet — week 1 builds this. When `W1-03` and `W1-13` are merged, this section becomes real.

```bash
cp .env.example .env
just up          # start the stack in detached mode
just migrate     # run database migrations
```

For development with hot reload:

```bash
just dev         # start with file watching (auto-reload on code changes)
```

API on http://localhost:8000/docs

Run `just` to see all available commands.

## Documentation

| Doc | What it is |
|---|---|
| [ROADMAP.md](docs/ROADMAP.md) | The 8-week plan — what gets built when, and why in that order |
| [DECISIONS.md](docs/DECISIONS.md) | Every architectural decision and the reasoning behind it |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How we work: branches, PRs, review, definition of done |
| `docs/adr/` | Architecture Decision Records |
| `docs/api-conventions.md` | Error envelope, pagination, naming — agreed by the team in week 1 |

## The one rule

**A module never imports another module.** Modules depend on `core`. When ASM needs data that
Threat Intelligence owns, it goes through an interface in `core` — never a direct import.

Everything else about the architecture is negotiable. This isn't.
