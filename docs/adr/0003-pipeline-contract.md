# ADR 0003: Pipeline Contract — Target, ScanRun, Finding, Jobs and API

**Date:** 2026-09-07
**Status:** proposed — gates Week 3 (must merge Sunday per W3-01)
**Owners:** Islam (ADR + W3-12 + W3-13) · **Reviewers:** all four + mentor
**Gates:** W3-02, W3-03, W3-04 start from this. Three people stall Monday if it doesn't merge.
**Applies to:** W3-02 … W3-13 (all `week-3` issues), and every module that plugs into the pipeline in weeks 4–7 (ASM, intel, darkweb, brand).

## Context

Week 3 moves work off the request path. The API stops doing scans and starts scheduling them; a
separate `arq` worker does the work; `Target`, `ScanRun` and `Finding` become the spine that four
modules plug into for five weeks.

Constraints we designed under:

1. **Four producers, one schema.** ASM is the only producer visible today (subdomains). Week 5
   brings IOCs with confidence scores and feed names; week 6 brings leaked credentials with breach
   dates and paste URLs; week 7 brings app-store listings impersonating a brand. The schema must
   hold all four **without a schema change** (W3-01, W3-02).
2. **At-least-once delivery.** The queue guarantees a job runs, not that it runs once. Duplicate
   execution is normal operation. Jobs must be idempotent; re-running a scan must not duplicate
   rows (W3-06, W3-08, W3-13).
3. **No request in a job.** No `Authorization` header, no ASGI scope, no middleware. A job carries
   `tenant_id` in its payload and must establish the same scope the middleware would — failing
   closed, never open (W3-05, ADR-0002 §4).
4. **One blocking call stalls the worker.** `arq` runs N jobs concurrently on one event loop. DNS,
   HTTP and sleeps must all be async with per-call timeouts (W3-04, W3-07).
5. **The repo contradicts itself.** `docs/api-conventions.md` (week 1) mandates flat
   `items`/`pagination` with limit/offset; the tenant endpoints ship JSON:API `data`/`links` with
   cursor pagination. W3-11 adds five endpoints that bake in whichever answer wins. The
   contradiction ends this week (W3-01, #52).
6. **Per-call commits don't survive a scan.** `TenantScopedRepository.create()` commits per row.
   W3-07 hands it ~400 findings per job. Batching and idempotency must compose (W3-02, W3-08,
   W3-13).

## Goals / non-goals

Goals: a domain model W3-02 can migrate without asking a question; a job contract W3-03/05/06/07
can code against; a fingerprint rule W3-08 can implement; an API envelope W3-11 can follow
blindly; a doc W3-12 can hand to a week-5 newcomer.

Non-goals: ClickHouse analytics (week 5), RLS (week 7), staging ops (deferred — the runbook half
of W3-12 went with it), real dark-web access, active port probing (W3-07 is passive only:
public DNS + public CT logs).

## Decisions

### 1. Placement: `Target`, `ScanRun`, `Finding` live in `core`

Per ADR-0001's dependency rule (`modules → core`, never `modules → modules`), all three are
platform concepts in `src/app/core/` (models + repositories + state machine + severity mapping +
source protocol). ASM is the first consumer, not the owner. The alternative — four pipelines by
week 7 — is exactly what ADR-0001 forbids.

Each model inherits `TenantOwnedMixin` (indexed `tenant_id` FK `ondelete="CASCADE"` — never
hand-rolled) and each repository subclasses `TenantScopedRepository`.

### 2. `Target`: one table with `kind`, not one table per kind

**Table `targets`:**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK, default `uuid4` | server-generated; client never supplies |
| `tenant_id` | FK `tenants.id` CASCADE, indexed, NOT NULL | from `TenantOwnedMixin` |
| `kind` | `TEXT`, NOT NULL | `domain` \| `ipv4` \| `ipv6` \| `cidr` \| `keyword` \| `brand_name` \| `app_store_url` (open enum — new kinds are new values, not migrations) |
| `value` | `TEXT`, NOT NULL | as submitted (`Admin.Example.COM.`) |
| `value_normalized` | `TEXT`, NOT NULL | canonical form used for uniqueness + fingerprint (§6) |
| `is_active` | `BOOL`, default true | deactivated targets are never enqueued |
| `created_at` / `updated_at` | `timestamptz`, `server_default=now()` | UTC, `Z`-suffixed in API |

Constraints/indexes: `UNIQUE (tenant_id, kind, value_normalized)`; index `(tenant_id, kind)`;
index `(tenant_id, created_at, id)` — required for the `(created_at, id)` cursor to use an
index scan rather than a sequential scan; without this every page-load is O(N).
Cursor for pagination: `(created_at, id)` — stable and unique; every new repository implements
`_cursor_columns` / `_encode_cursor` / `_decode_cursor` (the `NotImplementedError` trio) with a
stable + unique ordering, or the PR doesn't merge.

**Normalization (in service, not SQL):** domains → lowercase, strip trailing dot, IDNA/punycode,
reject wildcards (`*.example.com` is never a target); IPs/CIDRs → `ipaddress` module canonical
form; keywords/brand names → casefold + collapse whitespace; URLs → lowercase host + strip
trailing slash. **Validation lives in Pydantic schemas + service** (`POST /api/v1/targets` rejects an
invalid domain with 422). We deliberately put no `CHECK` constraint on `kind`/`value` shape in
Postgres: a new kind in week 6 must not require a constraint migration. The DB enforces identity
(uniqueness); the app enforces shape.

Why one table: separate tables per kind (`domains`, `cidrs`, `keywords`…) would force every
downstream query — runs by target, findings by target, week-7 correlation — into unions, and week
6's keyword would need a new table + new FKs. One table with `kind` holds a dark-web keyword with
zero DDL.

### 3. `ScanRun`: the honest record of what happened

**Table `scan_runs`:**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | created by the API when the scan is **enqueued** (state `queued`), passed as the job arg |
| `tenant_id` | FK CASCADE, NOT NULL | |
| `target_id` | FK `targets.id` CASCADE, NOT NULL | index `(tenant_id, target_id, created_at)` |
| `status` | `TEXT`, NOT NULL, default `queued` | `queued` \| `running` \| `succeeded` \| `failed` — the only four values |
| `attempt` | `INT`, default 1 | incremented per try; **a retry never creates a second row** |
| `max_attempts` | `INT`, NOT NULL | mirrors arq `max_tries` so the row explains itself without reading worker config |
| `arq_job_id` | `TEXT`, nullable | correlation into worker logs; advisory only |
| `sources_attempted` | `JSONB`, default `[]` | e.g. `["dns","crtsh"]` |
| `sources_degraded` | `JSONB`, default `[]` | subset of attempted; `[]` + zero findings = "nothing found", non-empty = "source was down" |
| `findings_count` / `new_findings_count` | `INT`, default 0 | written once on completion |
| `started_at` / `finished_at` | `timestamptz`, nullable | `queued` has neither; `running` has `started_at` |
| `error_kind` | `TEXT`, nullable | `retryable` \| `terminal` \| `stale` \| null |
| `error_message` | `TEXT`, nullable, truncated to 2000 chars | **scrubbed** — never a secret, token, connection string, traceback or raw SQL |
| `created_at` / `updated_at` | `timestamptz`, `server_default=now()` | `updated_at` advances on every state transition |

Indexes: `(tenant_id, target_id, created_at)` for "runs for this target" queries;
`(tenant_id, created_at, id)` for the `(created_at, id)` list cursor — without this every
`GET /api/v1/scan_runs` page is a sequential scan.
Cursor for pagination: `(created_at, id)`.

**State machine** (single module, e.g. `src/app/core/jobs/states.py` — the only place that may
assign `status`):

```
queued → running → succeeded
               → → failed
```

Illegal transitions raise; there is no `running → queued`, no resurrection of a terminal row, no
ad-hoc assignment elsewhere. Terminal errors skip remaining retries and go straight to `failed`.

**Source of truth: Postgres, not Redis.** `arq` tracks job results in Redis with a TTL; the
`ScanRun` row is permanent. When they disagree, the row wins and Redis is advisory. Consequences:
`GET /api/v1/scan_runs/{id}` reads the row; worker-down means the row sits in `queued` (with `created_at`
telling the caller how long); a re-delivered `succeeded` run is a no-op upsert, never a second
row (the week-5 bug this prevents).

**Stuck runs.** A worker killed mid-job leaves `running` with nobody working. Decision: no
heartbeat thread in week 3 (complexity the team can't absorb); instead (a) `started_at` age check
— any consumer may treat `running` older than `2 × job_timeout` as suspect, (b) a periodic sweep
job (week 4) marks them `failed`/`stale` with a note, (c) `docs/pipeline.md` documents the exact
operator query ("how to tell a stuck scan", W3-12). Any of heartbeat/sweep/age-check is a real
answer; not having thought about it is not — this is ours.

### 4. `Finding`: normalized core + `details` JSONB + platform severity

**Table `findings`:**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | FK CASCADE, NOT NULL | part of uniqueness (§6) |
| `target_id` | FK CASCADE, NOT NULL | index `(tenant_id, target_id, last_seen_at)` |
| `last_seen_run_id` | FK `scan_runs.id` `SET NULL`, nullable | provenance; null only if the creating run was purged |
| `kind` | `TEXT`, NOT NULL | `subdomain` \| `ip` \| `credential` \| `app_listing` \| `ioc` … (open set like `Target.kind`) |
| `value` | `TEXT`, NOT NULL | human display (`admin.example.com`, `admin@example.com`, `1.2.3.4`, store URL) |
| `value_normalized` | `TEXT`, NOT NULL | fingerprint input (§6) |
| `fingerprint` | `CHAR(64)`, NOT NULL | hex SHA-256, deterministic across processes/restarts |
| `severity` | `TEXT`, NOT NULL | platform enum `info` \| `low` \| `medium` \| `high` \| `critical` (§5) |
| `raw_severity` | `TEXT`, nullable | what the module said, kept for audit |
| `status` | `TEXT`, default `active` | `active` \| `resolved` — disappearance marks, never deletes |
| `first_seen_at` | `timestamptz`, NOT NULL | set once, **never moves** |
| `last_seen_at` | `timestamptz`, NOT NULL | moves on every sighting |
| `times_seen` | `INT`, default 1 | incremented on upsert |
| `details` | `JSONB`, NOT NULL, default `{}` | module-specific: `{"ip": "203.0.113.10"}`, `{"confidence": 0.8, "feed": "c2"}`, `{"breach_date": "2026-08-14", "paste_url": "…"}`, `{"store": "apple", "app_id": "…"}` |
| `created_at` | `timestamptz`, NOT NULL, `server_default=now()` | database record creation — distinct from `first_seen_at` (which is the security-domain concept: when the threat was first observed) |
| `updated_at` | `timestamptz`, NOT NULL, `server_default=now()`, `onupdate=now()` | advanced on every upsert |

Constraints/indexes: `UNIQUE (tenant_id, fingerprint)`; indexes `(tenant_id, kind, severity)`,
`(tenant_id, status)`, `(tenant_id, created_at, id)` — required for the `(created_at, id)` cursor
to use an index scan rather than a sequential scan; GIN on `details` only if week 4 proves a query
needs it (no speculative indexes). `first_seen_at` immutability is enforced in the upsert
(`ON CONFLICT DO UPDATE` never assigns it) + a regression test.

**The shape rule:** anything you filter, sort, page or alert on is a real column (`kind`,
`severity`, `status`, timestamps). Anything module-specific lives in `details`. Pure-columns
fails week 6 (a column per module, mostly null); pure-blob fails alerting (can't index/sort).
This hybrid is the only shape that fits all four week-1 examples without DDL:

- ASM: `kind=subdomain, value=admin.example.com, details={"ip":"203.0.113.10"}` (+ DNS record
  types as needed, still no new column)
- Intel: `kind=ioc, value=1.2.3.4, details={"confidence":0.8,"feed":"botnet-c2"}`
- Dark web: `kind=credential, value=admin@example.com, details={"breach_date":"2026-08-14","paste_url":"…"}`
- Brand: `kind=app_listing, value=<store URL>, details={"store":"apple","title":"…","developer":"…"}`

### 5. Severity: module proposes, platform disposes

`severity` is a platform enum (`info/low/medium/high/critical`); a single function in core
(e.g. `core/severity.py::normalize(kind, raw)`) maps each module's native scale onto it.
Modules send a suggestion (`raw_severity` preserved); core owns the stored value so sorting,
filtering and week-7 alert rules behave identically across modules. Unknown/unmapped input →
`info` + a warning log (never a 500, never a null).

### 6. Fingerprint: what makes two findings the same finding

**Rule:** `fingerprint = hex(sha256(kind + "|" + target_id + "|" + value_normalized))`.

- `value_normalized`: domains → lower, no trailing dot, punycode; emails → lower, trim; IPs →
  canonical packed form; URLs → lower host, no trailing slash. Normalization is versioned with
  the code that computes it; changing it is a conscious migration, not an edit.
- **`target_id` string format:** always `str(target.id)` — the standard hyphenated lowercase UUID
  string (e.g. `"3fa85f64-5717-4562-b3fc-2c963f66afa6"`). Never `target.id.hex` (no hyphens).
  Both are valid Python but produce different SHA-256 values; using the wrong form silently breaks
  deduplication across processes. This format is non-negotiable.
- **Included:** `kind`, owning `target_id`, normalized identity value. That's it.
- **Excluded:** `source` (DNS and crt.sh finding `admin.example.com` is **one** finding — argue
  this with your reviewer before writing the constraint, per W3-08), IPs/TTLs behind a hostname,
  confidence scores, timestamps, severity, `details`.
- Deterministic across processes/restarts: SHA-256 over a canonical string. Python `hash()` is
  salted per process and is a correctness bug here.
- Scoped by tenant via `UNIQUE (tenant_id, fingerprint)`: two tenants finding the same subdomain
  get two rows. Same scan three times → one set of rows, `first_seen_at` pinned,
  `last_seen_at` advancing, `times_seen` incrementing.

**Upsert:** single-statement Postgres `ON CONFLICT (tenant_id, fingerprint) DO UPDATE` with the
following SET clause — never touching `first_seen_at`:

```sql
ON CONFLICT (tenant_id, fingerprint) DO UPDATE SET
    last_seen_at     = EXCLUDED.last_seen_at,
    last_seen_run_id = EXCLUDED.last_seen_run_id,
    times_seen       = findings.times_seen + 1,
    status           = 'active',
    severity         = EXCLUDED.severity,
    raw_severity     = EXCLUDED.raw_severity,
    details          = findings.details || EXCLUDED.details,
    updated_at       = now()
    -- first_seen_at deliberately excluded
```

`details = findings.details || EXCLUDED.details` is a JSONB shallow merge: new top-level keys
from the latest scan are added; existing keys are overwritten with the freshest value. This
preserves historical telemetry (e.g. previously seen DNS record types) while reflecting current
state (e.g. updated IP). No read-then-write (races under at-least-once). Findings absent from a
scan are **not deleted** — a vanished subdomain is a signal; the job marks it `resolved` (or
week 4's change detection does), it never erases it.

Too much in the fingerprint (IP, TTL) → every rescan fabricates "new" findings. Too little (no
`kind`, no `target_id`) → distinct findings collapse silently, which is worse because nothing
looks wrong. The inputs above are the line.

### 7. Job contract (W3-03 / W3-05 / W3-06 / W3-07 share this)

- **Test harness first (W3-03).** `run_job(fn, *args, tenant_id=…, try_number=…)` runs the real
  job function in-process against a real Postgres with a constructed `ctx` (`job_id`, `try`,
  session, enqueued metadata). No worker, no Redis, no private event loop in CI. Retry is
  simulated as same-job-same-args-try-2. The boundary substituted is the queue — everything on
  our side runs for real; mocked job functions asserting "called" are rejected. Week-1
  transactional rollback stays; the suite stays seconds-fast. Constraint this forces (and the
  valuable part): jobs may only reach the outside world through `ctx`/injected deps, never by
  reaching out directly.
- **Tenant context as mechanism, not reminder (W3-05).** A decorator/wrapper (e.g.
  `@with_tenant_context`) establishes `Principal` from the enqueued `tenant_id` on entry and
  **resets it in a `finally` (reset token) on exit, including on raise** — `contextvars` are
  reused across jobs on one loop and a leak is a quiet cross-tenant breach. Forgetting the
  context raises `MissingTenantContextError` (fail closed, never empty-scope reads). The
  explicit `tenant_id=` escape hatch on the repository is **not** the job path — convention
  ("remember to pass it") is what week 2 replaced with structure. System/scheduled jobs carry a
  synthetic `Principal(user_id="system:<job>", tenant_id=<tenant>, role=OWNER)` — no `Principal`
  shape change in week 3 (rejected as churn; revisit if week 5 needs machine scopes). Every log
  line binds `tenant_id` + `job_id` (structlog `contextvars`).
- **Lifecycle (W3-06).** `max_tries=3` + exponential backoff **with full jitter** (lockstep
  retries are self-DDoS); **two timeouts** — `job_timeout` on the job (e.g. 300 s) *and* a
  timeout on every outbound call (httpx `connect=5s/read=15s/total=30s`; DNS per-query timeout);
  **retryable vs terminal** classified once (`Retry` for 502/timeout/SERVFAIL; plain raise for
  invalid domain/4xx incl. validation) — terminal skips retries and lands `failed` immediately;
  **retry visibility during backoff:** before raising `arq.worker.Retry` the worker updates the
  `ScanRun` row — `attempt` incremented, `error_kind = 'retryable'`, `error_message` = scrubbed
  reason (e.g. `"crt.sh 502 — retrying with jitter"`); `status` remains `'running'` so polling
  clients can distinguish "actively running" from "waiting before retry N" without a fifth state;
  failure rows carry `error_kind` + scrubbed `error_message` + `attempt`; **never log a secret,
  token, connection string, traceback or SQL**. Tests: retry reuses one run; deadline exceeded →
  `failed` with reason; terminal never retries.
- **Discovery (W3-07).** Async only (`dnspython` asyncio resolver; `httpx` — promoted from
  `dev` to runtime deps in this PR); `ScanSource` protocol in core with
  `collect(target) -> SourceResult(items, degraded, note)`; DNS (A/AAAA/CNAME) + crt.sh
  (`https://crt.sh/?q=%25.<domain>&output=json`) both implement it; **a down source returns
  fewer results, never an exception** (`DECISIONS.md` §5) and lands in `sources_degraded` so
  "zero findings" ≠ "crt.sh was down"; dedup/normalize across sources (case, trailing dots,
  `*.` wildcards dropped, out-of-scope names dropped); bounded concurrency
  (`asyncio.Semaphore`, e.g. 50) + result caps + per-call timeouts + no recursion into
  discovered names; persist via W3-02's repo + W3-08's fingerprint seam; **tests never touch the
  network** (`respx` fixtures incl. 502 + timeout; fake DNS resolver); passive only — no probing,
  no port opens, no packets to non-ours.
- **Transaction boundary (W3-02 + W3-13).** The caller owns the unit of work. `create()`'s
  per-call commit stays for single-row request paths; jobs use a batch path (many rows, one
  transaction, chunked e.g. 500/chunk so 50 k CT rows never hold locks for a minute) that
  **overwrites `tenant_id` per row exactly like `create()`** (no opt-out — a batch that skips
  stamping is a silent cross-tenant write that passes every test you thought of) and composes
  with `ON CONFLICT` upsert. W3-08 reports the before-count; W3-13 proves the after-count.

### 8. Worker (W3-04)

`arq` (`WorkerSettings`: Redis via existing `core/redis.py` — no second client, function
registry, startup/shutdown hooks, modest concurrency). `worker` service in `compose.yaml` shares
the app image with its own command, same env/network, no exposed ports. `just worker` /
`just worker-logs`. **Graceful shutdown:** `SIGTERM` drains (stop taking jobs, finish in-flight;
`stop_grace_period` ≥ `job_timeout` + margin) so redeploys never strand a `running` row.
Structured logs with `job_id` + `tenant_id` on every line. **`redis_required` is `True` for the
worker** (a queue consumer that tolerates a missing queue reports healthy while doing nothing —
rejected); it stays `False` for the API. Crash-loop on missing Redis at startup is correct for
the worker. PR references `DECISIONS.md` §4 (arq is approved — explain why briefly, don't
relitigate) and warns W3-07 that one blocking call stalls the whole loop.

### 9. API contract — the contradiction ends here (W3-11 + #52)

**Keep JSON:API `data` + cursor pagination (`size`/`cursor`, `links.next`); reject flat
`items`/`pagination` + limit/offset.** Rationale (already in `api-conventions.md` "Option B" and
now binding): findings/runs churn between requests — offsets skip/repeat, cursors don't; no
count query; scales past tenant-sized tables. W3-11's five endpoints follow the winner:

- `POST /api/v1/targets` → `201 Created` + `Location: /api/v1/targets/{id}`, strict validation
  (bad domain → 422, duplicate → 409); `GET /api/v1/targets` paginated, tenant-scoped
- `PATCH /api/v1/targets/{id}` → toggle `is_active`; `owner`/`analyst` only; `viewer` → 403
- `POST /api/v1/targets/{id}/scans` → **`202 Accepted` + the run resource (`queued`)** — the
  request path does no scanning and waits for nothing; `Location: /api/v1/scan_runs/{id}`
- `GET /api/v1/scan_runs/{id}` → state, timings, `attempt`/`max_attempts`,
  `sources_attempted/degraded`, counts, scrubbed failure reason; JSON:API type: `"scan_runs"`
- `GET /api/v1/findings` → paginated, filterable by `target_id` and `run_id` minimum
- Envelope/pagination/naming/timestamps/UUIDs/RFC-9457 errors per `api-conventions.md`;
  **no raw exception/SQL text to clients**; unknown filter params → 400; `size > 100` → 400.

Per-resource cursor orderings (stable + unique):

| Resource | Cursor columns | Index required |
|---|---|---|
| `targets` | `(created_at, id)` | `(tenant_id, created_at, id)` |
| `scan_runs` | `(created_at, id)` | `(tenant_id, created_at, id)` |
| `findings` | `(created_at, id)` | `(tenant_id, created_at, id)` |

**RBAC + existence:** `viewer` reads, never enqueues (W2-08). Cross-tenant reads → **`404`, not
403** (week-2 rule, unchanged — prevents ID enumeration; this is the one documented exception to
`api-conventions.md`'s 403 default and W3-01 amends that section accordingly). Duplicate
`POST …/scans` → a decision, not an accident: each call enqueues a new run (rescan is
legitimate); client-side dedup/idempotency keys are out of scope for v1 and documented as such.
W2-10's isolation suite gains the five new routes in `DATA_ROUTES`.

Required `api-conventions.md` amendments with this ADR (Islam, Sunday): (a) collections are
JSON:API + cursor — delete the `items`/`pagination` alternative; (b) cross-tenant reads return
404 (enumeration resistance); (c) `202` + polling contract for async commands; (d) per-resource
cursor orderings are declared per endpoint (tenants: `(name,id)`; targets/runs/findings:
`(created_at,id)` unless the endpoint documents otherwise).

### 10. Docs (W3-12)

`docs/pipeline.md` (short — linked from README): request→enqueue→worker→persist path in one
diagram/paragraph; **how a module adds a job** (registration, context, transitions it owns, what
the framework does — longest half-life section); `ScanRun` states + un-enqueued transitions;
fingerprint rule + `first_seen_at` immutability; reading worker logs (filter one job among many);
diagnosing `running`-forever (the operator query from §3); confirming "crt.sh is down vs bug".
Written while it still annoys you, tested by handing it to Tasneem cold.

## Team roles — how this ADR becomes behaviour

| Issue | Owner → Reviewer | Rule this ADR imposes on them |
|---|---|---|
| W3-01 (this ADR) | Islam → all + mentor | Merges **Sunday**. W3-02/03/04 start Monday from it. Amends `api-conventions.md` or the code stops contradicting itself. |
| W3-02 domain | Zyad → Arwa + mentor | `core/`, `TenantOwnedMixin`, one migration (+ deletes orphaned `alembic/` per #54), repos with real cursor impls, indexes as specified, states what the txn boundary should be. `needs-mentor-review`. |
| W3-03 harness | Tasneem → Islam | Substitute the queue, run everything else for real. `run_job()` + retry simulation + no-context failure path. CI starts no Redis/worker. |
| W3-04 worker | Zyad → Arwa | arq + `core/redis.py`, Compose service, `just worker*`, graceful shutdown, `redis_required=True` for worker, async-only warning to W3-07 in the PR. |
| W3-05 tenant-in-job | Tasneem → Islam | Decorator mechanism + `finally` reset + system principal + tenant-bound logs; four named tests. Never the `tenant_id=` escape hatch on the job path. |
| W3-06 lifecycle | Arwa → Zyad | One state machine module; one run per job incl. retries; jittered backoff; dual timeouts; retryable/terminal split; stale-run answer; scrubbed failures; no secret in logs. |
| W3-07 discovery | Arwa → Zyad | `ScanSource` interface, async-only, graceful degradation + `sources_degraded`, normalize/dedup, caps + semaphore, `httpx` promoted to runtime, `respx` fixtures (502 + timeout), passive only. |
| W3-08 fingerprint | Zyad → Tasneem | SHA-256 rule exactly as §6; `ON CONFLICT (tenant_id, fingerprint)`; `first_seen_at` pinned; no deletes; publishes the before-count for W3-13. Source excluded from fingerprint — argued aloud before the constraint is written. |
| W3-11 API | Tasneem → Islam | Five endpoints in the §9 envelope; `202` for enqueue; viewer-can't-scan; cross-tenant 404; no raw errors; documents the triple-POST decision. |
| W3-13 batch | Islam → Zyad | Batch path alongside `create()`; one txn per scan (chunked); forced tenant stamp per row + adversarial test; `create()` unchanged; before/after numbers in PR. |
| W3-12 docs | Islam → Tasneem | `docs/pipeline.md` + README link; passes the cold-read test. |
| W3-77 keywords | all | Thursday demo defends choices, not definitions. 45-min stuck timebox, except stuck-worker → ask immediately. |

**Merge order:** Sun W3-01 → Mon W3-02 + W3-03 + W3-04 (parallel) → W3-05 + W3-06 (need 02/03) →
W3-07 (needs 05/06) + W3-08 (needs 02/07-seam) + W3-13 (needs 02) → W3-11 (needs 02/06) → W3-12
(needs 07/11). **Definition of done** for every PR: tests for the cross-tenant, retry, and
degradation paths it touches; no blocking calls in job code; no secret in logs/errors; cursor
impl stable + unique; PR states what was rejected.

## Consequences

Positive: one pipeline four modules share; schema survives weeks 5–7 with no DDL; duplicates are
structurally impossible rather than disciplinarily avoided; tenant isolation holds without a
request; the API contradiction is gone; week 4's change detection is possible (`first/last_seen`
+ stable fingerprints); a week-5 newcomer onboards from one doc.

Negative: upfront interface cost (`ScanSource`, state machine, severity map); one-table `Target`
pushes validation into app code; cursor pagination is harder to hand-test than `?offset=`;
`ON CONFLICT` + batch upsert is more SQL than `create()` in a loop; synthetic system principals
coarsen audit (`system:asm-scan` vs a human) until week 5 scopes; no heartbeat means a stale-run
sweep is owed in week 4.

## What we rejected and why

| Rejected | Why |
|---|---|
| Separate tables per target kind / per-module finding tables | Unions everywhere downstream; every new kind is DDL + FK churn. One table + `kind` + `details` JSONB scales by value, not by migration. |
| Pure-JSONB finding (`details` for everything) | Unqueryable: can't index/sort/alert on severity, kind, time. Core columns for query paths, blob for module detail. |
| Pure-column finding (nullable column per module) | Null-sprawl; week 6 wants three new columns. Rejected in the meeting using the four-row test. |
| Fingerprint incl. source / IP / confidence / timestamps; Python `hash()` | Source-included splits one host into two findings; volatile fields fabricate "new" findings every rescan; `hash()` is per-process salted. SHA-256 over `(kind, target, normalized value)` only. |
| Read-then-write dedup; delete-on-absence | Races under at-least-once; disappearance is a signal (`resolved`), not an absence. `ON CONFLICT` in one statement. |
| Second `ScanRun` per attempt; Redis as source of truth | Attempts aren't work units; Redis entries expire. One row per job, Postgres wins disagreements. |
| `tenant_id` from URL/header in jobs; explicit-arg-only scoping | Two sources of tenant truth; one forgetful author leaks cross-tenant. Context mechanism + fail-closed repo. |
| New `ServicePrincipal` type this week | Churn for one consumer. Synthetic `Principal(role=OWNER, user_id="system:…")` is tenant-bound and sufficient; revisit with machine scopes. |
| Heartbeat thread for stuck runs now | Correct but heavy for week 3. Age-check + week-4 sweep + operator doc answers the question honestly. |
| Flat `items`/`pagination` + offset; per-module envelopes | Skips/repeats on churn + count queries + five new endpoints baking in the loser. JSON:API + cursor wins; doc amended. |
| Cross-tenant 403 for pipeline reads | Leaks existence (enumeration/BOLA #65). 404 for cross-tenant reads, documented as the exception. |
| Sync DNS / `requests` / `time.sleep` in jobs; unbounded fan-out | Stalls the single event loop; resolver stops answering. Async + semaphore + caps + dual timeouts. |
| Fail-the-scan when crt.sh is down | Third-party uptime gates our demo. Degraded results + `sources_degraded` note. |
| Per-row commit for scan writes | 400 commits/scan, no atomicity. Batch upsert, one txn per scan (chunked). |
| Mock-the-job-function tests; through-Redis e2e in CI | First tests nothing, second tests arq. In-process real-job harness. |
| `PUT`, HATEOAS, idempotency-keys framework in v1 | No replace-all resource needs `PUT`; hypermedia out of 8-week scope; scan dedup is a documented decision, not a framework. |

## References

- ADR-0001 (module boundaries), ADR-0002 (identity/tenant isolation, esp. §4 tenant-from-token,
  §8 `Principal`, §9 service users), `DECISIONS.md` §4 (arq) + §5 (graceful source degradation),
  `docs/api-conventions.md` (amended per §9), `ROADMAP.md` weeks 3–7
- Week-3 issues: #66 (this ADR) · #67 domain · #68 harness · #69 worker · #70 tenant-in-job ·
  #71 lifecycle · #72 discovery · #73 fingerprint · #74 API · #75 docs · #76 batch · #77 keywords
- `src/app/core/repository.py` (`TenantScopedRepository`, `MissingTenantContextError`,
  cursor trio), `src/app/core/models.py` (`TenantOwnedMixin`), `src/app/core/auth/context.py`
  (`contextvars` + `PrincipalContextMiddleware`), `src/app/core/auth/principal.py`
- arq docs (lifecycle, `WorkerSettings`, `max_tries`/`job_timeout`/`Retry`); AWS Builders'
  Library (backoff with jitter); Brandur idempotency keys; CT how-it-works; dnspython asyncio;
  SQLAlchemy session/unit-of-work; #52 (envelope contradiction); #54 (orphaned `alembic/`);
  #65 (BOLA tenant enumeration → 404 rule)

## Appendix A — the four-row test (must fit with no DDL)

```
targets: {kind: domain, value: "Example.COM.", normalized: "example.com"}
scan_runs: {status: succeeded, sources_attempted: ["dns","crtsh"], sources_degraded: []}
findings: {kind: subdomain, value: "admin.example.com",
           fingerprint: sha256("subdomain|<target-uuid>|admin.example.com"),
           severity: low, details: {"ip": "203.0.113.10", "record_types": ["A"]}}

targets: {kind: cidr, value: "1.2.3.0/24", normalized: "1.2.3.0/24"}
findings: {kind: ioc, value: "1.2.3.4",
           fingerprint: sha256("ioc|<target-uuid>|1.2.3.4"),
           severity: high, details: {"confidence": 0.8, "feed": "botnet-c2"}}

targets: {kind: keyword, value: "acme", normalized: "acme"}
findings: {kind: credential, value: "admin@example.com",
           fingerprint: sha256("credential|<target-uuid>|admin@example.com"),
           severity: critical, details: {"breach_date": "2026-08-14", "paste_url": "…"}}

targets: {kind: brand_name, value: "Acme", normalized: "acme"}
findings: {kind: app_listing, value: "https://apps.apple.com/…/id123",
           fingerprint: sha256("app_listing|<target-uuid>|https://apps.apple.com/…/id123"),
           severity: medium, details: {"store": "apple", "title": "Acme Wallet", "developer": "…"}}
```

## Appendix B — `ScanRun` transitions + operator query

Allowed: `queued→running`, `running→succeeded`, `running→failed`. Everything else raises.
Sweep/age rule: `running AND started_at < now() - 2*job_timeout` → suspect; sweep marks
`failed/stale`. Operator query (for `pipeline.md`): filter `status=running`, order
`started_at`, join `targets` for scope, check `arq_job_id` in worker logs, check
`sources_degraded` before declaring a bug.
