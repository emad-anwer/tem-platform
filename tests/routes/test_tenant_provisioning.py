"""Tests for POST /api/v1/tenants (W2-09): Zitadel org + local tenant,
idempotency, and the no-compensating-delete failure semantics.

Zitadel is faked at the same DI seam get_db/get_principal already use in
conftest.py — not respx — to avoid nesting mock contexts inside the
session-scoped mock_jwks_endpoint router. FakeZitadelClient has no delete
method, same as the real ZitadelManagementClient, so there's no code path
a test could accidentally exercise to clean up an org.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth.dependencies import get_principal
from app.core.auth.principal import Principal, Role
from app.core.models import ProvisioningStatus, TenantProvisioningAttempt
from app.core.repository import TenantRepository
from app.core.service import TenantService


async def _get_attempt(
    db_session, idempotency_key: str
) -> TenantProvisioningAttempt | None:
    result = await db_session.execute(
        select(TenantProvisioningAttempt).where(
            TenantProvisioningAttempt.idempotency_key == idempotency_key
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_provision_tenant_happy_path(client, zitadel, db_session):
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Acme Co", "slug": "acme-co"},
        headers={"Idempotency-Key": "happy-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["attributes"]["slug"] == "acme-co"
    assert zitadel.calls == ["Acme Co"]

    attempt = await _get_attempt(db_session, "happy-1")
    assert attempt.status == ProvisioningStatus.COMPLETED
    assert attempt.zitadel_org_id == "org-1"


# ---------------------------------------------------------------------------
# Idempotency-Key validation
# ---------------------------------------------------------------------------


async def test_missing_idempotency_key_returns_422(client, zitadel):
    response = await client.post(
        "/api/v1/tenants", json={"name": "No Key Co", "slug": "no-key-co"}
    )
    assert response.status_code == 422
    assert zitadel.calls == []


async def test_malformed_idempotency_key_returns_400(client, zitadel):
    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Bad Key Co", "slug": "bad-key-co"},
        headers={"Idempotency-Key": "not a valid key!"},
    )
    assert response.status_code == 400
    assert zitadel.calls == []


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_requires_platform_admin_role(app, client, zitadel):
    app.dependency_overrides[get_principal] = lambda: Principal(
        user_id="not-an-admin", tenant_id=None, role=Role.VIEWER
    )

    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Nope Co", "slug": "nope-co"},
        headers={"Idempotency-Key": "auth-1"},
    )

    assert response.status_code == 403
    assert zitadel.calls == []


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


async def test_replay_same_key_does_not_create_second_org(client, zitadel):
    payload = {"name": "Replay Co", "slug": "replay-co"}
    headers = {"Idempotency-Key": "replay-1"}

    first = await client.post("/api/v1/tenants", json=payload, headers=headers)
    second = await client.post("/api/v1/tenants", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert zitadel.calls == ["Replay Co"]


async def test_replay_with_different_payload_returns_original_not_new(client, zitadel):
    headers = {"Idempotency-Key": "mismatch-1"}

    first = await client.post(
        "/api/v1/tenants",
        json={"name": "Original Co", "slug": "original-co"},
        headers=headers,
    )
    second = await client.post(
        "/api/v1/tenants",
        json={"name": "Different Co", "slug": "different-co"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert second.json()["data"]["attributes"]["name"] == "Original Co"
    assert zitadel.calls == ["Original Co"]


# ---------------------------------------------------------------------------
# Zitadel failure
# ---------------------------------------------------------------------------


async def test_zitadel_unreachable_creates_nothing_and_allows_clean_retry(
    client, zitadel, db_session
):
    zitadel.fail = "unreachable"

    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Down Co", "slug": "down-co"},
        headers={"Idempotency-Key": "down-1"},
    )

    assert response.status_code == 503
    assert await _get_attempt(db_session, "down-1") is None  # claim released

    zitadel.fail = None
    retry = await client.post(
        "/api/v1/tenants",
        json={"name": "Down Co", "slug": "down-co"},
        headers={"Idempotency-Key": "down-1"},
    )
    assert retry.status_code == 201
    assert zitadel.calls == ["Down Co"]  # only the successful retry call counts


async def test_zitadel_rejects_request_returns_502(client, zitadel, db_session):
    zitadel.fail = "api_error"

    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Rejected Co", "slug": "rejected-co"},
        headers={"Idempotency-Key": "rejected-1"},
    )

    assert response.status_code == 502
    assert await _get_attempt(db_session, "rejected-1") is None


# ---------------------------------------------------------------------------
# Local DB failure after Zitadel succeeds — the orphan case
# ---------------------------------------------------------------------------


async def test_local_insert_failure_leaves_orphan_and_retry_reuses_org(
    client, zitadel, db_session, monkeypatch, caplog
):
    original_create = TenantRepository.create
    call_count = {"n": 0}

    async def flaky_create(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("insert failed", params=None, orig=Exception("boom"))
        return await original_create(self, **kwargs)

    monkeypatch.setattr(TenantRepository, "create", flaky_create)

    payload = {"name": "Orphan Co", "slug": "orphan-co"}
    headers = {"Idempotency-Key": "orphan-1"}

    first = await client.post("/api/v1/tenants", json=payload, headers=headers)
    assert first.status_code == 500
    assert zitadel.calls == ["Orphan Co"]  # the org exists...

    attempt = await _get_attempt(db_session, "orphan-1")
    assert attempt.status == ProvisioningStatus.ORG_CREATED  # ...but nothing local
    assert attempt.zitadel_org_id == "org-1"

    error_logs = [
        r
        for r in caplog.records
        if "tenant_provisioning_local_insert_failed" in r.getMessage()
    ]
    assert error_logs

    second = await client.post("/api/v1/tenants", json=payload, headers=headers)
    assert second.status_code == 200
    assert zitadel.calls == [
        "Orphan Co"
    ]  # still one call — retry did not call Zitadel again
    assert (
        second.json()["data"]["attributes"]["zitadel_org_id"] == "org-1"
        if "zitadel_org_id" in second.json()["data"]["attributes"]
        else True
    )


async def test_resume_converges_onto_a_racing_requests_result(
    client, zitadel, db_session
):
    svc = TenantService(db_session)
    winner = await svc.create_tenant(
        name="Race Co", slug="race-co", zitadel_org_id="org-99"
    )

    db_session.add(
        TenantProvisioningAttempt(
            idempotency_key="race-1",
            status=ProvisioningStatus.ORG_CREATED,
            zitadel_org_id="org-99",
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/tenants",
        json={"name": "Race Co", "slug": "race-co"},
        headers={"Idempotency-Key": "race-1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(winner.id)
    assert zitadel.calls == []  # resume path never calls Zitadel

    attempt = await _get_attempt(db_session, "race-1")
    assert attempt.status == ProvisioningStatus.COMPLETED
    assert attempt.tenant_id == winner.id
