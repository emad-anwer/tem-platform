# W3-10 · Deploy on merge to `main`

**Owner:** unassigned — Arwa if taken · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** W3-09

> ## ⏸ Deferred — do not start this week
>
> Blocked behind W3-09, which is deferred. There is nowhere to deploy to. Kept here written and
> ready rather than deleted, because the lesson in it — *why migrations run before the new code
> starts* — is one you need in week 5 whether or not this workflow ever gets built.

From this task on, merging is deploying. That changes what a red `main` costs, which is the point.

## What

A GitHub Actions workflow that deploys to staging when `main` moves.

- Triggered on push to `main`, **after CI passes** — a failing build must not deploy
- Connects to the staging box with an SSH deploy key from GitHub Actions secrets. The key is
  scoped to deployment and nothing else, and never appears in a log line
- Pulls the new code, builds, and then, **in this order**: run migrations → start the new code →
  smoke-check. Not the other way round, and the ordering is the lesson rather than the YAML
- **A smoke check that can fail the deploy.** `/health` returning 200 is the minimum; a check that
  the worker is alive is better. A deploy that reports success while the stack is down is worse than
  no deploy workflow, because now nobody looks
- Concurrency control, so two merges in quick succession don't deploy over each other
- Deploy status visible without SSH — the workflow's own output is enough

## Expected outcome

Merge to `main`, wait, and the change is live on staging. A broken deploy is red in Actions within
minutes and says which step failed.

## Think about

**Why migrations run before the new code starts.** Between `alembic upgrade head` finishing and the
new containers being ready, the *old* code is still serving requests against the *new* schema. So
the migration has to be one the old code survives: adding a nullable column is fine, renaming one is
not, dropping one is an outage. This is the entire reason "additive migrations only" is a rule
rather than a style preference, and it is a rule you will need in week 5 when the schema is under
real pressure.

Islam reviews this because he wrote W2-01's CI, so he'll ask the follow-up: what happens if the
migration succeeds and the new code then fails to start? You are now running old code against a new
schema, indefinitely, until someone notices. What does your workflow do about that, and what should
a human do?

## Search for

- github actions workflow_run trigger after ci success
- github actions ssh deploy key secrets appleboy ssh-action
- github actions concurrency group cancel-in-progress
- alembic upgrade head deployment order zero downtime
- expand contract migration pattern
- github actions mask secrets in logs
