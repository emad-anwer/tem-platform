# W2-08 · RBAC from IdP role claims

**GitHub issue:** [#38](https://github.com/emad-anwer/tem-platform/issues/38)

**Owner:** Zyad · **Reviewer:** Arwa · **Effort:** 3h · **Depends on:** #36, #32

## What

Zitadel tells you what roles a caller has. It does not tell you whether they may call *this route*.
That decision is yours, it belongs in one place, and it's declared at the route rather than
re-derived inside handlers.

- `require_role(...)` / `require_permission(...)` dependencies driven by the permission matrix
  from ADR-0002
- The matrix lives in **one file**. Reading it should answer "who can do what" without grepping
- Applied to every existing route, including the ones week 1 left open
- Roles arrive as a claim in a vendor-specific shape. Normalise them in W2-04's mapping so the
  matrix is written in *your* vocabulary, not Zitadel's

## Expected outcome

A viewer's token gets `403` on a write. A missing token gets `401`. A cross-tenant read gets
`404` — and that last one comes from W2-07, not from here. Know which layer produces which.

## Think about

Two systems now hold opinions about authorisation: Zitadel's role grants and your permission
matrix. That's fine — one is *what roles exist and who holds them*, the other is *what a role may
do here*. It stops being fine the moment the same fact is written in both places.

Is there anything in your matrix that Zitadel also encodes? If yes, which one wins, and what
happens when they drift?

## Search for

- zitadel project roles claim urn:zitadel:iam
- rbac permission matrix design
- fastapi dependency with parameters factory
- authorization 401 vs 403 semantics
- principle of least privilege
