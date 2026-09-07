# Local Authentication Guide

This is the shortest supported path from a fresh checkout to a real
`Authorization: Bearer <token>` header for the local API. It uses the local
Zitadel instance from Compose and the development user created by the
bootstrap script. No production credentials belong in this workflow.

For the identity-provider background and the complete console/API walkthrough,
see [Zitadel Local Identity Provider](./zitadel-local.md). For the decisions
this guide implements, see [ADR-0002](./adr/0002-identity-and-tenant-isolation.md).

## 1. Start From A Fresh Checkout

Install Docker with Compose v2 and `just`, then run:

```bash
git clone <repository-url>
cd tem-platform
cp .env.example .env
```

The values in `.env.example` are throwaway development values. Do not reuse
them outside a local machine.

Zitadel is configured with the hostname `zitadel`, not `localhost`. On macOS
or Linux, add that hostname once:

```bash
echo "127.0.0.1 zitadel" | sudo tee -a /etc/hosts
```

Start the stack and apply the application migrations:

```bash
just up
just migrate
```

Wait for the services to become healthy, then check them:

```bash
just health
curl http://localhost:8000/healthz
curl -H 'Host: zitadel' http://127.0.0.1:8080/debug/ready
```

The API is at `http://localhost:8000`. Zitadel's console and OAuth endpoints
must use `http://zitadel:8080`, or Zitadel will return `404 Instance not found`.

## 2. Bootstrap The Local IdP

Run the idempotent bootstrap after Zitadel is healthy:

```bash
just zitadel-bootstrap
```

It creates or reconciles:

- the shared `tem-platform` project;
- the `owner`, `analyst`, and `viewer` project roles;
- the native OIDC application `tem-platform-dev`;
- the development organization `tem-platform-dev`;
- the development user from `ZITADEL_DEV_USERNAME` and
  `ZITADEL_DEV_PASSWORD`; and
- grants for all three roles to that user.

Keep the command output. It includes the `Project ID` and `Organization ID`.
Put the project ID in `.env`:

```dotenv
ZITADEL_PROJECT_ID=<Project ID printed by just zitadel-bootstrap>
```

Restart the API so it reloads the setting:

```bash
docker compose restart app
```

The bootstrap command does not print the OIDC client ID. Find it in the
console at `http://zitadel:8080/ui/console`:

1. Sign in with `ZITADEL_ADMIN_USERNAME` and `ZITADEL_ADMIN_PASSWORD` from
   `.env`.
2. Open **Projects**, then `tem-platform`.
3. Open **Applications**, then `tem-platform-dev`.
4. Copy the **Client ID**.

The application is already configured as a native public client using
Authorization Code + PKCE, with JWT access tokens and role claims enabled.

## 3. Get A JWT With PKCE

Set the values from the previous steps in the current shell:

```bash
export PROJECT_ID='<Project ID>'
export CLIENT_ID='<Client ID from the console>'
export REDIRECT_URI='http://localhost:3000/callback'
export ISSUER='http://zitadel:8080'
```

Generate a PKCE verifier and challenge. Python 3 is already available in the
application image; macOS and Linux also normally provide it locally:

```bash
export CODE_VERIFIER="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
export CODE_CHALLENGE="$(printf %s "$CODE_VERIFIER" | openssl dgst -sha256 -binary | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
```

Build the login URL and open it in a browser:

```bash
export AUTH_URL="${ISSUER}/oauth/v2/authorize?client_id=${CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code&scope=openid%20profile%20urn%3Azitadel%3Aiam%3Aorg%3Aproject%3Aid%3A${PROJECT_ID}%3Aaud%20urn%3Azitadel%3Aiam%3Auser%3Aresourceowner%20urn%3Azitadel%3Aiam%3Aorg%3Aproject%3Aroles&code_challenge=${CODE_CHALLENGE}&code_challenge_method=S256"
open "$AUTH_URL"       # macOS
# xdg-open "$AUTH_URL" # Linux
```

Sign in as the development user using `ZITADEL_DEV_USERNAME` and
`ZITADEL_DEV_PASSWORD` from `.env`. The browser redirects to
`http://localhost:3000/callback?code=...`. A local callback server is not
required for this manual flow: copy the `code` query parameter from the
address bar before exchanging it. The code is single-use and short-lived.

```bash
export AUTH_CODE='<code copied from the browser address bar>'
```

Exchange the code for an access token:

```bash
export ACCESS_TOKEN="$(curl -fsS -X POST "${ISSUER}/oauth/v2/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=authorization_code' \
  --data-urlencode "code=${AUTH_CODE}" \
  --data-urlencode "redirect_uri=${REDIRECT_URI}" \
  --data-urlencode "client_id=${CLIENT_ID}" \
  --data-urlencode "code_verifier=${CODE_VERIFIER}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
```

The header used for API calls is now:

```text
Authorization: Bearer ${ACCESS_TOKEN}
```

For a local sanity check, decode the token without treating decoding as
verification:

```bash
just zitadel-decode "$ACCESS_TOKEN"
```

The payload should contain `iss`, `aud`, `exp`,
`urn:zitadel:iam:user:resourceowner:id`, and the project roles claim. The API
still verifies the signature, issuer, audience, expiry, key ID, tenant mapping,
and role; decoding alone proves none of those properties.

## 4. Make An Authenticated Request

Use the token in the `Authorization` header:

```bash
curl -i http://localhost:8000/api/v1/tenants \
  -H "Authorization: Bearer ${ACCESS_TOKEN}"
```

The development organization created by `just zitadel-bootstrap` is a Zitadel
organization, not automatically an application tenant row. Until that org is
mapped to a tenant in the application database, the request above is expected
to return `403` with an RFC 9457 problem response: the token is valid, but its
authenticated organization is not available to this API. That is different
from a `401`, which means the token was absent or failed authentication.

Tenant provisioning requires the application's Zitadel management credentials
(`ZITADEL_MANAGEMENT_CLIENT_ID` and `ZITADEL_MANAGEMENT_CLIENT_SECRET`) and
creates both sides of the mapping. Do not copy the placeholder values from
`.env.example` into a real provisioning environment. Once a tenant exists,
its stored `zitadel_org_id` must match the token's resource-owner claim.

## 5. Org And Tenant IDs

There are three IDs that are easy to confuse:

| ID | Meaning | Where it appears |
|---|---|---|
| Project ID | Shared TEM Platform application identifier | `.env` as `ZITADEL_PROJECT_ID`; token `aud` |
| Zitadel organization ID | Identity boundary for one organization | Token claim `urn:zitadel:iam:user:resourceowner:id`; database column `tenants.zitadel_org_id` |
| Application tenant ID | TEM Platform's own row identifier | Database `tenants.id`; resource URLs and response bodies |

The mapping is one-to-one: one Zitadel organization maps to one application
tenant. The token's resource-owner claim is the only trusted source of tenant
identity. It is never taken from a URL, header, or query parameter. The API
resolves the claim to the application's UUID before repository code runs.

## 6. Permission Matrix

Zitadel supplies the role claim. The API's permission dependency decides what
that role can do:

| Role | `GET /api/v1/tenants` | `GET /api/v1/tenants/{tenant_id}` | `POST /api/v1/tenants` |
|---|---:|---:|---:|
| `viewer` | 200 in own tenant scope | 200 in own tenant scope | 403 |
| `analyst` | 200 in own tenant scope | 200 in own tenant scope | 403 |
| `owner` | 200 in own tenant scope | 200 in own tenant scope | 403 |
| `platform_admin` | 200 | 200 | 201 or 200 on an idempotent retry |

An authenticated token for another tenant must not read the target tenant or
its collection data. The API's documented decision is `403` for a known,
existing resource that the caller cannot access. A genuinely missing UUID is
`404`.

## 7. Expiry And Client Behaviour

Local access tokens are configured for approximately 15 minutes. A client
should:

1. send the access token as `Authorization: Bearer <token>`;
2. treat `401` with `WWW-Authenticate: Bearer` as an authentication failure;
3. obtain a fresh access token through Zitadel's login or refresh flow; and
4. retry the original request only after obtaining the new token.

Do not retry an expired token indefinitely. A `403` is not fixed by refreshing
the token when the identity is valid but lacks permission or tenant access.

## 8. What Zitadel Downtime Changes

| Operation | During Zitadel outage |
|---|---|
| Login or token refresh | Fails; no new access token can be issued |
| API call with a valid, unexpired JWT | Continues using the cached JWKS locally |
| API call with an expired JWT | Fails with 401; it needs a new token |
| Tenant provisioning | Fails because it needs the management API |
| Verification of a token signed by a newly rotated key | May fail if the key is not in the cached JWKS |

Local JWT verification is deliberately not an introspection call on every API
request. Existing valid sessions can therefore continue briefly during an IdP
outage, within the token lifetime and cached-key limits.

## Troubleshooting

### `404 Instance not found` from Zitadel

Use `http://zitadel:8080`, not `http://localhost:8080`, and confirm the
`127.0.0.1 zitadel` entry exists in `/etc/hosts`.

### Token exchange returns `invalid_grant`

The authorization code is single-use, the redirect URI must match exactly, and
`CODE_VERIFIER` must be from the same shell session that generated the login
URL. Repeat the PKCE steps from challenge generation onward.

### API returns `401`

Check the `Authorization` spelling, that the value begins with `Bearer `, and
that the token has not expired. Also confirm `.env` contains the correct
`ZITADEL_PROJECT_ID` and `ZITADEL_ISSUER`, then restart the app.

### API returns `403` with a valid token

The token authenticated successfully. Check that the resource-owner claim
matches an active `tenants.zitadel_org_id` row and that the role is allowed for
the operation. This is expected for the bootstrap-created dev organization
until it is provisioned as an application tenant.