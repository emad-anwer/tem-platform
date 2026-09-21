# W3-11 · Pipeline API: targets, scan runs, findings

**GitHub issue:** [#74](https://github.com/emad-anwer/tem-platform/issues/74)

**Owner:** Tasneem · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** #67, #71

The user-facing half of the deliverable. Five endpoints, and one of them behaves differently from
everything you have written so far.

## What

- `POST /targets` — create a target, with validation. A domain is not any string, and this is the
  one place a bad value can enter the pipeline
- `GET /targets` — list, paginated, tenant-scoped
- `POST /targets/{id}/scans` — **enqueue a scan and return `202` with a run ID.** Not the result.
  The request path does no scanning and waits for nothing
- `GET /scans/{id}` — the run's state, timings, and failure reason if it has one
- `GET /findings` — paginated, filterable by target and by run at minimum

All of it in the envelope and pagination style **ADR-0003 settled** — the contradiction between
`docs/api-conventions.md` and the tenant endpoints gets resolved on Sunday, and these five endpoints
follow the winner consistently.

RBAC per W2-08: a `viewer` may read findings and may not start a scan. Cross-tenant access returns
`404`, not `403` — week 2's rule, unchanged, and W2-10's isolation suite will now find four new
routes to cover.

**No raw exception text, stack trace or SQL error reaches a client.** Week 1's error handling
already does this; make sure the new routes go through it rather than around it.

## Expected outcome

The demo runs end to end through HTTP: create a target, start a scan, poll the run, list the
findings. `POST /scans` returns in milliseconds regardless of how long the scan takes.

## Think about

**`202 Accepted` is a different contract from `201 Created`**, and it is the first time this API has
made a promise it hasn't kept yet. You are telling the caller "I've accepted this; here's where to
look". So: what does `GET /scans/{id}` return while the job is queued? What if the worker is down —
does the run sit in `queued` forever, and how would the caller ever find out? Is there anything in
the response telling them how long to wait before polling again?

**Then the question the reviewer should ask you.** If the same client sends `POST /targets/{id}/scans`
three times in two seconds, do you enqueue three scans? The answer isn't obviously no — a user might
genuinely want to rescan — but it should be a decision you made rather than one you defaulted into.

## Search for

- http 202 accepted async job status polling
- rest api long running operation pattern
- fastapi background enqueue arq redis pool dependency
- pydantic validator domain name hostname
- retry-after header polling interval
- fastapi dependency require role permission
