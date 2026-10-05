from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.fingerprint import FindingKind
from app.core.repository import DiscoveryPersistenceSummary
from app.modules.asm.scanner.http_prober import HTTPService
from app.modules.asm.scanner.port_findings import record_http_services, record_port_scan
from app.modules.asm.scanner.port_scanner import PortResult, PortScanReport, PortState
from app.modules.asm.scanner.tls_certificate import TLSCertificateObservation


def _report(results: list[PortResult]) -> PortScanReport:
    return PortScanReport(
        host="lab-nginx",
        addresses=(),
        results=tuple(results),
        concurrency=50,
        connect_timeout_seconds=1.5,
        duration_seconds=0.1,
        max_in_flight=3,
        sockets_opened=1,
        sockets_closed=1,
    )


@pytest.mark.asyncio
async def test_open_ports_become_kind_scoped_open_port_findings(monkeypatch):
    repo = AsyncMock()
    repo.persist_discovery_run.return_value = DiscoveryPersistenceSummary(1, 1, 0)
    target_id, run_id = uuid4(), uuid4()
    probe = AsyncMock(return_value=None)
    monkeypatch.setattr(port_findings, "probe_tls_certificate", probe)

    summary = await record_port_scan(
        repo,
        target_id=target_id,
        run_id=run_id,
        host="lab-nginx",
        domain="example.com",
        report=_report(
            [
                PortResult(80, PortState.OPEN),
                PortResult(81, PortState.CLOSED),
                PortResult(82, PortState.FILTERED, "timeout"),
            ]
        ),
    )

    kwargs = repo.persist_discovery_run.call_args.kwargs
    items = kwargs["items"]
    assert len(items) == 1
    assert items[0]["kind"] is FindingKind.OPEN_PORT
    assert items[0]["value"] == "lab-nginx:80/tcp"
    assert items[0]["details"] == {"port": 80, "protocol": "tcp"}  # stable keys only
    probe.assert_awaited_once_with("lab-nginx", 80)

    assert kwargs["kinds"] == {FindingKind.OPEN_PORT}
    assert kwargs["degraded"] is False
    assert kwargs["return_summary"] is True
    assert (summary.total, summary.new, summary.resolved) == (1, 1, 0)


@pytest.mark.asyncio
async def test_certificate_sans_write_only_in_domain_dns_names(monkeypatch):
    repo = AsyncMock()
    repo.upsert_discovery_batch.return_value = (5, 5)
    repo.resolve_missing_discoveries.return_value = 0
    target_id, run_id = uuid4(), uuid4()
    observation = TLSCertificateObservation(
        details={
            "sans": [
                {"type": "DNS", "value": "target4.lab.local"},
                {"type": "DNS", "value": "sub1.target4.lab.local"},
                {"type": "DNS", "value": "api.target4.lab.local"},
                {"type": "DNS", "value": "admin.internal.tem.local"},
                {"type": "IP", "value": "127.0.0.1"},
            ]
        },
        dns_names=(
            "target4.lab.local",
            "sub1.target4.lab.local",
            "api.target4.lab.local",
            "admin.internal.tem.local",
        ),
    )
    probe = AsyncMock(return_value=observation)
    monkeypatch.setattr(port_findings, "probe_tls_certificate", probe)

    await record_port_scan(
        repo,
        target_id=target_id,
        run_id=run_id,
        host="lab-tls-san",
        domain="target4.lab.local",
        report=_report([PortResult(443, PortState.OPEN)]),
    )

    (items,), _ = repo.upsert_discovery_batch.call_args
    assert [item["kind"] for item in items] == [
        FindingKind.OPEN_PORT,
        FindingKind.TLS_CERTIFICATE,
        FindingKind.SUBDOMAIN,
        FindingKind.SUBDOMAIN,
        FindingKind.SUBDOMAIN,
    ]
    assert items[1]["value"] == "lab-tls-san:443"
    assert items[1]["details"]["sans"] == observation.details["sans"]
    assert [item["value"] for item in items[2:]] == [
        "target4.lab.local",
        "sub1.target4.lab.local",
        "api.target4.lab.local",
    ]
    resolved = repo.resolve_missing_discoveries.call_args.kwargs
    assert resolved["kinds"] == {
        FindingKind.OPEN_PORT,
        FindingKind.TLS_CERTIFICATE,
    }


@pytest.mark.asyncio
async def test_tls_san_subdomains_deduplicate_across_runs(
    db_session, two_tenants, monkeypatch
):
    tenant, _ = two_tenants
    set_current_principal(
        Principal(user_id="scanner", tenant_id=tenant.id, role=Role.OWNER)
    )
    target = await TargetRepository(db_session, tenant_id=tenant.id).create(
        kind="domain",
        value="target4.lab.local",
        value_normalized="target4.lab.local",
    )
    run_repository = ScanRunRepository(db_session, tenant_id=tenant.id)
    findings = FindingRepository(db_session, tenant_id=tenant.id)
    observation = TLSCertificateObservation(
        details={"sans": [{"type": "DNS", "value": "sub1.target4.lab.local"}]},
        dns_names=("sub1.target4.lab.local",),
    )
    monkeypatch.setattr(
        port_findings,
        "probe_tls_certificate",
        AsyncMock(return_value=observation),
    )

    summaries = []
    for _ in range(2):
        run = await run_repository.create(target_id=target.id, max_attempts=3)
        summaries.append(
            await record_port_scan(
                findings,
                target_id=target.id,
                run_id=run.id,
                host="lab-tls-san",
                domain="target4.lab.local",
                report=_report([PortResult(443, PortState.OPEN)]),
            )
        )

    stored, _ = await findings.list(target_id=target.id)
    assert (summaries[0].new, summaries[1].new) == (3, 0)
    assert len(stored) == 3
    assert len({finding.fingerprint for finding in stored}) == 3
    assert {finding.times_seen for finding in stored} == {2}
    assert {finding.kind for finding in stored} == {
        FindingKind.OPEN_PORT,
        FindingKind.TLS_CERTIFICATE,
        FindingKind.SUBDOMAIN,
    }


@pytest.mark.asyncio
async def test_fully_out_of_scope_scan_does_not_resolve_anything():
    repo = AsyncMock()
    repo.persist_discovery_run.return_value = DiscoveryPersistenceSummary(0, 0, 0)
    await record_port_scan(
        repo,
        target_id=uuid4(),
        run_id=uuid4(),
        host="127.0.0.1",
        domain="example.com",
        report=_report(
            [PortResult(22, PortState.OUT_OF_SCOPE, "loopback_port_not_allowed")]
        ),
    )
    kwargs = repo.persist_discovery_run.call_args.kwargs
    assert kwargs["degraded"] is True


@pytest.mark.asyncio
async def test_http_services_use_atomic_discovery_persistence_and_degraded_guard():
    repo = AsyncMock()
    repo.persist_discovery_run.return_value = DiscoveryPersistenceSummary(1, 1, 0)
    target_id, run_id = uuid4(), uuid4()
    service = HTTPService(
        scheme="http",
        host="lab-nginx",
        port=80,
        status_code=200,
        final_url="http://lab-nginx:80/",
        title="TEM Target Lab - Nginx Web Server",
        headers={"Server": "nginx/1.25.4"},
        cookie_names=(),
        technologies=(),
        body_truncated=False,
        redirects_followed=0,
    )

    summary = await record_http_services(
        repo,
        target_id=target_id,
        run_id=run_id,
        services=[service],
        degraded=True,
    )

    kwargs = repo.persist_discovery_run.call_args.kwargs
    assert kwargs["target_id"] == target_id
    assert kwargs["run_id"] == run_id
    assert kwargs["kinds"] == {FindingKind.HTTP_SERVICE}
    assert kwargs["degraded"] is True
    assert kwargs["return_summary"] is True
    assert kwargs["items"][0]["value"] == "http://lab-nginx:80"
    repo.upsert_discovery_batch.assert_not_called()
    repo.resolve_missing_discoveries.assert_not_called()
    assert summary == type(summary)(total=1, new=1, resolved=0)
