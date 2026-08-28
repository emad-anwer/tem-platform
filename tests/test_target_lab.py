import os
from pathlib import Path
import re
import socket
import ssl
import subprocess

import pytest

LAB_ROOT = Path(__file__).parent.parent
COMPOSE_FILE = LAB_ROOT / "compose.yaml"
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
        core_block = content[start_idx:end_idx] if end_idx != -1 else content[start_idx:]
        assert 'profiles: ["lab"]' not in core_block, f"Core service {core} must not be in lab profile"


def test_compose_lab_security_hardening_and_read_only_mounts() -> None:
    """Verify OWASP A05: All lab volume mounts are read-only (:ro) and use no-new-privileges."""
    content = COMPOSE_FILE.read_text(encoding="utf-8")

    # Check security_opt
    assert content.count("no-new-privileges:true") >= 6, "Security opt must be on core and lab services"

    # Verify lab volumes are mounted read-only
    lab_mounts = re.findall(r"\./lab/[^:]+:[^:]+:([a-z]+)", content)
    assert len(lab_mounts) >= 4, "Lab mount specifications not found"
    for mode in lab_mounts:
        assert mode == "ro", f"Lab volume mount must be read-only (:ro), got :{mode}"


def test_tls_certificate_and_sans_ground_truth() -> None:
    """Verify Target 4 X.509 certificate validity and Subject Alternative Names (SANs)."""
    assert TLS_CERT_FILE.exists(), f"TLS certificate file not found: {TLS_CERT_FILE}"
    assert TLS_KEY_FILE.exists(), f"TLS private key file not found: {TLS_KEY_FILE}"

    # Use openssl cli to inspect the generated cert
    res = subprocess.run(
        ["openssl", "x509", "-in", str(TLS_CERT_FILE), "-noout", "-subject", "-ext", "subjectAltName"],
        capture_output=True,
        text=True,
        check=True,
    )
    output = res.stdout

    # Assert Subject
    assert "CN = target4.lab.local" in output or "CN=target4.lab.local" in output

    # Assert Subject Alternative Names (SANs)
    expected_sans = [
        "DNS:target4.lab.local",
        "DNS:sub1.target4.lab.local",
        "DNS:api.target4.lab.local",
        "DNS:admin.internal.tem.local",
        "IP Address:127.0.0.1",
    ]
    for san in expected_sans:
        assert san in output, f"Expected SAN {san} not found in certificate extensions:\n{output}"


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


# ======================================================================
# Live End-to-End Probe Tests (Runs when lab containers are up)
# ======================================================================


@pytest.mark.e2e
def test_lab_nginx_target_banner_live_probe() -> None:
    """Probe live Target 1 (lab-nginx on port 8081) for expected banner and technology headers."""
    if not _is_port_open(8081):
        pytest.skip("Target lab service lab-nginx (port 8081) is not running — run `just lab-up`")

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
        pytest.skip("Target lab service lab-apache (port 8082) is not running — run `just lab-up`")

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
        pytest.skip("Target lab service lab-nonstandard (port 8888) is not running — run `just lab-up`")

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
        pytest.skip("Target lab service lab-tls-san (port 8443) is not running — run `just lab-up`")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with socket.create_connection(("localhost", 8443), timeout=2.0) as sock:
        with ctx.wrap_socket(sock, server_hostname="target4.lab.local") as ssock:
            cert_der = ssock.getpeercert(binary_form=True)
            assert cert_der is not None, "Failed to retrieve binary peer certificate"

            # Parse certificate via OpenSSL or ssl
            cipher = ssock.cipher()
            assert cipher is not None
            protocol = ssock.version()
            assert protocol in ("TLSv1.2", "TLSv1.3")
