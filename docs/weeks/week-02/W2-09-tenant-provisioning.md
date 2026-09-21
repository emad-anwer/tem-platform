# W2-09 · Tenant provisioning across two systems

**GitHub issue:** [#39](https://github.com/emad-anwer/tem-platform/issues/39)

**Owner:** Tasneem · **Reviewer:** Zyad · **Effort:** 6h · **Depends on:** #35, #36

The hardest task of the week, and the most real. Read the scope fence below before you write
anything — it is there to stop this eating three days.

## What

`POST /api/v1/tenants` now has to make a change in **two systems that do not share a transaction**:
a Zitadel organisation, and a row in our `tenants` table.

- Create the Zitadel org (and whatever grant the ADR says a new tenant needs) via the management
  API, authenticated as a service user
- Create the local `tenants` row, storing the Zitadel org ID as the link between them
- Accept an **idempotency key** from the caller. The same key replayed returns the same result and
  does not create a second org
- Restrict who may call it at all — per ADR-0002. This endpoint being open was acceptable in
  week 1 and is not acceptable now

### Scope fence — read this

If the Zitadel org is created and the local insert then fails: **leave the orphan.** Log it at
error level with the org ID and the idempotency key, return a `5xx`, and make the operation safe to
retry.

Do **not** build compensating deletes, a saga framework, an outbox, or a two-phase commit. All four
are real answers to this problem and all four are out of scope this week. A reconciliation job is a
later week's task — open an issue for it and move on.

You are done when a retry converges and an orphan is visible in the logs. That's the line.

## Expected outcome

Creating a tenant produces a Zitadel org and a local row, linked. Replaying the same request with
the same idempotency key produces no second org. A failure halfway through is logged loudly enough
that a human could clean it up, and retrying the call works.

Tests: happy path · replayed idempotency key · local insert fails after the org is created (fake
the failure) · Zitadel unreachable.

## Think about

In week 1, "create a tenant" was one `INSERT` and either it happened or it didn't. That guarantee
is gone and it is not coming back — this is what every integration with a third-party system looks
like, forever.

So: what does the *caller* see in each failure case, and can they safely retry without you telling
them to? "Retry-safe" is a property you design in, not one you apologise for later.

And be honest about what you've built: after this task, is the local row or the Zitadel org the
source of truth for "does this tenant exist"?

## Search for

- idempotency key api design stripe
- dual write problem distributed systems
- orphaned resource reconciliation
- zitadel management api create organization service user
- compensating transaction saga pattern (background reading — not to implement)
- structured logging error context correlation id
