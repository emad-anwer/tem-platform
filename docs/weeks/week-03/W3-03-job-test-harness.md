# W3-03 · Job test harness: run a job without a worker

**GitHub issue:** [#68](https://github.com/emad-anwer/tem-platform/issues/68)

**Owner:** Tasneem · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** #66

🔑 Do this **before** the worker exists. Everything downstream — W3-05, W3-06, W3-07, W3-08 — is
built and tested against this, not against a running arq container. It is the reason the week
doesn't stall behind infrastructure.

If you did W2-03, you already know the shape of this task. Same move, different boundary.

## What

Give the test suite the ability to run a job function directly, in-process, with a real database and
a constructed job context:

- A fixture that builds whatever context object your job functions receive, populated the way arq
  would populate it — job ID, try number, the database session, the enqueue-time metadata
- `run_job(fn, *args, tenant_id=..., try_number=1)` or similar: one call, no worker, no Redis queue,
  no event loop of its own
- The ability to **simulate a retry** — the same job, same arguments, try number 2 — because that is
  the single most important behaviour to test this week and you cannot reproduce it by hoping
- The ability to run a job **without** tenant context, to prove W3-05's failure path
- Whatever fixture data the pipeline needs: a tenant, a target, a scan run

Keep week 1's transactional rollback intact. The suite still finishes in seconds, and **CI never
starts a worker, a queue or a Redis container for jobs.**

## Expected outcome

The whole pipeline can be built and proven on a laptop with nothing but Postgres running. `just test`
stays as fast as it was in week 2, and a test can express "this job ran twice" in one line.

## Think about

There is a version of this where the fixture mocks the job function and asserts it was called. It is
half the work and it tests nothing — every bug the job could have still ships.

There is a subtler version where you test through `enqueue_job` and a real Redis queue. That one
tests arq, which arq's maintainers already did. What you need to test is *your* job code.

The line to find: **substitute at the boundary you don't own — the queue — and run everything on
your side of it for real.** Where exactly is that boundary? You'll discover that answering it forces
a constraint on how W3-06 and W3-07 write their jobs: anything they take from the outside world has
to be reachable through the context rather than reached for directly. That constraint is the
valuable part of this task, so notice it and write it down for them.

Worth asking Islam, who reviews this: what did W2-03 make easy that a mocked verifier would have
made impossible? The answer generalises.

## Search for

- pytest fixture dependency injection async
- arq job context ctx dictionary
- testing background jobs without broker
- test doubles at the boundary
- pytest-asyncio event loop fixture scope
- factory fixtures test data builders
