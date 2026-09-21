# W2-03 · Test identity harness: keypair, fixture JWKS, token factory

**GitHub issue:** [#33](https://github.com/emad-anwer/tem-platform/issues/33)

**Owner:** Islam · **Reviewer:** Tasneem · **Effort:** 4h · **Depends on:** #32

🔑 Do this **before** Zitadel exists. Everything downstream — W2-04, W2-06, W2-07, W2-08, W2-10 —
is built and tested against this, not against a running IdP. It is the reason the week doesn't
stall behind a container.

## What

Give the test suite its own identity provider, in-process:

- An RSA keypair generated once per test session
- A **fixture JWKS** — the public half, served or injected wherever W2-04's verifier fetches keys
  from, so the verifier is exercised for real rather than mocked out
- `make_token(tenant_id, roles=..., **overrides)` — mints a signed token with the claim shape
  ADR-0002 specified, and lets any single claim be overridden or removed
- `auth_headers(...)` so writing an authenticated test is one line
- A **two-tenant fixture** with real data in both, ready for W2-10

The overrides matter as much as the happy path. A test must be able to ask for: expired, not yet
valid, wrong issuer, wrong audience, unknown `kid`, `alg: none`, signed with the wrong key.

Keep week 1's transactional rollback intact. The suite must still finish in seconds.

## Expected outcome

The entire authentication and isolation stack can be tested with **no Zitadel running and no
network access**, while still executing the real verification code path.

One integration test — marked so it can be skipped — points at a live Zitadel and proves the
fixture didn't lie. That one is allowed to be slow. It does not run in CI.

## Think about

There is a version of this where you mock `verify_token()` to return a fake `Principal`. It is
half the work and it tests nothing: every bug W2-04 could have — unpinned algorithm, unchecked
audience, accepted expiry — passes silently.

The rule you're learning: **substitute at the boundary you don't own, not at the code you wrote.**
Where exactly is that boundary here, and what did you have to change in W2-04's design to make it
substitutable at all?

## Search for

- cryptography generate rsa private key python
- python-jose OR pyjwt PyJWKClient testing
- jwk from public key kid thumbprint
- pytest fixture session scope
- respx OR responses mock http endpoint pytest
- test doubles at the boundary
