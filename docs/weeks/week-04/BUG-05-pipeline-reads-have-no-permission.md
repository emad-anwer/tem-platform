# BUG-05 · Pipeline read routes have no permission check

**Severity:** medium (policy gap, not a leak) · **Found:** week-3 review ·
**Owner:** Arwa · **Reviewer:** Tasneem · **Effort:** 1h · **Depends on:** — ·
**Do it Thursday**, or whenever a gap opens. Never ahead of W4-04.

## What is wrong

Of the five routes W3-11 added, the two writes are gated and the four reads are not:

```
src/app/core/pipeline/routes.py:49    require_permission(TARGET_CREATE)   POST /targets
src/app/core/pipeline/routes.py:98    require_permission(SCAN_START)      POST /targets/{id}/scans
src/app/core/pipeline/routes.py:61    (none)                              GET  /targets/{id}
src/app/core/pipeline/routes.py:74    (none)                              GET  /targets
src/app/core/pipeline/routes.py:110   (none)                              GET  /scan_runs/{id}
src/app/core/pipeline/routes.py:123   (none)                              GET  /findings
```

And the matrix they would check against has nothing to check:

```python
class Permission(StrEnum):
    TENANT_CREATE, TENANT_READ, TARGET_CREATE, SCAN_START     # that is the whole list
```

**This is not #65 again.** Those routes leaked across tenants; these do not. `get_pipeline_service`
depends on `get_principal`, and every repository is constructed with `principal.tenant_id`, so an
unauthenticated caller gets 401 and an authenticated one sees only their own tenant. Isolation
holds. Say that plainly in the PR so nobody reads this as a reopened BOLA.

What is missing is **authorization**: any role holding a valid token — `viewer` included — reads
every target, every run and every finding in its tenant. That may well be the right policy. Nobody
decided it. It is absent, not chosen, and the difference matters because the blast radius is zero
right now and stops being zero the first time a role exists that shouldn't see findings.

## What to do

1. Add read permissions to `Permission` and `PERMISSION_MATRIX` — `TARGET_READ`, `SCAN_READ`,
   `FINDING_READ`, or fewer if you can argue the collapse.
2. Attach them to the four GET routes.
3. Tests: for each new permission, one role that may and one role that may not, asserting 403 and
   not 404. A 404 here would be a different (defensible) choice — if you make it, write down why.
4. One paragraph in `docs/auth.md`: which role may read what, and why `viewer` exists at all.

## Expected outcome

The permission matrix is the single place anyone has to read to answer "who can see findings?" —
and the answer it gives is the one that is actually enforced.

## Think about

**Should `viewer` see findings?** It is the only role whose entire purpose is reading. If the answer
is "yes, everything", then the permission exists so that the *next* role doesn't. Write the reason
down; a matrix entry with no rationale gets deleted by someone in week 7.

**403 or 404?** Telling an unauthorized caller that a target exists is itself a disclosure. For a
resource inside your own tenant that you merely lack the role for, 403 is usually right. For one in
another tenant, 404 is the safer answer. Check which one the current code produces for the
cross-tenant case before you change anything — it is already correct, and it would be easy to break
while "fixing" this.

**Why did this happen?** Two of five routes got a check and three didn't, in one PR, reviewed. That
is not carelessness, it is what happens when the check is opt-in per route. Is there a shape that
makes forgetting harder — a router-level dependency, a default-deny test that enumerates every route
and fails on any without a permission? The second one is ten lines and would have caught this.

## Search for

- fastapi router level dependencies
- 403 vs 404 authorization information disclosure
- rbac permission matrix design
- test that enumerates all routes fastapi app.routes
- principle of least privilege read permissions
