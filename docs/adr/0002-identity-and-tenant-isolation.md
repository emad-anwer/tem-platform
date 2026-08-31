# ADR 0002: Identity and Tenant Isolation

**Date:** 2026-08-31  
**Status:** Proposed  
**Supersedes:** The Week 2 "self-built JWT + password hashing" plan in [ROADMAP.md](../ROADMAP.md)

## Context

Week 1 shipped tenant CRUD with no authentication — `POST /api/v1/tenants` is open to the
world. Week 2 must close that gap. The original roadmap assumed we would build user management,
password hashing, JWT issuance, and RBAC ourselves. We are now delegating identity to
[Zitadel](https://zitadel.com), a self-hosted OIDC identity provider.

Delegating identity is usually correct. It is also a decision that moves a class of choices out
of our hands, so this ADR exists to say exactly which choices are now made for us, which ones
remain ours, and what the boundary between the two looks like in code.

---

## Decisions

### 1. What Zitadel owns

Zitadel is the **sole authority** for:

| Concern | Why we delegate it |
|---|---|
| User identities (create, update, delete) | We are not a user directory. Rebuilding SCIM, email verification, and account recovery is a project, not a feature. |
| Credentials (passwords, passkeys, MFA) | Storing credentials correctly is hard and high-consequence. Zitadel does it; we do not. |
| Sessions and login flows | OIDC authorization code flow with PKCE. We never see a password. |
| Token issuance | Access tokens and refresh tokens are minted by Zitadel. We never sign a JWT. |
| Key management (signing keys, JWKS) | Zitadel rotates its signing keys and publishes them at `/.well-known/jwks.json`. We consume that endpoint; we do not manage keys. |
| Brute-force protection and lockout | Zitadel rate-limits login attempts per user. |

**What we gave up:** the ability to issue tokens with arbitrary claims or custom lifetimes
without going through Zitadel's configuration or Actions. We accept this because the alternative
is reimplementing an authorization server.

**What Zitadel can do that we would not have allowed ourselves:** Zitadel can disable a user
globally, instantly revoking all future token issuance. This is more power than our app-layer
`is_active` flag, which only gates API access on the next request. We accept this because
account-level lockout belongs at the IdP.

### 2. What stays ours, and why

| Concern | Why it stays | Where it lives |
|---|---|---|
| Tenant data isolation | Zitadel has no knowledge of which database rows belong to which tenant. Row-level scoping is the product's problem, permanently. | Repository layer — every query is scoped by `tenant_id` from the Principal. |
| Authorisation decisions at the route | "Can this user perform this action on this resource?" is a product decision, not an identity decision. Zitadel authenticates; we authorise. | FastAPI dependencies in `core/auth`. |
| The mapping from token claims to a Principal | A token is an external artifact. A `Principal` is our internal representation of "who is making this request and what are they allowed to do." The translation is ours. | `core/auth/principal.py` (new). |
| Tenant lifecycle (create, deactivate, configure) | Our `tenants` table is the system of record for tenant metadata, billing state, feature flags, and product configuration. Zitadel orgs hold identity configuration. | `core/service.py`, `core/models.py`. |
| `POST /tenants` access control | Creating a tenant is a platform-admin operation. Week 1 left it open; Week 2 closes it behind authentication. Only users with a `platform_admin` role (or a bootstrap token in dev) may call it. | Route-level dependency guard. |

**What we gave up:** nothing. These concerns were never candidates for delegation.

### 3. Zitadel org ↔ our tenant

**Decision:** One Zitadel organization per tenant, mapped 1:1.

**Our `tenants` table is authoritative.** A tenant exists when it has a row in our database.
The Zitadel org is a dependent resource created during tenant provisioning. We store the
Zitadel org ID on the tenant row (`zitadel_org_id` column, nullable UUID) so we can correlate,
but the **ID of record** in our database is `tenants.id` — our own UUID, not Zitadel's.

**What happens if the two disagree:**

- If our tenant row exists but the Zitadel org does not → the tenant is in a broken provisioning
  state. The tenant is treated as inactive until the org is recreated. A background reconciliation
  job (not built this week) should detect and repair this.
- If a Zitadel org exists but we have no tenant row → the org is orphaned. It has no effect on
  our system. Users in that org will receive valid Zitadel tokens, but those tokens will fail
  our tenant lookup and receive `403 Forbidden`.
- If `tenants.is_active = false` → the tenant is suspended regardless of the Zitadel org's state.
  Token validation succeeds (the token is real), but the authorisation layer rejects the request.

**What we gave up:** the simplicity of using the Zitadel org ID as our primary key. We chose our
own UUID because we do not want our primary key space controlled by an external system, and
because changing IdPs should not require a data migration on every foreign key in the database.

### 4. Where `tenant_id` comes from

**Decision:** `tenant_id` is extracted from the validated access token's
`urn:zitadel:iam:user:resourceowner:id` claim. Never from the URL. Never from a request header. Never from a
query parameter.

The token is the **only trusted source** of tenant identity. The auth middleware validates the
token, extracts the org ID from the claim, maps it to our internal `tenant_id` via a lookup on
`tenants.zitadel_org_id`, and places it on the `Principal`. Every downstream layer receives
`tenant_id` from the Principal, never from the request.

**Claim:** `urn:zitadel:iam:user:resourceowner:id`

This claim is present in Zitadel JWTs when the `urn:zitadel:iam:user:resourceowner` scope is
requested during authentication. We require this scope on all OIDC clients. Tokens without the
resourceowner claim are rejected with `403`.

**The org-to-tenant lookup** will be cached in-process (TTL 60s, invalidated on tenant update)
to avoid a database round-trip on every request. The cache key is the Zitadel org ID; the value
is the internal tenant UUID and `is_active` flag.

**What we gave up:** the option of accepting `tenant_id` from the URL path
(`/api/v1/tenants/{tenant_id}/targets`). URL-based tenant resolution is convenient but requires
a cross-check against the token on every request, and mismatches between the two are a class of
bug we can avoid entirely by having one source.

### 5. Where roles live

**Decision:** Zitadel project roles, asserted in the access token. One source of truth.

Roles are defined as Zitadel project roles: `owner`, `analyst`, `viewer`. They appear in the
token under `urn:zitadel:iam:org:project:roles`. The auth layer reads them from the token and
maps them to the Principal's `role` field.

We do **not** maintain a separate `user_roles` table. Two sources of truth for authorisation is
the failure mode we are avoiding. If a user's role changes, it changes in Zitadel, and the next
token they receive reflects it.

**Consequence of token-based roles:** a role change does not take effect until the current token
expires and a new one is issued. With a 15-minute token lifetime (our default), this is
acceptable. For emergency revocation (e.g., a compromised analyst account), an admin disables
the user in Zitadel, which prevents all future token issuance immediately.

**What we gave up:** per-resource permission grants (e.g., "analyst on project X but viewer on
project Y"). Zitadel project roles are per-tenant, not per-resource. If we need resource-level
permissions later, we will add a `permissions` table in our database — but the three base roles
(`owner`, `analyst`, `viewer`) are still sourced from the token. Fine-grained permissions would
extend, not replace, the token roles.

### 6. Token type

**Decision:** JWT access tokens with local JWKS validation.

Zitadel is configured to issue JWT access tokens (not opaque). Our API validates them locally
using Zitadel's JWKS endpoint (`{issuer}/.well-known/jwks.json`). The JWKS keyset is cached
in-process and refreshed when signature verification fails with an unknown `kid`, or every
60 minutes, whichever comes first.

**Why not opaque + introspection:**

- Introspection requires a network call to Zitadel on **every request**. At 3am when Zitadel is
  down, every API call fails — including for users who already have valid tokens. With local JWT
  validation, a user with a valid, unexpired token can continue working even if Zitadel is
  temporarily unreachable. The only operation that fails is *acquiring a new token* (login, refresh).
- Introspection adds latency to every request (~5–20ms per call). Local validation is sub-millisecond.
- The information in our JWTs (user ID, org ID, roles) is not sensitive enough to warrant hiding
  it behind an opaque reference. The tokens travel over TLS and are never exposed to end users
  in a browser context (this is a backend API, not a SPA).

**What we gave up:** instant token revocation. A revoked user's existing JWT remains valid until
it expires (max 15 minutes). We accept this because:

1. Disabling the user in Zitadel stops all new token issuance immediately.
2. 15 minutes is an acceptable window for a security platform where the primary threat is
   credential misuse, not session hijacking.
3. If we need faster revocation later, we can add a short-lived deny-list in Redis checked
   on each request — a small, local addition, not an architecture change.

**Token lifetime:** 15 minutes for access tokens, 12 hours for refresh tokens. Short access
tokens limit the blast radius of a leaked token. Refresh tokens are stored only by the client
and rotated on each use (Zitadel's default).

### 7. Audience and issuer

**Decision:**

- **`iss` (issuer):** must exactly match our Zitadel instance URL (e.g.,
  `https://auth.tem-platform.dev`). Configurable via `ZITADEL_ISSUER` env var.
- **`aud` (audience):** must contain our Zitadel project ID (e.g.,
  `289366262830841861`). Configurable via `ZITADEL_PROJECT_ID` env var. The audience is set
  by requesting the scope `urn:zitadel:iam:org:project:id:{project_id}:aud` during login.

**What we do with a valid Zitadel token minted for a different application:**

Reject it. A token with a valid signature and correct issuer but wrong audience was minted for
someone else's project on the same Zitadel instance. We return `401 Unauthorized` with detail
`"Token audience does not match this application."` We do not return 403 because the token is
not authenticated *for us* — it is not a permissions problem, it is an identity problem.

**What we gave up:** the ability to accept tokens from other applications on the same Zitadel
instance. This is intentional — cross-application token reuse is a security boundary we want
closed.

### 8. The Principal type

**Decision:** all authenticated request context flows through a single `Principal` dataclass
defined in `src/app/core/auth/principal.py`. Nothing outside `core/auth/` may import a JWT
library or reference Zitadel-specific claims.

```python
@dataclasses.dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated identity for the current request.

    This is the ONLY object the rest of the codebase sees.
    It does not leak token format, IdP vendor, or claim names.
    """
    user_id: str           # Zitadel user ID (sub claim), opaque to consumers
    tenant_id: uuid.UUID   # OUR tenant UUID, not the Zitadel org ID
    role: Role             # owner | analyst | viewer
    # Future: scopes, permissions, session_id

class Role(enum.StrEnum):
    OWNER = "owner"
    ANALYST = "analyst"
    VIEWER = "viewer"
```

The mapping from JWT claims to `Principal` happens inside `core/auth/dependencies.py` as a
FastAPI dependency. Route handlers declare `principal: Principal = Depends(require_auth)` and
receive a fully-resolved, vendor-neutral identity object. Role checks use a second dependency:
`Depends(require_role(Role.OWNER))`.

**What we gave up:** the convenience of reading token claims directly in route handlers. We
chose the indirection because the alternative is Zitadel-specific import statements scattered
across every module. When (not if) we change IdP configuration or claim shapes, the blast
radius is one file.

### 9. Machine access

**Decision:** Zitadel service users, not our own API keys. Decided now; implemented in Week 4.

Machine-to-machine access (CI/CD pipelines, automation scripts, partner integrations) will use
Zitadel service users authenticated via the **client credentials grant** (with private key JWT
for production, client secret for dev/test). Service users are created within a Zitadel
organization, so they inherit the same org→tenant mapping as human users.

**Why not our own per-tenant API keys:**

- Our own API keys would require us to build key generation, hashing, storage, rotation, and
  revocation. That is a significant surface area for a security product.
- API keys would be a second authentication path with different validation logic, different
  revocation semantics, and different audit trail. One path through one IdP is simpler to
  reason about and audit.
- Zitadel service users get the same token format (JWT), the same claims structure, the same
  JWKS validation path. The `Principal` type does not need to know whether the caller is human
  or machine — it sees the same fields either way.

**What we gave up:** the ability to issue API keys without Zitadel. If Zitadel is down, no new
machine tokens can be issued. Existing tokens remain valid (JWT, local validation). For
long-running automation, we configure longer access token lifetimes on the service user's
application (1 hour instead of 15 minutes), still with refresh token rotation.

---

## `POST /tenants` — closing the open door

Week 1 left `POST /api/v1/tenants` unauthenticated. Week 2 changes this:

- **In production:** requires a valid token with `role = platform_admin` (a role we add to
  Zitadel but do NOT include in the three tenant-level roles above — it is a platform-wide
  role, not a tenant role).
- **In dev/test:** a bootstrap mechanism (env var `BOOTSTRAP_ADMIN_TOKEN`) allows initial
  tenant creation before any org/user exists. This token is a static secret, not a JWT, and is
  only accepted when `ENVIRONMENT=dev`.
- Tenant creation is a two-step process: (1) create the tenant row in our database, (2) create
  the corresponding Zitadel org via the management API. If step 2 fails, the tenant row is
  rolled back. This is not a distributed transaction — it is a sequential operation with
  explicit compensation.

---

## What happens at 3am when Zitadel is down

| Operation | Impact | Why |
|---|---|---|
| User login (acquire new token) | **Fails.** Users cannot authenticate. | Zitadel's token endpoint is unreachable. This is unavoidable with any external IdP. |
| API call with valid, unexpired JWT | **Succeeds.** | Local JWKS validation. No network call to Zitadel required. Cached JWKS keys remain valid. |
| API call with expired JWT | **Fails.** | The token is expired. The client must refresh, which requires Zitadel. |
| Token refresh | **Fails.** | Refresh requires Zitadel's token endpoint. |
| Tenant creation | **Fails.** | Requires Zitadel management API to create the org. |
| JWKS key rotation during outage | **Graceful degradation.** | We continue using the cached keyset. If Zitadel rotated keys during the outage AND the old key was removed, tokens signed with the new key will fail validation. This is an extremely unlikely edge case (key rotation is infrequent and old keys are kept for a grace period). |

**Is this answer different for a user who already has a valid token?** Yes, and that is the
primary argument for JWTs over opaque tokens. An already-authenticated user with a valid JWT
continues to work uninterrupted. With opaque tokens + introspection, even that user would be
blocked.

---

## If we ever leave Zitadel

What would have to change:

1. **`core/auth/dependencies.py`** — the JWT validation logic (issuer URL, JWKS endpoint,
   claim names). This is the primary file.
2. **`core/auth/principal.py`** — only if the new IdP's claim structure cannot provide
   `sub`, org ID, and roles. The `Principal` type itself stays unchanged; only the mapping
   function changes.
3. **`core/config.py`** — environment variables for the new IdP (issuer URL, project/client
   ID, JWKS URL).
4. **Tenant provisioning** — the code that calls Zitadel's management API to create orgs.
   Replace with the new IdP's equivalent, or remove if the new IdP does not have an org
   concept.
5. **`tenants.zitadel_org_id` column** — rename or replace with the new IdP's tenant
   identifier. One migration.

That is three Python files, one config change, and one migration. Everything else — the
`Principal` type, the route-level role checks, the repository-layer tenant scoping, the error
handling — is IdP-agnostic by design. If this list were longer, the boundary would be in the
wrong place.

---

## Consequences

**Positive:**

- Identity is not our problem. We do not store passwords, manage sessions, or rotate signing
  keys.
- One authentication path for humans and machines. One token format. One validation function.
- The codebase outside `core/auth/` has no idea Zitadel exists. Changing IdP is a
  three-file change.
- Tenant isolation is enforced at two independent layers: application (Principal → tenant_id
  on every query) and database (Postgres RLS in Week 7).

**Negative:**

- Zitadel is a hard runtime dependency for login and tenant provisioning. If it is down, new
  users cannot authenticate and new tenants cannot be created.
- Role changes have up to 15 minutes of propagation delay (token lifetime).
- Tenant provisioning is a two-system operation (our DB + Zitadel management API) with
  eventual consistency, not a single transaction.
- The team must learn Zitadel's admin console, org model, and project/role configuration in
  addition to the application codebase.

We accept these costs because building a secure identity system from scratch in a week is not
realistic, and the boundary we have drawn keeps the coupling small enough that the costs are
contained.

---

## References

- [RFC 9068 — JWT Profile for OAuth 2.0 Access Tokens](https://www.rfc-editor.org/rfc/rfc9068.html)
- [RFC 7662 — OAuth 2.0 Token Introspection](https://www.rfc-editor.org/rfc/rfc7662.html)
- [Zitadel Organizations and Multi-Tenancy](https://zitadel.com/docs/guides/solution-scenarios/multi-tenancy)
- [Zitadel Project Roles and Token Claims](https://zitadel.com/docs/guides/integrate/retrieve-user-roles)
- [Zitadel Service Users](https://zitadel.com/docs/guides/integrate/service-users)
- [ADR 0001 — Module Boundaries](./0001-module-boundaries.md)
