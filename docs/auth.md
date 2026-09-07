# Authentication & Authorization


This doc gets you from a clean clone to a working `Authorization` header, explains what's
actually inside that header and why, and tells you what to expect when things go wrong — an
expired token, a bad role, Zitadel being down. If you're here because an endpoint just gave you
a 401 or 403 and you want to know why, skip to [§6](#6-401-vs-403-vs-404-what-each-one-means).

Read this alongside [`docs/zitadel-local.md`](./zitadel-local.md) (how Zitadel itself is set up)
and [ADR-0002](./adr/0002-identity-and-tenant-isolation.md) (why it's set up this way). This doc
is the "make it actually work on my machine" layer on top of both.

---

## 0. The two ways in, up front

There are exactly two ways to get a `Principal` out of this API, and they are not equivalent:

| | Real Zitadel login | Dev bootstrap token |
|---|---|---|
| What you send | A real signed JWT from Zitadel | The literal value of `BOOTSTRAP_ADMIN_TOKEN` |
| Who you become | Whatever role Zitadel granted you (`owner`/`analyst`/`viewer` — see §5, `platform_admin` is **not** grantable this way yet) | Always `platform_admin` |
| Works if Zitadel is down | Yes, if your token hasn't expired | Yes, always — never touches Zitadel |
| Where it's checked | `app/core/auth/dependencies.py::get_principal`, real path | Same function, first `if` block, dev-only shortcut |

**If you just need to hit `POST /tenants` right now**, skip to [§1.4](#14-fast-path-the-dev-bootstrap-token) — it's three lines and doesn't need a browser.

**If you're testing the thing new developers will actually hit** (a real human logging in and getting a role-scoped token), read §1.1–§1.3 in order — there are two non-obvious gaps in the current bootstrap script that will 403 you if you don't know they're there. They're not bugs in your setup; they're gaps in the tooling, called out explicitly below.

---

## 1. From `just up` to a working header

### 1.1 Boot and bootstrap

```bash
just up
just zitadel-bootstrap
```

The second command runs `scripts/zitadel_bootstrap.py`. Read its output — it prints two IDs you need in the next steps and nowhere else:

```
Zitadel bootstrap complete.
Project ID:      <PROJECT_ID>
Organization ID: <DEV_ORG_ID>
Application:     tem-platform-dev
Dev user:        dev-user
```

**What this script did and didn't do**, because it matters for what happens next:

- Created one Zitadel **project** (`tem-platform`) with three roles: `owner`, `analyst`, `viewer`.
- Created one Zitadel **organization** (`tem-platform-dev`) — this is *a* tenant's identity home, but note carefully: **creating this org does not create a `tenants` row for it.** Nobody has told our own database this org exists yet. Keep the `Organization ID` from the output — you'll need it in §1.3.
- Created one Zitadel **application** (`tem-platform-dev`, Native/PKCE) that a human can log in through.
- Created and granted one **dev user** all three project roles.
- **Did not print the application's Client ID.** You need this to actually log in (§1.2) and the script simply doesn't surface it. Get it now:

  **Console:** open `http://zitadel:8080/ui/console` → *Projects* → `tem-platform` → *Applications* → `tem-platform-dev`. The Client ID is on that page.

  **API**, if you'd rather not open a browser yet:
  ```bash
  export ADMIN_PAT=$(cat .zitadel-bootstrap/admin.pat)
  export ZITADEL_URL=http://zitadel:8080
  export PROJECT_ID=<paste from bootstrap output>

  curl -s -X POST "$ZITADEL_URL/management/v1/projects/$PROJECT_ID/apps/_search" \
    -H "Authorization: Bearer $ADMIN_PAT" -H "Content-Type: application/json" -d '{}' \
    | python3 -m json.tool
  ```
  Find the entry named `tem-platform-dev` and read the client id field out of its `oidcConfig` block. (I haven't verified the exact JSON key name against this Zitadel version — if `oidcConfig.clientId` isn't there, the printed JSON will show you what it's actually called. The console is the more reliable source if this feels fragile.)

  ```bash
  export CLIENT_ID=<value from either method above>
  ```

- **Set `ZITADEL_PROJECT_ID` in your `.env`** to the Project ID from the bootstrap output — it ships blank in `.env.example`. `TokenVerifier` checks the token's `aud` against this value; leave it blank and every real login will fail with `401` (audience mismatch), full stop.

  ```bash
  # .env
  ZITADEL_PROJECT_ID=<paste from bootstrap output>
  ```

  `Settings` is loaded once per process and cached (`@lru_cache` on `get_settings()`), so editing `.env` alone does nothing to a running container:

  ```bash
  docker compose restart app
  ```

### 1.2 Log in as the dev user and get a token

You need a browser for this step — Zitadel's login pages are a real stateful UI, not something a single `curl` can drive. This is the same limitation `docs/zitadel-local.md` calls out for its own token walkthrough.

**Generate a PKCE pair** (the app is a public/native client — no client secret, so PKCE is mandatory):

```bash
export CODE_VERIFIER=$(openssl rand -base64 96 | tr -d '\n=+/' | cut -c1-64)
export CODE_CHALLENGE=$(printf '%s' "$CODE_VERIFIER" | openssl dgst -sha256 -binary | openssl base64 | tr -d '=' | tr '+/' '-_' | tr -d '\n')
export REDIRECT_URI=http://localhost:3000/callback   # must match what bootstrap registered — see below if you changed ZITADEL_REDIRECT_URI
```

If you set `ZITADEL_REDIRECT_URI` before running `zitadel-bootstrap`, use that value instead — whatever the script registered on the application is the only redirect URI Zitadel will accept.

**Build the authorize URL and open it in a browser:**

```bash
echo "http://zitadel:8080/oauth/v2/authorize?client_id=$CLIENT_ID&redirect_uri=$REDIRECT_URI&response_type=code&scope=openid%20profile%20urn:zitadel:iam:org:project:id:$PROJECT_ID:aud%20urn:zitadel:iam:user:resourceowner%20urn:zitadel:iam:org:projects:roles&code_challenge=$CODE_CHALLENGE&code_challenge_method=S256"
```

Log in as `ZITADEL_DEV_USERNAME` / `ZITADEL_DEV_PASSWORD` from your `.env`. The browser will redirect to `http://localhost:3000/callback?code=...` and show a connection-refused page — nothing's listening on that port, and that's fine. **Copy the `code` value out of the address bar.**

**Exchange the code for a token:**

```bash
export CODE=<paste from the redirect URL>

curl -s -X POST http://zitadel:8080/oauth/v2/token \
  -d grant_type=authorization_code \
  -d code=$CODE \
  -d redirect_uri=$REDIRECT_URI \
  -d client_id=$CLIENT_ID \
  --data-urlencode code_verifier=$CODE_VERIFIER \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'

export ACCESS_TOKEN=<paste the output>
```

**Sanity-check the token before touching our API.** Decode it (`just zitadel-decode "$ACCESS_TOKEN"` if that recipe exists, or `python3 -c "import jwt; print(jwt.decode('$ACCESS_TOKEN', options={'verify_signature': False}))"`) and confirm two claims are present and non-empty:

- `urn:zitadel:iam:user:resourceowner:id` — should equal your `Organization ID` from bootstrap
- `urn:zitadel:iam:org:project:<PROJECT_ID>:roles` — should be a dict containing `owner`, `analyst`, `viewer` (the project-ID-scoped key, not the generic `urn:zitadel:iam:org:project:roles` — this is why the scope string above used the plural `urn:zitadel:iam:org:projects:roles`)

If either is missing, don't go further into our app to debug it — it's a Zitadel-side scope/config issue, not an app bug, and `docs/zitadel-local.md` §9's troubleshooting table covers it.

### 1.3 Call the API — and read the first error as a good sign

```bash
curl -s -i http://localhost:8000/api/v1/tenants -H "Authorization: Bearer $ACCESS_TOKEN"
```

**Expect a `403` here**, with body detail `"Authenticated tenant is not available."` — and this is the checkpoint worth pausing on: **this 403 means authentication succeeded.** Zitadel signed your token, we verified the signature, we read your org id out of it correctly. What failed is the next step — looking that org id up in our own `tenants` table — because nothing has ever inserted a row for `tem-platform-dev`. Compare this to what you get with no header at all (`401`, different code path entirely) or a garbage token (`401`, same "Invalid authentication credentials" either way) — a 403 here is qualitatively different information, and it's the thing to look for the first time you wire this up.

Fix it by giving the dev org a tenant row — this is a one-time local hack, not something the app does for you:

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  INSERT INTO tenants (id, name, slug, is_active, zitadel_org_id)
  VALUES (gen_random_uuid(), 'Tem Platform Dev', 'tem-platform-dev', true, '<DEV_ORG_ID from bootstrap output>');
"
```

Retry the same `curl`. Expect `200` this time, with a JSON:API document listing tenants (possibly empty — that's fine, an empty list is still a `200`).

### 1.4 Fast path: the dev bootstrap token

For anything gated on `platform_admin` (right now, that's just `POST /tenants` — see §5), there is currently no way to get that role from a real Zitadel login at all: the bootstrap script's three project roles are `owner`/`analyst`/`viewer` only, and nothing grants `platform_admin` to any Zitadel user. The only way in is the dev-only static token:

```bash
export BOOTSTRAP_ADMIN_TOKEN=dev-only-bootstrap-secret-change-me   # from your .env

curl -s -i -X POST http://localhost:8000/api/v1/tenants \
  -H "Authorization: Bearer $BOOTSTRAP_ADMIN_TOKEN" \
  -H "Idempotency-Key: auth-doc-check-1" \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test Co", "slug": "smoke-test-co"}'
```

Expect `201` (or `503`/`502` if the separate Zitadel *management* service account for org creation isn't set up — that's a different credential from anything in this doc; see the W2-09 PR's test plan for provisioning it). This request never touches Zitadel's login flow at all — `get_principal` matches the raw token string against `BOOTSTRAP_ADMIN_TOKEN` and short-circuits straight to a `Principal(role=PLATFORM_ADMIN)`, no signature, no JWKS, no tenant lookup. It only works when `ENVIRONMENT=dev`; it does nothing in staging/prod, by design.

---

## 2. Org ↔ tenant: which ID appears where

Two different IDs exist for the same conceptual "tenant," and they never appear interchangeably. Getting these crossed is the single most common way to misdebug this system.

| | Zitadel Organization ID | Our `tenants.id` |
|---|---|---|
| Format | Zitadel's own numeric string, e.g. `290...861` | Our UUID |
| Lives in | Zitadel's database | Our `tenants` table |
| Appears in a JWT as | `urn:zitadel:iam:user:resourceowner:id` | Never — this ID never appears in a token |
| Appears in our DB as | `tenants.zitadel_org_id` (nullable, unique) | `tenants.id` (primary key) |
| Appears on `Principal` as | Never | `Principal.tenant_id` |
| Who generates it | Zitadel, when the org is created | Our own `uuid4()` default, at insert time |

The translation direction only ever goes one way: **token → org id → look up `tenants.zitadel_org_id` → get our UUID → put that UUID on `Principal`.** Nothing downstream of `get_principal` ever sees the Zitadel org id again — by the time a route handler runs, `principal.tenant_id` is already our own UUID (ADR-0002 §3/§4). If you're grepping for a tenant and only have one of the two IDs, that table tells you which column to grep.

---

## 3. Permission matrix

From `app/core/auth/permissions.py` — this *is* the matrix, not a paraphrase of it:

| Permission | Endpoint | `platform_admin` | `owner` | `analyst` | `viewer` |
|---|---|:---:|:---:|:---:|:---:|
| `tenant:create` | `POST /api/v1/tenants` | ✅ | ❌ | ❌ | ❌ |
| `tenant:read` | `GET /api/v1/tenants`, `GET /api/v1/tenants/{id}` | ✅ | ✅ | ✅ | ✅ |

Two things worth knowing that the table alone doesn't say:

- **A user can hold more than one role** (the bootstrap dev user holds all three), but `Principal.role` is a single value. `TokenVerifier._select_role` picks the highest-privilege role present, in this fixed order: `platform_admin > owner > analyst > viewer`. If you're granted `owner` and `viewer` both, your `Principal.role` is `owner` — the others are simply not visible past that point.
- **`tenant:read` isn't tenant-scoped.** Any of the four roles can list *every* tenant and fetch *any* tenant by id — `list_tenants`/`get_tenant` don't filter by `principal.tenant_id` at all. That may be intentional (these are platform-level admin objects, not tenant-owned business data), but it's not something this doc is asserting is correct — it's just what the code currently does, worth knowing before you assume tenant isolation applies here the way ADR-0002 §2 describes for regular data.

---

## 4. Token expiry — what a client sees, what it should do

Access tokens live 15 minutes (`ADR-0002 §6`, enforced in `compose.yaml`'s `OIDCSETTINGS`). Refresh tokens live 12 hours idle by default.

**What expiry looks like from the outside:** identical to any other invalid token. `jwt.decode(..., options={"verify_exp": True})` raises `ExpiredSignatureError`, which `TokenVerifier.verify` catches and re-raises as the same `TokenVerificationError` every other verification failure raises. `get_principal` turns that into `401` with detail `"Invalid authentication credentials."` — the same message you'd get from a garbage token, a wrong-issuer token, or a token with no recognized role. **The response body cannot tell you it was specifically expiry.** The only structural signal is the `WWW-Authenticate: Bearer` header, which is present on every 401 from this path — its presence is the cue to re-authenticate, not a diagnosis of why.

**What a client should do:** on any `401` with `WWW-Authenticate: Bearer`, don't retry the same token — exchange the refresh token instead:

```bash
curl -s -X POST http://zitadel:8080/oauth/v2/token \
  -d grant_type=refresh_token \
  -d refresh_token=$REFRESH_TOKEN \
  -d client_id=$CLIENT_ID
```

and retry the original request once with the new access token. If the refresh call itself fails (refresh token also expired or was revoked), there's no recovery short of the full login flow in §1.2 again.

---

## 5. What breaks when Zitadel is down, and what doesn't

This is the developer-facing version of the table in ADR-0002; same facts, framed around "what will I actually see locally."

| Situation | What happens | Why |
|---|---|---|
| You already have an unexpired access token, JWKS cache is warm | Requests keep working | `TokenVerifier` never calls Zitadel per-request — it validates against a cached JWKS (`JWKSCache`, 1hr TTL). No live dependency on the request path at all. |
| Unexpired token, but its `kid` isn't in the cache yet (first time you've seen this signing key) and Zitadel is down | `401`, `"Failed to fetch JWKS and cache is empty"` if the cache was never populated at all; a **stale-but-working** cache instead falls back gracefully and logs a warning, still succeeding | `JWKSCache._fetch_keys()` only hard-fails when it has *nothing* cached yet — an already-populated cache tolerates a failed refresh silently. |
| You try to log in (§1.2) or refresh (§4) | Fails, no workaround | Both need Zitadel's live `/oauth/v2/token` endpoint. |
| You use the `BOOTSTRAP_ADMIN_TOKEN` path (§1.4) | Keeps working, unaffected | It never calls Zitadel — string comparison against a config value, nothing else. Notably, this is the *only* dev-time auth path immune to a local Zitadel outage. |
| You call `POST /api/v1/tenants` at all — any auth method | Fails with `503` | Independent of how you authenticated: creating a tenant separately calls Zitadel's *management* API to create the org, and that call has no fallback. See the W2-09 provisioning docs. |

---

## 6. 401 vs 403 vs 404: what each one means

See `docs/api-conventions.md` for the general rule; this section is the auth-specific instance of it, matched against the actual code paths in `get_principal`/`require_permission`:

| You get | Detail message | What it actually means | What to do about it |
|---|---|---|---|
| `401` | `"Authentication credentials are required."` | No `Authorization` header at all | Add one |
| `401` | `"Invalid authentication credentials."` | Header present, but: bad signature, expired, wrong issuer/audience, unsupported algorithm, missing `kid`, unknown `kid` (after one forced JWKS refetch), missing resourceowner claim, or **no recognized role in the roles claim at all** | Get a new token (§1.2 or §1.4) — retrying the same one will never work |
| `403` | `"Authenticated tenant is not available."` | Token verified fine; the org it names has no matching `tenants` row, or that tenant's `is_active` is `false` | This is a provisioning/data problem, not a token problem — see §1.3 |
| `403` | `"Insufficient permission for this operation."` / `"Insufficient role for this operation."` | Token verified, tenant is active, but `principal.role` isn't in the permission matrix (§3) for this endpoint | Expected outcome for that role — not a bug to chase |
| `404` | varies | The specific resource id doesn't exist | See `docs/api-conventions.md` |
