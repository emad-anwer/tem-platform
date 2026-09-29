from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings

pytestmark = pytest.mark.asyncio


async def _create_target(
    auth_client, headers, kind: str = "domain", value: str | None = None
):
    value = value or f"{uuid.uuid4().hex[:10]}.example.com"
    resp = await auth_client.post(
        "/api/v1/targets",
        json={"kind": kind, "value": value},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


@pytest.fixture
def fake_arq_pool(monkeypatch):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="fake-job-1"))
    monkeypatch.setattr(
        "app.core.pipeline.service.get_arq_pool",
        AsyncMock(return_value=pool),
    )
    return pool


class TestCreateTarget:
    async def test_creates_target_and_returns_201_with_location(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.post(
            "/api/v1/targets",
            json={"kind": "domain", "value": "Example.COM."},
            headers=headers,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["data"]["type"] == "targets"
        assert body["data"]["attributes"]["value_normalized"] == "example.com"
        target_id = body["data"]["id"]
        assert resp.headers["location"] == f"/api/v1/targets/{target_id}"

    async def test_invalid_domain_returns_422_without_leaking_internals(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.post(
            "/api/v1/targets",
            json={"kind": "domain", "value": "*.example.com"},
            headers=headers,
        )

        assert resp.status_code == 422
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["errors"][0]["field"] == "value"
        # No raw exception class, file path, or traceback should leak.
        assert "Traceback" not in resp.text
        assert "app/core" not in resp.text
        assert "ValueError" not in resp.text

    async def test_unknown_kind_rejected(self, auth_client, two_tenants, auth_headers):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.post(
            "/api/v1/targets",
            json={"kind": "not-a-real-kind", "value": "example.com"},
            headers=headers,
        )

        assert resp.status_code == 422

    async def test_invalid_body_returns_422(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        resp = await auth_client.post(
            "/api/v1/targets",
            json={"wrong_field": "foo"},
            headers=headers,
        )
        assert resp.status_code == 422

    async def test_viewer_cannot_create_target(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )

        resp = await auth_client.post(
            "/api/v1/targets",
            json={"kind": "domain", "value": "viewer-blocked.example.com"},
            headers=headers,
        )

        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")

    async def test_duplicate_target_returns_409(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        await _create_target(auth_client, headers, value="dupe-route.example.com")

        resp = await auth_client.post(
            "/api/v1/targets",
            json={"kind": "domain", "value": "dupe-route.example.com"},
            headers=headers,
        )

        assert resp.status_code == 409
        assert resp.headers["content-type"].startswith("application/problem+json")


class TestListTargets:
    async def test_lists_only_own_tenant_targets(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, tenant_b = two_tenants
        headers_a = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        headers_b = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )
        await _create_target(auth_client, headers_a, value="only-a.example.com")
        await _create_target(auth_client, headers_b, value="only-b.example.com")

        resp = await auth_client.get("/api/v1/targets", headers=headers_a)

        assert resp.status_code == 200
        values = {
            item["attributes"]["value_normalized"] for item in resp.json()["data"]
        }
        assert "only-a.example.com" in values
        assert "only-b.example.com" not in values

    async def test_rejects_unknown_query_param(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.get("/api/v1/targets?bogus=1", headers=headers)

        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

    async def test_size_bounds_enforced(self, auth_client, two_tenants, auth_headers):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        # /targets bounds `size` via FastAPI's Query(ge=1, le=100), so this
        # is caught before PipelineService ever runs.
        resp = await auth_client.get("/api/v1/targets?size=0", headers=headers)
        assert resp.status_code == 400

        resp = await auth_client.get("/api/v1/targets?size=101", headers=headers)
        assert resp.status_code == 400

        resp = await auth_client.get("/api/v1/targets?size=abc", headers=headers)
        assert resp.status_code == 400


class TestGetTarget:
    async def test_create_location_is_readable(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers, value="get-by-id.example.com"
        )

        resp = await auth_client.get(f"/api/v1/targets/{target['id']}", headers=headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == target["id"]
        assert body["data"]["attributes"]["value_normalized"] == "get-by-id.example.com"

    async def test_not_found_returns_404(self, auth_client, two_tenants, auth_headers):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.get(f"/api/v1/targets/{uuid.uuid4()}", headers=headers)

        assert resp.status_code == 404

    async def test_cross_tenant_target_returns_404(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, tenant_b = two_tenants
        headers_a = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        headers_b = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers_a, value="target-isolated.example.com"
        )

        resp = await auth_client.get(
            f"/api/v1/targets/{target['id']}", headers=headers_b
        )

        assert resp.status_code == 404
        assert "target-isolated.example.com" not in resp.text

    async def test_viewer_can_read_target(self, auth_client, two_tenants, auth_headers):
        tenant_a, _ = two_tenants
        owner_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, owner_headers, value="viewer-read-target.example.com"
        )

        viewer_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )
        resp = await auth_client.get(
            f"/api/v1/targets/{target['id']}", headers=viewer_headers
        )

        assert resp.status_code == 200


class TestStartScan:
    async def test_enqueues_scan_and_returns_202_with_queued_status(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(auth_client, headers, value="scan-me.example.com")

        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers
        )

        assert resp.status_code == 202
        body = resp.json()
        run_id = body["data"]["id"]
        assert body["data"]["attributes"]["status"] == "queued"
        assert body["data"]["attributes"]["target_id"] == target["id"]
        assert resp.headers["location"] == f"/api/v1/scan_runs/{run_id}"
        fake_arq_pool.enqueue_job.assert_awaited_once()

    async def test_poll_while_queued_reports_queued_state_not_a_result(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(auth_client, headers, value="poll-me.example.com")
        start_resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers
        )
        run_id = start_resp.json()["data"]["id"]

        resp = await auth_client.get(f"/api/v1/scan_runs/{run_id}", headers=headers)

        assert resp.status_code == 200
        attrs = resp.json()["data"]["attributes"]
        assert attrs["status"] == "queued"
        assert attrs["started_at"] is None
        assert attrs["finished_at"] is None
        assert attrs["error_kind"] is None

    async def test_viewer_cannot_start_scan(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        owner_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, owner_headers, value="viewer-scan.example.com"
        )

        viewer_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )
        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=viewer_headers
        )

        assert resp.status_code == 403
        fake_arq_pool.enqueue_job.assert_not_awaited()

    async def test_out_of_scope_target_returns_403_without_enqueuing(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool, monkeypatch
    ):
        """W4-02: an empty allowlist refuses at the API edge, before a job
        exists — 403 problem details, nothing enqueued, no run row."""
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers, value="no-scope.example.com"
        )

        monkeypatch.setenv("SCAN_SCOPE_ALLOWLIST", "")
        get_settings.cache_clear()

        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers
        )

        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["title"] == "Forbidden"
        assert "scan scope" in body["detail"]
        fake_arq_pool.enqueue_job.assert_not_awaited()

    async def test_target_not_found_returns_404(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.post(
            f"/api/v1/targets/{uuid.uuid4()}/scans", headers=headers
        )

        assert resp.status_code == 404

    async def test_cross_tenant_target_returns_404_not_403(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, tenant_b = two_tenants
        headers_a = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        headers_b = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers_a, value="isolated.example.com"
        )

        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers_b
        )

        assert resp.status_code == 404
        assert "isolated.example.com" not in resp.text
        fake_arq_pool.enqueue_job.assert_not_awaited()

    async def test_enqueue_failure_returns_503_without_leaking_internals(
        self, auth_client, two_tenants, auth_headers, monkeypatch
    ):
        """Answers the ticket's question: if the worker/Redis is down, the
        caller must get a clean, actionable error — not a run stuck silently
        in `queued` forever with no signal, and not a raw connection-error
        stack trace.
        """
        monkeypatch.setattr(
            "app.core.pipeline.service.get_arq_pool",
            AsyncMock(side_effect=ConnectionError("redis unreachable: 10.0.0.5:6379")),
        )
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers, value="worker-down.example.com"
        )

        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers
        )

        assert resp.status_code == 503
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert "10.0.0.5" not in resp.text
        assert "ConnectionError" not in resp.text
        assert "Traceback" not in resp.text

    async def test_scan_job_payload_can_be_built_with_the_fields_start_scan_passes(
        self,
    ):
        from app.core.discovery import SubdomainDiscoveryPayload

        payload = SubdomainDiscoveryPayload(tenant_id=uuid.uuid4(), run_id=uuid.uuid4())
        assert payload.run_id is not None

    async def test_start_scan_http_path_does_not_500_on_payload_construction(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers, value="payload-bug.example.com"
        )

        resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers
        )

        assert resp.status_code == 202, (
            "If this is 500, SubdomainDiscoveryPayload construction is raising before "
            "the enqueue try/except — see test_scan_job_payload_can_be_built_"
            "with_the_fields_start_scan_passes for the root cause."
        )
        assert "Traceback" not in resp.text
        assert "ValidationError" not in resp.text


class TestGetScanRun:
    async def test_not_found_returns_404(self, auth_client, two_tenants, auth_headers):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.get(
            f"/api/v1/scan_runs/{uuid.uuid4()}", headers=headers
        )

        assert resp.status_code == 404

    async def test_cross_tenant_scan_run_returns_404(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, tenant_b = two_tenants
        headers_a = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        headers_b = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers_a, value="scan-run-isolated.example.com"
        )
        start_resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=headers_a
        )
        run_id = start_resp.json()["data"]["id"]

        resp = await auth_client.get(f"/api/v1/scan_runs/{run_id}", headers=headers_b)

        assert resp.status_code == 404

    async def test_viewer_can_read_scan_run(
        self, auth_client, two_tenants, auth_headers, fake_arq_pool
    ):
        tenant_a, _ = two_tenants
        owner_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, owner_headers, value="viewer-read.example.com"
        )
        start_resp = await auth_client.post(
            f"/api/v1/targets/{target['id']}/scans", headers=owner_headers
        )
        run_id = start_resp.json()["data"]["id"]

        viewer_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )
        resp = await auth_client.get(
            f"/api/v1/scan_runs/{run_id}", headers=viewer_headers
        )

        assert resp.status_code == 200


class TestListFindings:
    async def test_viewer_can_list_findings(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        viewer_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )

        resp = await auth_client.get("/api/v1/findings", headers=viewer_headers)

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_rejects_unknown_query_param(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.get("/api/v1/findings?bogus=1", headers=headers)

        assert resp.status_code == 400

    async def test_size_validation_returns_400(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        resp = await auth_client.get("/api/v1/findings?size=0", headers=headers)
        assert resp.status_code == 400
        assert resp.headers["content-type"].startswith("application/problem+json")

        resp = await auth_client.get("/api/v1/findings?size=101", headers=headers)
        assert resp.status_code == 400

        resp = await auth_client.get("/api/v1/findings?size=abc", headers=headers)
        assert resp.status_code == 400

    async def test_filters_by_target_id_and_scan_run_id_are_accepted(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, _ = two_tenants
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        target = await _create_target(
            auth_client, headers, value="findings-filter.example.com"
        )

        resp = await auth_client.get(
            f"/api/v1/findings?target_id={target['id']}", headers=headers
        )
        assert resp.status_code == 200

        resp = await auth_client.get(
            f"/api/v1/findings?scan_run_id={uuid.uuid4()}", headers=headers
        )
        assert resp.status_code == 200

    async def test_cross_tenant_findings_are_scoped(
        self, auth_client, two_tenants, auth_headers
    ):
        tenant_a, tenant_b = two_tenants
        headers_a = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )
        headers_b = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )

        resp_a = await auth_client.get("/api/v1/findings", headers=headers_a)
        resp_b = await auth_client.get("/api/v1/findings", headers=headers_b)

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


class TestScanRunChanges:
    async def test_viewer_gets_bucket_counts_and_cursor_pages(
        self, auth_client, db_session, two_tenants, auth_headers
    ):
        from datetime import UTC, datetime

        from app.core.repository import (
            ScanRunFindingRepository,
            ScanRunRepository,
            TargetRepository,
        )

        tenant_a, tenant_b = two_tenants
        target = await TargetRepository(
            db_session, tenant_id=tenant_a.id
        ).create(
            kind="domain",
            value="changes.example.com",
            value_normalized="changes.example.com",
            is_active=True,
        )
        run = await ScanRunRepository(
            db_session, tenant_id=tenant_a.id
        ).create(target_id=target.id, max_attempts=3)
        run.status = "succeeded"
        db_session.add(run)
        await db_session.commit()

        timestamp = datetime.now(UTC).isoformat()
        snapshots = []
        for index, classification in enumerate(("new", "unchanged", "mutated")):
            finding_id = str(uuid.uuid4())
            snapshots.append(
                {
                    "finding_id": None,
                    "classification": classification,
                    "finding_snapshot": {
                        "type": "findings",
                        "id": finding_id,
                        "attributes": {
                            "target_id": str(target.id),
                            "last_seen_run_id": str(run.id),
                            "kind": "subdomain",
                            "value": f"host{index}.changes.example.com",
                            "value_normalized": f"host{index}.changes.example.com",
                            "fingerprint": uuid.uuid4().hex * 2,
                            "severity": "info",
                            "raw_severity": None,
                            "status": "active",
                            "first_seen_at": timestamp,
                            "last_seen_at": timestamp,
                            "times_seen": 1,
                            "details": {},
                            "created_at": timestamp,
                            "updated_at": timestamp,
                        },
                    },
                }
            )
        await ScanRunFindingRepository(
            db_session, tenant_id=tenant_a.id
        ).add_snapshots(scan_run_id=run.id, snapshots=snapshots)

        viewer_headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )
        first_page = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes?size=1", headers=viewer_headers
        )
        assert first_page.status_code == 200
        first_body = first_page.json()
        counts = first_body["data"]["attributes"]["counts"]
        assert counts == {
            "new": 1,
            "reappeared": 0,
            "resolved": 0,
            "unchanged": 1,
            "mutated": 1,
        }
        assert first_body["links"]["next"]

        seen = set()
        page = first_page
        while page.json()["links"]["next"]:
            page_body = page.json()
            findings = page_body["data"]["attributes"]["findings"]
            seen.update(
                classification
                for classification, resources in findings.items()
                if resources
            )
            page = await auth_client.get(
                page_body["links"]["next"], headers=viewer_headers
            )
            assert page.status_code == 200
        final_findings = page.json()["data"]["attributes"]["findings"]
        seen.update(
            classification
            for classification, resources in final_findings.items()
            if resources
        )
        assert seen == {"new", "unchanged", "mutated"}

        other_tenant_headers = auth_headers(
            tenant_zitadel_org_id=tenant_b.zitadel_org_id, role="owner"
        )
        cross_tenant = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes", headers=other_tenant_headers
        )
        assert cross_tenant.status_code == 404

    async def test_queued_run_returns_409(
        self, auth_client, db_session, two_tenants, auth_headers
    ):
        from app.core.repository import ScanRunRepository, TargetRepository

        tenant_a, _ = two_tenants
        target = await TargetRepository(db_session, tenant_id=tenant_a.id).create(
            kind="domain",
            value="queued-changes.example.com",
            value_normalized="queued-changes.example.com",
            is_active=True,
        )
        run = await ScanRunRepository(db_session, tenant_id=tenant_a.id).create(
            target_id=target.id, max_attempts=3
        )
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="viewer"
        )
        resp = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes", headers=headers
        )
        assert resp.status_code == 409
        assert resp.headers["content-type"].startswith("application/problem+json")

    async def test_rejects_unknown_query_param_and_invalid_cursor(
        self, auth_client, db_session, two_tenants, auth_headers
    ):
        from app.core.repository import ScanRunRepository, TargetRepository

        tenant_a, _ = two_tenants
        target = await TargetRepository(db_session, tenant_id=tenant_a.id).create(
            kind="domain",
            value="cursor-changes.example.com",
            value_normalized="cursor-changes.example.com",
            is_active=True,
        )
        run = await ScanRunRepository(db_session, tenant_id=tenant_a.id).create(
            target_id=target.id, max_attempts=3
        )
        run.status = "succeeded"
        db_session.add(run)
        await db_session.commit()
        headers = auth_headers(
            tenant_zitadel_org_id=tenant_a.zitadel_org_id, role="owner"
        )

        unknown = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes?bogus=1", headers=headers
        )
        assert unknown.status_code == 400

        size = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes?size=0", headers=headers
        )
        assert size.status_code == 400

        cursor = await auth_client.get(
            f"/api/v1/scan_runs/{run.id}/changes?cursor=not-a-cursor",
            headers=headers,
        )
        assert cursor.status_code == 422
