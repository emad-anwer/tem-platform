# Decision Record — Backend Internship

**Project:** Multi-tenant Threat Exposure Management platform (modular monolith)
**Duration:** 8 weeks · **Team:** 4 interns · **Mentor:** Emad Anwer
**Status:** Roadmap approved · Week 1 planned and filed as issues · Week 2 pending
**Last updated:** 2026-08-22

This records *what was decided and why*. It is the reference for "why did we do it this way"
questions later in the program. It is not a plan — the roadmap and weekly tasks live separately.

---

## 1. Program shape

| | |
|---|---|
| Working week | **Sunday–Thursday**, 4h/day = 20h/week per intern |
| Task load target | **14–16h/week** — the remainder is code review, debugging, reading, meetings |
| Total capacity | ~640 person-hours, of which ~400 are realistically productive |
| Sprint | Weekly, Sunday → Thursday |
| Ceremonies | Stand-up Sunday (kickoff) + Tuesday (mid-week); demo Thursday (~30 min) |
| Mentor time budget | ~3–4h/week |
| Evaluation | Informal judgement. Weekly knowledge checks, no formal scorecard |
| Start date | *TBC* |

---

## 2. Team

| Intern | Track |
|---|---|
| Arwa | Backend + optional AI lane |
| Tasneem | Backend + optional AI lane |
| Zyad | Backend |
| Islam | Backend |

All four have built and deployed APIs backed by a database. Framework fundamentals do not need
teaching; the program can go straight at architecture, concurrency and integration.

**Two standing rules:**

- **All four are backend engineers first.** Arwa and Tasneem get first refusal on optional AI
  tasks, but those never replace a backend deliverable and never sit on the critical path. If the
  AI lane slips entirely, the sprint still ships. Zyad and Islam may take AI tasks if interested —
  the lane is not fenced off.
- **The lead rotates across all four.** Eight weeks, four people — each leads twice, once early
  and once late. The weekly lead runs stand-up and owns integration for that sprint.

Contact emails are held outside this repo; they are needed only for GitHub invitations.

---

## 3. Architecture

| Decision | Choice | Why |
|---|---|---|
| Shape | Modular monolith | Good module boundaries matter; premature service splitting does not |
| Multi-tenancy | `tenant_id` on every row, resolved from the auth token, enforced in a shared repository layer | Simplest correct model. Schema-per-tenant adds migration and `search_path` complexity that teaches little here |
| Tenant isolation, phase 2 | Postgres **Row-Level Security**, added mid-program | Introduced *after* app-layer isolation exists, so the lesson is defense in depth rather than framework fighting |
| Auth | Tenant-scoped users, JWT access tokens, RBAC (owner/analyst/viewer), per-tenant API keys | Realistic without becoming a project of its own |
| Core abstraction | One shared pipeline: **targets → jobs → findings → alerts → analytics** | Four modules plug into one pipeline instead of each rebuilding it. This is what makes four balanced modules fit in eight weeks |

---

## 4. Stack

**From the original brief:** Python, FastAPI, PostgreSQL, Redis, ClickHouse, Docker, REST, Git.

**Additions, with justification:**

| Addition | Why it earns its place |
|---|---|
| **arq** (job queue) | Scanning and feed ingestion cannot run in request handlers. Async-native like FastAPI, runs on the Redis already in the stack, and small enough that an intern can read the whole library |
| **Alembic** | Migrations are an explicit learning goal; there is no way to teach them without it |
| **SQLAlchemy 2.0 (async)** | Industry standard, async-native, most transferable to their next job |
| **Pydantic v2** | Already the FastAPI contract layer |
| **ruff** | Lint and format in one fast tool; removes style from code review so review is about substance |

**ClickHouse timing:** deliberately withheld until ~week 4–5. The team runs on Postgres alone
until scan and event volume makes queries hurt. The lesson only lands if they have felt the
problem first.

---

## 5. Modules and data sources

All four modules are built, balanced — each a real vertical slice sharing the core pipeline,
differing in the data source and the engineering skill it exercises.

| Module | Approach | Sources |
|---|---|---|
| **ASM** | Hybrid: build the core scanner first (async resolver, TCP connect scanner, HTTP prober, TLS parsing), then wrap an external tool such as `subfinder`/`nuclei` in later weeks | crt.sh, DNS, RDAP, RIPEstat, SecLists wordlists, own probing |
| **Threat Intelligence** | Feed ingestion, normalization, enrichment | CISA KEV, NVD, EPSS, MITRE ATT&CK, abuse.ch, OTX |
| **Dark Web Monitoring** | Real ingestion / normalization / matching pipeline on **simulated** leak feeds | Synthetic leak data, public paste-style sources |
| **Brand Protection** | App store impersonation built for real; social platforms designed as a pluggable source interface but **stubbed** | Apple iTunes Search API (free, keyless), Google Play scraping, crt.sh + RDAP for the domain side |

**Scanning authorization:** active scanning is approved against a defined customer scope. A Docker
target lab is still built in week 1 — not as a fallback, but because a scanner needs known-good
ground truth to be tested against.

**Source policy:** every external source sits behind an interface that degrades gracefully to
nothing. No demo may depend on a third party being available.

**Keys:** no paid APIs. Free-registration keys (abuse.ch, OTX, NVD rate limit) are acceptable and
live in GitHub Actions secrets.

---

## 6. Engineering workflow

| | |
|---|---|
| Repository | Single private GitHub repo, branch protection on `main` |
| CI | GitHub Actions — lint + tests on every PR, from week 2 |
| Tracker | GitHub Issues + Projects (chosen over Trello: tasks sit next to the code and link to PRs) |
| Merge policy | Peer approval for routine PRs; a `needs-mentor-review` label gates schema changes, auth, and cross-module contracts |
| Testing | pytest, integration tests against dockerized Postgres, meaningful coverage of module logic. **No percentage gate.** Ramped in from week 2 |
| Docs | `/docs` in the repo, so documentation goes through code review |
| Design docs | One page required for anything crossing a module boundary; ADRs for decisions that matter |

---

## 7. Infrastructure

- **Local:** Docker Compose — Postgres, Redis, ClickHouse, app, worker.
- **Staging:** from **week 3**, on a cheap VPS (Hetzner / DigitalOcean).
- **Built by the interns**, reviewed by the mentor — Compose file, environment config, secrets
  handling, deploy script. Roughly one intern-week, and the rotating lead inherits operating it.
- **Auto-deploy on merge to `main`** via GitHub Actions. Makes a broken `main` immediately visible
  and enforces that `main` must always work.
- **Sizing:** Postgres + Redis + ClickHouse + app needs ~8GB RAM to be comfortable — a Hetzner
  CX32 (~€7/month), not the €4 box.
- **Account ownership:** the VPS account and billing stay on the mentor's side. Interns operate
  the environment; they do not hold billing credentials.

---

## 8. Deliberately excluded

| Excluded | Reason |
|---|---|
| Shodan, Censys, VirusTotal, urlscan, SecurityTrails | No paid API budget. Consequence is a net positive: the team writes the scanner instead of calling someone else's API, which teaches far more |
| Tor / real dark web access | Legal and operational exposure not justified for an internship. A simulated feed pipeline teaches the same ingestion, normalization and matching skills |
| Social platform APIs (X, Instagram, Facebook) | Paid, restricted, or closed to this use case; scraping violates ToS and breaks constantly. The source interface is designed and stubbed so the architecture stays correct |
| LLM APIs | No paid keys. The AI lane runs offline — regex + spaCy IOC extraction, classical classification. Slots in later if access appears, without changing anything |
| Frontend | Swagger UI plus demo scripts are the demo surface. The brief asks for a clean REST API |
| Kubernetes, managed cloud services | Cloud onboarding would consume most of a week and teach little relevant to backend engineering |
| Microservices | Explicit non-goal. Module boundaries inside one deployable |

---

## 9. The scope principle

640 person-hours minus learning, review, debugging and meetings leaves roughly **400 productive
hours** across four engineers who are still learning the domain. That does not buy four deep
modules.

What it does buy is **one shared pipeline with four genuinely different data sources plugged into
it**. Each module is a real vertical slice exercising a different skill — ASM: concurrency and
rate limiting; Threat Intel: parsing and enrichment; Dark Web: matching and normalization; Brand
Protection: permutation and third-party integration — while sharing the core rather than each
rebuilding it.

This is also what makes the team feel like one engineering team building one product, rather than
four people building four mini-projects.

**Standing test for any proposal:** *is this necessary for the interns to learn, or for the
product to work?* If neither, it stays out.
