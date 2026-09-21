# W3-13 · Batch writes on the scoped repository

**GitHub issue:** [#76](https://github.com/emad-anwer/tem-platform/issues/76)

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 3h · **Depends on:** #67

`TenantScopedRepository.create()` commits on every call. That was invisible while every write was a
single tenant row. W3-07 is about to hand it four hundred findings from one job.

## What

Add a batched write path to the repository base, alongside `create()` rather than replacing it.

- **Many rows, one transaction.** The caller hands over a scan's worth of findings and gets one
  commit — or, if something fails halfway, none of them and a scan that can be retried cleanly
- **The tenant stamp is forced, exactly as `create()` forces it.** `create()` overwrites
  `attributes["tenant_id"]` with the repository's tenant rather than trusting the caller. The batch
  path must do the same thing, for every row, with no way to opt out. This is the whole reason the
  base class exists
- Works with W3-08's `ON CONFLICT` upsert — batching and idempotency have to compose, because
  W3-07's job needs both at once
- A sane cap on batch size, so a target with fifty thousand certificate-transparency results doesn't
  become one transaction that holds locks for a minute
- Tests: the batch commits once; a failure mid-batch leaves no partial rows; **a row whose
  `tenant_id` the caller tried to set to another tenant is written with the repository's tenant
  anyway**; the existing `create()` behaviour is unchanged

Measure it. W3-08 will have the "before" number — put both in the PR.

## Expected outcome

A scan's findings are one transaction. Week 5 arrives with higher volumes and doesn't find this
waiting for it.

## Think about

**Why the per-call commit was there in the first place.** It isn't obviously wrong — it makes every
write atomic and independent, and for one tenant row created by one request that's exactly right.
The question is who owns the transaction boundary. If the repository commits, the caller can never
group. If the caller commits, every caller has to remember to. Which of those is the mistake you're
fixing, and does your batch path fix it or just add a second opinion alongside the first?

**Then the one your reviewer will ask about.** `create()` is safe because it *overwrites*
`tenant_id` rather than validating it. A batch path that skips that — because it's building rows in
bulk and stamping each one felt wasteful — is not a slow cross-tenant write, it's a silent one. It
will pass every test you thought to write. Write the test you didn't think of.

Zyad reviews this, across the usual pairing, because he owns the repository base and W3-08 is its
first consumer.

## Search for

- sqlalchemy session bulk_save_objects vs add_all
- sqlalchemy asyncio session commit vs flush
- postgres insert multiple rows single statement
- unit of work pattern repository transaction boundary
- sqlalchemy on_conflict_do_update multiple values
- chunking batch size database locks
