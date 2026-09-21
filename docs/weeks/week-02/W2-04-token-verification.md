# W2-04 · OIDC token verification: JWKS fetch, cache, rotation, claims

**GitHub issue:** [#34](https://github.com/emad-anwer/tem-platform/issues/34)

**Owner:** Arwa · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** #32, #33

## What

The only code in the project that knows what a JWT is. Everything else gets a `Principal`.

- Fetch the OIDC **discovery document**, read the `jwks_uri` from it rather than hardcoding it
- Fetch and **cache** the key set with a TTL. Do not fetch on every request
- Select the key by `kid`. On an unknown `kid`, refetch once — because that is what key rotation
  looks like from your side
- **Rate-limit that refetch.** An attacker who can send you tokens with random `kid` values can
  otherwise make you hammer the IdP. A short cooldown is enough
- Validate: signature, `exp`, `nbf`/`iat`, `iss`, `aud`. Pin the algorithm to what ADR-0002 chose
- Map claims to `Principal(subject, tenant_id, roles)` per ADR-0002
- Fail closed. An unverifiable token is not a token

Tests, all against W2-03's harness: expired · not yet valid · wrong issuer · wrong audience ·
unknown `kid` · `alg: none` · signed with a different key · a valid token missing `tenant_id`.

## Expected outcome

A valid token becomes a `Principal`. Everything else raises. There is a named test for each failure
mode above, and each one fails if you delete the corresponding check.

## Think about

Two things worth being deliberate about.

**Zitadel may hand you an opaque token rather than a JWT**, depending on how the application is
configured. If that happens, none of the above works and you need introspection instead. Find out
which you're getting before you write four hours of code — and tell the team on Sunday, not
Wednesday.

**Your cache is a liveness/security trade.** A long TTL means the API survives Zitadel being down;
it also means a revoked signing key stays trusted for that long. Which did you choose, and what
would change your mind?

## Search for

- openid connect discovery well-known openid-configuration
- pyjwt PyJWKClient cache_keys lifespan
- jwt algorithm confusion RS256 HS256 attack
- validate aud iss claims jwt
- zitadel validate access token jwt vs introspection
- key rotation kid jwks refetch
