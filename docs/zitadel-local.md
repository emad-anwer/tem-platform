# Zitadel Local Identity Provider — Setup & Findings

**Status:** Active · **Module:** Identity Infra Prework (W2-05) · **Author:** Mentor (infra/docs only, no application code)

This is the base Zitadel Compose service and console walkthrough for **W2-05**. It gets you
from `git clone` to holding a real, decoded access token that satisfies ADR-0002. It does
**not** include the idempotent bootstrap script or `just zitadel-bootstrap` recipe — that
automation is the actual W2-05 deliverable and is intentionally left for you to build. What's
here is meant to make that task an ordinary one instead of a science project: the compose
service works, the console steps are spelled out, and every trap we hit while proving it out is
documented below so you don't lose a day rediscovering them.

Read [ADR-0002](./adr/0002-identity-and-tenant-isolation.md) first if you haven't. Everything
here exists to satisfy it.

---

## 1. Quickstart

```bash
git clone <repo> && cd tem-platform
cp .env.example .env          # fill in ZITADEL_PROJECT_ID after step 3 below
just up
```

Cold start (`docker compose down -v && up -d`, empty volumes) reaches a healthy `zitadel`
container in **~20–30 seconds** on a laptop. `zitadel-db` and `zitadel` add roughly **~200 MB**
of RAM to the stack at idle (~60 MB for zitadel-db, ~150 MB for zitadel) — noticeable but not
heavy. First boot also runs Zitadel's internal setup/migration steps once; you'll see
`migration failed` in the logs if something is wrong with the bootstrap env vars (see §6).

Console at **http://localhost:8080/ui/console** (or `http://zitadel:8080/ui/console` — see the
issuer trap immediately below before either URL confuses you). Log in with
`ZITADEL_ADMIN_USERNAME` / `ZITADEL_ADMIN_PASSWORD` from your `.env`.

---

## 2. The issuer trap — read this before anything else

`ZITADEL_EXTERNALDOMAIN` in `compose.yaml` is set to `zitadel` — the Compose service name —
**not** `localhost`. Every token's `iss` claim, and Zitadel's own instance routing, is keyed off
this value. This is deliberate: a container on the Compose network (the `app` service, later
consuming JWKS in W2-04) and a browser/script on your host must see the **same** issuer, or
token validation will disagree with itself depending on who's asking.

**The consequence:** Zitadel resolves which virtual instance to serve based on the `Host` header
of the incoming request. A request to `http://localhost:8080/...` gets:

```
unable to set instance using origin &{localhost:8080  http} (ExternalDomain is zitadel): ID=QUERY-1kIjX Message=Instance not found.
```

(`404`). This is not a bug — it's Zitadel correctly refusing a domain it doesn't recognize. Two
endpoints are exempt because they don't need instance resolution: `/debug/healthz` and
`/debug/ready` (which is what `compose.yaml`'s healthcheck and `just health` use) — those work
fine on `localhost:8080`. Everything else (`/.well-known/openid-configuration`, `/oauth/v2/*`,
the console UI, `/ui/login/*`) needs the `Host: zitadel` match.

**Fix, one time, on your host:**

```bash
echo "127.0.0.1 zitadel" | sudo tee -a /etc/hosts
```

After that, `http://zitadel:8080/...` works from your host exactly like it works from inside
any container on the Compose network (Docker's embedded DNS already resolves `zitadel` there —
no `/etc/hosts` edit needed *inside* containers, only on the host). Everything in this doc and
in the `just zitadel-*` recipes assumes this entry exists.

If you'd rather not touch `/etc/hosts`, `curl --resolve zitadel:8080:127.0.0.1 ...` does the
same thing for a single command and is how this doc's evidence was generated.

---

## 3. Console steps: project, roles, app

Zitadel needs a **project** with the three ADR-0002 roles and at least one **application**
before any client can get a usable token. These are the manual steps (there is no automation
for this yet — that's your W2-05 task):

1. Log into the console as the bootstrap admin.
2. **Projects → New Project.** Name it (e.g. `tem-platform`). Note the **Project ID** shown on
   the project's General tab — this is `ZITADEL_PROJECT_ID` in `.env`.
3. **Project → Roles → New.** Add exactly three role keys: `owner`, `analyst`, `viewer`
   (Display Name can match). These must match ADR-0002 exactly — the auth layer will read these
   literal strings out of the token.
4. **Project → General → enable "Assert Roles on Authentication"** (this is
   `project_role_assertion` under the hood) — without it, roles you grant a user will **not**
   appear in their token even if everything else is configured correctly.
5. **Project → Applications → New.**
   - Type: pick based on what's consuming the token. For a browser/native OIDC login test,
     choose **Native**, redirect URI `http://localhost:<some-port>/callback` (must start with
     `http://localhost`, `http://127.0.0.1`, or `http://[::1]` — anything else is accepted but
     flagged non-compliant).
   - Authentication Method: **None** (PKCE, public client) for a native/test app.
   - **Token Type: JWT**, not opaque — this is the ADR-0002-required setting and is **not** the
     default (see §7).
   - Enable **"Add user roles to the access token"** and **"...to the ID token"** — these are
     `access_token_role_assertion` / `id_token_role_assertion`. Same trap as step 4: without
     this on the *application*, roles don't appear even if the project-level assertion is on.
   - Save. Note the **Client ID**.
6. **Grant yourself (or a test user) the roles:** Project → Authorizations (or the user's
   Authorizations tab) → **New Authorization** → pick the project → select all three roles.
   Without this grant, the roles claim is simply empty, assertion settings notwithstanding.
7. For a machine-to-machine client instead of a human login, use **Users → Service Users → New**
   instead of step 5. See §7 for a hard limitation this path has.

This walkthrough was verified end-to-end via Zitadel's Management API (`/management/v1/...`)
rather than literal console clicks, since this environment has no browser available — but it's
the same operations the console UI performs, and the console's field names above (assertion
toggles, token type, role keys) match the actual API fields we drove
(`project_role_assertion`, `access_token_role_assertion`, `access_token_type`). Screenshots
would need a human with a browser to confirm pixel-for-pixel, but the underlying mechanics are
confirmed working.

---

## 4. Getting and checking a token

**Human login (recommended path to test against):** run the OIDC Authorization Code + PKCE flow
against the application from §3 step 5. If you have a browser, this is just visiting
`http://zitadel:8080/oauth/v2/authorize?client_id=...&redirect_uri=...&response_type=code&scope=openid%20profile%20urn:zitadel:iam:org:project:id:{PROJECT_ID}:aud%20urn:zitadel:iam:user:resourceowner%20urn:zitadel:iam:org:project:roles&code_challenge=...&code_challenge_method=S256`
and logging in normally; the redirect will carry `?code=...`. Exchange it:

```bash
just zitadel-decode "$(curl -s -X POST http://zitadel:8080/oauth/v2/token \
  -d grant_type=authorization_code -d code=<code> \
  -d redirect_uri=<your redirect_uri> -d client_id=<client_id> \
  --data-urlencode code_verifier=<verifier> \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')"
```

**Machine user (client_credentials):** once you have a client_id/secret from §3 step 7:

```bash
just zitadel-token <client_id> <client_secret>
```

**Checklist against ADR-0002** — confirm every one of these on the decoded access token:

| Requirement | Where to look | Confirmed working? |
|---|---|---|
| `alg: RS256`, real 3-part JWT (not opaque) | header | Yes — once Token Type is set to JWT (§3 step 5); **opaque by default**, see §7 |
| `iss` matches `ZITADEL_ISSUER` | payload | Yes |
| `aud` contains `ZITADEL_PROJECT_ID` | payload | Yes, alongside the client ID and any other apps in that project |
| `urn:zitadel:iam:user:resourceowner:id` present | payload | Yes, given the `urn:zitadel:iam:user:resourceowner` scope is requested |
| `urn:zitadel:iam:org:project:roles` present, correct role keys | payload | **Yes for human login** through a configured Application. **No for client_credentials/machine users** — see §7, this is a real gap |
| `kid` in header matches a key in JWKS | header vs. `GET /oauth/v2/keys` | Yes |
| Access token lifetime ≈ 15 minutes | `exp - iat` | Yes, **after** the fix in `compose.yaml` — Zitadel's own default is 12 hours, see §7 |

Decode any token without a browser via `just zitadel-decode <token>` (header + payload, no
signature verification — this is a local sanity tool, not what W2-04's real verification should
do).

---

## 5. What's in `compose.yaml` and why

- **`zitadel-db`** is a separate Postgres instance from the app's own `postgres` service. Its
  schema is Zitadel's to migrate; ours must never touch it and vice versa.
- **`ghcr.io/zitadel/zitadel:v3.4.15`**, pinned, not `:latest`. This is deliberately the
  pre-Login-V2 major line: one binary with the classic embedded `/ui/console` and `/ui/login`
  server-rendered flow, rather than the Traefik + separate Next.js login-UI topology Zitadel
  ships by default from v4 on. Staying on v3.x keeps this a one-container identity service.
  Upgrading to v4+ is a real decision, not a patch bump — flag it before anyone does it casually.
- **`start-from-init`** as the command: this is Zitadel's idempotent-on-existing-data bootstrap
  command. Re-running `docker compose up`/`restart` against an already-initialized volume just
  starts the server; it does not attempt to re-bootstrap the first-instance admin, and confirmed
  safe across multiple `restart` cycles.
- **`--tlsMode disabled`**: dev-only. TLS termination in front of Zitadel (or Zitadel's own TLS)
  is a production requirement this compose file does not attempt to solve.
- **Healthcheck** uses `/app/zitadel ready`, the binary's own readiness subcommand — no sleep,
  no guessing. `start_period: 60s` gives first-boot migrations room; observed actual boot time
  was well under that (~20s).
- **`ZITADEL_DEFAULTINSTANCE_OIDCSETTINGS_*`**: sets the instance-wide access/ID token lifetime
  to 15 minutes at first-boot time, per ADR-0002. All four duration fields must be supplied
  together or Zitadel errors at startup (confirmed — see §6). Refresh token lifetime was left at
  Zitadel's stock defaults (30-day idle / 90-day absolute) rather than the "12 hours" ADR-0002
  mentions in passing — that number is ambiguous (idle vs. absolute) and is a session-policy
  decision, not a compose-file default; flagging it rather than guessing.

---

## 6. First-boot failure modes we actually hit

**Machine user + PAT auto-bootstrap crash loop.** We tried adding
`ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` and `ZITADEL_FIRSTINSTANCE_PATPATH` env vars to
auto-provision a machine user + personal access token at first boot, for fully headless testing.
With an `ORG_MACHINE_PAT_EXPIRATIONDATE` set, the `03_default_instance` setup migration failed
outright:

```
level=error msg="migration failed" ... error="ID=V3-DKcYh Message=Errors.Instance.Domain.AlreadyExists ... duplicate key value violates unique constraint \"unique_constraints_pkey\" ... Key (instance_id, unique_type, unique_field)=(, instance_domain, zitadel) already exists."
level=fatal msg="setup failed, skipping cleanup"
```

This put the container into a permanent crash loop — confirmed across three consecutive
automatic restarts, recoverable only with `docker compose down -v` (full volume wipe). Root
cause not fully isolated (possibly an ordering/idempotency bug in this Zitadel version's
first-instance machine+PAT path specifically, since the human-only bootstrap path is solid). We
abandoned this approach as unnecessary scope creep for this deliverable — it is **not** in
`compose.yaml`. If W2-05's bootstrap script wants a fully headless machine user at first boot,
budget time to either debug this further or avoid `FirstInstance.Org.Machine` entirely and
create the service user via the Management API instead (which works reliably, see §3 step 7).

**`ZITADEL_DEFAULTINSTANCE_OIDCSETTINGS_*` partial config.** The docs for this setting say "if
defined but not all durations are set it will result in an error" — this is accurate. Set all
four (`ACCESSTOKENLIFETIME`, `IDTOKENLIFETIME`, `REFRESHTOKENIDLEEXPIRATION`,
`REFRESHTOKENEXPIRATION`) or none.

**No shell in the Zitadel container.** `docker compose exec zitadel sh` (or `bash`, `ls`, `cat`)
fails with "executable file not found in $PATH" — this is a minimal single-binary image
(`Entrypoint: [/app/zitadel]`), not a distro image. Use `docker cp` to pull files out, and
`/app/zitadel <subcommand>` (e.g. `ready`) for anything you'd normally shell in for.

---

## 7. ADR-0002 gaps found — flagged, not fixed

These are real findings from driving the actual API, not speculation. None of them are fixed
here — some aren't infra's to fix, and one is a structural limitation of this Zitadel version.

**1. Machine-user client_credentials tokens do not carry the roles claim — at all, in this
version, no matter how it's configured.** We created a service user, gave it
`access_token_type: JWT`, granted it all three project roles (confirmed `USER_GRANT_STATE_ACTIVE`),
turned on `project_role_assertion` at the project level, and requested the
`urn:zitadel:iam:org:project:roles` scope explicitly. The resulting JWT (verified via
`/oauth/v2/token` with `grant_type=client_credentials`) has **no** roles claim, in the access
token or `/oidc/v1/userinfo`. Root cause, confirmed by reading Zitadel's own source
(`internal/api/oidc/token_client_credentials.go`): client_credentials sessions are served by a
synthetic `clientCredentialsClient` that never goes through a stored Application object, and
`access_token_role_assertion` is an Application-only setting. There is currently no
configuration path to get roles onto a client_credentials token here.

**Why this matters for ADR-0002 §9 ("Machine access"):** the ADR states machine users "get the
same token format (JWT), the same claims structure" as human users, and that the `Principal`
type "does not need to know whether the caller is human or machine." That assumption does not
hold for the roles claim specifically, on this Zitadel version, via client_credentials. Whoever
builds machine-to-machine auth (ADR §9 says "implemented in Week 4") needs to either find a
newer Zitadel feature/config that closes this gap, or have `core/auth` treat machine principals
as roleless (or role-by-convention) rather than assuming the token will tell it. **Human login
through a properly configured Application does carry the roles claim correctly** — this is
specific to the client_credentials grant, not a general Zitadel/OIDC problem.

**2. ADR-0002 §6 says JWKS lives at `{issuer}/.well-known/jwks.json`. It does not, on this
version.** That path 404s. The real JWKS endpoint, per this instance's own discovery document
(`{issuer}/.well-known/openid-configuration` → `jwks_uri`), is `{issuer}/oauth/v2/keys`. If
W2-04's JWKS fetch/cache hardcodes the ADR's stated path instead of reading `jwks_uri` from
discovery (or just using the confirmed-working `/oauth/v2/keys`), it will fail outright. This
should be corrected in ADR-0002 or explicitly overridden in W2-04's implementation notes —
flagging here rather than editing someone else's merged ADR.

**3. Default access tokens are opaque, not JWT — confirmed, and matches Zitadel's own docs**
("service accounts get an opaque access token by default"). ADR-0002 §6 requires JWT. This is
not a bug, just a setting that must be explicitly turned on per-Application (human login) or
per-service-user (`access_token_type: ACCESS_TOKEN_TYPE_JWT`, machine users) — there's no
instance-wide default that makes this automatic. Console steps in §3 call this out; don't skip
it.

**4. Default access token lifetime is 12 hours, not 15 minutes** — fixed here via
`ZITADEL_DEFAULTINSTANCE_OIDCSETTINGS_ACCESSTOKENLIFETIME` in `compose.yaml` (§5), confirmed by
decoding a token and checking `exp - iat == 900`. Noting it here anyway because it's the kind of
default that's easy to silently miss if someone rebuilds this compose service from scratch
without reading this doc.

---

## 8. Dev-only vs. production

- `--tlsMode disabled` and `ZITADEL_EXTERNALSECURE: "false"`: fine on a laptop behind nothing;
  production needs real TLS termination.
- `ZITADEL_MASTERKEY`, `ZITADEL_ADMIN_PASSWORD`: the `.env.example` placeholders are
  intentionally obvious dev values. Generate real random secrets for anything beyond a laptop,
  and never commit them.
- Single Zitadel instance, single Postgres, no read replicas, no backups: fine for local dev,
  not a production topology.
- `ZITADEL_EXTERNALDOMAIN: zitadel` only resolves inside the Compose network plus your own
  `/etc/hosts` entry. A real deployment needs a real DNS name matching a real TLS certificate.
- The v3.x single-binary/embedded-login-UI topology (§5) is itself a dev-simplicity choice, not
  necessarily what a production Zitadel deployment should run.
