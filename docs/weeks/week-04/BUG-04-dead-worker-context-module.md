# BUG-04 · `worker/context.py` is a second, dead way to bind job context

**Severity:** low (dead code, real trap) · **Found:** week-3 review ·
**Closed by:** [#102](https://github.com/emad-anwer/tem-platform/issues/102) · **Owner:** Arwa, as part of W4-10 ·
**Effort:** included in W4-10 (a deletion)

**Status:** Resolved. `src/app/worker/context.py` and its commented import are absent; tenant jobs
use `@tenant_job` from `src/app/core/auth/job_context.py`.

## What is wrong

`src/app/worker/context.py` defines `bind_job_context`, `clear_job_context` and a `job_context`
async context manager. All three duplicate what `@tenant_job`
(`src/app/core/auth/job_context.py`) already does — and does better, because `tenant_job` also sets
the `Principal` contextvar that `TenantScopedRepository` reads, and resets both in a `finally`.

The module's only reference in the entire codebase is a **commented-out import**:

```
src/app/worker/__init__.py:7    #   from app.worker.context import bind_job_context, clear_job_context
```

## Why it matters

It is not that dead code is untidy. It is that a future job author greps for "job context", finds
two answers, and picks the one that binds structlog but **not** the principal. That job then writes
findings with no tenant — or worse, with whatever tenant the previous job left behind. Having two
ways to establish tenant context is how a job ends up with neither.

## Fix

Delete `src/app/worker/context.py` and the commented import in `src/app/worker/__init__.py`. If
anything turns out to need it, it needs `tenant_job` instead.

## Verification

`grep -rn "worker.context\|bind_job_context" src/` returns nothing.
