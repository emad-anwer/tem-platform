from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.fingerprint import FindingKind
from app.core.repository import DiscoveryPersistenceSummary
from app.modules.asm.scanner.http_prober import HTTPService
from app.modules.asm.scanner.port_findings import record_http_services, record_port_scan
from app.modules.asm.scanner.port_scanner import PortResult, PortScanReport, PortState


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
async def test_open_ports_become_kind_scoped_open_port_findings():
    repo = AsyncMock()
    repo.persist_discovery_run.return_value = DiscoveryPersistenceSummary(1, 1, 0)
    target_id, run_id = uuid4(), uuid4()

    summary = await record_port_scan(
        repo,
        target_id=target_id,
        run_id=run_id,
        host="lab-nginx",
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

    assert kwargs["kinds"] == {FindingKind.OPEN_PORT}
    assert kwargs["degraded"] is False
    assert kwargs["return_summary"] is True
    assert (summary.total, summary.new, summary.resolved) == (1, 1, 0)


@pytest.mark.asyncio
async def test_fully_out_of_scope_scan_does_not_resolve_anything():
    repo = AsyncMock()
    repo.persist_discovery_run.return_value = DiscoveryPersistenceSummary(0, 0, 0)
    await record_port_scan(
        repo,
        target_id=uuid4(),
        run_id=uuid4(),
        host="127.0.0.1",
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
