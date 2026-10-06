from __future__ import annotations

import pytest

from app.core.auth.context import set_current_principal
from app.core.auth.job_context import JOB_REGISTRY
from app.core.auth.principal import Principal, Role
from app.core.fingerprint import FindingKind
from app.core.jobs.scan import ScanPayload, run_scheduled_scan
from app.core.jobs.states import ScanRunStatus
from app.core.repository import (
    FindingRepository,
    ScanRunFindingRepository,
    ScanRunRepository,
    TargetRepository,
)
from app.modules.asm.scanner import port_findings
from app.modules.asm.scanner.http_prober import HTTPService
from app.modules.asm.scanner.port_scanner import PortResult, PortScanReport, PortState
from app.modules.asm.scanner.tls_certificate import TLSCertificateObservation


class StaticSource:
    def __init__(self, name: str, items: set[str] | None = None) -> None:
        self.name = name
        self.items = items or set()

    async def collect(self, domain: str):
        from app.core.discovery import SourceResult

        return SourceResult(self.items)


class FailedSource:
    name = "crtsh"

    async def collect(self, domain: str):
        raise RuntimeError("simulated source failure")


def _report(host: str, results: list[PortResult]) -> PortScanReport:
    opened = sum(result.state is PortState.OPEN for result in results)
    return PortScanReport(
        host=host,
        addresses=(),
        results=tuple(results),
        concurrency=5,
        connect_timeout_seconds=0.5,
        duration_seconds=0.01,
        max_in_flight=1,
        sockets_opened=opened,
        sockets_closed=opened,
    )


def _http_service(host: str) -> HTTPService:
    return HTTPService(
        scheme="http",
        host=host,
        port=80,
        status_code=200,
        final_url=f"http://{host}:80/",
        title="Lab service",
        headers={"Server": "nginx/1.25.4"},
        cookie_names=(),
        technologies=(),
        body_truncated=False,
        redirects_followed=0,
    )


def _certificate() -> TLSCertificateObservation:
    return TLSCertificateObservation(
        details={
            "subject_common_name": "target4.lab.local",
            "issuer": "CN=target4.lab.local",
            "not_valid_before_utc": "2026-01-01T00:00:00+00:00",
            "not_valid_after_utc": "2036-01-01T00:00:00+00:00",
            "sha256_fingerprint": "a" * 64,
            "signature_algorithm": "1.2.840.113549.1.1.11",
            "sans": [
                {"type": "DNS", "value": "target4.lab.local"},
                {"type": "DNS", "value": "sub1.target4.lab.local"},
                {"type": "DNS", "value": "api.target4.lab.local"},
                {"type": "DNS", "value": "admin.internal.tem.local"},
                {"type": "IP", "value": "127.0.0.1"},
            ],
        },
        dns_names=(
            "target4.lab.local",
            "sub1.target4.lab.local",
            "api.target4.lab.local",
            "admin.internal.tem.local",
        ),
    )


async def _create_target_and_run(
    db_session, tenant, *, kind="domain", value="target4.lab.local"
):
    set_current_principal(
        Principal(user_id="scan-test", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session, tenant_id=tenant.id).create(
        kind=kind, value=value, value_normalized=value, is_active=True
    )
    run = await ScanRunRepository(db_session, tenant_id=tenant.id).create(
        target_id=target.id, max_attempts=3
    )
    return target, run


@pytest.mark.asyncio
async def test_one_run_persists_all_four_kinds_and_rechecks_discovered_hosts(
    db_session, two_tenants, monkeypatch
):
    tenant, _ = two_tenants
    target, run = await _create_target_and_run(db_session, tenant)
    checked_hosts: list[str] = []

    async def allow_scoped_host(host: str, **_kwargs):
        checked_hosts.append(host)

    async def fake_scan_host(host: str):
        return _report(
            host,
            [PortResult(80, PortState.OPEN), PortResult(443, PortState.OPEN)],
        )

    async def fake_tls(_host: str, port: int):
        return _certificate() if port == 443 else None

    async def fake_http(host: str, ports: list[int], **_kwargs):
        return [_http_service(host)] if 80 in ports else []

    monkeypatch.setattr("app.core.jobs.scan.check_scope", allow_scoped_host)
    monkeypatch.setattr("app.core.discovery.check_scope", allow_scoped_host)
    monkeypatch.setattr("app.core.jobs.scan.scan_host", fake_scan_host)
    monkeypatch.setattr(port_findings, "probe_tls_certificate", fake_tls)
    monkeypatch.setattr("app.core.jobs.scan.probe_open_ports", fake_http)

    result = await run_scheduled_scan(
        {
            "db": db_session,
            "job_id": "orchestration-job",
            "job_try": 1,
        },
        ScanPayload(tenant_id=tenant.id, run_id=run.id),
        domain_sources=(
            StaticSource("dns", {"api.target4.lab.local"}),
            StaticSource("crtsh"),
        ),
    )

    assert result is not None
    assert result.id == run.id
    assert result.status == ScanRunStatus.SUCCEEDED
    assert set(checked_hosts) >= {"target4.lab.local", "api.target4.lab.local"}
    assert result.sources_attempted == ["dns", "crtsh", "ports", "tls", "http"]
    assert result.sources_degraded == []

    findings, _ = await FindingRepository(db_session, tenant_id=tenant.id).list(
        target_id=target.id
    )
    assert {finding.kind for finding in findings} == {
        FindingKind.SUBDOMAIN,
        FindingKind.OPEN_PORT,
        FindingKind.HTTP_SERVICE,
        FindingKind.TLS_CERTIFICATE,
    }
    assert all(finding.last_seen_run_id == run.id for finding in findings)
    assert result.findings_count == len(findings)
    assert result.new_findings_count == len(findings)

    snapshots = await ScanRunFindingRepository(
        db_session, tenant_id=tenant.id
    ).list_for_run(run.id)
    assert len(snapshots) == len(findings)
    assert "run_scheduled_scan" in JOB_REGISTRY
    assert "subdomain_discovery_job" not in JOB_REGISTRY


@pytest.mark.asyncio
async def test_failed_stages_degrade_without_failing_successful_stages(
    db_session, two_tenants, monkeypatch
):
    tenant, _ = two_tenants
    target, previous_run = await _create_target_and_run(db_session, tenant)
    repository = FindingRepository(db_session, tenant_id=tenant.id)
    seed_items = [
        {
            "target_id": target.id,
            "run_id": previous_run.id,
            "kind": FindingKind.SUBDOMAIN,
            "value": "target4.lab.local",
        },
        {
            "target_id": target.id,
            "run_id": previous_run.id,
            "kind": FindingKind.SUBDOMAIN,
            "value": "old.target4.lab.local",
        },
        {
            "target_id": target.id,
            "run_id": previous_run.id,
            "kind": FindingKind.OPEN_PORT,
            "value": "target4.lab.local:8443/tcp",
        },
        {
            "target_id": target.id,
            "run_id": previous_run.id,
            "kind": FindingKind.HTTP_SERVICE,
            "value": "http://target4.lab.local:80",
        },
    ]
    await repository.persist_discovery_run(
        target_id=target.id,
        run_id=previous_run.id,
        items=seed_items,
        kinds={
            FindingKind.SUBDOMAIN,
            FindingKind.OPEN_PORT,
            FindingKind.HTTP_SERVICE,
            FindingKind.TLS_CERTIFICATE,
        },
    )
    run_repository = ScanRunRepository(db_session, tenant_id=tenant.id)
    claimed = await run_repository.claim_for_job(previous_run.id, job_id="previous-job")
    assert claimed is not None
    await run_repository.succeed(previous_run.id)

    next_run = await run_repository.create(target_id=target.id, max_attempts=3)

    async def allow_scoped_host(_host: str, **_kwargs):
        return None

    async def fake_scan_host(host: str):
        return _report(host, [PortResult(80, PortState.OPEN)])

    async def no_tls(_host: str, _port: int):
        return None

    async def fail_http(_host: str, _ports: list[int], **_kwargs):
        raise TimeoutError

    monkeypatch.setattr("app.core.jobs.scan.check_scope", allow_scoped_host)
    monkeypatch.setattr("app.core.discovery.check_scope", allow_scoped_host)
    monkeypatch.setattr("app.core.jobs.scan.scan_host", fake_scan_host)
    monkeypatch.setattr(port_findings, "probe_tls_certificate", no_tls)
    monkeypatch.setattr("app.core.jobs.scan.probe_open_ports", fail_http)

    result = await run_scheduled_scan(
        {
            "db": db_session,
            "job_id": "degraded-orchestration-job",
            "job_try": 1,
        },
        ScanPayload(tenant_id=tenant.id, run_id=next_run.id),
        domain_sources=(StaticSource("dns"), FailedSource()),
    )

    assert result is not None
    assert result.status == ScanRunStatus.SUCCEEDED
    assert set(result.sources_degraded) == {"crtsh", "http"}
    assert "crtsh: source failed (RuntimeError)" in result.error_message
    assert "http: probe failed (TimeoutError)" in result.error_message

    stored, _ = await repository.list(target_id=target.id)
    status_by_kind_and_value = {
        (finding.kind, finding.value): finding.status for finding in stored
    }
    assert (
        status_by_kind_and_value[(FindingKind.SUBDOMAIN, "old.target4.lab.local")]
        == "active"
    )
    assert (
        status_by_kind_and_value[(FindingKind.OPEN_PORT, "target4.lab.local:8443/tcp")]
        == "resolved"
    )
    assert (
        status_by_kind_and_value[
            (FindingKind.HTTP_SERVICE, "http://target4.lab.local:80")
        ]
        == "active"
    )
    snapshots = await ScanRunFindingRepository(
        db_session, tenant_id=tenant.id
    ).list_for_run(next_run.id)
    assert {item.classification for item in snapshots} == {
        "new",
        "unchanged",
        "resolved",
    }


@pytest.mark.asyncio
async def test_empty_scan_stages_are_successful_with_zero_findings(
    db_session, two_tenants, monkeypatch
):
    tenant, _ = two_tenants
    _target, run = await _create_target_and_run(
        db_session, tenant, kind="hostname", value="lab-nginx"
    )

    async def allow_scoped_host(_host: str, **_kwargs):
        return None

    async def closed_scan(host: str):
        return _report(host, [PortResult(81, PortState.CLOSED)])

    async def no_http(_host: str, _ports: list[int], **_kwargs):
        return []

    monkeypatch.setattr("app.core.jobs.scan.check_scope", allow_scoped_host)
    monkeypatch.setattr("app.core.jobs.scan.scan_host", closed_scan)
    monkeypatch.setattr("app.core.jobs.scan.probe_open_ports", no_http)

    result = await run_scheduled_scan(
        {"db": db_session, "job_id": "empty-scan-job", "job_try": 1},
        ScanPayload(tenant_id=tenant.id, run_id=run.id),
    )

    assert result is not None
    assert result.status == ScanRunStatus.SUCCEEDED
    assert result.findings_count == result.new_findings_count == 0
    assert result.sources_degraded == []
