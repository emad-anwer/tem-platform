from __future__ import annotations

import socket

import pytest

from app.core.config import get_settings
from app.modules.asm.scanner.port_scanner import PortState, scan_host

LAB = [
    ("lab-nginx", 80),
    ("lab-apache", 80),
    ("lab-nonstandard", 8888),
    ("lab-tls-san", 443),
]


def _lab_reachable() -> bool:
    try:
        socket.gethostbyname("lab-nginx")
    except OSError:
        return False
    return True


pytestmark = [
    pytest.mark.lab,
    pytest.mark.skipif(not _lab_reachable(), reason="lab not up (just lab-up)"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("host", "port"), LAB)
async def test_lab_service_found_with_default_curated_list(host: str, port: int):
    report = await scan_host(host)  # real scope from SCAN_SCOPE_ALLOWLIST
    assert port in report.open_ports
    assert report.max_in_flight <= get_settings().port_scan_concurrency
    assert report.sockets_opened == report.sockets_closed


@pytest.mark.asyncio
async def test_open_and_closed_on_lab_nginx():
    report = await scan_host("lab-nginx", ports=[80, 9999])
    states = {r.port: r.state for r in report.results}
    assert states[80] is PortState.OPEN
    assert states[9999] is PortState.CLOSED


@pytest.mark.asyncio
async def test_all_four_lab_services_in_seconds():
    reports = [await scan_host(host) for host, _ in LAB]
    assert sum(r.duration_seconds for r in reports) < 15
    for (host, port), report in zip(LAB, reports, strict=True):
        assert port in report.open_ports