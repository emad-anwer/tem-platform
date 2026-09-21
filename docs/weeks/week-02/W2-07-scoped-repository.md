# W2-07 · Tenant-scoped repository base

**GitHub issue:** [#37](https://github.com/emad-anwer/tem-platform/issues/37)

**Owner:** Zyad · **Reviewer:** Tasneem + mentor · **Effort:** 4h · **Depends on:** #36

🔑 **The most important code written this week.** Read this twice before starting. Every future
module depends on it being correct, and it's Wednesday's bottleneck — if it slips past Wednesday
afternoon, W2-10 has nowhere to go.

Note what this task is *not*: it is untouched by the Zitadel decision. An identity provider tells
you who the caller is. It has no opinion whatsoever about which rows they may see. That half of
multi-tenancy is ours and always will be.

## What

`TenantScopedRepository` in `core/`:

- Every read applies `WHERE tenant_id = <context tenant>` — automatically, not on request
- Every create stamps `tenant_id` from the context
- Every update and delete verifies ownership **before** acting
- Constructed without a context, or used when the context is empty → raise loudly. Never silently
  fall back to an unfiltered query

Plus a `TenantOwnedMixin` supplying the `tenant_id` column and its index, and the migration of the
existing repositories onto the base class.

## Expected outcome

Tenant isolation is **structural**. An endpoint author in week 6 cannot forget to filter by tenant,
because they never write the filter at all.

Include a test that the base class raises when there's no context. That test protects the property
that makes everything else safe.

## Think about

The alternative is a code-review rule: "always remember to filter by tenant." Assume your team is
competent and attentive. Over four more weeks and roughly fifty endpoints, how many times does that
rule need to be forgotten once for the product to leak? What does that tell you about rules that
depend on memory?

## Search for

- multi-tenant shared database shared schema
- SQLAlchemy declarative mixin
- SQLAlchemy 2.0 select where async session
- repository pattern base class generics Python
- defense in depth
