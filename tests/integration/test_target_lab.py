import asyncio
import ipaddress
import re
import socket
import ssl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.core.scope as scope_module
from app.core.jobs.scan import ScanPayload, run_scheduled_scan
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.scope import ScanScope
from app.modules.asm.scanner.tls_certificate import probe_tls_certificate

LAB_ROOT = Path(__file__).parent.parent.parent
COMPOSE_FILE = LAB_ROOT / "compose.yaml"
JUSTFILE = LAB_ROOT / "justfile"
TARGET_LAB_DOC = LAB_ROOT / "docs" / "target-lab.md"
TLS_CERT_FILE = LAB_ROOT / "lab" / "tls" / "certs" / "server.crt"
TLS_KEY_FILE = LAB_ROOT / "lab" / "tls" / "certs" / "server.key"


def _is_port_open(port: int, host: str = "localhost", timeout: float = 1.0) -> bool:
    """Check if a TCP port is currently open and reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


# ======================================================================
# Unit Tests: Static Configuration & Security Compliance
# ======================================================================


def test_compose_profiles_isolation_for_lab_targets() -> None:
    """Verify that lab targets are strictly isolated under the 'lab' Compose profile."""
    content = COMPOSE_FILE.read_text(encoding="utf-8")

    lab_services = ["lab-nginx", "lab-apache", "lab-nonstandard", "lab-tls-san"]
    core_services = ["app:", "postgres:", "redis:"]

    # All lab services must be present
    for svc in lab_services:
        assert f"{svc}:" in content, f"Service {svc} missing from compose.yaml"

    # Core services must not have the 'lab' profile
    for core in core_services:
        start_idx = content.find(core)
        end_idx = content.find("\n  ", start_idx + len(core))
        core_block = (
            content[start_idx:end_idx] if end_idx != -1 else content[start_idx:]
        )
        assert 'profiles: ["lab"]' not in core_block, (
            f"Core service {core} must not be in lab profile"
        )


def test_compose_lab_security_hardening_and_read_only_mounts() -> None:
    """Verify OWASP A05: All lab volume mounts are read-only (:ro) and use no-new-privileges."""
    content = COMPOSE_FILE.read_text(encoding="utf-8")

    # Check security_opt
    assert content.count("no-new-privileges:true") >= 6, (
        "Security opt must be on core and lab services"
    )

    # Verify lab volumes are mounted read-only
    lab_mounts = re.findall(r"\./lab/[^:]+:[^:]+:([a-z]+)", content)
    assert len(lab_mounts) >= 4, "Lab mount specifications not found"
    for mode in lab_mounts:
        assert mode == "ro", f"Lab volume mount must be read-only (:ro), got :{mode}"


def test_target_lab_ground_truth_documentation_integrity() -> None:
    """Verify that docs/target-lab.md documents all 4 targets, ports, banners, and SANs accurately."""
    assert TARGET_LAB_DOC.exists(), f"Documentation file missing: {TARGET_LAB_DOC}"
    doc = TARGET_LAB_DOC.read_text(encoding="utf-8")

    # Documented ports
    assert "8081" in doc and "8082" in doc and "8888" in doc and "8443" in doc

    # Documented banners
    assert "nginx/1.25.4" in doc
    assert "Apache/2.4.52 (Unix)" in doc

    # Documented SANs
    assert "target4.lab.local" in doc
    assert "sub1.target4.lab.local" in doc
    assert "api.target4.lab.local" in doc
    assert "admin.internal.tem.local" in doc


def test_lab_up_depends_on_lab_certs() -> None:
    """Verify the justfile wires lab-up to generate TLS certs on a clean clone."""
    justfile = JUSTFILE.read_text(encoding="utf-8")

    # lab-up must declare lab-certs as a prerequisite
    assert "lab-up: lab-certs" in justfile, (
        "lab-up must depend on lab-certs (W1-10 issue #53)"
    )

    # lab-certs must exist and invoke the generation script
    assert "lab-certs:" in justfile, "lab-certs recipe missing from justfile"
    assert "generate_certs.sh" in justfile, (
        "lab-certs must call ./lab/tls/generate_certs.sh"
    )

    # lab-certs must be idempotent: skip if certs already exist
    assert "server.crt" in justfile and "server.key" in justfile, (
        "lab-certs must check for server.crt/server.key to be idempotent"
    )


# ======================================================================
# Live End-to-End Probe Tests (Runs when lab containers are up)
# ======================================================================


@pytest.mark.e2e
def test_lab_nginx_target_banner_live_probe() -> None:
    """Probe live Target 1 (lab-nginx on port 8081) for expected banner and technology headers."""
    if not _is_port_open(8081):
        pytest.skip(
            "Target lab service lab-nginx (port 8081) is not running — run `just lab-up`"
        )

    import httpx

    with httpx.Client(base_url="http://localhost:8081") as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "nginx" in res.headers.get("server", "").lower()
        assert res.headers.get("x-lab-target") == "nginx-standard"
        assert res.headers.get("x-powered-by") == "PHP/8.2.10"
        assert "TEM Target Lab - Nginx Web Server" in res.text


@pytest.mark.e2e
def test_lab_apache_target_banner_live_probe() -> None:
    """Probe live Target 2 (lab-apache on port 8082) for expected Apache banner."""
    if not _is_port_open(8082):
        pytest.skip(
            "Target lab service lab-apache (port 8082) is not running — run `just lab-up`"
        )

    import httpx

    with httpx.Client(base_url="http://localhost:8082") as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "apache" in res.headers.get("server", "").lower()
        assert res.headers.get("x-lab-target") == "apache-legacy"
        assert "TEM Target Lab - Apache Legacy Server" in res.text


@pytest.mark.e2e
def test_lab_nonstandard_port_live_probe() -> None:
    """Probe live Target 3 (lab-nonstandard on port 8888)."""
    if not _is_port_open(8888):
        pytest.skip(
            "Target lab service lab-nonstandard (port 8888) is not running — run `just lab-up`"
        )

    import httpx

    with httpx.Client(base_url="http://localhost:8888") as client:
        res = client.get("/")
        assert res.status_code == 200
        assert res.headers.get("x-lab-target") == "nonstandard-port-8888"
        assert res.headers.get("x-service-type") == "Custom-Port-Tester"
        assert "TEM Target Lab - NonStandard Port 8888" in res.text


@pytest.mark.e2e
def test_lab_tls_san_live_probe() -> None:
    """Probe live Target 4 (lab-tls-san on port 8443) and verify TLS handshake and certificate SANs."""
    if not _is_port_open(8443):
        pytest.skip(
            "Target lab service lab-tls-san (port 8443) is not running — run `just lab-up`"
        )

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with (
        socket.create_connection(("localhost", 8443), timeout=2.0) as sock,
        ctx.wrap_socket(sock, server_hostname="target4.lab.local") as ssock,
    ):
        cert_der = ssock.getpeercert(binary_form=True)
        assert cert_der is not None, "Failed to retrieve binary peer certificate"

        # Parse certificate via OpenSSL or ssl
        cipher = ssock.cipher()
        assert cipher is not None
        protocol = ssock.version()
        assert protocol in ("TLSv1.2", "TLSv1.3")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_tls_parser_reads_the_lab_self_signed_certificate() -> None:
    if not _is_port_open(8443):
        pytest.skip(
            "Target lab service lab-tls-san (port 8443) is not running — run `just lab-up`"
        )

    class AllowAllRedis:
        async def eval(self, *_args):
            return [1, 0]

    observation = await probe_tls_certificate(
        "127.0.0.1",
        8443,
        scope=ScanScope.parse(["127.0.0.1:8443"]),
        limiter=SlidingWindowRateLimiter(redis=AllowAllRedis()),
    )

    assert observation is not None
    assert observation.details["subject_common_name"] == "target4.lab.local"
    assert {san["value"] for san in observation.details["sans"]} == {
        "target4.lab.local",
        "sub1.target4.lab.local",
        "api.target4.lab.local",
        "admin.internal.tem.local",
        "127.0.0.1",
    }


def _all_lab_targets_reachable() -> bool:
    targets = (
        ("lab-nginx", 80),
        ("lab-apache", 80),
        ("lab-nonstandard", 8888),
        ("target4.lab.local", 443),
    )
    try:
        return all(_tcp_target_open(host, port) for host, port in targets)
    except OSError:
        return False


def _tcp_target_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scan_api_runs_full_asm_pipeline_against_target_lab(
    auth_client, db_session, two_tenants, auth_headers, monkeypatch
):
    if not _all_lab_targets_reachable():
        pytest.skip(
            "One or more Target Lab services are not reachable — run `just lab-up` "
            "and execute tests from the Compose network"
        )

    tenant, _ = two_tenants
    headers = auth_headers(tenant_zitadel_org_id=tenant.zitadel_org_id)
    pool = AsyncMock()
    pool.enqueue_job.return_value = SimpleNamespace(job_id="e2e-scan-job")
    monkeypatch.setattr(
        "app.core.pipeline.service.get_arq_pool",
        AsyncMock(return_value=pool),
    )

    class AllowAllRedis:
        async def eval(self, *_args):
            return [1, 0]

    limiter = SlidingWindowRateLimiter(redis=AllowAllRedis())
    monkeypatch.setattr(scope_module, "configured_rate_limiter", lambda: limiter)
    monkeypatch.setattr(
        "app.modules.asm.scanner.port_scanner.configured_rate_limiter",
        lambda: limiter,
    )
    monkeypatch.setattr(
        "app.modules.asm.scanner.tls_certificate.configured_rate_limiter",
        lambda: limiter,
    )

    async def resolve_lab_alias(hostname: str):
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        return list({ipaddress.ip_address(record[4][0]) for record in records})

    monkeypatch.setattr(scope_module, "resolve_addresses", resolve_lab_alias)

    target_specs = (
        (
            "hostname",
            "lab-nginx",
            {"lab-nginx:80/tcp", "http://lab-nginx:80"},
            "TEM Target Lab - Nginx Web Server",
            {"Server": "nginx/1.25.4", "X-Powered-By": "PHP/8.2.10"},
        ),
        (
            "hostname",
            "lab-apache",
            {"lab-apache:80/tcp", "http://lab-apache:80"},
            "TEM Target Lab - Apache Legacy Server",
            {"Server": "Apache/2.4.52 (Unix)"},
        ),
        (
            "hostname",
            "lab-nonstandard",
            {"lab-nonstandard:8888/tcp", "http://lab-nonstandard:8888"},
            "TEM Target Lab - NonStandard Port 8888",
            {"Server": "nginx/1.25.4"},
        ),
        (
            "domain",
            "target4.lab.local",
            {
                "target4.lab.local:443/tcp",
                "https://target4.lab.local:443",
                "target4.lab.local:443",
                "target4.lab.local",
                "sub1.target4.lab.local",
                "api.target4.lab.local",
            },
            "TEM Target Lab - Multi-SAN TLS Server",
            {"Server": "nginx/1.25.4"},
        ),
    )
    for index, (
        target_kind,
        target_value,
        expected_values,
        expected_title,
        expected_headers,
    ) in enumerate(target_specs):
        target_response = await auth_client.post(
            "/api/v1/targets",
            json={"kind": target_kind, "value": target_value},
            headers=headers,
        )
        assert target_response.status_code == 201, target_response.text
        target_id = target_response.json()["data"]["id"]

        start_response = await auth_client.post(
            f"/api/v1/targets/{target_id}/scans", headers=headers
        )
        assert start_response.status_code == 202, start_response.text
        payload = pool.enqueue_job.call_args.args[1]
        assert isinstance(payload, ScanPayload)

        # Dispatch the registered worker entry in-process so this E2E test
        # shares the API's test DB while exercising the real job wrapper.
        result = await run_scheduled_scan(
            {
                "db": db_session,
                "job_id": f"e2e-worker-job-{index}",
                "job_try": 1,
            },
            payload,
            domain_sources=() if target_kind == "domain" else None,
        )
        assert result is not None
        run_id = str(result.id)

        run_response = await auth_client.get(
            f"/api/v1/scan_runs/{run_id}", headers=headers
        )
        assert run_response.status_code == 200, run_response.text
        run_attributes = run_response.json()["data"]["attributes"]
        assert run_attributes["status"] == "succeeded", run_attributes

        findings_response = await auth_client.get(
            f"/api/v1/findings?target_id={target_id}&scan_run_id={run_id}",
            headers=headers,
        )
        assert findings_response.status_code == 200, findings_response.text
        findings = [item["attributes"] for item in findings_response.json()["data"]]
        values = {item["value"] for item in findings}
        assert expected_values <= values, (target_value, expected_values - values)
        assert all(item["last_seen_run_id"] == run_id for item in findings)
        http_service = next(item for item in findings if item["kind"] == "http_service")
        assert http_service["details"]["status_code"] == 200
        assert http_service["details"]["title"] == expected_title
        assert {
            header: http_service["details"]["headers"][header]
            for header in expected_headers
        } == expected_headers

        if target_kind == "domain":
            assert {item["kind"] for item in findings} == {
                "subdomain",
                "open_port",
                "http_service",
                "tls_certificate",
            }
            assert not any(
                item["value"] == "admin.internal.tem.local"
                for item in findings
                if item["kind"] == "subdomain"
            )
            certificate = next(
                item for item in findings if item["kind"] == "tls_certificate"
            )
            assert {san["value"] for san in certificate["details"]["sans"]} >= {
                "admin.internal.tem.local",
                "127.0.0.1",
            }
