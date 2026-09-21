# Week 2 — Identity we don't own, isolation we do

**Sunday–Thursday · Lead: Arwa**

Code repository: **<https://github.com/emad-anwer/tem-platform/>** — every task below is a live issue there.
Milestone: [Week 2 — Identity We Don't Own, Isolation We Do](https://github.com/emad-anwer/tem-platform/milestone/2) ·
Keywords issue: [#42](https://github.com/emad-anwer/tem-platform/issues/42)

Authentication is delegated to **Zitadel**, self-hosted in Docker Compose. You are not building
login. You are integrating an identity provider correctly — and then building the half it has no
opinion about, which is which rows a tenant may see.

## Tasks

| # | Task | Owner | Reviewer | Effort | Depends on |
|---|---|---|---|---|---|
| [W2-01](W2-01-ci-pipeline.md) | CI pipeline: ruff and pytest on every PR | Islam | Zyad | 4h | — |
| [W2-02](W2-02-identity-design-adr.md) 🔑 | Identity design huddle and ADR-0002 | Arwa | all + mentor | 45m + 2h | — |
| [W2-03](W2-03-test-identity-harness.md) 🔑 | Test identity harness: keypair, fixture JWKS, token factory | Islam | Tasneem | 4h | W2-02 |
| [W2-04](W2-04-token-verification.md) | OIDC token verification: JWKS cache, rotation, claims | Arwa | Islam | 4h | W2-02, W2-03 |
| [W2-05](W2-05-zitadel-compose.md) | Zitadel in Compose and an idempotent bootstrap | Zyad | Islam | 5h | W2-02 |
| [W2-06](W2-06-request-context.md) | Auth dependency and request-scoped context | Islam | Arwa | 3h | W2-04 |
| [W2-07](W2-07-scoped-repository.md) 🔑 | Tenant-scoped repository base | Zyad | Tasneem + mentor | 4h | W2-06 |
| [W2-08](W2-08-rbac.md) | RBAC from IdP role claims | Zyad | Arwa | 3h | W2-06, W2-02 |
| [W2-09](W2-09-tenant-provisioning.md) | Tenant provisioning across two systems | Tasneem | Zyad | 6h | W2-05, W2-06 |
| [W2-10](W2-10-isolation-tests.md) 🔑 | Cross-tenant isolation suite and route coverage | Tasneem | all four | 4h | W2-07, W2-03 |
| [W2-11](W2-11-auth-docs.md) | Auth documentation and local dev guide | Arwa | Tasneem | 2h | W2-05, W2-08, W2-09 |

## Load

| Intern | Tasks | Task hours | + review/standups | Total |
|---|---|---|---|---|
| **Arwa** (lead) | 02, 04, 11 | 9h | +4h lead, +3h review | **16h** |
| **Islam** | 01, 03, 06 | 11h | +3h | **14h** |
| **Zyad** | 05, 07, 08 | 12h | +3h | **15h** |
| **Tasneem** | 09, 10 | 10h | +3h | **13h** |

42h of task work against 20h/week each. Tasneem is deliberately light: W2-09 is the task most
likely to overrun, and it needs the room.

## Critical path

```
W2-02 (Sunday) ─┬─ W2-03 ─→ W2-04 ─→ W2-06 ─┬─ W2-07 ─→ W2-10
                │                            └─ W2-08
                └─ W2-05 ─────────────────────────→ W2-09 ─→ W2-11

W2-01 ── independent, always available as parallel work
```

**Notice what is not on the isolation path: Zitadel.** W2-03 gives the whole stack minted tokens on
day one, so W2-04 → W2-06 → W2-07 → W2-10 can be built and proven before the IdP container is
healthy. That's deliberate. The riskiest task in the week should not be the one everything waits on.

**W2-02 must merge Sunday** — three people stall Monday morning otherwise.
**W2-06 → W2-07 → W2-10** is Wednesday's chain and the tightest of the week.

## Not this week

Deliberately deferred, so nobody builds them early:

- **Per-tenant API keys** — ADR-0002 *decides* whether these are ours or Zitadel service users.
  Week 4 implements whichever it picked, when there's a customer-facing surface to justify them
- **Refresh token handling** — Zitadel issues them; we don't need to store or rotate anything yet
- **Compensating transactions / outbox / saga** — W2-09 stops at "retry-safe and loudly logged".
  Reconciliation is a later week
- **Redis rate limiting** — week 4, alongside scanner politeness
- **Postgres row-level security** — week 7, as a second layer under W2-07. Not a replacement for it

---

## Concepts you're expected to understand by Thursday

You'll be asked about these at Thursday's demo — not to recite a definition, but to defend a choice.

| Concept | What you should be able to say |
|---|---|
| **OIDC vs OAuth 2.0** | OAuth 2.0 delegates *authorisation*; OIDC is the identity layer on top that tells you *who* the caller is |
| **Issuer and discovery** | `iss` identifies who minted the token; the discovery document tells you where its keys live. The URL must be identical everywhere or nothing validates |
| **JWKS, `kid`, rotation** | The IdP publishes its public keys; `kid` selects one. Keys change, so your cache has to cope without a restart |
| **Algorithm pinning** | Never trust the token's own `alg` header. `alg: none` and RS256→HS256 confusion are both attacks on believing it |
| **Audience (`aud`)** | A valid token minted for a different application is not a token for you. Checking `aud` is what makes that true |
| **Opaque token vs JWT** | Local validation against JWKS, or a network call to introspect. Different failure modes, different latency, different trust |
| **Trust boundary** | What we delegate to Zitadel and what stays ours. Written down in ADR-0002, not assumed |
| **Claims → `Principal`** | Vendor claim shapes stop at one module. The rest of the codebase never learns the IdP's name |
| **Dual write** | Two systems, no shared transaction. Something *will* half-succeed; the design question is what happens then |
| **Idempotency key** | A caller-supplied token that makes retrying a write safe. The difference between "please don't retry" and "retry freely" |
| **Tenant scoping** | Every query filtered by tenant, enforced in one place rather than fifty. Structural, not disciplinary |
| **`401` / `403` / `404` and IDOR** | "Who are you?" / "not allowed" / "not telling you it exists". Cross-tenant is `404`, because `403` confirms the row exists |

## Search terms

Each task file has its own **Search for** list at the bottom, scoped to that task. Start there.

> The concepts, search terms and resources below are also filed on tem-platform as
> [#42 · Week 2 · Keywords, concepts and learning resources](https://github.com/emad-anwer/tem-platform/issues/42),
> the counterpart to week 1's #14. Source: [`KEYWORDS.md`](KEYWORDS.md).

## Resources

Seven things, all short, all directly applicable.

**[Zitadel — Self-hosting with Docker Compose](https://zitadel.com/docs/self-hosting/deploy/compose)** *(official)*
The reference for W2-05. Read the configuration section properly — the external domain and issuer
settings are where the afternoon goes if you guess.

**[Zitadel — Validate access tokens](https://zitadel.com/docs/guides/integrate/token-introspection)** *(official)*
Answers the question W2-04 has to settle before writing any code: are you getting a JWT you can
validate locally, or an opaque token you have to introspect?

**[OpenID Connect Discovery + JSON Web Key (RFC 7517)](https://openid.net/specs/openid-connect-discovery-1_0.html)** *(skim)*
Why you read `jwks_uri` out of a discovery document instead of hardcoding a URL, and what the key
set actually contains. The `kid` field is the part that matters this week.

**[RFC 9068 — JWT Profile for OAuth 2.0 Access Tokens](https://www.rfc-editor.org/rfc/rfc9068.html)** *(skim §2, the claims)*
A real specification for what belongs in an access token, so ADR-0002's claim expectations are a
considered choice rather than whatever Zitadel happened to send.

**[OWASP Top 10 — A01: Broken Access Control](https://owasp.org/Top10/A01_2021-Broken_Access_Control/)**
The category this entire week exists to prevent, and the reason cross-tenant reads return `404`.
W2-10 is a direct answer to this document.

**[Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests)**
Two screens, and the clearest statement of the contract W2-09 needs: what a key is, how long it
lives, and what a replay returns.

**[GitHub Actions — Service containers](https://docs.github.com/en/actions/using-containerized-services/about-service-containers)** *(official)*
Exactly the Postgres-in-CI problem W2-01 solves, with the healthcheck options that make it reliable
instead of flaky.

## How to use these

Read the resource when the task needs it, not before.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.

One exception, and it's specific to this week: **if Zitadel itself won't start or won't issue a
usable token, the timebox is 30 minutes and the question goes to the mentor.** Debugging someone
else's Go service is not what this week is for.
