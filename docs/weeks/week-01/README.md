# Week 1 — Walking Skeleton

**Sunday–Thursday · Lead: Zyad**

Code repository: **<https://github.com/emad-anwer/tem-platform/>** — every task below is a live issue there.
Milestone: [Week 1 — Walking Skeleton](https://github.com/emad-anwer/tem-platform/milestone/1)

## Tasks

| # | Task | Owner | Reviewer | Effort | Depends on |
|---|---|---|---|---|---|
| [W1-01](W1-01-repository-scaffold.md) | Repository scaffold and module layout | Zyad | Islam | 4h | — |
| [W1-02](W1-02-api-conventions.md) | API conventions huddle and written decision | Arwa | all four | 45m + 2h | — |
| [W1-03](W1-03-docker-compose.md) | Docker Compose: Postgres, Redis, app | Islam | Zyad | 4h | W1-01 |
| [W1-04](W1-04-app-factory-health.md) | App factory, settings, health endpoints | Arwa | Tasneem | 3h | W1-01 |
| [W1-05](W1-05-alembic-setup.md) | Alembic setup and initial migration | Tasneem | Arwa | 3h | W1-01, W1-04 |
| [W1-06](W1-06-tenant-model.md) | Tenant model and repository | Zyad | Arwa | 4h | W1-05 |
| [W1-07](W1-07-tenant-api.md) | Tenant API endpoints | Arwa | Zyad | 4h | W1-06, W1-02 |
| [W1-08](W1-08-error-envelope.md) | Error envelope and exception handlers | Islam | Tasneem | 3h | W1-02, W1-04 |
| [W1-09](W1-09-structured-logging.md) | Structured logging and request ID middleware | Tasneem | Islam | 3h | W1-04 |
| [W1-10](W1-10-target-lab.md) | Docker target lab | Islam | Zyad | 4h | — |
| [W1-11](W1-11-test-scaffolding.md) | Test scaffolding and first tests | Tasneem | Arwa | 3h | W1-07 |
| [W1-12](W1-12-adr-module-boundaries.md) 🔑 | ADR-0001: module boundaries | Zyad | all + mentor | 2h | W1-01 |
| [W1-13](W1-13-readme-dev-guide.md) | README and local development guide | Tasneem | Islam | 2h | W1-03, W1-05 |

## Load

| Intern | Tasks | Task hours | + review/standups | Total |
|---|---|---|---|---|
| **Zyad** (lead) | 01, 06, 12 | 10h | +4h lead duties | **14h** |
| **Arwa** | 02, 04, 07 | 9h | +3h | **12h** |
| **Islam** | 03, 08, 10 | 11h | +3h | **14h** |
| **Tasneem** | 05, 09, 11, 13 | 11h | +3h | **14h** |

Against 20h/week — leaves 6–8h each for reading, debugging, and first PR cycles being slow.

## Critical path

```
W1-01 ──┬── W1-03 ──────────────┐
        ├── W1-04 ──┬── W1-05 ──┴─→ W1-13
        │           │      ↓
        │           │   W1-06 → W1-07 → W1-11
        │           └── W1-09
        ├── W1-08 (also needs W1-02)
        └── W1-12

W1-02 (Sunday huddle) ──→ W1-07, W1-08
W1-10 ── independent, always available as parallel work
```

**W1-01 blocks almost everything** — ships first thing Sunday.
**W1-05 → W1-06 → W1-07** is a three-person chain across Tuesday–Wednesday. If Alembic slips,
two people stall. **W1-10 is deliberately dependency-free** so parallel work always exists.

---

## Keywords, concepts and resources

Everything here connects to something you are actually building this week. Nothing is background
reading for its own sake.

## Concepts you're expected to understand by Thursday

You will be asked about these in the Thursday demo — not to recite a definition, but to defend a
choice you made.

| Concept | What you should be able to say |
|---|---|
| **Modular monolith** | One deployable, hard internal boundaries. Why it beats microservices at this scale |
| **Layered architecture** | api → service → repository → model, and what belongs in each layer |
| **Dependency rule / acyclic dependencies** | Modules depend on `core`, never each other. Cycles are how monoliths rot |
| **Dependency injection (`Depends`)** | Wiring passed in rather than imported; the reason handlers are testable |
| **Repository pattern** | Data access behind an interface, so the service layer never writes SQL |
| **Schema migration** | Versioned, ordered, reversible database change. `revision`, `head`, `upgrade`, `downgrade` |
| **12-factor config** | Configuration from the environment. Same image, different environments |
| **Structured logging & correlation ID** | Logs as parseable JSON events, with one ID threading every line of a request |
| **REST resource modelling** | Plural nouns, no verbs in paths. The HTTP method is the verb |
| **Safe vs idempotent methods** | `GET` changes nothing; `PUT`/`DELETE` retry safely; `POST` generally doesn't |
| **Liveness vs readiness** | "Is the process alive?" vs "can it serve traffic?" — different endpoints, different consumers |
| **Surrogate vs natural key** | UUID primary key vs the human-meaningful slug, and why the tenant has both |

## Search terms

Each task issue has its own **Search for** list at the bottom. Start there — they're scoped to
what that specific task needs.

## Resources

Six things. All short, all directly applicable. This is not a course.

**[FastAPI — Bigger Applications, Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/)**
The closest official guidance to the layout we're building. Read it **before** the folder-structure
argument, not after.

**[SQLAlchemy 2.0 — ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)** + the async ORM docs
2.0 style differs materially from the 1.x tutorials that dominate search results. Going to the
source saves a day of confusion about `select()` vs `query()`.

**[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)** + [what autogenerate detects](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect)
You'll run `--autogenerate` fifty times over eight weeks. Knowing what it *silently misses* —
server defaults, constraint renames, some type changes — prevents a data-loss migration in week 5.

**[RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)**, status code section only
The actual specification, not a blog post's interpretation. Fifteen minutes settles most of the
status-code arguments in W1-02 before they start — including `401` vs `403`, which every team gets
wrong at least once.

**[RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)** *(skim)*
A real standard for the error envelope we're deciding in W1-02. Adopt it or reject it
deliberately — don't invent a shape by accident.

**[Modular Monolith: A Primer](https://www.kamilgrzybek.com/blog/posts/modular-monolith-primer)** — Kamil Grzybek
The architecture we're building, with the vocabulary needed for ADR-0001.

## How to use these

Read the resource when the task needs it, not before. If you're on W1-05, read the Alembic docs.
Don't read all six on Sunday — you'll retain none of it.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.
