# Week 3 — Work leaves the request path

**Sunday–Thursday · Lead: Islam**

Code repository: **<https://github.com/emad-anwer/tem-platform/>** — every active task below is a
live issue there.
Milestone: [Week 3 — Jobs and the Pipeline Spine](https://github.com/emad-anwer/tem-platform/milestone/3) ·
Keywords issue: [#77](https://github.com/emad-anwer/tem-platform/issues/77)

> **Staging is deferred.** W3-09 and W3-10 are still written below, marked optional and unassigned.
> No VPS is being provisioned this week, so nothing you build depends on one. They are deliberately
> **not** filed as issues — if you can't find them on GitHub, that's why. Don't start them.

This is the week the platform stops being four empty module directories. A request stops doing the
work and starts *scheduling* it. `Target`, `ScanRun` and `Finding` land in **`core`** — they belong
to the platform, and ASM is only the first thing to plug into them. And the tenant boundary you
built in week 2 gets tested somewhere it has never run: a process with no request, no header and no
middleware.

## Tasks

| # | Task | Owner | Reviewer | Effort | Depends on |
|---|---|---|---|---|---|
| [W3-01](W3-01-pipeline-design-adr.md) 🔑 | Pipeline design huddle and ADR-0003 | Islam | all four + mentor | 2h + 45m | — |
| [W3-02](W3-02-domain-model.md) 🔑 | Domain model: Target, ScanRun, Finding | Zyad | Arwa + mentor | 5h | W3-01 |
| [W3-03](W3-03-job-test-harness.md) 🔑 | Job test harness: run a job without a worker | Tasneem | Islam | 4h | W3-01 |
| [W3-04](W3-04-arq-worker.md) | arq worker service and Compose wiring | Zyad | Arwa | 4h | W3-01 |
| [W3-05](W3-05-job-tenant-context.md) 🔑 | Tenant context inside a job | Tasneem | Islam | 4h | W3-02, W3-03 |
| [W3-06](W3-06-job-lifecycle.md) | Job lifecycle: states, retries, timeouts, failure | Arwa | Zyad | 4h | W3-02, W3-03 |
| [W3-07](W3-07-subdomain-discovery.md) | Subdomain discovery: DNS and crt.sh behind a source interface | Arwa | Zyad | 5h | W3-05, W3-06 |
| [W3-08](W3-08-finding-fingerprint.md) | Finding fingerprint and idempotent upsert | Zyad | Tasneem | 3h | W3-02, W3-07 |
| [W3-11](W3-11-pipeline-api.md) | Pipeline API: targets, scan runs, findings | Tasneem | Islam | 4h | W3-02, W3-06 |
| [W3-12](W3-12-pipeline-docs.md) | Pipeline documentation | Islam | Tasneem | 2h | W3-07, W3-11 |
| [W3-13](W3-13-batch-writes.md) | Batch writes on the scoped repository | Islam | Zyad | 3h | W3-02 |

**Optional — deferred, do not start:**

| # | Task | Owner | Reviewer | Effort | Depends on |
|---|---|---|---|---|---|
| [W3-09](W3-09-staging-vps.md) | Staging: VPS, Compose overlay, secrets | — | Tasneem | 4h | a VPS |
| [W3-10](W3-10-deploy-workflow.md) | Deploy on merge to `main` | — | Islam | 4h | W3-09 |

## Load

| Intern | Tasks | Task hours | + review/standups | Total |
|---|---|---|---|---|
| **Islam** (lead) | 01, 12, 13 | 7h | +4h lead, +3h review | **14h** |
| **Zyad** | 02, 04, 08 | 12h | +3h | **15h** |
| **Tasneem** | 03, 05, 11 | 12h | +3h | **15h** |
| **Arwa** | 06, 07 | 9h | +3h | **13h** |

40h of task work against 20h/week each — two below week 2, and that slack is deliberate. Every
task on this board is on the critical path now that there's no second track, and a week where
everything is load-bearing has nowhere to absorb a bad day.

**Arwa is lightest on purpose.** W3-07 is the task most likely to overrun — two external sources, a
concurrency problem, and the only network-facing code in the week.

Carried in from week 2: **#63** and **#64** are open PRs, so they need review rather than hours.
#54 is folded into W3-02, #56 into W3-04, #52 into W3-01.

## Critical path

```
W3-01 (Sunday) ─┬─ W3-02 ─┬─→ W3-05 ─┐
                │         │          ├─→ W3-07 ─→ W3-08
                ├─ W3-03 ─┴─→ W3-06 ─┘        └──────────→ W3-12
                │         │     └───→ W3-11 ──────────────┘
                │         └─→ W3-13
                └─ W3-04   ── needed to run the pipeline, not to build it

W3-09 ─→ W3-10             ── optional, deferred, nothing depends on it
```

**Notice what is not on the deliverable path: the worker.** W3-03 lets every job be built and proven
in-process, so W3-05 → W3-07 → W3-08 does not wait on a healthy arq container — the same move W2-03
made with Zitadel, for the same reason.

There is no second track this week, which means everyone is on one dependency graph. That makes
**W3-01 merging on Sunday** matter more than it did last week, not less.

**W3-01 must merge Sunday** — three people stall Monday morning otherwise.
**W3-05 → W3-07 → W3-08** is Wednesday's chain and the tightest of the week.

## Not this week

Deliberately deferred, so nobody builds them early:

- **Scheduled / recurring scans** — week 4. This week a scan starts because somebody asked for it
- **Change detection and alerts** — week 4 builds on W3-08's fingerprint. Get identity right first
- **Rate limiting and scanner politeness** — week 4, when there is more than one source to be
  polite to
- **Port scanning, HTTP probing, tech fingerprinting** — later ASM work. One source, done properly
- **ClickHouse** — week 5. Findings go in Postgres for now
- **Multiple workers, queue priorities, sharding** — one worker process is enough for four interns
  and one scan at a time
- **Staging and auto-deploy** — deferred. W3-09 and W3-10 are written and parked; the box isn't
  being provisioned this week, so the whole demo runs on a laptop and that's fine
- **Zero-downtime deploys** — not this week and not next. Blue-green is a later problem

---

## Concepts you're expected to understand by Thursday

You'll be asked about these at Thursday's demo — not to recite a definition, but to defend a choice.

| Concept | What you should be able to say |
|---|---|
| **Task queue / worker** | The API enqueues and returns; a separate process does the work. The request path never waits for a scan |
| **At-least-once delivery** | The queue guarantees the job runs, not that it runs once. Duplicates are normal operation, not an incident |
| **Idempotent job** | Running it twice leaves the same state as running it once — a property of the work, not a promise from the queue |
| **Fingerprint / finding identity** | The deterministic key deciding whether this is a new finding or the same one seen again. It is what makes change detection possible |
| **Job state machine** | `queued → running → succeeded \| failed`, with every transition written down — including the ones caused by a worker dying |
| **Retry and exponential backoff with jitter** | Retry what is safe to retry, wait longer each time, and randomise — or four workers retry in lockstep and take the source down |
| **Job timeout vs client timeout** | The deadline on the whole job, and the deadline on each HTTP call it makes. Missing the second makes the first your only defence |
| **Worker concurrency** | N jobs on one event loop in one process. One blocking call stalls all of them |
| **Tenant context without a request** | A job carries `tenant_id` in its payload and must establish the same scope middleware would. Fail closed if it doesn't |
| **Graceful shutdown** | SIGTERM means stop taking new jobs and finish the current one — not drop it half-written |
| **Transaction boundary** | Who decides what a unit of work is. One commit per scan or one per row is the same code and a different program |
| **Graceful degradation of a source** | crt.sh being down returns fewer results, never an exception. No demo depends on a third party being up |

## Search terms

Each task file has its own **Search for** list at the bottom, scoped to that task. Start there.

## Resources

Seven things, all short, all directly applicable.

**[arq — documentation](https://arq-docs.helpmanual.io/)** *(official, and short enough to read entirely)*
The whole library is small. Read the job lifecycle and `WorkerSettings` sections properly —
`max_tries`, `job_timeout` and `Retry` are most of W3-06 in three parameters.

**[AWS Builders' Library — Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)**
Why "retry three times" is a denial-of-service against your own dependency, and why the fix is
randomness. Two pages, and it is the reasoning W3-06 needs rather than the code.

**[Brandur — Implementing Stripe-like idempotency keys](https://brandur.org/idempotency-keys)** *(skim — you read the Stripe doc in week 2)*
The follow-on to what you already know: what idempotency looks like when nobody supplies a key and
the operation has to be intrinsically repeatable. Directly W3-08.

**[Certificate Transparency — how it works](https://certificate.transparency.dev/howctworks/)** *(short)*
Why a public log of every issued certificate is a subdomain discovery tool, and why it finds hosts
that DNS enumeration never will. The domain lesson behind W3-07.

**[dnspython — asyncio resolver](https://dnspython.readthedocs.io/en/stable/async.html)** *(official)*
The API W3-07 needs, and the reason the blocking resolver would stall every other job sharing the
worker's event loop.

**[Martin Fowler — BlueGreenDeployment](https://martinfowler.com/bliki/BlueGreenDeployment.html)** *(optional track — park it with W3-10)*
Why migrations and deploys are ordered rather than simultaneous, and what "the old code must survive
the new schema" means in practice. Staging is deferred, so this keeps until the task does.

**[SQLAlchemy — Session basics: committing and the unit of work](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)** *(official)*
What a session actually does between `add()` and `commit()`, and why the repository committing on
every call is a design decision rather than a detail. Directly W3-13.

## How to use these

Read the resource when the task needs it, not before.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.

One exception this week: **if a job hangs and you cannot tell whether it is running, queued or
dead, ask immediately.** Debugging a stuck worker by staring at it is the least productive hour
available to you, and knowing where to look is the point of W3-06 rather than a prerequisite for it.
