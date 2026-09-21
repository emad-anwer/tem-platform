# W3-05 · Tenant context inside a job

**GitHub issue:** [#70](https://github.com/emad-anwer/tem-platform/issues/70)

**Owner:** Tasneem · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** #67, #68

🔑 W2-06 ended with a note saying week 3 would add a background worker, and that whichever mechanism
you picked would be the one that gets tested then. This is then.

## What

A job has no request. No `Authorization` header, no ASGI scope, no middleware — and
`PrincipalContextMiddleware` returns early on anything where `scope["type"] != "http"`, so it does
nothing here at all. What a job *does* have is a `tenant_id` in its payload and a
`TenantScopedRepository` that will raise `MissingTenantContextError` rather than quietly return
every tenant's rows.

Build the job-side equivalent of the middleware:

- Establish principal context on job entry from the enqueued payload, and **tear it down on exit —
  including when the job raises.** `contextvars` in a worker are reused across jobs on the same
  event loop; a context that leaks from a failed job into the next one is a cross-tenant data leak
  with a very quiet failure mode
- Make it something a job author cannot forget: a decorator, a wrapper, a base — your call, but
  "remember to call this first" is not a mechanism
- Decide what principal a *system* job carries. A scheduled scan has a tenant but no human user.
  `Principal` requires a `user_id` and a `Role` — so either the system gets an identity, or
  `Principal` grows an alternative shape. Whichever you choose, write down why in the PR
- Every log line a job emits carries the tenant ID, so one tenant's scan can be followed through a
  log with four other jobs interleaved into it

Tests, using W3-03's harness:

- A job with context reads only its own tenant's rows
- A job that **forgets** the context raises `MissingTenantContextError` — it does not return
  everything
- A job that raises mid-work leaves no context behind for the next job on that loop
- Two jobs for two different tenants, interleaved, don't see each other's data

## Expected outcome

A job cannot silently read another tenant's rows. Forgetting the context is a loud failure, proven
by a test that goes red when you delete one line.

## Think about

`TenantScopedRepository` accepts an explicit `tenant_id=` argument as well as reading the context.
That is an escape hatch, and this task is exactly where somebody would reach for it: pass the tenant
ID straight into the repository and skip the context entirely. It would work. It would also mean
every future job author has to remember to do it, and the one who forgets gets a repository scoped
to nothing rather than an exception.

Which of those two is a *mechanism* and which is a *convention*? Week 2's whole argument was that
tenant scoping should be structural rather than disciplinary. Apply it here and be able to defend
what you chose.

Islam reviews this, and he chose `contextvars` in W2-06. If the abstraction only works when its
author is driving, that is worth finding out now rather than in week 5.

## Search for

- contextvars asyncio task isolation
- contextvars reset token finally
- python contextmanager exception safety
- arq on_job_start on_job_end hooks
- structlog bind_contextvars clear
- service account principal background job identity
