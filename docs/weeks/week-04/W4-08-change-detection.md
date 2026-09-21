# W4-08 · Change detection between runs

**Owner:** Zyad · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** W4-03

## What

A scanner that reports 400 findings every run reports nothing. The product is the **diff**.

Week 3 built the data this needs and then didn't use it: `first_seen_at` stays fixed,
`last_seen_at` moves, `times_seen` increments, and `resolve_missing_discoveries` already marks
findings that a run did not see. This task turns that into an answer to "what changed?" — and it
should be mostly a query, not a schema change. If you find yourself adding columns, stop and check
whether the data is already there.

Build:

- **A diff between two runs** — the current one and the previous successful one for the same target.
  Every finding falls into one of the buckets ADR-0004 named: `new`, `reappeared`, `resolved`,
  `unchanged`, and `mutated` if the ADR decided that exists
- **Generalise `resolve_missing_discoveries`.** Today it is subdomain-shaped. A run that scans ports
  must not resolve the target's subdomain findings just because it didn't look for any. Scope the
  "not seen this run" logic to the *kinds this run actually produced* — this is the subtle bug in
  the task and the one the reviewer should hunt for
- **A `GET /api/v1/scan_runs/{id}/changes` endpoint** returning the counts and the findings in each
  bucket, with the same cursor pagination W3-11 built. Do not invent a second pagination style
- **Counts on the run itself.** `ScanRun` already has `findings_count` and `new_findings_count`.
  Decide whether resolved/reappeared counts join them or stay derived, and say why

Tests:

- Run twice with no change → everything `unchanged`, `first_seen_at` unmoved, `times_seen` at 2
- Stop `lab-apache`, run again → its findings are `resolved`, and *nothing else is*
- Start it again, run a third time → `reappeared`, with the original `first_seen_at` intact
- A port scan does not resolve subdomain findings — the bug above, proven
- The first run of a target has no previous run: every finding is `new`, and nothing raises
- Two tenants with identical findings diff independently

## Expected outcome

`docker compose stop lab-apache`, a scan, then `GET /scan_runs/{id}/changes` → `{"new": 0, "reappeared": 0,
"resolved": 1, "unchanged": 11}`. Start it again, scan again, and the same finding comes back as
`reappeared` carrying its original `first_seen_at`.

## Think about

**`reappeared` is why you don't delete.** A port that was open in January, closed in February and
open again in March is a more interesting security event than a port that has always been open —
and you can only say that if February's row still exists. W3-08 chose soft-resolve over delete;
this task is where that choice pays, and it is worth saying so at the demo.

Think about what "the previous run" means when the previous run **failed**. It scanned nothing, so
diffing against it would resolve everything the target has. Diff against the last *successful* run —
and notice that `ScanRun` already has the status field that makes that a one-line filter. Also think
about a run that succeeded but was degraded: W3-07's `sources_degraded` records when crt.sh was
down. Findings missing because a source was unavailable are not findings that went away. Decide what
you do about that; it is a real product decision and there is no obviously right answer.

The endpoint is a read endpoint, and `core/auth/permissions.py` has no read permissions in its
matrix — every authenticated role can read everything. That is fine today. Note it in the PR so
whoever builds alerts in week 6 finds the note rather than the surprise.

## Search for

- set difference previous run snapshot diffing
- sql lateral join previous row per group
- soft delete vs hard delete audit history
- postgres distinct on latest per group
- idempotent upsert last_seen first_seen
- asset inventory change detection security
