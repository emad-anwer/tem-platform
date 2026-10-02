from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.fingerprint import FindingKind, compute_fingerprint
from app.modules.asm.scanner.port_findings import record_port_scan
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
    repo.upsert_discovery_batch.return_value = (1, 1)
    repo.resolve_missing_discoveries.return_value = 0
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

    (items,), _ = repo.upsert_discovery_batch.call_args
    assert len(items) == 1
    assert items[0]["kind"] is FindingKind.OPEN_PORT
    assert items[0]["value"] == "lab-nginx:80/tcp"
    assert items[0]["details"] == {"port": 80, "protocol": "tcp"}  # stable keys only

    kwargs = repo.resolve_missing_discoveries.call_args.kwargs
    assert kwargs["kinds"] == {FindingKind.OPEN_PORT}
    assert kwargs["seen_fingerprints"] == {
        compute_fingerprint(FindingKind.OPEN_PORT, target_id, "lab-nginx:80/tcp")
    }
    assert (summary.total, summary.new) == (1, 1)


@pytest.mark.asyncio
async def test_fully_out_of_scope_scan_does_not_resolve_anything():
    repo = AsyncMock()
    repo.upsert_discovery_batch.return_value = (0, 0)
    await record_port_scan(
        repo,
        target_id=uuid4(),
        run_id=uuid4(),
        host="127.0.0.1",
        report=_report(
            [PortResult(22, PortState.OUT_OF_SCOPE, "loopback_port_not_allowed")]
        ),
    )
    repo.resolve_missing_discoveries.assert_not_called()
