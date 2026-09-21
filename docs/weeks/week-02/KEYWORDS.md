Everything here connects to something you are actually building this week. Nothing is background
reading for its own sake.

**This week's shape:** authentication is delegated to **Zitadel**, self-hosted in Docker Compose.
You are not building login — you are integrating an identity provider correctly, and then building
the half it has no opinion about: which rows a tenant is allowed to see.

## Concepts you're expected to understand by Thursday

You will be asked about these in the Thursday demo — not to recite a definition, but to defend a
choice you made.

| Concept | What you should be able to say |
|---|---|
| **OIDC vs OAuth 2.0** | OAuth 2.0 delegates *authorisation*; OIDC is the identity layer on top that tells you *who* the caller is |
| **Issuer and discovery** | `iss` identifies who minted the token; the discovery document says where its keys live. The URL must be identical everywhere or nothing validates |
| **JWKS, `kid`, key rotation** | The IdP publishes its public keys; `kid` selects one. Keys change without asking you, so the cache has to cope without a restart |
| **Algorithm pinning** | Never trust the token's own `alg` header. `alg: none` and RS256→HS256 confusion are both attacks on believing it |
| **Audience (`aud`)** | A valid token from our own Zitadel, minted for a different application, is not a token for us. Checking `aud` is what makes that true |
| **Opaque token vs JWT** | Local validation against JWKS, or a network call to introspect. Different failure modes, different latency, different revocation |
| **Trust boundary** | What we delegate to Zitadel and what stays ours. Decided in ADR-0002, not assumed |
| **Claims → `Principal`** | Vendor claim shapes stop at one module. The rest of the codebase never learns the IdP's name — that's what makes it replaceable |
| **Dual write** | Two systems, no shared transaction. Something *will* half-succeed; the design question is what happens then |
| **Idempotency key** | A caller-supplied token that makes a retried write safe. The difference between "please don't retry" and "retry freely" |
| **Tenant scoping** | Every query filtered by tenant, enforced in one place rather than fifty. Structural, not disciplinary |
| **`401` / `403` / `404` and IDOR** | "Who are you?" / "not allowed" / "not telling you it exists". Cross-tenant reads return `404`, because a `403` confirms the row exists |

## Search terms

Each task issue has its own **Search for** list at the bottom. Start there — they're scoped to what
that specific task needs.

## Resources

Seven things. All short, all directly applicable. This is not a course.

**[Zitadel — Self-hosting with Docker Compose](https://zitadel.com/docs/self-hosting/deploy/compose)** *(official)*
The reference for W2-05. Read the configuration section properly — the external domain and issuer
settings are where the afternoon goes if you guess at them.

**[Zitadel — Validate access tokens](https://zitadel.com/docs/guides/integrate/token-introspection)** *(official)*
Settles the question W2-04 has to answer **before** writing any code: are you getting a JWT you can
validate locally, or an opaque token you have to introspect? Cheap to read, expensive to skip.

**[OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)** + **[RFC 7517 — JSON Web Key](https://www.rfc-editor.org/rfc/rfc7517.html)** *(skim both)*
Why you read `jwks_uri` out of a discovery document instead of hardcoding a URL, and what a key set
actually contains. The `kid` field is the part that carries this week.

**[RFC 9068 — JWT Profile for OAuth 2.0 Access Tokens](https://www.rfc-editor.org/rfc/rfc9068.html)** *(skim §2, the claims)*
A real specification for what belongs in an access token, so ADR-0002's claim expectations are a
considered choice rather than whatever Zitadel happened to send you.

**[OWASP Top 10 — A01: Broken Access Control](https://owasp.org/Top10/A01_2021-Broken_Access_Control/)**
The category this entire week exists to prevent, and the reason cross-tenant reads return `404`.
W2-10's isolation suite is a direct answer to this document.

**[Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)**
Two screens, and the clearest statement anywhere of the contract W2-09 needs: what a key is, how
long it lives, and what a replay returns.

**[GitHub Actions — Service containers](https://docs.github.com/en/actions/using-containerized-services/about-service-containers)** *(official)*
Exactly the Postgres-in-CI problem W2-01 solves, with the healthcheck options that make it reliable
instead of flaky.

## How to use these

Read the resource when the task needs it, not before. If you're on W2-09, read the Stripe page.
Don't read all seven on Sunday — you'll retain none of it.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.

**One exception this week:** if **Zitadel itself** won't start, or won't issue a usable token, the
timebox is **30 minutes** and the question goes straight to the mentor. Debugging someone else's Go
service is not what this week is for.
