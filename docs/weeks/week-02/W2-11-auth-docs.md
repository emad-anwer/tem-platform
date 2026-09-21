# W2-11 · Auth documentation and local dev guide

**GitHub issue:** [#41](https://github.com/emad-anwer/tem-platform/issues/41)

**Owner:** Arwa · **Reviewer:** Tasneem · **Effort:** 2h · **Depends on:** #35, #38, #39

More load-bearing than it looks. Before this week, a new developer could run the API and call it.
Now they can't get a token without knowing things that exist only in your heads.

## What

`docs/auth.md`:

- **How to get a token on a fresh machine** — from `just up` to a working `Authorization` header,
  every step, no gaps. This is the section people will actually open
- How the Zitadel org maps to a tenant, and which ID appears where
- The permission matrix from ADR-0002, rendered as a table
- What expiry looks like from a client, and what a client should do about it
- What breaks when Zitadel is down, and what doesn't

Update `docs/api-conventions.md` with the `401` / `403` / `404` rules and the reasoning for `404`.

## Expected outcome

Week 3's worker author authenticates without asking anyone anything.

Validate it the only way that works: hand it to a teammate who didn't build this, watch them follow
it, and fix every place they hesitate. Don't explain — watch.

## Think about

You wrote parts of this system, so you can't tell which steps are obvious and which are only
obvious to you. That's not a discipline problem, it's a structural one. The teammate walkthrough
isn't a nice-to-have here; it's the only instrument you have.

## Search for

- documentation for developers getting started guide
- markdown tables
- curl bearer token examples
- openapi security schemes fastapi
