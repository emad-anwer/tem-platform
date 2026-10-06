# BUG-03 · `run_scheduled_scan` is a registered stub

**Severity:** medium (misleading, not broken) · **Found:** week-3 review ·
**Closed by:** [W4-10](W4-10-scan-orchestration.md) · **Owner:** Tasneem, as part of W4-10 ·
**Effort:** included in W4-10

**Status:** Resolved. `run_scheduled_scan` now orchestrates all ASM stages for one `ScanRun`.

## What is wrong

`src/app/core/jobs/scan.py:21` defines `run_scheduled_scan`, decorated with `@tenant_job` — so it is
in `JOB_REGISTRY` and the worker will happily accept and execute it. What it does is log
`scan.started`, pass over a comment reading `# actual scan orchestration...`, and log
`scan.completed`.

A job that reports success without doing anything is worse than a job that does not exist. The
registry says the capability is there. The logs say the work happened. Nothing happened.

## Why it matters

Anyone reading `JOB_REGISTRY` to find out what the platform can do gets a wrong answer, and any
future caller that enqueues it gets a green light for free. Right now nothing enqueues it, so the
blast radius is zero — which is exactly the condition under which this kind of thing survives for
months.

## Fix

W4-10 replaces the body with real orchestration: resolve the target, check scope, fan out to the
three sources, write findings, run change detection, close the run. If for any reason W4-10 slips,
the stub should be **deleted** rather than left registered — an unregistered capability is honest,
a registered lie is not.

## Verification

`POST /api/v1/targets/{id}/scans` produces a run that actually contains port, service and
certificate findings — not just two log lines.
