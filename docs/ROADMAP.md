# 8-Week Roadmap — Threat Exposure Management Platform

**Backend internship · 4 engineers · Sunday–Thursday, 4h/day**

Decisions and rationale live in [DECISIONS.md](./DECISIONS.md). This file is the plan.

---

## The shape of the arc

**Weeks 1–3 · Spine.** All four build the shared platform together on parallel tracks.
No module work until the pipeline they all plug into exists.

**Weeks 4–6 · Modules.** Pairs take modules, rotating so nobody owns one thing for six weeks.
Every module is a vertical slice reusing the same spine.

**Weeks 7–8 · Insight and hardening.** The pipeline stops storing findings and starts producing
answers. Then it becomes something another engineer could pick up.

**Lead rotation** — the weekly lead runs stand-up and owns integration for that sprint:

| Wk 1 | Wk 2 | Wk 3 | Wk 4 | Wk 5 | Wk 6 | Wk 7 | Wk 8 |
|---|---|---|---|---|---|---|---|
| Zyad | Tasneem | Islam | Arwa | Tasneem | Islam | Arwa | Zyad |

Each leads twice. The second turn is where growth shows.

---

## At a glance

| Wk | Goal | Ends with |
|---|---|---|
| 1 | Walking skeleton | `docker compose up` works, tenants CRUD, everyone has merged a PR |
| 2 | Multi-tenancy that holds | JWT + RBAC + API keys; a test proves tenant A can't reach tenant B; CI blocks red PRs |
| 3 | Jobs, pipeline spine, staging | POST a target → worker discovers subdomains → findings persist. Live on staging |
| 4 | ASM depth | Real scanner they wrote: ports, HTTP probing, TLS, rate limiting, change detection |
| 5 | ClickHouse + Threat Intel | Time-series analytics endpoints; KEV/NVD/EPSS feeds refreshing on schedule |
| 6 | Dark Web + Brand Protection | All four modules producing findings through one pipeline |
| 7 | Insight, alerts, RLS | "Which assets run known-exploited software, and who was alerted?" + DB-level isolation |
| 8 | Hardening, docs, demo | Documented, tested, deployed, rehearsed demo, retrospectives |

---

## Week 1 — Walking skeleton

**Goal:** every intern can run the whole stack, and module boundaries are decided before any
module exists.

**Build:** repo scaffold with `core/` + `modules/{asm,intel,darkweb,brand}` · Docker Compose
(Postgres, Redis, app) · Alembic wired with a first migration · Tenant model + CRUD · Docker
target lab for scanning against known ground truth · structured logging, error envelope, Pydantic
Settings, health endpoint · ADR-0001 on module boundaries.

**Concepts:** modular monolith layering, FastAPI dependency injection, Alembic revisions,
12-factor config, repository pattern, Compose networking, trunk-based branching and PR flow.

**Deliverable:** `docker compose up` produces a working API. Create and list tenants. Every intern
has merged one reviewed PR. The team has agreed a single error-response and pagination convention
in writing.

---

## Week 2 — Multi-tenancy that actually holds

**Goal:** nobody can read another tenant's data, and CI proves it on every push.

**Build:** users + password hashing · JWT issue and verify · RBAC (owner/analyst/viewer) as
FastAPI dependencies · per-tenant API keys, hashed at rest · request-scoped tenant context
enforced in the repository layer · GitHub Actions running ruff + pytest against a Postgres service
container · pytest fixtures and transactional test isolation.

**Concepts:** JWT claims and expiry, hashing vs encryption, RBAC, request-scoped context, API key
storage, test fixtures and rollback isolation, CI service containers.

**Deliverable:** authenticated multi-tenant API. A test proves tenant A cannot reach tenant B's
data through any endpoint. CI is red or green on every PR, and red blocks merge.

---

## Week 3 — Jobs, pipeline spine, staging ⚠️

**Goal:** work leaves the request path, the shared pipeline exists, and the thing runs somewhere
that isn't a laptop.

**Build:** arq worker + Redis · core domain models — `Target`, `ScanRun`, `Finding` — and the job
state machine · retries, timeouts, failure handling · first real ASM job: DNS resolution + crt.sh
subdomain discovery · staging VPS provisioned, deploy workflow auto-deploying on merge to `main`.

**Concepts:** async task queues, idempotency, at-least-once delivery, retry and backoff, job state
machines, worker concurrency, secrets in CI, migration-vs-deploy ordering.

**Deliverable:** POST a target → job enqueues → worker discovers subdomains → findings persist →
GET returns them. Running on staging, deployed automatically.

> **Riskiest week.** Two people on jobs and the domain model, two on staging. If it slips, week 4
> absorbs it — everything downstream depends on this spine.

---

## Week 4 — ASM depth

**Goal:** a real scanner they wrote themselves, and enough data volume to start hurting.

**Build:** async TCP connect scanner with semaphores and timeouts · HTTP prober (status, title,
headers, tech fingerprint) · TLS certificate parsing, with SANs feeding back into discovery ·
Redis-backed per-host rate limiting and politeness caps · recurring scheduled scans · finding
dedup and change detection between runs.

**Concepts:** asyncio semaphores/gather/timeouts, backpressure, token bucket rate limiting, TLS
SANs, service fingerprinting, idempotent upsert, change detection.

**Deliverable:** a full repeatable scan of the approved scope — subdomains, live hosts, open
ports, services, TLS data — rate-limited, reporting what changed since the last run.

---

## Week 5 — ClickHouse + Threat Intelligence

**Goal:** event volume gets a proper home; the second module lands.

**Build:** *Pair A* — ClickHouse event/timeline store, worker event stream, analytics endpoints
(asset timeline, findings over time, top services), Redis caching on hot reads. *Pair B* — Threat
Intel module: CISA KEV, NVD and EPSS ingestion, normalization to a common shape, scheduled
refresh.

**Concepts:** OLTP vs OLAP, columnar storage, MergeTree, partitioning and ordering keys,
dual-write consistency, cache invalidation and TTL, feed normalization, CVE/CPE structure, EPSS vs
CVSS.

**Deliverable:** analytics endpoints answering time-series questions from ClickHouse; threat intel
feeds refreshing on a schedule into normalized storage.

> **Why ClickHouse arrives now:** by week 5 they have four weeks of scan events in Postgres and the
> queries are slow. The lesson only lands because they felt the problem first.

*Optional AI lane (Arwa, Tasneem): offline IOC extractor — regex + spaCy over unstructured feed text.*

---

## Week 6 — Dark Web + Brand Protection

**Goal:** all four modules producing findings through one pipeline.

**Build:** *Pair A* — Dark Web: simulated leak feed ingestion, normalization, matching leaked
records against tenant domains and identities. *Pair B* — Brand Protection: domain permutation
generation, crt.sh certificate transparency monitoring, RDAP lookups, app store impersonation via
Apple's keyless iTunes Search API, social platform source designed as an interface and stubbed.

**Concepts:** fuzzy and exact matching strategies, normalizing messy third-party data, permutation
algorithms (typosquatting, homoglyphs, bitsquatting), certificate transparency, RDAP vs WHOIS,
adapter pattern for unavailable sources.

**Deliverable:** four modules, one pipeline, one findings model. A demo that walks a single tenant
across all four surfaces.

*Optional AI lane: entity extraction over leak dumps.*

---

## Week 7 — Insight, alerts, and RLS

**Goal:** the platform stops storing findings and starts telling you things.

**Build:** correlation feature, whole team — ASM findings matched against known-exploited CVEs ·
alert model + rule engine (severity threshold, new asset appeared, KEV match, leak match) · alert
dedup and suppression · webhook delivery with retry · **Postgres RLS** applied to core tables, so
week 2's cross-tenant test passes at two independent layers · API rate limiting.

**Concepts:** RLS policies and session variables, defense in depth, rule engines, alert fatigue
and suppression, webhook delivery semantics, correlation across module boundaries.

**Deliverable:** *"which of my assets run software with known-exploited vulnerabilities, and who
was alerted?"* — answered by the API. Tenant isolation enforced in the database as well as the
application.

---

## Week 8 — Hardening, docs, demo

**Goal:** something another engineer could pick up on Monday.

**Build:** performance pass — find the slow query with `EXPLAIN ANALYZE`, add the index, prove the
improvement with numbers · close test coverage gaps · OpenAPI polish, README, architecture doc,
runbook · seed/demo data script · final demo · retrospective.

**Concepts:** query plans, N+1 detection, index design, connection pooling, profiling, API docs as
contract, runbooks, honest retrospectives.

**Deliverable:** a documented, tested, deployed platform with a rehearsed end-to-end demo, and a
written retrospective from each intern on what they would do differently.

---

## Risks being watched

**Week 3 is load-bearing.** Jobs, domain model and staging land together, and everything after
depends on it. If it slips, cut staging to week 4 before cutting the pipeline spine.

**Week 6 tests the "four balanced modules" premise.** Two modules in one week only works because
they are thin slices on a spine that already works. If weeks 3–5 slipped, Brand Protection shrinks
first — it has the fewest downstream dependencies.

**The week 7 correlation feature is the demo.** Everything before it is plumbing. If time runs
short anywhere, protect that feature — it is what makes eight weeks look like a product rather
than four exercises.
