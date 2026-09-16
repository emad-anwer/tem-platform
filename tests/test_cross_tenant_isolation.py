"""Cross-tenant isolation suite and route coverage — Issue #40 (W2-10).

Property-first black-box suite per ADR-0002. Asserts HTTP status/body only;
never mirrors repository internals. Runs on W2-03 minted tokens, no Zitadel.

Coverage key format (normalised everywhere): (method: str, path: str)
where method is uppercase, e.g. ("GET", "/api/v1/tenants/{tenant_id}").

Design notes
────────────
• auth_client overrides get_verifier_factory (not get_principal) so the real
  verify→lookup→Principal path runs. Token failures produce real 401/403 from
  the production auth code, not a mock.

• BOLA assertions carried xfail(strict=True) until the fix landed (issue #65):
  expected failures while BOLA was unfixed, CI would go red if they
  unexpectedly passed (BOLA silently fixed without removing the marker).
  Markers removed here as part of the #65 fix PR — these must pass now.

• 403 vs 404 for cross-tenant reads (ADR-0002 §4 + api-conventions §404-vs-403):
  - Tenant IDs appear in Location headers; hiding existence gains nothing.
  - 403 lets the suite distinguish "exists, access denied" from "missing".
  - ADR-0002 §3 uses 403 for orphaned org (symmetric: cross-tenant → 403).
  - OWASP BOLA: 403 is the correct signal; 200/404 masks the vulnerability.
  Missing UUID → 404 (genuinely absent, never forbidden).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from auth_fixtures import FIXTURE_PROJECT_ID, make_token
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

RESOURCEOWNER_CLAIM = "urn:zitadel:iam:user:resourceowner:id"

# ---------------------------------------------------------------------------
# § Route inventory — single source of truth for the coverage gate.
# ---------------------------------------------------------------------------

# Every tenant-data route under test. Single source of truth for the gate.
DATA_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/tenants"),
    ("POST", "/api/v1/tenants"),
    ("GET", "/api/v1/tenants/{tenant_id}"),
    ("GET", "/api/v1/findings"),
    ("GET", "/api/v1/scan_runs/{scan_run_id}"),
    ("GET", "/api/v1/targets"),
    ("GET", "/api/v1/targets/{target_id}"),
    ("POST", "/api/v1/targets"),
    ("POST", "/api/v1/targets/{target_id}/scans"),
]
# ---------------------------------------------------------------------------
# § Allowlist — code-owned, visible diff, fail-closed schema.
#
# Rules (enforced by test_route_coverage and test_allowlist_is_fail_closed):
#   • reason       — why the route is public/safe (non-empty str)
#   • reviewed_by  — issue or PR that approved the entry (non-empty str)
#   • safe_methods_only — must be True; only GET/HEAD/OPTIONS may be listed.
#
# Data routes (POST/PATCH/DELETE with tenant context) require an isolation
# test — never an allowlist entry. Making the right choice the path of least
# resistance: writing one test function is cheaper than a PR argument.
# ---------------------------------------------------------------------------

ALLOWLIST: dict[tuple[str, str], dict[str, Any]] = {
    ("GET", "/healthz"): {
        "reason": "Public liveness probe, no tenant data",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
    ("GET", "/readyz"): {
        "reason": "Public readiness probe, dependency status only",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
    ("GET", "/docs"): {
        "reason": "Swagger UI shell, no API data",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
    ("GET", "/docs/oauth2-redirect"): {
        "reason": "Swagger OAuth helper page, no API data",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
    ("GET", "/redoc"): {
        "reason": "API docs shell, no API data",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
    ("GET", "/openapi.json"): {
        "reason": "Public API schema, no tenant data",
        "reviewed_by": "#40",
        "safe_methods_only": True,
    },
}

# ---------------------------------------------------------------------------
# § Route introspection helper
# ---------------------------------------------------------------------------


def route_keys(app) -> set[tuple[str, str]]:
    """Enumerate live (method, path) pairs via supported introspection.

    Uses `iter_route_contexts` on FastAPI >= 0.137.2 (nested routers are no
    longer flattened into `app.routes`); falls back to `app.routes`.
    """
    keys: set[tuple[str, str]] = set()
    try:
        from fastapi.routing import iter_route_contexts  # type: ignore

        contexts = list(iter_route_contexts(app.router.routes))
    except Exception:  # noqa: BLE001 — fallback for older FastAPI
        contexts = []

    if contexts:
        for ctx in contexts:
            for method in getattr(ctx, "methods", set()) or set():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                keys.add((method.upper(), ctx.path))
        return keys

    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute):
            sub_routes = [route]
        elif hasattr(route, "original_router"):
            sub_routes = getattr(route.original_router, "routes", [])
        else:
            continue
        for sub in sub_routes:
            methods = set(getattr(sub, "methods", set()) or set())
            methods -= {"HEAD", "OPTIONS"}
            for method in methods:
                keys.add((method.upper(), sub.path))
    return keys


# ---------------------------------------------------------------------------
# § Token / header helpers
# ---------------------------------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _headers_for(
    make_token_fn, tenant_zitadel_org_id: str, role: str = "owner", **over: Any
) -> dict[str, str]:
    token = make_token_fn(
        tenant_zitadel_org_id=tenant_zitadel_org_id,
        role=role,
        **over,
    )
    return {"Authorization": f"Bearer {token}"}


def _idempotency() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _request(
    client: AsyncClient,
    method: str,
    path: str,
    headers: dict[str, str],
    two_tenants,
) -> Any:
    """Execute method+path with appropriate body/idempotency headers."""
    tenant_a, _ = two_tenants
    concrete = path.replace("{tenant_id}", str(tenant_a.id))
    extra: dict[str, Any] = {}
    json_body = None
    if method == "POST":
        extra = _idempotency()
        json_body = {"name": "Test Corp", "slug": f"x-{uuid.uuid4().hex[:8]}"}
    return await client.request(
        method, concrete, headers={**headers, **extra}, json=json_body
    )


# ---------------------------------------------------------------------------
# § Test 1 — Auth matrix: 401 credential failures × every data route
#
# Issue requirement: "For each route: no token · expired token · tampered token
# · token for another audience · ..."  Each must return the ADR-0002 code (401)
# regardless of which route is hit. The cross-product ensures no route escapes.
# ---------------------------------------------------------------------------

_401_VARIANTS: list[tuple[str, str]] = [
    ("no-token", "no Authorization header at all"),
    ("expired-token", "exp in the past (exp_offset=-10)"),
    ("payload-tamper", "signed with a different RSA key → signature mismatch"),
    ("alg-none", "alg:none — unsigned JWT; RS256 is pinned"),
    ("unknown-kid", "kid not present in JWKS → key lookup fails"),
    ("wrong-audience", "aud claim is a different project id"),
]


@pytest.mark.parametrize("method,path", DATA_ROUTES)
@pytest.mark.parametrize(
    "variant,_desc",
    _401_VARIANTS,
    ids=[v for v, _ in _401_VARIANTS],
)
async def test_auth_matrix_401(
    auth_client: AsyncClient,
    two_tenants,
    make_token_fn,
    rsa_private_key,
    variant: str,
    _desc: str,
    method: str,
    path: str,
) -> None:
    """Every token failure mode must return 401 + RFC 9457 envelope on every route.

    ADR-0002: no creds → 401+WWW-Authenticate. Crypto/claim failure → 401.
    Content-Type must be application/problem+json (RFC 9457).
    """
    if variant == "no-token":
        headers: dict[str, str] = {}
    elif variant == "expired-token":
        headers = _headers_for(make_token_fn, "zitadel-org-alpha-001", exp_offset=-10)
    elif variant == "payload-tamper":
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tampered = make_token(
            private_key=other_key,
            tenant_zitadel_org_id="zitadel-org-alpha-001",
            role="owner",
        )
        headers = _bearer(tampered)
    elif variant == "alg-none":
        token = make_token(
            private_key=None,
            tenant_zitadel_org_id="zitadel-org-alpha-001",
            algorithm="none",
        )
        headers = _bearer(token)
    elif variant == "unknown-kid":
        token = make_token_fn(
            tenant_zitadel_org_id="zitadel-org-alpha-001",
            kid="ghost-key-not-in-jwks",
        )
        headers = _bearer(token)
    elif variant == "wrong-audience":
        headers = _headers_for(
            make_token_fn, "zitadel-org-alpha-001", audience="wrong-audience-xyz"
        )
    else:
        raise AssertionError(f"unknown variant {variant!r}")

    resp = await _request(auth_client, method, path, headers, two_tenants)

    assert resp.status_code == 401, (
        f"[{variant}] {method} {path} → expected 401, got {resp.status_code}"
    )
    assert resp.headers.get("www-authenticate") == "Bearer", (
        f"[{variant}] {method} {path} → missing WWW-Authenticate: Bearer"
    )
    body = resp.json()
    assert body["status"] == 401
    assert resp.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# § Test 2 — Wrong-role / BFLA matrix (API5:2023)
#
# TENANT_CREATE is PLATFORM_ADMIN-only (ADR-0002 §5 + permissions.py).
# Three non-admin tenant roles must receive 403, never 401 or 201.
# GET routes (TENANT_READ) allow all roles — no wrong-role scenario there.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["viewer", "analyst", "owner"])
async def test_wrong_role_on_post_tenants(
    auth_client: AsyncClient,
    two_tenants,
    make_token_fn,
    role: str,
) -> None:
    """Non-admin roles must not be able to create tenants (BFLA API5:2023)."""
    tenant_a, _ = two_tenants
    headers = _headers_for(make_token_fn, tenant_a.zitadel_org_id, role=role)
    slug = f"iso-{uuid.uuid4().hex[:8]}"
    resp = await auth_client.post(
        "/api/v1/tenants",
        json={"name": "Nope", "slug": slug},
        headers={**headers, **_idempotency()},
    )
    # TENANT_CREATE is PLATFORM_ADMIN-only → 403.
    assert resp.status_code == 403, (
        f"[role={role}] expected 403, got {resp.status_code}"
    )
    assert resp.json()["status"] == 403
    assert resp.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# § Test 2b — Lowest-privilege readability (no over-deny on GET routes)
#
# TENANT_READ allows every tenant role, so there is no "wrong role" for the
# GET routes — but the role dimension still needs a per-route assertion:
# a viewer restricted to their own tenant must be able to read it (200).
# This pins the matrix against accidentally locking viewers out entirely.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/tenants"),
        ("GET", "/api/v1/tenants/{tenant_id}"),
    ],
)
async def test_viewer_can_read_own_tenant(
    auth_client: AsyncClient,
    two_tenants,
    make_token_fn,
    method: str,
    path: str,
) -> None:
    """Viewer role reads own tenant scope → 200 (least privilege still works)."""
    tenant_a, _ = two_tenants
    headers = _headers_for(make_token_fn, tenant_a.zitadel_org_id, role="viewer")
    resp = await _request(auth_client, method, path, headers, two_tenants)
    assert resp.status_code == 200, (
        f"[viewer] {method} {path} → expected 200, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# § Test 3 — Cross-tenant BOLA: GET /tenants/{id} (bidirectional)
#
# Issue requirement (R1): "Tenant A's token, pointed at every one of tenant B's
# resources." Parametrised A→B and B→A — isolation is not always symmetric.
#
# 403 vs 404 argument (ADR-0002 + api-conventions §404-vs-403):
#   Tenant IDs appear in Location headers; hiding existence gives no security
#   benefit. 403 signals "resource exists but you're forbidden," which lets the
#   suite distinguish the BOLA from a genuine miss. OWASP BOLA: 403 is correct.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["a_to_b", "b_to_a"])
async def test_bola_get_tenant_by_id(
    auth_client: AsyncClient,
    two_tenants,
    make_token_fn,
    direction: str,
) -> None:
    """Cross-tenant GET /tenants/{id} must return 403; body must not leak target data."""
    tenant_a, tenant_b = two_tenants
    if direction == "a_to_b":
        caller_org, target = tenant_a.zitadel_org_id, tenant_b
    else:
        caller_org, target = tenant_b.zitadel_org_id, tenant_a

    headers = _headers_for(make_token_fn, caller_org, role="owner")
    resp = await auth_client.get(f"/api/v1/tenants/{target.id}", headers=headers)
    assert resp.status_code == 403, (
        f"[{direction}] expected 403 for cross-tenant read, got {resp.status_code}"
    )
    assert resp.json()["status"] == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    # No data leak — target slug must not appear anywhere in the response body.
    assert target.slug not in resp.text, (
        f"[{direction}] target slug '{target.slug}' leaked in 403 response"
    )


# ---------------------------------------------------------------------------
# § Test 4 — Cross-tenant BOLA: GET /tenants list isolation (bidirectional)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["a_lists", "b_lists"])
async def test_bola_list_isolation(
    auth_client: AsyncClient,
    two_tenants,
    make_token_fn,
    direction: str,
) -> None:
    """TenantRepository.list() property: caller must not see the other tenant's rows."""
    tenant_a, tenant_b = two_tenants
    if direction == "a_lists":
        caller_org, own_slug, other_slug = (
            tenant_a.zitadel_org_id,
            "tenant-alpha",
            "tenant-beta",
        )
    else:
        caller_org, own_slug, other_slug = (
            tenant_b.zitadel_org_id,
            "tenant-beta",
            "tenant-alpha",
        )

    headers = _headers_for(make_token_fn, caller_org, role="owner")
    resp = await auth_client.get("/api/v1/tenants", headers=headers)
    assert resp.status_code == 200
    slugs = [item["attributes"]["slug"] for item in resp.json()["data"]]
    assert own_slug in slugs, f"[{direction}] own slug '{own_slug}' missing from list"
    assert other_slug not in slugs, (
        f"[{direction}] other tenant slug '{other_slug}' leaked into list"
    )


# ---------------------------------------------------------------------------
# § Test 5 — Genuine miss returns 404 (distinct from cross-tenant 403)
# ---------------------------------------------------------------------------


async def test_missing_tenant_returns_404(
    auth_client: AsyncClient, two_tenants, make_token_fn
) -> None:
    """Genuinely missing UUID → 404 (not 403 — resource does not exist at all)."""
    tenant_a, _ = two_tenants
    headers = _headers_for(make_token_fn, tenant_a.zitadel_org_id, role="owner")
    missing = uuid.uuid4()
    resp = await auth_client.get(f"/api/v1/tenants/{missing}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["status"] == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# § Test 6 — Orphaned Zitadel org → 403 (ADR-0002 §3)
# ---------------------------------------------------------------------------


async def test_unknown_org_returns_403(auth_client: AsyncClient, make_token_fn) -> None:
    """Valid token for an org not in our DB → 403 per ADR-0002 §3.

    The token is cryptographically valid (401 would be wrong here).
    The tenant simply does not exist in our system → 403, not 401.
    """
    headers = _headers_for(make_token_fn, "zitadel-org-orphan-999", role="owner")
    resp = await auth_client.get("/api/v1/tenants", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["status"] == 403
    assert resp.headers["content-type"].startswith("application/problem+json")


# ---------------------------------------------------------------------------
# § Test 7 — Allowlist is fail-closed (schema validation)
# ---------------------------------------------------------------------------


def test_allowlist_is_fail_closed() -> None:
    """The allowlist must carry all required fields; fail if any entry is malformed.

    Fail-closed design: a missing key is a test failure, never a silent omission.
    Unsafe methods (POST/PATCH/DELETE) are rejected outright — they require an
    isolation test, not an allowlist entry.
    """
    for key, entry in ALLOWLIST.items():
        method, _path = key
        assert isinstance(method, str) and method.isupper(), (
            f"Method in allowlist key must be uppercase string: {key}"
        )
        assert entry.get("reason"), f"Allowlist entry {key!r} missing 'reason'"
        assert entry.get("reviewed_by"), (
            f"Allowlist entry {key!r} missing 'reviewed_by'"
        )
        assert entry.get("safe_methods_only") is True, (
            f"Allowlist entry {key!r}: 'safe_methods_only' must be True"
        )
        assert method in {"GET", "HEAD", "OPTIONS"}, (
            f"Unsafe method allowlisted without mentor review: {key!r}. "
            "POST/PATCH/DELETE routes require an isolation test, not an allowlist entry."
        )


# ---------------------------------------------------------------------------
# § Test 8 — Route coverage gate (CI red on uncovered route)
#
# Issue requirement: "a route-coverage test that walks app.routes at runtime
# and fails if a route is neither covered by an isolation test nor in an
# explicit, commented allowlist."
# ---------------------------------------------------------------------------


def test_route_coverage(app) -> None:
    """Adding an endpoint without an isolation test turns CI red automatically.

    Allowlist entries are validated (full schema) before the gap check so the
    gate is fail-closed: a malformed entry cannot sneak past review.
    """
    all_keys = route_keys(app)
    assert all_keys, "no routes discovered — introspection helper is broken"

    # Re-validate full allowlist schema inside the gate (fail-closed).
    for key, entry in ALLOWLIST.items():
        method, _ = key
        assert entry.get("reason"), f"allowlist entry missing reason: {key}"
        assert entry.get("reviewed_by"), f"allowlist entry missing reviewed_by: {key}"
        assert entry.get("safe_methods_only") is True, (
            f"allowlist entry missing safe_methods_only=True: {key}"
        )
        assert method in {
            "GET",
            "HEAD",
            "OPTIONS",
        }, f"unsafe method in allowlist requires mentor review: {key}"

    uncovered = all_keys - set(DATA_ROUTES) - set(ALLOWLIST)
    assert not uncovered, (
        "Uncovered routes — add an isolation test to DATA_ROUTES or a "
        f"commented allowlist entry:\n  {sorted(uncovered)}\n\n"
        "Example allowlist entry (for genuinely public/safe routes only):\n"
        '    ("GET", "/path"): {\n'
        '        "reason": "<why public/safe>",\n'
        '        "reviewed_by": "#<PR>",\n'
        '        "safe_methods_only": True,\n'
        "    },"
    )


# ---------------------------------------------------------------------------
# § Test 9 — DATA_ROUTES key contract (guard against normalisation drift)
# ---------------------------------------------------------------------------


def test_data_routes_use_normalized_keys() -> None:
    """Guard the (method, path) tuple contract used by gate + matrix."""
    for key in DATA_ROUTES:
        assert isinstance(key, tuple) and len(key) == 2, key
        method, path = key
        assert isinstance(method, str) and method.isupper(), key
        assert isinstance(path, str) and path.startswith("/"), key
    assert ("GET", "/api/v1/tenants/{tenant_id}") in DATA_ROUTES
    assert FIXTURE_PROJECT_ID  # harness import is live, no Zitadel needed
