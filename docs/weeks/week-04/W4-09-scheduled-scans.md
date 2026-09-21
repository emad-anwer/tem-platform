# W4-09 · Scheduled scans and the stale-run sweeper

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 3h · **Depends on:** W4-03

Picks up a loose end: **`mark_stale_runs` has no caller anywhere in the codebase.** It was written
in W3-06, merged with tests, and has been dead code ever since. This is where it gets one.

## What

Until now every job existed because somebody made a request. This task makes the platform do things
nobody asked for — which also means a bug now repeats on a timer.

Two cron jobs, using arq's built-in `cron` support. No new dependency, no OS crontab, no separate
scheduler container.

**1. The stale-run sweeper.** Every few minutes, call `mark_stale_runs`. It marks runs stuck in
`running` past twice the job deadline as `stale` failures — the state a run lands in when a worker
is killed holding it. Without this, a crashed worker leaves rows in `running` forever and nothing
notices.

**2. Recurring scans.** Every active target gets re-scanned on a schedule. This means enqueueing one
job per target, per tenant, from a context with no request and no tenant — so the cron job has to
establish tenant context per target the way `tenant_job` does, and must not leak it between
iterations. W3-05 built the mechanism; this is its second caller and the first one that loops.

Also in this task: **delete `src/app/worker/context.py`.** It duplicates the structlog binding that
`tenant_job` already does, is referenced only from a commented-out line in `worker/__init__.py`, and
having two ways to bind job context is how a job ends up with neither.

Tests:

- The sweeper marks a run stuck in `running` past the cutoff and leaves a fresh one alone
- The sweeper is idempotent — running it twice marks nothing twice
- The recurring scan enqueues one job per active target and skips inactive ones
- Tenant context is established per target and does not leak from one iteration to the next
- Nothing is enqueued for a target whose previous run is still `running` — or something is, if you
  decided that; see below

## Expected outcome

Kill the worker mid-scan (`docker compose kill worker`), wait, and the run moves to `failed` with
`error_kind=stale` on its own. A target left alone gets re-scanned without anybody calling the API.

## Think about

**`run_at_startup` is a trap.** It looks like exactly what you want — the schedule fires when the
worker starts. Now consider a worker that restarts on every deploy, and three deploys on a Thursday
afternoon. Decide, and write down what you decided.

**What if the previous run of the same scan is still running?** Skip it, queue it anyway, run them
concurrently, or cancel the old one — all four are defensible, and the failure mode is not having
considered it. The mentor will ask this at the demo, in exactly those words.

Think about the interval. A scan every five minutes against one lab container is fine. The same
schedule across 200 real targets is a self-inflicted outage, and W4-05's limiter is per-host, so it
will not save you from fanning out across 200 different hosts at once. What is the right knob —
scan interval, or a cap on concurrent scheduled runs? Probably both. Pick.

This job carries the `tenant_id` that everything downstream trusts. A loop that sets context on
iteration 1 and reuses it on iteration 2 writes tenant A's findings into tenant B. That is the
exact failure W3-05 was built to prevent, in the exact shape that makes it easy to reintroduce.

## Search for

- arq cron jobs run_at_startup
- cron job overlap prevention lock
- contextvars reset in loop per iteration
- distributed lock redis setnx expiry
- stale job reaper heartbeat timeout
- scheduled job jitter thundering herd
