"""Live HTTP-prober checks against the optional Docker target lab."""

from __future__ import annotations

import socket

import pytest

from app.modules.asm.scanner.http_prober import probe_open_ports


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
async def test_prober_reports_all_four_documented_lab_http_services():
    targets = (
        ("lab-nginx", 80),
        ("lab-apache", 80),
        ("lab-nonstandard", 8888),
        ("lab-tls-san", 443),
    )

    services = []
    for host, port in targets:
        services.extend(await probe_open_ports(host, [port]))

    assert len(services) == 4
    observed = {(service.host, service.port): service for service in services}

    nginx = observed[("lab-nginx", 80)]
    assert nginx.status_code == 200
    assert nginx.headers["Server"] == "nginx/1.25.4"
    assert nginx.headers["X-Powered-By"] == "PHP/8.2.10"
    assert nginx.title == "TEM Target Lab - Nginx Web Server"
    assert {
        (item["technology"], item.get("version")) for item in nginx.technologies
    } >= {
        ("nginx", "1.25.4"),
        ("PHP", "8.2.10"),
    }

    apache = observed[("lab-apache", 80)]
    assert apache.headers["Server"] == "Apache/2.4.52 (Unix)"
    assert apache.title == "TEM Target Lab - Apache Legacy Server"
    assert [
        (item["technology"], item.get("version")) for item in apache.technologies
    ] == [("Apache HTTP Server", "2.4.52")]

    nonstandard = observed[("lab-nonstandard", 8888)]
    assert nonstandard.status_code == 200
    assert nonstandard.headers["Server"] == "nginx/1.25.4"
    assert nonstandard.title == "TEM Target Lab - NonStandard Port 8888"

    tls = observed[("lab-tls-san", 443)]
    assert tls.scheme == "https"
    assert tls.status_code == 200
    assert tls.headers["Server"] == "nginx/1.25.4"
    assert tls.title == "TEM Target Lab - Multi-SAN TLS Server"
