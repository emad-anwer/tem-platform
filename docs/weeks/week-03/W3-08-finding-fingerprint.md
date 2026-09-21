# W3-08 · Finding fingerprint and idempotent upsert

**GitHub issue:** [#73](https://github.com/emad-anwer/tem-platform/issues/73)

**Owner:** Zyad · **Reviewer:** Tasneem · **Effort:** 3h · **Depends on:** #67, #72

The at-least-once lesson, made concrete. This is the task that decides whether week 4 can build
change detection or has to rebuild this first.

## What

- A **deterministic fingerprint** per ADR-0003's identity rule. Same finding, same inputs, same
  fingerprint — across processes, across restarts, across a redeploy. Python's `hash()` is salted
  per process and will betray you here
- An **upsert** rather than an insert. Postgres `ON CONFLICT` against a unique constraint on
  (tenant, fingerprint) — one statement, no read-then-write race
- `first_seen_at` is set once and **never moves**. `last_seen_at` moves on every sighting. That pair
  is the whole basis of next week's "what changed" feature
- Findings the scan didn't see this time are **not deleted**. A subdomain that disappears is a
  finding, not an absence — mark it, don't erase it
- **Measure the write cost.** `TenantScopedRepository.create()` commits per call and W3-07 will
  hand you hundreds of findings in one job. Count the transactions and put the number in your PR —
  W3-13 is the task that fixes it, and it needs your "before" figure to prove it worked

Tests: run the same scan three times, get one set of rows, with `first_seen_at` unchanged and
`last_seen_at` advancing. Two tenants finding the same subdomain get two separate findings — the
fingerprint is scoped, not global.

## Expected outcome

Running the same scan three times produces the same rows. That property is what makes week 4's
change detection possible at all — without it, "what's new since Monday" is unanswerable.

## Think about

**What goes into the fingerprint, and what doesn't.** Too much and every scan produces "new"
findings because a TTL changed or an IP rotated. Too little and two genuinely different findings
collapse into one and you lose data silently — which is the worse failure, because nothing looks
wrong. Write down your inputs and defend each one.

**Then the one nobody gets right first time.** Does the fingerprint include the source? If DNS and
crt.sh both find `admin.example.com`, is that one finding or two? Argue it out loud with your
reviewer before you write the constraint, because changing a unique constraint after there's data
behind it is a migration and an outage rather than an edit.

Tasneem reviews this. She built week 2's idempotency and knows the difference between *idempotent*
and *happens not to crash on the second run* — expect that distinction to come up.

## Search for

- postgres insert on conflict do update excluded
- sqlalchemy dialects postgresql insert on_conflict_do_update
- deterministic hash sha256 canonical json
- python hash randomization PYTHONHASHSEED
- bulk insert sqlalchemy performance executemany
- soft delete vs status column audit trail
