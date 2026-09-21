# W2-10 · Cross-tenant isolation suite and route coverage

**GitHub issue:** [#40](https://github.com/emad-anwer/tem-platform/issues/40)

**Owner:** Tasneem · **Reviewer:** all four · **Effort:** 4h · **Depends on:** #37, #33

🔑 The week's proof. Everything else this week is a claim; this is the evidence.

**Write this without reading W2-07's implementation.** You are testing the property, not the code.
If you find yourself writing a test that mirrors how the repository happens to be built, you've
written a test that will pass even when the property breaks.

## What

Tenant A's token, pointed at every one of tenant B's resources.

For each route: no token · expired token · tampered token · token for another audience · valid
token, wrong role · valid token, **other tenant**. Each one asserted with the status code
ADR-0002 committed to.

Then the part that makes it last: a **route-coverage test** that walks `app.routes` at runtime and
fails if a route is neither covered by an isolation test nor in an explicit, commented allowlist.

All of it runs on W2-03's minted tokens. No Zitadel in this suite.

## Expected outcome

Adding an endpoint without an isolation test turns CI red. Automatically. Forever, or until
somebody deliberately edits the allowlist — which is a visible, reviewable line in a diff rather
than a silent omission.

## Think about

The allowlist is the interesting design decision. Make it too easy to add to and people will add to
it under deadline pressure; make it too hard and they'll delete the coverage test instead. What did
you do to make the *right* choice the path of least resistance — and what does an entry have to
carry to get past review?

Also: `403` or `404` for a cross-tenant read? Your ADR decided. Say the argument out loud again
here, because this suite is where that decision becomes fifty assertions.

## Search for

- IDOR insecure direct object reference
- broken access control owasp a01
- fastapi app.routes introspection test
- parametrized pytest across routes
- test the property not the implementation
