# TEM Platform

A multi-tenant **Threat Exposure Management** platform, built as a modular monolith.

Four modules — **ASM**, **Threat Intelligence**, **Dark Web Monitoring**, **Brand Protection** —
plugged into one shared pipeline:

```
targets → jobs → findings → alerts → analytics
```

## Stack

Python · FastAPI · PostgreSQL · Redis · ClickHouse · arq · SQLAlchemy 2.0 (async) · Alembic · Docker

## Getting started

> Not yet — week 1 builds this. When `W1-03` and `W1-13` are merged, this section becomes real.

```bash
cp .env.example .env
just up
just migrate
```

API on http://localhost:8000/docs

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
