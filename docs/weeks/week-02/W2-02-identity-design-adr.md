# W2-02 · Identity design huddle and ADR-0002

**GitHub issue:** [#32](https://github.com/emad-anwer/tem-platform/issues/32)

**Owner:** Arwa · **Reviewer:** all four + mentor · **Effort:** 45min meeting + 2h writing · **Depends on:** —

🔑 Must merge **Sunday**. Three people are blocked on it Monday morning.

## What

Forty-five minutes, all four, before anyone writes auth code. You are not designing an
authentication system this week — you are deciding **where the boundary sits between what we
delegate to Zitadel and what stays ours**, and then writing that down.

Decide, and record the reasoning for each:

1. **What Zitadel owns.** Users, credentials, sessions, token issuance, key management. Say it
   explicitly so nobody re-implements one of them by accident.
2. **What stays ours, and why.** Tenant data isolation. Authorisation *decisions* at the route.
   The mapping from a token's claims to a `Principal`. Zitadel has no idea which rows belong to
   which tenant — that is the product's problem, permanently.
3. **Zitadel org ↔ our tenant.** One-to-one? Which one is authoritative? What is the ID of record
   in our database, and what happens if the two disagree?
4. **Where `tenant_id` comes from.** Same question as it would have been without an IdP, same
   right answer: the validated token, never the URL, never a header. Write down which claim.
5. **Where roles live.** Zitadel project roles in the token, or our own table? Pick one. Two
   sources of truth for authorisation is the failure mode you're avoiding.
6. **Token type.** Zitadel can issue opaque tokens or JWTs. Local JWKS validation and remote
   introspection are different systems with different failure modes. Choose deliberately.
7. **Audience and issuer.** What `aud` do we require, what `iss`, and what do we do with a valid
   Zitadel token that was minted for a different application?
8. **The `Principal` type.** The one object the rest of the codebase is allowed to know about.
   Nothing outside `core/auth` should ever import a JWT library or know Zitadel exists.
9. **Machine access.** Not built this week — but decide now whether the answer is Zitadel service
   users or our own per-tenant API keys, and write down which and why. Week 4 implements it.

## Expected outcome

`docs/adr/0002-identity-and-tenant-isolation.md`, merged Sunday.

Every numbered item above has a decision and a sentence of reasoning. An ADR that describes what
Zitadel does is not an ADR. It has to say what *we* chose and what we gave up.

Include one paragraph titled **"If we ever leave Zitadel"** listing what would have to change. If
that list is longer than a few files, the boundary is in the wrong place and you should move it
before Monday.

## Think about

You are inheriting somebody else's security model. That is normal and usually correct — but it
means a class of decisions is now made for you, and you should know which ones. What can Zitadel
do that you would not have allowed yourself to do? What happens to your API at 3am when Zitadel is
down — and is that answer different for a user who already has a valid token?

Also: `POST /tenants` is currently open to the world. Week 1 didn't have to care. You do.

## Search for

- zitadel organizations multi-tenancy
- zitadel project roles custom claims access token
- oidc access token opaque vs jwt introspection
- rfc 9068 jwt profile oauth 2.0 access tokens
- architecture decision record format
- identity provider trust boundary
