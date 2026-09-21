# BUG-02 · `mark_stale_runs` has no caller

**Severity:** high (silent data problem) · **Found:** week-3 review ·
**Closed by:** [W4-09](W4-09-scheduled-scans.md) · **Owner:** Islam, as part of W4-09 ·
**Effort:** included in W4-09

## What is wrong

`mark_stale_runs` (`src/app/core/jobs/lifecycle.py:122`) is referenced exactly twice in the
repository, and both references are in `tests/core/jobs/test_job_lifecycle.py`. Nothing in
`src/` calls it. It was written in W3-06, merged with passing tests, and has been dead since the
day it landed.

## Why it matters

It is the function that cleans up after a worker that died holding a run. Without a caller:

- kill the worker mid-scan and that `scan_run` row stays `running` **forever**
- the API keeps reporting the run as in-progress, so a client polling it never stops
- nothing ever retries the work, and nothing reports it as failed

The tests pass, the function is correct, and the system has the bug it was written to prevent.
That gap — *tested* and *reachable* are different properties — is the actual lesson here and it is
worth naming at the demo.

## Why it is not being filed as a week-3 regression

It needs a scheduler to have a caller, and week 3 had no scheduler. W4-09 adds one. The bug is real
from the moment it merged, but the fix genuinely belonged in this week.

## Verification

`docker compose kill worker` mid-scan, wait past the sweep interval, and the run moves to `failed`
with `error_kind=stale` with nobody touching it.
