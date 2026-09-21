# W2-06 · Auth dependency and request-scoped context

**GitHub issue:** [#36](https://github.com/emad-anwer/tem-platform/issues/36)

**Owner:** Islam · **Reviewer:** Arwa · **Effort:** 3h · **Depends on:** #34

## What

Turn a verified token into something the rest of the application can use, and make it reachable
from the query layer without threading it through every function signature.

- `get_principal()` — a FastAPI dependency returning `Principal(subject, tenant_id, roles)`
- The `Principal` is available to the repository layer in W2-07. Decide **explicitly**:
  `contextvars` or explicit passing. Write the reasoning in the PR description, not just the code
- Missing or malformed credentials → `401`, with the `WWW-Authenticate` header REST expects
- Nothing outside this module and W2-04 imports a JWT library or mentions Zitadel by name

## Expected outcome

Any handler can ask who is calling. So can the query layer. Swapping the token source in a later
week touches `core/auth` and nothing else — that's the property W2-02 promised, and this is the
task that either delivers it or quietly doesn't.

## Think about

Week 3 adds a background worker. There is no HTTP request there, no header, no dependency
injection — and it still has to run scoped to a tenant. Whichever mechanism you pick here is the
one that gets tested then. Which of the two survives that, and what does the other one need
bolted on?

## Search for

- python contextvars asyncio request scoped
- fastapi dependency injection Depends security scheme
- starlette middleware vs dependency ordering
- www-authenticate bearer challenge 401
- fastapi HTTPBearer
